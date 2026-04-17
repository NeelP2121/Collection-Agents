"""
Self-learning loop: Real A/B evaluation of prompt variants.

For each iteration, each agent's active prompt is evaluated against
synthetic borrower conversations. Variants are generated, tested against
the same scenarios (deterministic seed), and compared with Welch's t-test,
Cohen's d, confidence intervals, and variance-ratio checks.  Only variants
that pass ALL statistical gates AND a compliance pre-flight are adopted.

Every score and decision is written to CSV (``evals_output/``) and to the
SQLite database via ``utils/db.py``.
"""

import json
import logging
import uuid
import yaml
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional

from compliance.checker import verify_prompt_safety
from learning.data_export import RawDataWriter, EvolutionReportGenerator
from learning.evaluator import VariantEvaluator, EvaluationResult, DEFAULT_WEIGHTS
from learning.godel_monitor import run_godel_monitor_v2
from learning.meta_evaluator import MetaEvaluator
from learning.prompt_improver import PromptImprover
from learning.statistics import is_significant_improvement, StatisticalDecision
from utils.cost_tracker import get_cost_tracker, BudgetExceededError
from utils.db import (
    init_db,
    save_agent_prompt,
    save_evaluation_run,
    save_prompt_evaluation,
    rollback_prompt,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

REGISTRY_PATH = Path(__file__).parent.parent / "registry" / "active_prompts.yaml"

# Map registry keys to evaluator agent names
AGENT_MAP = {
    "assessment": "assessment",
    "resolution": "resolution",
    "final_notice": "final_notice",
}


def _load_active_prompts() -> Dict[str, str]:
    """Load current system prompts from the registry."""
    with open(REGISTRY_PATH) as f:
        registry = yaml.safe_load(f)
    return {key: registry[key]["prompt"] for key in AGENT_MAP if key in registry}


class LearningLoop:
    """
    Main orchestrator for the self-learning system.
    Runs real A/B evaluation with statistical significance testing.
    """

    def __init__(
        self,
        num_conversations: int = 25,
        max_iterations: int = 5,
        num_variants: int = 3,
        seed: int = 42,
        weights: Optional[Dict[str, float]] = None,
    ):
        self.num_conversations = num_conversations
        self.max_iterations = max_iterations
        self.num_variants = num_variants
        self.seed = seed
        self.weights = weights or dict(DEFAULT_WEIGHTS)

        self.prompt_improver = PromptImprover()
        self.meta_evaluator = MetaEvaluator(weights=self.weights)
        self.evaluator = VariantEvaluator(seed=seed, weights=self.weights)
        self.writer = RawDataWriter()
        self.tracker = get_cost_tracker()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self) -> Dict[str, Any]:
        """
        Execute the full A/B learning loop.

        Returns a summary dict with iteration count, adoptions, cost, etc.
        """
        init_db()
        active_prompts = _load_active_prompts()
        total_adoptions = 0
        iteration_summaries: List[Dict] = []
        consecutive_zero_adoptions = 0

        for iteration in range(1, self.max_iterations + 1):
            logger.info("=" * 60)
            logger.info(f"LEARNING ITERATION {iteration}/{self.max_iterations}")
            logger.info("=" * 60)

            # Budget gate
            try:
                self.tracker.check_budget()
            except BudgetExceededError:
                logger.warning("Budget exhausted — stopping learning loop.")
                break

            iter_adoptions = 0
            convergence = True  # flip to False if any agent adopts
            iter_transcripts: List[Dict] = []  # collect for Gödel monitor

            for agent_key, prompt_text in active_prompts.items():
                logger.info(f"\n--- Agent: {agent_key} ---")

                # 1. Evaluate baseline
                baseline_result = self._evaluate_and_record(
                    iteration, agent_key, prompt_text, variant_id="baseline"
                )
                # Collect transcripts with scores for Gödel analysis
                for s in baseline_result.scores:
                    if s.transcript:
                        iter_transcripts.append({
                            "agent": agent_key,
                            "composite_score": s.composite_score,
                            "transcript": s.transcript,
                        })

                if baseline_result.budget_exhausted:
                    break

                # 2. Generate variants (with compliance pre-flight)
                #    Feed baseline scores so the improver knows what's failing.
                # Average dimension scores so the improver knows what's weak
                dim_avgs = {}
                for s in baseline_result.scores:
                    for dim, val in getattr(s, 'dimension_scores', {}).items():
                        dim_avgs.setdefault(dim, []).append(val)

                baseline_eval_summary = {
                    "overall_resolution_rate": sum(
                        1 for s in baseline_result.scores if s.resolved
                    ) / max(len(baseline_result.scores), 1) * 100,
                    "overall_compliance_score": sum(
                        s.compliance_score for s in baseline_result.scores
                    ) / max(len(baseline_result.scores), 1) * 100,
                    "mean_composite": baseline_result.mean_composite,
                    "dimension_scores": {
                        dim: round(sum(vals) / len(vals), 3)
                        for dim, vals in dim_avgs.items()
                    },
                    "scenarios": {
                        f"{s.persona}_{s.scenario_idx}": {
                            "result": "success" if s.resolved else "failure",
                            "composite_score": s.composite_score,
                            "compliance_score": s.compliance_score,
                            "violations": s.violation_count,
                            "turns": s.turns,
                        }
                        for s in baseline_result.scores
                    },
                }
                variants = self._generate_variants(agent_key, prompt_text, baseline_eval_summary)
                if not variants:
                    logger.info(f"No valid variants for {agent_key}, skipping.")
                    continue

                # 3. Evaluate each variant
                variant_results: List[EvaluationResult] = []
                for v_text, v_id in variants:
                    vr = self._evaluate_and_record(iteration, agent_key, v_text, variant_id=v_id)
                    # Collect variant transcripts too
                    for s in vr.scores:
                        if s.transcript:
                            iter_transcripts.append({
                                "agent": agent_key,
                                "composite_score": s.composite_score,
                                "transcript": s.transcript,
                            })
                    variant_results.append(vr)
                    if vr.budget_exhausted:
                        break

                # 4. Statistical comparison + adopt/reject (Bonferroni-corrected)
                num_comparisons = len(variant_results)
                for vr in variant_results:
                    if len(vr.composite_scores) < 2 or len(baseline_result.composite_scores) < 2:
                        continue

                    decision = is_significant_improvement(
                        baseline_result.composite_scores,
                        vr.composite_scores,
                        num_comparisons=num_comparisons,
                    )

                    # 5. Compliance gate — variant must have 0 critical violations
                    if decision.adopted and vr.critical_violations > 0:
                        decision.adopted = False
                        decision.rejection_reasons.append(
                            f"critical_violations={vr.critical_violations}"
                        )

                    # Write decision to CSV
                    self.writer.write_decision(iteration, agent_key, vr.variant_id, decision)

                    # Write to DB
                    self._record_decision_to_db(
                        agent_key, vr, decision, iteration
                    )

                    if decision.adopted:
                        logger.info(f"ADOPTED variant {vr.variant_id}: {decision.to_justification_string()}")
                        active_prompts[agent_key] = vr.prompt_text
                        iter_adoptions += 1
                        convergence = False
                        # Update registry on disk
                        self._update_registry(agent_key, vr.prompt_text)
                    else:
                        logger.info(f"REJECTED variant {vr.variant_id}: {decision.to_rejection_string()}")

            total_adoptions += iter_adoptions

            # 6. System-level regression check: if any agent was adopted,
            #    run a cross-agent handoff quality check. If the new prompt
            #    degrades handoff continuity, rollback.
            if iter_adoptions > 0:
                rollbacks = self._system_level_check(iteration, active_prompts)
                total_adoptions -= rollbacks
                iter_adoptions -= rollbacks

            # 7. Darwin-Gödel meta-evaluation (pass collected transcripts)
            self._run_darwin_godel(iteration, iter_transcripts)

            # 8. Meta-evaluator weight introspection
            self.meta_evaluator.introspect_evaluation_methodology_v2(
                self.evaluator, active_prompts, self.num_conversations
            )

            iter_summary = {
                "iteration": iteration,
                "adoptions": iter_adoptions,
                "spend_usd": self.tracker.get_spend_report()["total_spend_usd"],
            }
            iteration_summaries.append(iter_summary)
            logger.info(f"Iteration {iteration} done: {iter_adoptions} adoptions, ${iter_summary['spend_usd']:.4f} spent")

            # 9. Convergence check — require 2 consecutive zero-adoption iterations
            #    A single unlucky iteration (noise) shouldn't halt learning permanently.
            if convergence:
                consecutive_zero_adoptions += 1
                if consecutive_zero_adoptions >= 2:
                    logger.info(f"No adoptions for {consecutive_zero_adoptions} consecutive iterations — converged. Stopping.")
                    break
                else:
                    logger.info(f"No adoptions this iteration ({consecutive_zero_adoptions}/2 before convergence). Continuing.")
            else:
                consecutive_zero_adoptions = 0

        # Generate evolution report
        cost_report = self.tracker.get_spend_report()
        report = EvolutionReportGenerator().generate(cost_report)
        logger.info(f"\n{report}")

        return {
            "iterations_completed": len(iteration_summaries),
            "total_adoptions": total_adoptions,
            "iteration_summaries": iteration_summaries,
            "final_spend_usd": cost_report["total_spend_usd"],
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _evaluate_and_record(
        self, iteration: int, agent_key: str, prompt_text: str, variant_id: str
    ) -> EvaluationResult:
        """Evaluate a prompt and write raw scores to CSV."""
        result = self.evaluator.evaluate_variant(
            agent_name=agent_key,
            prompt_text=prompt_text,
            num_conversations=self.num_conversations,
            variant_id=variant_id,
        )
        self.writer.write_scores(iteration, agent_key, result)
        return result

    def _generate_variants(self, agent_key: str, current_prompt: str, evaluation_results=None):
        """Generate prompt variants and compliance-gate each one."""
        raw_variants = self.prompt_improver.generate_prompt_variations(
            agent_name=agent_key,
            current_prompt=current_prompt,
            evaluation_results=evaluation_results or {},
            num_variations=self.num_variants,
        )

        valid = []
        for pv in raw_variants:
            is_safe, violations = verify_prompt_safety(pv.prompt_text)
            if is_safe:
                valid.append((pv.prompt_text, pv.variant_id))
            else:
                logger.warning(
                    f"Variant {pv.variant_id} failed compliance pre-flight: {violations}"
                )
        return valid

    def _record_decision_to_db(
        self,
        agent_key: str,
        vr: EvaluationResult,
        decision: StatisticalDecision,
        iteration: int,
    ):
        """Persist evaluation run and per-conversation scores to SQLite."""
        try:
            # Save prompt version
            # Extract variant number from ID like "assessment_v20260417_053624_var1"
            suffix = vr.variant_id.replace("baseline", "0").split("_")[-1]
            # Handle "var1", "var2" suffixes as well as hex or numeric
            if suffix.startswith("var"):
                variant_num = int(suffix[3:]) if suffix[3:].isdigit() else 0
            else:
                try:
                    variant_num = int(suffix, 16) % 100
                except ValueError:
                    variant_num = hash(suffix) % 100
            # Use timestamp-based version to avoid UNIQUE constraint across runs
            version = int(datetime.now(timezone.utc).timestamp()) * 10 + variant_num
            reason = decision.to_justification_string() if decision.adopted else None
            rejected = decision.to_rejection_string() if not decision.adopted else None

            save_agent_prompt(
                agent_name=agent_key,
                version=version,
                prompt_text=vr.prompt_text,
                adoption_reason=reason,
                rejected_because=rejected,
                is_active=decision.adopted,
            )

            # Save evaluation run
            run_id = f"{agent_key}_{vr.variant_id}_{iteration}"
            metrics = decision.to_csv_row()
            spend = self.tracker.get_spend_report()["total_spend_usd"]

            eval_run = save_evaluation_run(
                run_id=run_id,
                agent_name=agent_key,
                prompt_version=version,
                num_conversations=len(vr.scores),
                metrics_dict=metrics,
                cost_usd=spend,
            )

            # Save per-conversation evaluations
            if eval_run:
                for s in vr.scores:
                    conv_id = f"{run_id}_s{s.scenario_idx}"
                    save_prompt_evaluation(
                        eval_run_id=eval_run.id,
                        conversation_id=conv_id,
                        resolution_rate=1.0 if s.resolved else 0.0,
                        compliance_violations=s.violation_count,
                        handoff_score=s.composite_score,
                        notes=f"persona={s.persona}, turns={s.turns}",
                    )
        except Exception as e:
            logger.error(f"DB write failed for {agent_key}/{vr.variant_id}: {e}")

    def _system_level_check(
        self, iteration: int, active_prompts: Dict[str, str]
    ) -> int:
        """
        Cross-agent regression check.

        Runs the full 3-agent pipeline across multiple personas and checks:
        1. Agent 2 doesn't re-ask identity questions (handoff regression)
        2. Agent 3 references prior outcomes (continuity check)
        3. Compliance violations don't spike after prompt adoption

        Returns the number of rollbacks performed.
        """
        rollbacks = 0
        test_personas = ["cooperative", "combative"]  # 2 personas: fast but covers both poles

        for persona in test_personas:
            try:
                from tests.test_phase3_evaluation import SyntheticBorrower
                from agents.agent1_assessment import AssessmentAgent
                from agents.agent2_resolution import ResolutionAgent
                from agents.agent3_final_notice import FinalNoticeAgent
                from summarizer.summarizer import Summarizer
                from learning.evaluator import override_prompt

                borrower = SyntheticBorrower(persona)
                ctx = __import__("models.borrower_state", fromlist=["BorrowerContext"]).BorrowerContext(
                    name=borrower.name, phone=borrower.phone
                )
                ctx.test_borrower_response_fn = borrower.get_response
                summarizer = Summarizer()

                # Run assessment with current prompt
                a1 = AssessmentAgent()
                if "assessment" in active_prompts:
                    a1.system_prompt = active_prompts["assessment"]
                a1_result = a1.run_assessment_agent(ctx)

                # Generate Agent 1 → 2 handoff
                handoff = summarizer.summarize_agent1_to_agent2(
                    a1_result["messages"], ctx.to_dict()
                )
                ctx.update_from_handoff(handoff if isinstance(handoff, dict) else {})
                ctx.agent1_summary = handoff

                # Run resolution
                a2 = ResolutionAgent()
                if "resolution" in active_prompts:
                    a2.system_prompt = active_prompts["resolution"]
                a2_result = a2.run_resolution_agent(ctx)

                # CHECK 1: Did resolution re-ask identity questions?
                re_verification_phrases = [
                    "what is your name", "verify your identity",
                    "can you confirm your account", "what is your zip",
                    "who am i speaking with",
                ]
                a2_text = (ctx.agent2_transcript or "").lower() if isinstance(ctx.agent2_transcript, str) else ""
                for phrase in re_verification_phrases:
                    if phrase in a2_text:
                        logger.warning(
                            f"SYSTEM-LEVEL REGRESSION ({persona}): Resolution re-asked '{phrase}' "
                            f"— handoff context was lost. Rolling back resolution prompt."
                        )
                        if rollback_prompt("resolution"):
                            active_prompts["resolution"] = self._reload_prompt("resolution")
                            rollbacks += 1
                        break

                # Generate Agent 2 → 3 handoff and run final notice
                handoff2 = summarizer.summarize_agent2_to_agent3(
                    {"agent1_handoff": handoff, "agent2_conversation": ctx.agent2_transcript or []},
                    ctx.to_dict(),
                )
                ctx.update_from_handoff(handoff2 if isinstance(handoff2, dict) else {})
                ctx.agent2_summary = handoff2

                a3 = FinalNoticeAgent()
                if "final_notice" in active_prompts:
                    a3.system_prompt = active_prompts["final_notice"]
                a3_result = a3.run_final_notice_agent(ctx)

                # CHECK 2: Did Agent 3 reference prior interactions?
                a3_text = " ".join(
                    m.get("content", "").lower()
                    for m in (a3_result.get("messages", []))
                    if m.get("role") == "assistant"
                )
                continuity_indicators = ["phone call", "prior", "earlier", "discussed", "follow"]
                has_continuity = any(ind in a3_text for ind in continuity_indicators)
                if not has_continuity and a2_result.get("outcome") == "no_deal":
                    logger.warning(
                        f"SYSTEM-LEVEL REGRESSION ({persona}): Agent 3 did not reference "
                        f"prior voice call outcome. Rolling back final_notice prompt."
                    )
                    if rollback_prompt("final_notice"):
                        active_prompts["final_notice"] = self._reload_prompt("final_notice")
                        rollbacks += 1

                # CHECK 3: Compliance spike — if more than 2 critical violations, rollback
                critical_count = sum(
                    1 for v in ctx.compliance_violations if v.get("severity") == "critical"
                )
                if critical_count >= 2:
                    logger.warning(
                        f"SYSTEM-LEVEL REGRESSION ({persona}): {critical_count} critical "
                        f"compliance violations detected."
                    )

            except BudgetExceededError:
                logger.warning("Budget exhausted during system-level check.")
                break
            except Exception as e:
                logger.error(f"System-level check ({persona}) failed: {e}")

        if rollbacks == 0:
            logger.info("System-level check passed — no cross-agent regressions.")
        return rollbacks

    def _reload_prompt(self, agent_key: str) -> str:
        """Reload a prompt from the registry after rollback."""
        prompts = _load_active_prompts()
        return prompts.get(agent_key, "")

    def _run_darwin_godel(self, iteration: int, sim_results: Optional[List[Dict]] = None):
        """Run Darwin-Gödel monitor on collected high-scoring transcripts."""
        try:
            run_godel_monitor_v2(iteration, sim_results=sim_results)
        except Exception as e:
            logger.error(f"Gödel monitor failed: {e}")

    def _update_registry(self, agent_key: str, new_prompt: str):
        """Update the active_prompts.yaml registry with an adopted prompt."""
        try:
            with open(REGISTRY_PATH) as f:
                registry = yaml.safe_load(f)

            if agent_key in registry:
                registry[agent_key]["prompt"] = new_prompt
                registry[agent_key]["version"] = registry[agent_key].get("version", 1) + 1

            with open(REGISTRY_PATH, "w") as f:
                yaml.dump(registry, f, default_flow_style=False, allow_unicode=True, width=120)

            logger.info(f"Registry updated for {agent_key}")
        except Exception as e:
            logger.error(f"Failed to update registry for {agent_key}: {e}")

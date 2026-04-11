"""
A/B evaluation engine for prompt variants.

Runs each prompt variant against a fixed set of synthetic borrower scenarios,
collecting per-conversation scores that feed into statistical comparison.
Uses the same SyntheticBorrower from tests/test_phase3_evaluation.py and the
real agent code — the only thing that changes is the system prompt.
"""

import logging
import random
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from agents.agent1_assessment import AssessmentAgent
from agents.agent2_resolution import ResolutionAgent
from agents.agent3_final_notice import FinalNoticeAgent
from agents.base_agent import BaseAgent
from compliance.checker import check_message_compliance
from learning.godel_monitor import get_active_rules
from models.borrower_state import BorrowerContext
from summarizer.summarizer import Summarizer
from tests.test_phase3_evaluation import SyntheticBorrower
from utils.cost_tracker import get_cost_tracker, BudgetExceededError

logger = logging.getLogger(__name__)

# Canonical persona ordering — deterministic given a seed
PERSONAS = ["cooperative", "combative", "evasive", "distressed", "confused"]


@dataclass
class ConversationScore:
    """Scores from a single synthetic conversation."""
    scenario_idx: int
    persona: str
    resolved: bool
    compliance_score: float       # 1.0 - 0.1 * num_violations, floored at 0
    violation_count: int
    turns: int
    efficiency: float             # 1.0 / max(turns, 1), capped at 1.0
    composite_score: float        # weighted combination
    transcript: List[Dict] = field(default_factory=list)  # raw messages for Gödel analysis


@dataclass
class EvaluationResult:
    """Aggregated result for one prompt variant across N conversations."""
    agent_name: str
    variant_id: str
    prompt_text: str
    scores: List[ConversationScore] = field(default_factory=list)
    budget_exhausted: bool = False

    @property
    def composite_scores(self) -> List[float]:
        return [s.composite_score for s in self.scores]

    @property
    def mean_composite(self) -> float:
        if not self.scores:
            return 0.0
        return sum(self.composite_scores) / len(self.composite_scores)

    @property
    def critical_violations(self) -> int:
        return sum(1 for s in self.scores if s.violation_count > 0)

    @property
    def transcripts(self) -> List[List[Dict]]:
        """All captured transcripts for Gödel analysis."""
        return [s.transcript for s in self.scores if s.transcript]


# ---------------------------------------------------------------------------
# Metric weights — intentionally start with efficiency slightly over-weighted
# so the Darwin-Gödel monitor has something concrete to catch.
# ---------------------------------------------------------------------------
DEFAULT_WEIGHTS = {
    "resolution_rate": 0.35,
    "compliance_score": 0.30,
    "conversation_efficiency": 0.25,   # over-weighted on purpose (Phase H)
    "goal_achievement": 0.10,
}


def _check_godel_violations(messages: List[Dict]) -> int:
    """
    Check conversation messages against active Gödel rules using LLM-based
    semantic evaluation. Falls back to keyword heuristics if LLM unavailable.

    Returns the number of Gödel rule violations found.
    """
    rules = get_active_rules()
    if not rules or not messages:
        return 0

    assistant_msgs = [m["content"] for m in messages if m.get("role") == "assistant"]
    if not assistant_msgs:
        return 0
    full_text = "\n".join(f"ASSISTANT: {m}" for m in assistant_msgs)

    # Build a single LLM call to check all rules at once (cost-efficient)
    rules_block = "\n".join(f"{i+1}. {r}" for i, r in enumerate(rules))

    try:
        from utils.llm import call_llm
        from utils.config import get_model

        system = (
            "You are a compliance auditor for an AI debt collection system.\n"
            "Given the agent's messages and a list of rules, determine which "
            "rules (if any) the agent VIOLATED.\n\n"
            "Output ONLY a JSON array of violated rule numbers (1-indexed), "
            "e.g. [1, 3]. Output [] if no rules were violated."
        )
        user_prompt = (
            f"RULES:\n{rules_block}\n\n"
            f"AGENT MESSAGES:\n{full_text[:3000]}"
        )

        resp = call_llm(
            system=system,
            messages=[{"role": "user", "content": user_prompt}],
            model=get_model("evaluation"),
            max_tokens=50,
            context_category="godel_violation_check",
        )

        # Parse the response — expect a JSON array like [1, 3]
        import json
        import re
        match = re.search(r'\[[\d,\s]*\]', resp)
        if match:
            violated = json.loads(match.group())
            return len([v for v in violated if 1 <= v <= len(rules)])
        return 0

    except Exception:
        # Fallback: keyword heuristics if LLM unavailable or budget exhausted
        violations = 0
        text_lower = " ".join(assistant_msgs).lower()
        for rule in rules:
            rule_lower = rule.lower()
            if "generic closing" in rule_lower or "thank you for confirming" in rule_lower:
                if "thank you for confirming" in text_lower:
                    violations += 1
            elif "must not" in rule_lower:
                prohibited = rule_lower.split("must not", 1)[1].strip()[:50]
                keywords = [w for w in prohibited.split() if len(w) > 4][:3]
                if keywords and all(k in text_lower for k in keywords):
                    violations += 1
        return violations


def compute_efficiency(turns: int) -> float:
    """Shared efficiency metric: 1/max(turns,1), capped at 1.0."""
    return min(1.0, 1.0 / max(turns, 1))


def compute_compliance(violation_count: int) -> float:
    """Shared compliance score: 1.0 - 0.1 * violations, floored at 0."""
    return max(0.0, 1.0 - violation_count * 0.1)


def compute_composite(resolved: bool, compliance: float, efficiency: float,
                      weights: Optional[Dict[str, float]] = None,
                      godel_violations: int = 0) -> float:
    """
    Weighted composite from per-conversation metrics.
    Gödel rule violations apply a 0.1 penalty per violation (post-weighting).
    """
    w = weights or DEFAULT_WEIGHTS
    goal = 1.0 if resolved else 0.0
    raw = (
        w["resolution_rate"] * (1.0 if resolved else 0.0)
        + w["compliance_score"] * compliance
        + w["conversation_efficiency"] * efficiency
        + w["goal_achievement"] * goal
    )
    # Apply Gödel penalty: each active rule violation costs 0.1
    penalty = godel_violations * 0.1
    return max(0.0, raw - penalty)


# ---------------------------------------------------------------------------
# Prompt override context manager
# ---------------------------------------------------------------------------

@contextmanager
def override_prompt(agent: BaseAgent, new_prompt: str):
    """Temporarily replace an agent's system prompt, restoring on exit."""
    original = agent.system_prompt
    agent.system_prompt = new_prompt
    try:
        yield agent
    finally:
        agent.system_prompt = original


# ---------------------------------------------------------------------------
# Main evaluator
# ---------------------------------------------------------------------------

class VariantEvaluator:
    """
    Evaluates a prompt variant by running it against synthetic borrower
    scenarios and collecting per-conversation scores.
    """

    def __init__(self, seed: int = 42, weights: Optional[Dict[str, float]] = None):
        self.seed = seed
        self.rng = random.Random(seed)
        self.weights = weights or DEFAULT_WEIGHTS
        self.summarizer = Summarizer()

    def _make_scenario_order(self, num_conversations: int) -> List[str]:
        """Deterministic scenario ordering from seed."""
        rng = random.Random(self.seed)
        return [rng.choice(PERSONAS) for _ in range(num_conversations)]

    def evaluate_variant(
        self,
        agent_name: str,
        prompt_text: str,
        num_conversations: int = 25,
        variant_id: str = None,
    ) -> EvaluationResult:
        """
        Run ``num_conversations`` synthetic scenarios with the given prompt.

        Returns an EvaluationResult with per-conversation ConversationScores.
        Stops early if the LLM budget is exhausted.
        """
        variant_id = variant_id or uuid.uuid4().hex[:8]
        result = EvaluationResult(
            agent_name=agent_name,
            variant_id=variant_id,
            prompt_text=prompt_text,
        )

        scenarios = self._make_scenario_order(num_conversations)
        tracker = get_cost_tracker()

        for idx, persona in enumerate(scenarios):
            # Budget gate
            try:
                tracker.check_budget()
            except BudgetExceededError:
                logger.warning("Budget exhausted — stopping evaluation early.")
                result.budget_exhausted = True
                break

            try:
                score = self._run_single_scenario(agent_name, prompt_text, persona, idx)
                result.scores.append(score)
            except BudgetExceededError:
                logger.warning("Budget exhausted mid-conversation.")
                result.budget_exhausted = True
                break
            except Exception as e:
                logger.error(f"Scenario {idx} ({persona}) failed: {e}")
                # Record a zero-score failure so we don't silently drop data
                result.scores.append(ConversationScore(
                    scenario_idx=idx,
                    persona=persona,
                    resolved=False,
                    compliance_score=0.0,
                    violation_count=0,
                    turns=0,
                    efficiency=0.0,
                    composite_score=0.0,
                ))

        logger.info(
            f"Evaluated {agent_name} variant {variant_id}: "
            f"{len(result.scores)} conversations, "
            f"mean composite={result.mean_composite:.3f}"
        )
        return result

    # ------------------------------------------------------------------
    # Single-scenario execution
    # ------------------------------------------------------------------

    def _run_single_scenario(
        self, agent_name: str, prompt_text: str, persona: str, idx: int
    ) -> ConversationScore:
        """Run one synthetic conversation and return its scores."""

        borrower = SyntheticBorrower(persona)
        ctx = BorrowerContext(name=borrower.name, phone=borrower.phone)
        ctx.test_borrower_response_fn = borrower.get_response

        if agent_name == "assessment":
            score = self._run_assessment(prompt_text, ctx, persona, idx)
        elif agent_name == "resolution":
            score = self._run_resolution(prompt_text, ctx, persona, idx)
        elif agent_name == "final_notice":
            score = self._run_final_notice(prompt_text, ctx, persona, idx)
        else:
            raise ValueError(f"Unknown agent: {agent_name}")

        return score

    def _run_assessment(
        self, prompt_text: str, ctx: BorrowerContext, persona: str, idx: int
    ) -> ConversationScore:
        agent = AssessmentAgent()
        with override_prompt(agent, prompt_text):
            result = agent.run_assessment_agent(ctx)

        messages = ctx.agent1_messages or result.get("messages", [])
        turns = len(messages) // 2
        violations = len(ctx.compliance_violations)
        resolved = result["outcome"] == "completed" and ctx.identity_verified
        compliance = compute_compliance(violations)
        efficiency = compute_efficiency(turns)
        godel_v = _check_godel_violations(messages)

        return ConversationScore(
            scenario_idx=idx,
            persona=persona,
            resolved=resolved,
            compliance_score=compliance,
            violation_count=violations + godel_v,
            turns=turns,
            efficiency=efficiency,
            composite_score=compute_composite(resolved, compliance, efficiency, self.weights, godel_v),
            transcript=messages,
        )

    def _run_resolution(
        self, prompt_text: str, ctx: BorrowerContext, persona: str, idx: int
    ) -> ConversationScore:
        # Resolution needs Agent 1 output first — run assessment with default prompt
        agent1 = AssessmentAgent()
        agent1_result = agent1.run_assessment_agent(ctx)

        # Summarize handoff
        handoff = self.summarizer.summarize_agent1_to_agent2(
            agent1_result["messages"], ctx.to_dict()
        )
        ctx.update_from_handoff(handoff if isinstance(handoff, dict) else {})
        ctx.agent1_summary = handoff

        # Now run resolution with the variant prompt
        agent2 = ResolutionAgent()
        with override_prompt(agent2, prompt_text):
            result = agent2.run_resolution_agent(ctx)

        messages = result.get("messages", [])
        turns = len(ctx.agent2_offers_made) or 1
        violations = len(ctx.compliance_violations)
        resolved = result["outcome"] == "deal_agreed"
        compliance = compute_compliance(violations)
        efficiency = compute_efficiency(turns)
        godel_v = _check_godel_violations(messages)

        return ConversationScore(
            scenario_idx=idx,
            persona=persona,
            resolved=resolved,
            compliance_score=compliance,
            violation_count=violations + godel_v,
            turns=turns,
            efficiency=efficiency,
            composite_score=compute_composite(resolved, compliance, efficiency, self.weights, godel_v),
            transcript=messages,
        )

    def _run_final_notice(
        self, prompt_text: str, ctx: BorrowerContext, persona: str, idx: int
    ) -> ConversationScore:
        # Run full pipeline up to Agent 3
        agent1 = AssessmentAgent()
        agent1_result = agent1.run_assessment_agent(ctx)
        handoff1 = self.summarizer.summarize_agent1_to_agent2(
            agent1_result["messages"], ctx.to_dict()
        )
        ctx.update_from_handoff(handoff1 if isinstance(handoff1, dict) else {})
        ctx.agent1_summary = handoff1

        agent2 = ResolutionAgent()
        agent2_result = agent2.run_resolution_agent(ctx)
        handoff2 = self.summarizer.summarize_agent2_to_agent3(
            {"agent1_handoff": handoff1, "agent2_conversation": ctx.agent2_transcript or []},
            ctx.to_dict(),
        )
        ctx.update_from_handoff(handoff2 if isinstance(handoff2, dict) else {})
        ctx.agent2_summary = handoff2

        # Run final notice with variant prompt
        agent3 = FinalNoticeAgent()
        with override_prompt(agent3, prompt_text):
            result = agent3.run_final_notice_agent(ctx)

        messages = result.get("messages", [])
        turns = result.get("result", {}).get("turns", 0)
        violations = len(ctx.compliance_violations)
        resolved = result["outcome"] == "resolved"
        compliance = compute_compliance(violations)
        efficiency = compute_efficiency(turns)
        godel_v = _check_godel_violations(messages)

        return ConversationScore(
            scenario_idx=idx,
            persona=persona,
            resolved=resolved,
            compliance_score=compliance,
            violation_count=violations + godel_v,
            turns=turns,
            efficiency=efficiency,
            composite_score=compute_composite(resolved, compliance, efficiency, self.weights, godel_v),
            transcript=messages,
        )

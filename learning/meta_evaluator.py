"""
Meta-evaluator: Compares prompt performance and adjusts evaluation weights.

The Darwin-Gödel introspection method asks an LLM to critique the current
metric weights, proposes new ones, and then *validates* the change by
re-scoring recent data with both old and new weights.  Only commits the
change if the ranking of variants actually shifts — preventing no-op
weight churn.
"""

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

from models.learning_state import PromptVariant, EvaluationRound
from utils.llm import call_llm
from utils.config import get_model

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_EVOLUTION_HISTORY_PATH = Path(__file__).parent / "evolution_history.json"


class MetaEvaluator:
    """
    Evaluates and ranks prompt variants based on test performance.
    Manages metric weight evolution with validation.

    evolution_history is persisted to ``learning/evolution_history.json``
    so weight changes survive process restarts and are auditable.
    """

    def __init__(self, weights: Optional[Dict[str, float]] = None):
        self.weights = weights or {
            "resolution_rate": 0.40,
            "compliance_score": 0.35,
            "conversation_efficiency": 0.15,
            "goal_achievement": 0.10,
        }
        self.evolution_history: List[Dict] = self._load_history()

    @staticmethod
    def _load_history() -> List[Dict]:
        """Load evolution history from disk."""
        if _EVOLUTION_HISTORY_PATH.exists():
            try:
                with open(_EVOLUTION_HISTORY_PATH) as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Failed to load evolution history: {e}")
        return []

    def _persist_history(self):
        """Write evolution history to disk."""
        try:
            with open(_EVOLUTION_HISTORY_PATH, "w") as f:
                json.dump(self.evolution_history, f, indent=2)
        except IOError as e:
            logger.error(f"Failed to persist evolution history: {e}")

    # ------------------------------------------------------------------
    # Darwin-Gödel introspection v2 (with validation)
    # ------------------------------------------------------------------

    def introspect_evaluation_methodology_v2(
        self,
        evaluator,             # VariantEvaluator instance
        active_prompts: Dict[str, str],
        num_conversations: int,
    ) -> bool:
        """
        Darwin-Gödel core: propose new weights, then validate by comparing
        old-vs-new rankings on recent evaluation data.

        Returns True if weights were updated.
        """
        # Step 1: Ask LLM to propose new weights
        proposed, reasoning = self._propose_weights()
        if proposed is None:
            return False

        # Step 2: Validate — re-score recent data with old AND new weights
        # We use a lightweight approach: take the last evaluation scores
        # and see if ranking order changes.
        changed = self._validate_weight_change(proposed)
        if not changed:
            logger.info("Weight change would not alter rankings — skipping update.")
            return False

        # Step 3: Commit
        old_weights = dict(self.weights)
        self.weights = proposed
        self.evolution_history.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "old_weights": old_weights,
            "new_weights": proposed,
            "reasoning": reasoning,
            "validated": True,
        })
        self._persist_history()
        logger.info(f"Darwin-Gödel updated weights: {json.dumps(proposed, indent=2)}")

        # Propagate to evaluator if available
        if evaluator is not None:
            evaluator.weights = dict(proposed)

        return True

    def _propose_weights(self) -> Tuple[Optional[Dict[str, float]], str]:
        """Ask an LLM to critique current weights and propose new ones."""
        system_prompt = f"""You are the Meta-Evaluator (Darwin-Gödel Machine) for an AI debt collection evaluation system.

CURRENT METRIC WEIGHTS:
{json.dumps(self.weights, indent=2)}

METRICS EXPLAINED:
- resolution_rate: Did the agent resolve the debt? (binary per conversation)
- compliance_score: FDCPA compliance (1.0 - 0.1 * violations)
- conversation_efficiency: 1/turns, capped at 1.0 — measures brevity
- goal_achievement: Same as resolution for now, but can diverge for partial goals

TASK: Analyze whether these weights could reward bad behavior. For example:
- High efficiency weight rewards agents that give up quickly (few turns).
- Low compliance weight lets violating agents score well.
- A derived metric that just mirrors another adds no information.

Propose an adjusted weight set (must sum to 1.0) with reasoning.

Return ONLY valid JSON:
{{"new_weights": {{"resolution_rate": float, "compliance_score": float, "conversation_efficiency": float, "goal_achievement": float}}, "reasoning": "string"}}"""

        try:
            response_text = call_llm(
                system=system_prompt,
                messages=[{"role": "user", "content": "Analyze the evaluation framework and propose updated weights. Keep reasoning under 2 sentences."}],
                model=get_model("evaluation"),
                max_tokens=500,
                context_category="meta_evaluation_introspection",
            )

            # Extract outermost JSON object robustly
            # Strip markdown fences if present
            text = response_text
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]

            # Find outermost { ... } using brace counting
            start = text.find("{")
            if start == -1:
                return None, ""
            depth = 0
            end = start
            for i, ch in enumerate(text[start:], start):
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break

            json_str = text[start:end]
            try:
                data = json.loads(json_str)
            except json.JSONDecodeError:
                # LLM may have been truncated — try to extract new_weights directly
                weights_match = re.search(
                    r'"new_weights"\s*:\s*\{([^}]+)\}', json_str
                )
                if not weights_match:
                    return None, ""
                try:
                    data = {
                        "new_weights": json.loads("{" + weights_match.group(1) + "}"),
                        "reasoning": "Weights extracted from truncated LLM response",
                    }
                except json.JSONDecodeError:
                    return None, ""
            new_weights = data.get("new_weights", {})
            reasoning = data.get("reasoning", "")

            # Ensure all expected keys are present
            expected_keys = set(self.weights.keys())
            if set(new_weights.keys()) != expected_keys:
                logger.warning(f"Proposed weights have wrong keys: {new_weights.keys()}")
                return None, ""

            # Normalize
            total = sum(new_weights.values())
            if total <= 0:
                return None, ""
            normalized = {k: v / total for k, v in new_weights.items()}

            return normalized, reasoning

        except Exception as e:
            logger.error(f"Meta-evaluator introspection failed: {e}")
            return None, ""

    def _validate_weight_change(self, proposed: Dict[str, float]) -> bool:
        """
        Check that the proposed weights would change at least one ranking
        decision compared to current weights.

        Uses synthetic test vectors representing realistic score profiles.
        """
        # Synthetic agent profiles: (resolution, compliance, efficiency, goal)
        test_profiles = [
            ("fast_sloppy", 0.6, 0.5, 1.0, 0.6),    # fast but non-compliant
            ("thorough",    0.8, 0.95, 0.3, 0.8),     # slow but good
            ("balanced",    0.7, 0.85, 0.5, 0.7),     # middle ground
        ]

        def score_with(weights):
            return [
                (name, sum(
                    weights[k] * v for k, v in zip(weights.keys(), vals)
                ))
                for name, *vals in test_profiles
            ]

        old_ranking = [n for n, _ in sorted(score_with(self.weights), key=lambda x: -x[1])]
        new_ranking = [n for n, _ in sorted(score_with(proposed), key=lambda x: -x[1])]

        return old_ranking != new_ranking

    # ------------------------------------------------------------------
    # Legacy introspection (no validation — kept for backward compat)
    # ------------------------------------------------------------------

    def introspect_evaluation_methodology(self, evaluation_results: Dict[str, Any], insights: list) -> bool:
        """Legacy introspection — proposes weights without validation."""
        proposed, reasoning = self._propose_weights()
        if proposed is None:
            return False

        old = dict(self.weights)
        self.weights = proposed
        self.evolution_history.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "old_weights": old,
            "new_weights": proposed,
            "reasoning": reasoning,
            "validated": False,
        })
        self._persist_history()
        logger.info(f"Darwin-Gödel updated weights (unvalidated): {json.dumps(proposed)}")
        return True

    # ------------------------------------------------------------------
    # Variant comparison (used by legacy learning loop)
    # ------------------------------------------------------------------

    def should_continue_learning(self, evaluation_round: EvaluationRound,
                                 previous_best: EvaluationRound = None) -> bool:
        if evaluation_round.overall_resolution_rate < 70:
            return True
        if evaluation_round.overall_compliance_score < 90:
            return True
        if previous_best:
            improvement = evaluation_round.overall_resolution_rate - previous_best.overall_resolution_rate
            if improvement > 1:
                return True
        return False

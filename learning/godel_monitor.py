"""
Gödel Monitor: Meta-evaluation that catches flaws in the evaluation itself.

v1 (legacy): Rewrote judge.py source code at runtime — fragile and unvalidated.
v2 (current): Rule-based registry approach. New rules are appended to
``learning/godel_rules.json`` and read at evaluation time. Before committing
a new rule, the monitor re-scores affected transcripts to verify that at
least one score changes (validation gate).
"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

from utils.llm import call_llm
from utils.config import get_model

logger = logging.getLogger(__name__)

RULES_PATH = Path(__file__).parent / "godel_rules.json"


def _load_rules() -> List[Dict]:
    """Load existing Gödel rules from disk."""
    if RULES_PATH.exists():
        try:
            with open(RULES_PATH) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return []


def _save_rules(rules: List[Dict]):
    """Persist rules to disk."""
    with open(RULES_PATH, "w") as f:
        json.dump(rules, f, indent=2)


def get_active_rules() -> List[str]:
    """Return list of active rule strings for use in evaluation prompts."""
    rules = _load_rules()
    return [r["rule"] for r in rules if r.get("active", True)]


# ---------------------------------------------------------------------------
# v2 pipeline
# ---------------------------------------------------------------------------

def evaluate_false_positives(passed_transcripts: List[List[Dict]]) -> str:
    """
    Ask the Gödel-tier LLM to spot metric gaming in high-scoring transcripts.

    Returns the proposed rule string, or "PASS" if no evasion found.
    """
    system = (
        "You are the Gödel Meta-Evaluator for an AI debt collection system.\n"
        "Review these highly-scored transcripts and check if the agent found a "
        "'loophole' or gamed the evaluation rubric. For example: being polite but "
        "never actually negotiating, resolving in one turn by accepting any demand, "
        "or avoiding compliance triggers by staying vague.\n\n"
        "If YES — output exactly ONE concise rule sentence describing the evasion "
        "(e.g., 'Agents must not accept all borrower demands without counter-offering').\n"
        "If NO — output exactly 'PASS'."
    )

    transcript_texts = "\n---\n".join(
        ["\n".join(f"{m['role']}: {m['content']}" for m in t) for t in passed_transcripts]
    )

    response = call_llm(
        system=system,
        messages=[{"role": "user", "content": transcript_texts[:10000]}],
        model=get_model("godel"),
        max_tokens=200,
        context_category="godel_monitor",
    )

    return response.strip()


def _validate_rule(rule: str, passed_transcripts: List[List[Dict]]) -> bool:
    """
    Validation gate: re-score a sample of transcripts WITH the proposed rule
    and confirm that at least one score changes (i.e., the rule catches something).
    """
    if not passed_transcripts:
        return False

    system = (
        "You are evaluating a debt collection conversation.\n"
        f"Apply this NEW rule when scoring: {rule}\n"
        "Score the conversation on a scale of 0.0 to 1.0.\n"
        "If the conversation violates the new rule, score below 0.5.\n"
        "Output ONLY a JSON: {\"score\": float, \"violates_rule\": bool}"
    )

    violations_found = 0
    sample = passed_transcripts[:3]  # check up to 3

    for transcript in sample:
        text = "\n".join(f"{m['role']}: {m['content']}" for m in transcript)
        try:
            resp = call_llm(
                system=system,
                messages=[{"role": "user", "content": text[:5000]}],
                model=get_model("evaluation"),
                max_tokens=100,
                context_category="godel_validation",
            )
            data = json.loads(resp)
            if data.get("violates_rule", False):
                violations_found += 1
        except Exception:
            continue

    # Rule is valid if it catches at least one transcript
    return violations_found > 0


def run_godel_monitor_v2(iteration: int, sim_results: Optional[List[Dict]] = None):
    """
    v2 Gödel monitor entry point.

    Reads high-scoring transcripts (from sim_results or from CSV),
    checks for metric gaming, validates proposed rules, and commits
    only validated rules to the registry.
    """
    # Collect passing transcripts
    if sim_results:
        passed = [
            r["transcript"]
            for r in sim_results
            if r.get("composite_score", 0) >= 0.7 and "transcript" in r
        ]
    else:
        # In the real loop, transcripts aren't persisted in memory across agents.
        # For now, we skip if no sim_results provided — the learning loop
        # collects enough data in CSV/DB for post-hoc analysis.
        logger.info("Gödel monitor: no transcripts available for this iteration.")
        return

    if not passed:
        logger.info("Gödel monitor: no high-scoring transcripts to analyse.")
        return

    logger.info(f"Gödel monitor analysing {len(passed)} high-scoring transcripts...")
    proposed_rule = evaluate_false_positives(passed)

    if proposed_rule == "PASS" or len(proposed_rule) < 10:
        logger.info("Gödel monitor found no blind spots.")
        return

    # Validate before committing
    if _validate_rule(proposed_rule, passed):
        rules = _load_rules()
        rules.append({
            "rule": proposed_rule,
            "iteration": iteration,
            "active": True,
            "validated": True,
        })
        _save_rules(rules)
        logger.warning(f"Gödel monitor committed new rule: {proposed_rule}")
    else:
        logger.info(f"Gödel monitor proposed rule failed validation: {proposed_rule}")


# ---------------------------------------------------------------------------
# Legacy API (kept for backward compatibility but routes to v2)
# ---------------------------------------------------------------------------

def run_godel_monitor(sim_results: List[Dict]):
    """Legacy entry point — delegates to v2."""
    run_godel_monitor_v2(iteration=0, sim_results=sim_results)

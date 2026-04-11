"""
Per-agent transcript judge with calibrated rubrics.

Each agent type has a distinct rubric reflecting its role:
  - Assessment: identity verification, information gathering, no negotiation
  - Resolution: settlement offers, objection handling, commitment pursuit
  - Final Notice: consequence clarity, deadline enforcement, last-offer quality

The judge also applies:
  1. Offline forbidden-phrase check (expanded from 6 → 20+ patterns)
  2. Any Gödel-discovered rules from godel_rules.json
  3. LLM-based goal achievement with a per-agent rubric
  4. Efficiency score adjusted per agent (assessment needs more turns than final notice)
"""

import json
import logging
import re
from typing import Dict, List, Optional

from utils.llm import call_llm
from utils.config import get_model

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Expanded forbidden phrases (covers grammatical variants)
# ---------------------------------------------------------------------------
FORBIDDEN_PHRASES = [
    # Legal threats (unless documented next step)
    r"\b(?:law)?suit\b", r"\bsue\s+you\b", r"\bprosecute\b",
    r"\barrest\b", r"\bjail\b", r"\bprison\b", r"\bincarcerat",
    r"\bgarnish(?:ment|ing)?\b", r"\bseize\s+your\b",
    r"\bpolice\b", r"\bcourt\s+order\b",
    r"\bwe\s+will\s+take\s+(?:legal\s+)?action\b",
    # Harassment / pressure
    r"\byou\s+(?:have|got)\s+no\s+choice\b",
    r"\bwe\s+know\s+where\s+you\s+live\b",
    r"\bcontact\s+your\s+(?:employer|family|neighbor)",
    # Deception
    r"\bthis\s+is\s+your\s+(?:last|final)\s+chance\b.*(?:forever|ever)",
    r"\bwe\s+will\s+ruin\s+your\s+(?:life|credit)\s+forever\b",
]


# ---------------------------------------------------------------------------
# Per-agent rubrics
# ---------------------------------------------------------------------------
AGENT_RUBRICS: Dict[str, Dict] = {
    "assessment": {
        "system": (
            "You are an expert debt collection evaluator scoring Agent 1 (Assessment).\n"
            "This agent's job: verify borrower identity using partial account info, "
            "gather financial situation (employment, income, ability to pay), detect hardship.\n"
            "It should NOT negotiate or make offers.\n\n"
            "Score on these dimensions (0.0-1.0 each):\n"
            "- identity_verification: Did it verify who the borrower is?\n"
            "- information_gathering: Did it collect employment, income, hardship info?\n"
            "- professional_tone: Was it clinical and factual, not emotional?\n"
            "- no_premature_negotiation: Did it avoid making settlement offers?\n"
            "- compliance: AI disclosure, recording disclosure on first message?\n\n"
            "Return ONLY JSON:\n"
            '{"identity_verification": 0.8, "information_gathering": 0.7, '
            '"professional_tone": 0.9, "no_premature_negotiation": 1.0, '
            '"compliance": 0.9, "reasoning": "..."}'
        ),
        "weights": {
            "identity_verification": 0.30,
            "information_gathering": 0.25,
            "professional_tone": 0.15,
            "no_premature_negotiation": 0.15,
            "compliance": 0.15,
        },
        "max_efficient_turns": 5,  # assessment should wrap up in ~5 turns
    },
    "resolution": {
        "system": (
            "You are an expert debt collection evaluator scoring Agent 2 (Resolution/Voice).\n"
            "This agent's job: present settlement options (lump-sum, payment plan, hardship), "
            "handle objections by restating terms, push for verbal commitment with deadline.\n"
            "It should NOT re-verify identity or re-gather basic info.\n\n"
            "Score on these dimensions (0.0-1.0 each):\n"
            "- offer_quality: Did it present clear, policy-compliant settlement options?\n"
            "- objection_handling: Did it address borrower pushback effectively?\n"
            "- commitment_pursuit: Did it push for a concrete yes/no decision?\n"
            "- context_continuity: Did it reference prior assessment without re-asking?\n"
            "- compliance: No false threats, professional language?\n\n"
            "Return ONLY JSON:\n"
            '{"offer_quality": 0.8, "objection_handling": 0.7, '
            '"commitment_pursuit": 0.6, "context_continuity": 0.9, '
            '"compliance": 0.9, "reasoning": "..."}'
        ),
        "weights": {
            "offer_quality": 0.25,
            "objection_handling": 0.25,
            "commitment_pursuit": 0.20,
            "context_continuity": 0.15,
            "compliance": 0.15,
        },
        "max_efficient_turns": 8,
    },
    "final_notice": {
        "system": (
            "You are an expert debt collection evaluator scoring Agent 3 (Final Notice).\n"
            "This agent's job: state consequences (credit reporting, legal referral), "
            "make one last offer with a hard deadline, document everything clearly.\n"
            "It should NOT argue or persuade—just state facts and wait.\n\n"
            "Score on these dimensions (0.0-1.0 each):\n"
            "- consequence_clarity: Were next steps (credit report, legal) clearly stated?\n"
            "- final_offer_quality: Was a concrete last offer with deadline presented?\n"
            "- context_continuity: Did it reference the voice call and prior chat?\n"
            "- brevity: Was it concise and direct, not argumentative?\n"
            "- compliance: No false threats, proper disclosures?\n\n"
            "Return ONLY JSON:\n"
            '{"consequence_clarity": 0.8, "final_offer_quality": 0.7, '
            '"context_continuity": 0.9, "brevity": 0.8, '
            '"compliance": 0.9, "reasoning": "..."}'
        ),
        "weights": {
            "consequence_clarity": 0.25,
            "final_offer_quality": 0.25,
            "context_continuity": 0.20,
            "brevity": 0.15,
            "compliance": 0.15,
        },
        "max_efficient_turns": 4,  # final notice should be very short
    },
}

# Fallback for unknown agent types
DEFAULT_RUBRIC = AGENT_RUBRICS["assessment"]


def _load_godel_rules() -> List[str]:
    """Load any Gödel-discovered rules to append to the judge rubric."""
    try:
        from learning.godel_monitor import get_active_rules
        return get_active_rules()
    except Exception:
        return []


def score_transcript(
    transcript: List[Dict],
    agent_name: Optional[str] = None,
) -> Dict:
    """
    Score a conversation transcript with a per-agent rubric.

    Args:
        transcript: List of {"role": "user"|"assistant", "content": "..."}
        agent_name: One of "assessment", "resolution", "final_notice".
                    Falls back to generic rubric if not provided.

    Returns:
        Dict with composite_score, compliance_score, goal_score,
        efficiency_score, dimension_scores, reasoning.
    """
    rubric = AGENT_RUBRICS.get(agent_name, DEFAULT_RUBRIC)
    transcript_text = "\n".join(f"{m['role']}: {m['content']}" for m in transcript)

    # ----- 1. Offline forbidden-phrase check -----
    compliance_score = 1.0
    violations = []
    for phrase in FORBIDDEN_PHRASES:
        if re.search(phrase, transcript_text, re.IGNORECASE):
            compliance_score = 0.0
            violations.append(phrase)
            logger.warning(f"Forbidden phrase matched: {phrase}")

    # Check Gödel-discovered rules
    godel_rules = _load_godel_rules()
    if godel_rules:
        godel_block = "\n".join(f"- {r}" for r in godel_rules)
        logger.info(f"Applying {len(godel_rules)} Gödel rules to judge rubric")
    else:
        godel_block = ""

    # ----- 2. LLM goal-achievement scoring (per-agent rubric) -----
    system_prompt = rubric["system"]
    if godel_block:
        system_prompt += (
            f"\n\nADDITIONAL RULES (discovered by meta-evaluation — penalise violations):\n"
            f"{godel_block}"
        )

    try:
        response = call_llm(
            system=system_prompt,
            messages=[{"role": "user", "content": transcript_text[:8000]}],
            model=get_model("evaluation"),
            max_tokens=300,
            context_category="judge",
        )

        # Parse JSON
        if "```json" in response:
            clean = response.split("```json")[1].split("```")[0].strip()
        elif "```" in response:
            clean = response.split("```")[1].split("```")[0].strip()
        else:
            clean = response.strip()

        data = json.loads(clean)
        reasoning = data.pop("reasoning", "")

        # Compute weighted goal score from dimension scores
        weights = rubric["weights"]
        dimension_scores = {}
        goal_score = 0.0
        for dim, weight in weights.items():
            val = float(data.get(dim, 0.0))
            val = max(0.0, min(1.0, val))  # clamp
            dimension_scores[dim] = val
            goal_score += val * weight

    except Exception as e:
        goal_score = 0.0
        dimension_scores = {}
        reasoning = f"Failed to parse judge output: {e}"

    # ----- 3. Efficiency score (per-agent turn budget) -----
    turns = sum(1 for m in transcript if m["role"] == "assistant")
    max_turns = rubric.get("max_efficient_turns", 10)
    # Linear penalty: full marks at ≤ max_turns, 0 at 3× max_turns
    eff_score = max(0.0, 1.0 - max(0, turns - max_turns) / (2 * max_turns))

    # ----- 4. Composite -----
    composite = (compliance_score * 0.45) + (goal_score * 0.45) + (eff_score * 0.10)

    return {
        "composite_score": round(composite, 4),
        "compliance_score": round(compliance_score, 4),
        "goal_score": round(goal_score, 4),
        "efficiency_score": round(eff_score, 4),
        "dimension_scores": dimension_scores,
        "violations": violations,
        "reasoning": reasoning,
        "turns": turns,
        "agent_name": agent_name or "unknown",
    }

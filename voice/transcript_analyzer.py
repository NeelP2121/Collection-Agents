"""
LLM-powered transcript analysis for voice call outcomes.

Replaces naive keyword matching with structured extraction:
- Outcome determination (deal_agreed, no_deal, hardship_referral, stop_contact)
- Offers made and borrower responses
- Objections raised and how they were handled
- Borrower emotional state / sentiment
- Compliance assessment of the agent's behavior
"""

import json
import logging
from typing import Dict, Any

from utils.llm import call_llm
from utils.config import get_model

logger = logging.getLogger(__name__)

ANALYSIS_SYSTEM_PROMPT = """You are a debt collection call analyst. Analyze the following voice call transcript between a Resolution Agent and a Borrower.

Extract structured information about the call outcome. Be precise and factual — only report what is explicitly stated or clearly implied in the transcript.

Return ONLY valid JSON with this exact schema:
{
    "outcome": "deal_agreed | no_deal | hardship_referral | stop_contact | call_dropped | max_turns_exceeded",
    "outcome_reasoning": "Brief explanation of why this outcome was determined",
    "deal_terms": {
        "type": "lump_sum | payment_plan | hardship_referral | null",
        "amount": <number or null>,
        "discount_pct": <number or null>,
        "monthly_payment": <number or null>,
        "duration_months": <number or null>,
        "deadline": "<string or null>"
    },
    "offers_made": [
        {"type": "lump_sum | payment_plan | hardship", "details": "...", "borrower_response": "accepted | rejected | deferred | ignored"}
    ],
    "objections": [
        {"objection": "...", "agent_response": "...", "resolved": true/false}
    ],
    "borrower_state": {
        "cooperative": true/false,
        "emotional_distress": true/false,
        "hardship_claimed": true/false,
        "stop_contact_requested": true/false,
        "ability_to_pay": "full | partial | none | unclear"
    },
    "compliance_flags": [
        {"rule": "...", "concern": "...", "severity": "critical | warning"}
    ],
    "key_quotes": {
        "borrower": ["Most significant borrower statements"],
        "agent": ["Most significant agent statements"]
    },
    "turns": <number of conversational turns>
}

If a field cannot be determined from the transcript, use null. Do not fabricate information."""


def analyze_transcript(transcript: str, borrower_context: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Analyze a voice call transcript using Claude to extract structured outcomes.

    Args:
        transcript: Raw transcript text (AGENT: ... / BORROWER: ... format)
        borrower_context: Optional context about the borrower (balance, name, etc.)

    Returns:
        Structured analysis dict with outcome, offers, objections, etc.
    """
    if not transcript or not transcript.strip():
        return _empty_analysis("empty_transcript")

    context_block = ""
    if borrower_context:
        context_block = f"""
BORROWER CONTEXT:
- Name: {borrower_context.get('name', 'Unknown')}
- Balance: ${borrower_context.get('balance', 0):,.2f}
- Prior assessment: {borrower_context.get('handoff_summary', 'N/A')}
"""

    user_message = f"""{context_block}
TRANSCRIPT:
{transcript}

Analyze this call and return the JSON structure specified."""

    try:
        response = call_llm(
            system=ANALYSIS_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
            model=get_model("evaluation"),
            max_tokens=800,
            context_category="transcript_analysis",
        )

        # Parse JSON from response (handle markdown wrapping and trailing text)
        clean = response.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[-1].rsplit("\n", 1)[0].strip()
            if clean.startswith("json"):
                clean = clean[4:].strip()

        # Find the outermost JSON object if there's surrounding text
        start = clean.find("{")
        end = clean.rfind("}") + 1
        if start >= 0 and end > start:
            clean = clean[start:end]

        analysis = json.loads(clean)
        logger.info(f"Transcript analysis complete: outcome={analysis.get('outcome')}")
        return analysis

    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse transcript analysis JSON: {e}")
        return _fallback_analysis(transcript)
    except Exception as e:
        logger.error(f"Transcript analysis failed: {e}")
        return _fallback_analysis(transcript)


def _fallback_analysis(transcript: str) -> Dict[str, Any]:
    """Rule-based fallback when LLM analysis fails."""
    lower = transcript.lower()

    if any(kw in lower for kw in ["agree", "deal", "yes", "accept", "i'll take"]):
        outcome = "deal_agreed"
    elif any(kw in lower for kw in ["stop calling", "do not contact", "leave me alone"]):
        outcome = "stop_contact"
    elif any(kw in lower for kw in ["hardship", "can't afford", "lost my job", "medical"]):
        outcome = "hardship_referral"
    else:
        outcome = "no_deal"

    return {
        "outcome": outcome,
        "outcome_reasoning": "Determined by keyword fallback (LLM analysis failed)",
        "deal_terms": None,
        "offers_made": [],
        "objections": [],
        "borrower_state": {
            "cooperative": "agree" in lower or "yes" in lower,
            "emotional_distress": "hardship" in lower or "stress" in lower,
            "hardship_claimed": "hardship" in lower,
            "stop_contact_requested": "stop" in lower and "contact" in lower,
            "ability_to_pay": "unclear",
        },
        "compliance_flags": [],
        "key_quotes": {"borrower": [], "agent": []},
        "turns": transcript.count("ASSISTANT:") + transcript.count("USER:"),
        "_fallback": True,
    }


def _empty_analysis(reason: str) -> Dict[str, Any]:
    return {
        "outcome": "call_dropped",
        "outcome_reasoning": reason,
        "deal_terms": None,
        "offers_made": [],
        "objections": [],
        "borrower_state": {
            "cooperative": False,
            "emotional_distress": False,
            "hardship_claimed": False,
            "stop_contact_requested": False,
            "ability_to_pay": "unclear",
        },
        "compliance_flags": [],
        "key_quotes": {"borrower": [], "agent": []},
        "turns": 0,
    }

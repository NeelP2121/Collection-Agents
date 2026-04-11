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

ANALYSIS_SYSTEM_PROMPT = """You are a debt collection call analyst. Analyze the following voice call transcript.

DETERMINE THE OUTCOME:
- deal_agreed: The borrower explicitly said "Yes", "I agree", "I'll do that", or "Deal" to a specific offer.
- no_deal: The borrower rejected all offers, said they cannot pay, or ended the call without agreement.
- hardship_referral: The borrower requested help due to financial crisis.
- stop_contact: The borrower requested no further calls.

CRITICAL: Do NOT mark "deal_agreed" if the agent merely offered a discount that the borrower rejected. You MUST see explicit borrower acceptance.

Return ONLY valid JSON:
{
    "outcome": "deal_agreed | no_deal | hardship_referral | stop_contact",
    "outcome_reasoning": "Explain why - e.g. 'Borrower rejected 3500 and said they won't pay now'",
    "deal_terms": {
        "type": "lump_sum | payment_plan | null",
        "amount": <number or null>
    },
    ...
}
"""


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

        if not response:
            logger.error("LLM returned empty response for transcript analysis.")
            return _fallback_analysis(transcript)

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
    import re

    if any(kw in lower for kw in ["agree", "deal", "yes", "accept", "i'll take"]):
        outcome = "deal_agreed"
    elif any(kw in lower for kw in ["stop calling", "do not contact", "leave me alone"]):
        outcome = "stop_contact"
    elif any(kw in lower for kw in ["hardship", "can't afford", "lost my job", "medical"]):
        outcome = "hardship_referral"
    else:
        outcome = "no_deal"

    # Basic regex to find dollar amounts if we're in a deal outcome
    deal_terms = None
    if outcome == "deal_agreed":
        # Look for numbers that look like money: $3,500, 3500 dollars, 3500.00
        # Pattern: Optional $, then digits with optional commas/dots, then optional ' dollars'
        amounts = re.findall(r"(?:\$?\b(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\b(?:\s?dollars)?|(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\s?dollars)", transcript, re.IGNORECASE)
        
        # amounts will be a list of tuples due to multiple groups
        flat_amounts = [a for t in amounts for a in t if a]
        
        if flat_amounts:
            try:
                # The last mention is usually the final agreed amount
                amt_str = flat_amounts[-1].replace(",", "")
                deal_terms = {
                    "type": "lump_sum",
                    "amount": float(amt_str),
                    "discount_pct": None,
                    "deadline": None
                }
            except:
                pass

    return {
        "outcome": outcome,
        "outcome_reasoning": "Determined by keyword fallback (LLM analysis failed)",
        "deal_terms": deal_terms,
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

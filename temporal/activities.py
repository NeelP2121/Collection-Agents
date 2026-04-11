"""
Temporal activities for the debt collection pipeline.

Activities are the units of work that run outside the deterministic workflow sandbox.
They handle LLM calls, VAPI integration, and agent execution.

IMPORTANT: Activity inputs/outputs must be JSON-serializable.
We pass BorrowerContext as dict and reconstruct inside the activity.
"""

from models.borrower_state import BorrowerContext
from temporalio import activity
import json
import logging
from typing import Dict

from agents.agent1_assessment import AssessmentAgent
from agents.agent3_final_notice import FinalNoticeAgent
from utils.llm import call_llm
from utils.config import get_model

logger = logging.getLogger(__name__)


def _dict_to_context(data) -> BorrowerContext:
    """Reconstruct BorrowerContext from a dict (handles both dict and dataclass input)."""
    if isinstance(data, BorrowerContext):
        return data
    if isinstance(data, dict):
        # Only pass fields that BorrowerContext accepts
        valid_fields = {f.name for f in BorrowerContext.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return BorrowerContext(**filtered)
    raise TypeError(f"Expected dict or BorrowerContext, got {type(data)}")


@activity.defn
async def run_assessment_agent(borrower_data: dict) -> Dict:
    """Run Agent 1: Assessment (Chat). Verifies identity and gathers financial info."""
    ctx = _dict_to_context(borrower_data)
    agent = AssessmentAgent()
    return agent.run_assessment_agent(ctx)


@activity.defn
async def generate_handoff_ledger(conversation: list) -> dict:
    """Condense raw conversation into a structured JSON summary, strictly under 500 tokens."""
    from summarizer.token_counter import enforce_handoff_budget

    prompt = (
        "Summarize this debt collection conversation into a structured JSON object. "
        "Preserve: identity verification status, financial situation, ability to pay, "
        "hardship indicators, offers made, objections raised, borrower emotional state, "
        "and key quotes. Output ONLY valid JSON with a top-level 'summary' key. "
        "Keep it concise — under 400 tokens."
    )

    response = call_llm(
        system=prompt,
        messages=[{"role": "user", "content": json.dumps(conversation)}],
        model=get_model("agent"),
        max_tokens=450,  # buffer to guarantee <500
        context_category="handoff_ledger",
    )

    # Hard-enforce 500-token handoff budget (truncates if over, never raises)
    response, _ = enforce_handoff_budget(response)

    try:
        clean = response.strip()
        if "```json" in clean:
            clean = clean.split("```json")[1].split("```")[0].strip()
        elif "```" in clean:
            clean = clean.split("```")[1].split("```")[0].strip()
        # Find outermost JSON object
        start = clean.find("{")
        end = clean.rfind("}") + 1
        if start >= 0 and end > start:
            clean = clean[start:end]
        return json.loads(clean)
    except json.JSONDecodeError as e:
        logger.warning(f"Handoff JSON parse failed: {e}. Using raw text fallback.")
        return {"summary": response[:1000]}
    except Exception as e:
        logger.error(f"Unexpected error in handoff generation: {e}")
        raise


@activity.defn
async def run_voice_resolution_agent(handoff_summary: dict, borrower_data: dict) -> Dict:
    """
    Run Agent 2: Resolution — modality selection and execution.

    Agent 2 has TWO implementations that share the same negotiation logic
    (system prompt from active_prompts.yaml) but differ in delivery:

      1. **Voice (VAPI)** — preferred in production.  Creates an outbound
         phone call via the VAPI Custom LLM integration.  Each conversation
         turn routes through ``/chat/completions`` (webhook.py) where we
         run Claude with compliance checks.  Selected when:
         - VAPI_API_KEY is set and valid
         - borrower has a phone number

      2. **Chat simulation** — fallback for dev/test or when VAPI is
         unavailable.  Uses ``ResolutionAgent.run_resolution_agent()``
         directly (same system prompt, same compliance checks, no voice).
         Selected when VAPI_API_KEY is missing or call initiation fails.

    The workflow (workflow.py) treats both paths identically: it receives
    a result dict with ``outcome``, ``transcript``, ``offers_made``, etc.
    regardless of which modality was used.

    Idempotency: uses workflow_id as a dedup key for VAPI calls.
    If this activity is retried, the same workflow_id prevents duplicate
    outbound calls to the borrower's phone.
    """
    from voice.voice_handler import VapiHandler

    ctx = _dict_to_context(borrower_data)
    ctx.update_from_handoff(handoff_summary)

    # Idempotency key: workflow_id ensures retries don't create duplicate calls.
    # The VapiHandler checks if a call for this workflow_id already exists.
    idempotency_key = ctx.workflow_id or activity.info().workflow_id

    handler = VapiHandler()
    call_id = handler.initiate_call(
        phone=ctx.phone,
        agent1_handoff=handoff_summary,
        workflow_id=idempotency_key,
        borrower_name=ctx.name,
        balance=ctx.balance or 0.0,
        hardship_detected=ctx.hardship_detected,
    )

    if call_id and not call_id.startswith("mock-"):
        # Real VAPI call initiated — workflow will suspend until webhook signals
        logger.info(f"VAPI call initiated: {call_id} (idempotency_key={idempotency_key})")
        return {"call_id": call_id, "status": "initiated", "idempotency_key": idempotency_key}
    else:
        # VAPI unavailable — fall back to chat simulation.
        # This is logged as WARNING so it's visible in production monitoring.
        logger.warning(
            "VAPI unavailable — falling back to chat-based voice simulation. "
            "This breaks the modality requirement in production."
        )
        try:
            return await _run_voice_simulation(handoff_summary, ctx)
        except Exception as e:
            logger.error(f"Voice simulation fallback also failed: {e}")
            return {
                "call_id": "simulation-failed",
                "status": "completed",
                "outcome": "no_deal",
                "transcript": "",
                "offers_made": [],
                "outcome_reasoning": f"Voice simulation failed: {e}",
            }


async def _run_voice_simulation(handoff_summary: dict, ctx: BorrowerContext) -> Dict:
    """
    Fallback: run the resolution agent as a chat-based simulation.
    Returns the same structure as a real VAPI call result.
    """
    from agents.agent2_resolution import ResolutionAgent

    agent = ResolutionAgent()
    result = agent.run_resolution_agent(ctx)

    return {
        "call_id": "simulation",
        "status": "completed",
        "transcript": result.get("transcript", ""),
        "outcome": result.get("outcome", "no_deal"),
        "deal_terms": result.get("deal_terms"),
        "offers_made": result.get("offers_made", []),
    }


@activity.defn
async def run_final_notice_agent(handoff_summary: dict, borrower_data: dict) -> Dict:
    """Run Agent 3: Final Notice (Chat). Last offer with consequences."""
    ctx = _dict_to_context(borrower_data)
    ctx.update_from_handoff(handoff_summary)
    agent = FinalNoticeAgent()
    return agent.run_final_notice_agent(ctx)

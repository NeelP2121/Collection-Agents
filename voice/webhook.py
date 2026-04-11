"""
VAPI Webhook & Custom LLM Endpoint

Two endpoints that form the voice agent's brain:

1. POST /chat/completions — Custom LLM endpoint (OpenAI-compatible)
   VAPI sends each conversation turn here. We route through Claude with
   the resolution agent's system prompt, run compliance checks on the
   response, and return an OpenAI-shaped response for VAPI to speak.

2. POST /vapi-webhook — Server event handler
   Receives VAPI server messages (status-update, end-of-call-report, etc).
   On call end: analyzes the transcript with LLM, extracts structured
   outcome, and signals the Temporal workflow to resume.
"""

import asyncio
import json
import logging
import os
import uuid
from typing import Dict, List

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse
from temporalio.client import Client

from utils.llm import call_llm
from utils.config import get_model
from compliance.checker import check_message_compliance
from voice.call_state import get_call_store
from voice.transcript_analyzer import analyze_transcript

app = FastAPI(title="VAPI Voice Webhook")
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# Health check
# ──────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "voice-webhook"}


# ──────────────────────────────────────────────────────────────
# POST /chat/completions — Custom LLM for VAPI
# ──────────────────────────────────────────────────────────────

@app.post("/chat/completions")
async def custom_llm(request: Request):
    """
    OpenAI-compatible chat completion endpoint used by VAPI's Custom LLM.

    VAPI sends the full conversation (system prompt + message history) here
    on every turn. We:
      1. Extract system prompt and conversation
      2. Call Claude via our LLM interface
      3. Run compliance check on the response
      4. If non-compliant, regenerate with compliance guidance
      5. Return OpenAI-shaped response (streaming or non-streaming)
    """
    body = await request.json()
    messages = body.get("messages", [])
    stream = body.get("stream", False)
    call_info = body.get("call", {})
    call_id = call_info.get("id", "unknown")

    # Separate system prompt from conversation messages
    system = ""
    conv_messages: List[Dict] = []
    for msg in messages:
        if msg.get("role") == "system":
            system = msg["content"]
        else:
            conv_messages.append({"role": msg["role"], "content": msg["content"]})

    if not conv_messages:
        conv_messages = [{"role": "user", "content": "Hello"}]

    # Track turn count
    store = get_call_store()
    turn = store.increment_turn(call_id)

    # Generate response via Claude
    response_text = await asyncio.to_thread(
        call_llm,
        system=system,
        messages=conv_messages,
        model=get_model("agent"),
        max_tokens=200,
        context_category="vapi_voice",
    )

    # Compliance check on the generated response
    borrower_last = conv_messages[-1]["content"] if conv_messages else ""
    context = {
        "turn_number": turn,
        "borrower_last_message": borrower_last,
        "is_voice": True,
    }
    is_compliant, violations = check_message_compliance(
        response_text, agent_name="resolution", context=context
    )

    if not is_compliant:
        logger.warning(
            f"Voice response compliance violation on call {call_id}: {violations}"
        )
        store.add_violation(call_id, {
            "turn": turn,
            "violations": violations,
            "original_response": response_text[:200],
        })

        # Regenerate with explicit compliance guidance
        compliance_addendum = (
            "\n\nCOMPLIANCE CORRECTION REQUIRED: Your previous response violated "
            "these rules: " + ", ".join(v["reason"] for v in violations) + ". "
            "Restate your response while strictly following all compliance rules."
        )
        response_text = await asyncio.to_thread(
            call_llm,
            system=system + compliance_addendum,
            messages=conv_messages,
            model=get_model("agent"),
            max_tokens=200,
            context_category="vapi_voice_retry",
        )

    # Build OpenAI-compatible response
    call_resp_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

    if stream:
        return StreamingResponse(
            _sse_stream(call_resp_id, response_text),
            media_type="text/event-stream",
        )

    return {
        "id": call_resp_id,
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": response_text},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def _sse_stream(call_id: str, content: str):
    """Generate SSE chunks for streaming responses."""
    chunk = {
        "id": call_id,
        "object": "chat.completion.chunk",
        "choices": [
            {"index": 0, "delta": {"role": "assistant", "content": content}, "finish_reason": None}
        ],
    }
    yield f"data: {json.dumps(chunk)}\n\n"

    done = {
        "id": call_id,
        "object": "chat.completion.chunk",
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    yield f"data: {json.dumps(done)}\n\n"
    yield "data: [DONE]\n\n"


# ──────────────────────────────────────────────────────────────
# POST /vapi-webhook — Server event handler
# ──────────────────────────────────────────────────────────────

@app.post("/vapi-webhook")
async def webhook(request: Request, web_session_id: str = None):
    """
    Handle VAPI server messages.

    Key event types:
      - status-update: call ringing, in-progress, ended
      - end-of-call-report: final transcript + metadata → signals Temporal
      - conversation-update: mid-call transcript updates (logged)
      - function-call: if VAPI triggers tool use (not currently used)
    """
    event = await request.json()
    message = event.get("message", {})
    msg_type = message.get("type", "")

    logger.info(f"VAPI webhook event: {msg_type}")

    # ── Status updates (logging) ──
    if msg_type == "status-update":
        status = message.get("status", "unknown")
        call_id = message.get("call", {}).get("id", "unknown")
        logger.info(f"Call {call_id} status: {status}")
        return {"status": "acknowledged", "call_status": status}

    # ── Mid-call transcript updates ──
    if msg_type == "conversation-update":
        # Could be used for real-time monitoring; for now just log
        return {"status": "acknowledged"}

    # ── End of call report — the critical event ──
    if msg_type == "end-of-call-report":
        return await _handle_end_of_call(message, web_session_id)

    # ── Hang notification ──
    if msg_type == "hang":
        logger.info("VAPI hang notification received")
        return {"status": "acknowledged"}

    return {"status": "ignored", "type": msg_type}


async def _handle_end_of_call(message: Dict, query_web_session_id: str = None) -> JSONResponse:
    """
    Process end-of-call-report:
      1. Extract transcript from VAPI payload
      2. Run LLM-powered transcript analysis
      3. Build structured result
      4. Signal the Temporal workflow to resume
    """
    call = message.get("call", {})
    call_id = call.get("id", "unknown")
    metadata = call.get("metadata", {})
    workflow_id = metadata.get("temporal_workflow_id")
    web_session_id = query_web_session_id or metadata.get("web_session_id")
    ended_reason = message.get("endedReason", call.get("endedReason", "unknown"))

    # Extract transcript — VAPI provides it in multiple formats
    transcript = _extract_transcript(message)

    logger.info(
        f"End-of-call: call={call_id}, workflow={workflow_id}, session={web_session_id}, "
        f"reason={ended_reason}, transcript_len={len(transcript)}"
    )

    if not workflow_id and not web_session_id:
        logger.error("No temporal_workflow_id or web_session_id in call metadata — cannot signal")
        return JSONResponse(
            {"status": "error", "message": "missing workflow_id or web_session_id"},
            status_code=400,
        )

    # Retrieve call record for additional context
    store = get_call_store()
    call_record = store.get_by_call_id(call_id) or store.get_by_workflow_id(workflow_id)

    borrower_context = {}
    if call_record:
        borrower_context = {
            "name": call_record.borrower_name,
            "balance": call_record.balance,
            "handoff_summary": call_record.handoff_summary,
        }

    # LLM-powered transcript analysis
    analysis = await asyncio.to_thread(
        analyze_transcript, transcript, borrower_context
    )

    # Build the result payload for Temporal
    result = {
        "call_id": call_id,
        "transcript": transcript,
        "outcome": analysis.get("outcome", "no_deal"),
        "outcome_reasoning": analysis.get("outcome_reasoning", ""),
        "deal_terms": analysis.get("deal_terms"),
        "offers_made": analysis.get("offers_made", []),
        "objections": analysis.get("objections", []),
        "borrower_state": analysis.get("borrower_state", {}),
        "compliance_flags": analysis.get("compliance_flags", []),
        "ended_reason": ended_reason,
        "turns": analysis.get("turns", 0),
    }

    # Track VAPI call cost in the spend ledger
    call_duration = call.get("duration", call.get("durationSeconds", 0))
    if call_duration and float(call_duration) > 0:
        try:
            from utils.cost_tracker import get_cost_tracker
            get_cost_tracker().record_vapi_cost(float(call_duration))
            logger.info(f"Recorded VAPI cost for {float(call_duration):.0f}s call")
        except Exception as e:
            logger.warning(f"Failed to record VAPI cost: {e}")

    # Merge call-record compliance violations
    if call_record:
        result["inline_compliance_violations"] = call_record.compliance_violations
        store.mark_ended(call_id, result["outcome"], transcript)

    # If this is a web demo session, post back to the web portal instead of Temporal
    if web_session_id:
        import httpx
        try:
            # We use httpx inside the Async method to cleanly POST the json to the FastAPI portal
            async with httpx.AsyncClient() as client:
                await client.post(
                    "http://web-portal:8000/api/save-web-transcript",
                    json={"session_id": web_session_id, "analysis_result": result},
                    timeout=10.0
                )
            logger.info(f"Successfully posted transcript analysis for web session {web_session_id}")
            return JSONResponse({
                "status": "success",
                "signaled_web_session": web_session_id,
                "outcome": result["outcome"],
            })
        except Exception as e:
            logger.error(f"Failed to POST transcript to web-portal: {e}")
            return JSONResponse(
                {"status": "error", "message": str(e), "outcome": result["outcome"]},
                status_code=500,
            )

    # Signal Temporal workflow (with retry — transient network failures are common)
    max_signal_attempts = 3
    last_error = None
    for attempt in range(1, max_signal_attempts + 1):
        try:
            temporal_host = os.getenv("TEMPORAL_HOST", "localhost:7233")
            client = await Client.connect(temporal_host)
            handle = client.get_workflow_handle(workflow_id)
            await handle.signal("voice_done", result)

            logger.info(
                f"Signaled workflow {workflow_id}: outcome={result['outcome']}"
            )
            return JSONResponse({
                "status": "success",
                "signaled_workflow": workflow_id,
                "outcome": result["outcome"],
            })

        except Exception as e:
            last_error = e
            logger.warning(
                f"Temporal signal attempt {attempt}/{max_signal_attempts} failed "
                f"for workflow {workflow_id}: {e}"
            )
            if attempt < max_signal_attempts:
                await asyncio.sleep(2 ** attempt)  # exponential backoff: 2s, 4s

    logger.error(
        f"All {max_signal_attempts} signal attempts failed for workflow {workflow_id}: {last_error}"
    )
    return JSONResponse(
        {"status": "error", "message": str(last_error), "outcome": result["outcome"]},
        status_code=500,
    )


def _extract_transcript(message: Dict) -> str:
    """
    Extract a clean transcript from VAPI's end-of-call-report.

    VAPI may provide transcript in different formats:
      - message.transcript (string)
      - message.messages (array of {role, message} objects)
      - message.artifact.transcript (string)
      - message.artifact.messages (array)
    """
    # Try the structured messages array first (richest format)
    messages = (
        message.get("artifact", {}).get("messages")
        or message.get("messages")
    )
    if messages and isinstance(messages, list):
        lines = []
        for msg in messages:
            role = msg.get("role", "unknown").upper()
            content = msg.get("message") or msg.get("content", "")
            if content:
                lines.append(f"{role}: {content}")
        if lines:
            return "\n".join(lines)

    # Fall back to plain transcript string
    transcript = (
        message.get("artifact", {}).get("transcript")
        or message.get("transcript")
        or ""
    )
    return transcript

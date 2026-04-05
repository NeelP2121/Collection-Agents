from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
import logging
import os
import uuid
import json
import asyncio
from temporalio.client import Client
from utils.llm import call_llm
from utils.config import get_model

app = FastAPI()
logger = logging.getLogger(__name__)

@app.post("/vapi-webhook")
async def webhook(request: Request):
    """
    Ingest webhook triggers from Vapi.
    Specifically handles end-of-call-report mapped to our suspended Temporal instances.
    """
    event = await request.json()
    message = event.get("message", {})
    
    if message.get("type") == "end-of-call-report":
        call = message.get("call", {})
        metadata = call.get("metadata", {})
        workflow_id = metadata.get("temporal_workflow_id")
        
        if workflow_id:
            logger.info(f"Received End of Call Webhook. Signaling Workflow ID: {workflow_id}")
            try:
                client = await Client.connect(os.getenv("TEMPORAL_HOST", "localhost:7233"))
                handle = client.get_workflow_handle(workflow_id)
                
                # Raw transcript from WebRTC/provider
                transcript = message.get("transcript", "")
                
                result = {
                    "transcript": transcript,
                    # Simple heuristic parsing for demonstration. Prod maps LLM to parse transcript.
                    "outcome": "deal_agreed" if "deal" in transcript.lower() else "no_deal",
                    "offers_made": [{"offer_type": "lump_sum", "details": "Generated from VAPI asynchronous call"}]
                }
                
                # Release the block on Temporal
                await handle.signal("voice_done", result)
                return {"status": "success", "signaled_workflow": workflow_id}
            except Exception as e:
                logger.error(f"Failed to signal Temporal workflow natively: {e}")
                return {"status": "error", "message": str(e)}

    return {"status": "ignored_event_type"}


@app.post("/chat/completions")
async def custom_llm(request: Request):
    """
    OpenAI-compatible endpoint used as VAPI's Custom LLM.
    VAPI sends the full conversation here; we run it through our own LLM
    (Gemini/Anthropic/etc.) and return an OpenAI-shaped response.
    Supports both streaming (SSE) and non-streaming via the 'stream' flag.
    """
    body = await request.json()
    messages = body.get("messages", [])
    stream = body.get("stream", False)

    system = ""
    conv_messages = []
    for msg in messages:
        if msg.get("role") == "system":
            system = msg["content"]
        else:
            conv_messages.append({"role": msg["role"], "content": msg["content"]})

    if not conv_messages:
        conv_messages = [{"role": "user", "content": "Hello"}]

    response_text = await asyncio.to_thread(
        call_llm,
        system=system,
        messages=conv_messages,
        model=get_model("agent"),
        max_tokens=200,
        context_category="vapi_voice",
    )

    call_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

    if stream:
        def sse_stream():
            chunk = {
                "id": call_id,
                "object": "chat.completion.chunk",
                "choices": [{"index": 0, "delta": {"role": "assistant", "content": response_text}, "finish_reason": None}],
            }
            yield f"data: {json.dumps(chunk)}\n\n"
            done = {
                "id": call_id,
                "object": "chat.completion.chunk",
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
            yield f"data: {json.dumps(done)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(sse_stream(), media_type="text/event-stream")

    return {
        "id": call_id,
        "object": "chat.completion",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": response_text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }

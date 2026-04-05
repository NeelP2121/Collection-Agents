from fastapi import FastAPI, Request
import logging
from temporalio.client import Client

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
                client = await Client.connect("localhost:7233")
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

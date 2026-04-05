import os
import uuid
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import sys

# Ensure project root is in path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.agent1_assessment import AssessmentAgent
from agents.agent3_final_notice import FinalNoticeAgent
from utils.llm import call_llm
from utils.config import get_model, VAPI_PUBLIC_KEY, VAPI_ASSISTANT_ID, TEMPORAL_HOST, TEMPORAL_TASK_QUEUE

app = FastAPI()

# Instantiate agents once
agent1 = AssessmentAgent()
agent3 = FinalNoticeAgent()

AGENT1_PROMPT = agent1.system_prompt
AGENT3_PROMPT = agent3.system_prompt

# Mount frontend
app.mount("/static", StaticFiles(directory="frontend"), name="static")

# Very simple session dict for proxying the UI demo
sessions = {}

class ChatRequest(BaseModel):
    session_id: str
    message: str
    phase: int

class WorkflowRequest(BaseModel):
    name: str = "John Doe"
    phone: str = "+10000000000"

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    with open("frontend/index.html") as f:
        return f.read()

@app.post("/api/chat")
async def handle_chat(req: ChatRequest):
    if req.session_id not in sessions:
        # Provide base system rules
        sessions[req.session_id] = {
            "messages": [],
            "phase": 1,
            "agent2_handoff": "Borrower failed to accept terms smoothly over the phone."
        }
    
    session = sessions[req.session_id]
    session["messages"].append({"role": "user", "content": req.message})
    
    if req.phase == 1:
        sys_prompt = AGENT1_PROMPT
    else: # Phase 3: Final Notice
        sys_prompt = AGENT3_PROMPT + f"\n\nPREVIOUS CONTEXT:\n{session['agent2_handoff']}"
        
    try:
        response_text = call_llm(
            system=sys_prompt,
            messages=session["messages"],
            model=get_model("agent"),
            max_tokens=250,
            context_category="web_demo_chat"
        )
    except Exception as e:
        response_text = "I'm experiencing a brief network interruption. Please try again in a moment."
        print(f"Error calling LLM: {e}")
        
    session["messages"].append({"role": "assistant", "content": response_text})
    
    # Advanced logic: If Agent 1's AI successfully triggers a voice handoff dynamically by saying "call" or "resolution"
    trigger_call = False
    if req.phase == 1 and any(word in response_text.lower() for word in ["call", "resolution team", "transfer", "phone"]):
        trigger_call = True
        session["phase"] = 2
        
    return {
        "reply": response_text,
        "trigger_call": trigger_call,
        "phase": session["phase"]
    }
    
@app.get("/api/vapi-config")
async def get_vapi_config(session_id: str = ""):
    """
    Returns the VAPI public key and inline assistant config for the web SDK.
    The public key is safe to expose to the browser.
    Context from Agent 1's conversation is injected into the assistant system prompt.
    """
    context_str = ""
    if session_id and session_id in sessions:
        history = sessions[session_id].get("messages", [])
        # Summarise last few turns for the voice agent (keep under 500 chars)
        excerpt = " | ".join(
            f"{m['role'].upper()}: {m['content'][:120]}" for m in history[-6:]
        )
        context_str = excerpt[:500]

    system_prompt = (
        "You are the Resolution Voice Agent for a debt collection company. "
        "You are a transactional dealmaker.\n"
        f"CONTEXT FROM PRIOR CHAT:\n{context_str}\n\n"
        "INSTRUCTIONS:\n"
        "1. OPENING: Reference the prior chat interaction.\n"
        "2. NO RE-VERIFICATION: Do not re-ask for identity.\n"
        "3. NEGOTIATE SETTLEMENT AND LOCK IN DEAL."
    )

    raw_server_url = os.getenv("SERVER_URL", "")
    # Derive webhook URL and custom-LLM base from SERVER_URL
    webhook_url = raw_server_url if raw_server_url.endswith("/vapi-webhook") else raw_server_url.rstrip("/") + "/vapi-webhook"
    base_url = raw_server_url.replace("/vapi-webhook", "").rstrip("/")
    custom_llm_url = f"{base_url}/chat/completions" if base_url else ""

    assistant_config = {
        "name": "Resolution Agent",
        "firstMessage": "Hi, this is the resolution team. I'm following up on your account.",
        "model": {
            "provider": "custom-llm",
            "url": custom_llm_url,
            "model": get_model("agent"),
            "systemPrompt": system_prompt,
        },
        "voice": {
            "provider": "playht",
            "voiceId": "jennifer",
        },
        "transcriber": {
            "provider": "deepgram",
            "model": "nova-2",
            "language": "en",
        },
    }
    if webhook_url:
        assistant_config["serverUrl"] = webhook_url

    return {
        "public_key": VAPI_PUBLIC_KEY or "",
        "assistant_id": VAPI_ASSISTANT_ID or "",
        "assistant": assistant_config,
        "configured": bool(VAPI_PUBLIC_KEY),
    }


@app.post("/api/trigger-workflow")
async def trigger_workflow(req: WorkflowRequest):
    """
    Submits a BorrowerWorkflow to Temporal so it appears in the dashboard at localhost:8080.
    The worker service picks it up and runs the full 3-agent orchestration.
    """
    try:
        from temporalio.client import Client
        client = await Client.connect(TEMPORAL_HOST)
        workflow_id = f"borrower-{uuid.uuid4()}"
        handle = await client.start_workflow(
            "BorrowerWorkflow",
            {"name": req.name, "phone": req.phone},
            id=workflow_id,
            task_queue=TEMPORAL_TASK_QUEUE,
        )
        return {
            "status": "started",
            "workflow_id": workflow_id,
            "temporal_ui": f"http://localhost:8080/namespaces/default/workflows/{workflow_id}",
        }
    except Exception as e:
        return {"status": "error", "detail": str(e)}


@app.post("/api/simulate-call-end")
async def simulate_call_end(req: ChatRequest):
    """
    Called by the Frontend when the fake Voice Call completes, triggering the seamless Phase 3 chat continuation.
    In real production, VAPI's webhook triggers this state transition inside Temporal directly.
    """
    if req.session_id in sessions:
        sessions[req.session_id]["phase"] = 3
        # Flush messages so Agent 3 reads entirely fresh from final notice system prompt via history summary
        sessions[req.session_id]["messages"] = []
    return {"status": "ok", "message": "Voice call finished. Agent 3 text channel open."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.server:app", host="0.0.0.0", port=8000, reload=True)

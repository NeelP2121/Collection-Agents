import os
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import sys

# Ensure project root is in path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.agent1_assessment import SYSTEM_PROMPT_v1 as AGENT1_PROMPT
from agents.agent3_final_notice import SYSTEM_PROMPT_v1 as AGENT3_PROMPT
from utils.llm import call_llm
from utils.config import LLM_MODELS

app = FastAPI()

# Mount frontend
app.mount("/static", StaticFiles(directory="frontend"), name="static")

# Very simple session dict for proxying the UI demo
sessions = {}

class ChatRequest(BaseModel):
    session_id: str
    message: str
    phase: int

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
        sys_prompt = AGENT3_PROMPT.format(handoff_summary=session["agent2_handoff"])
        
    try:
        response_text = call_llm(
            system=sys_prompt,
            messages=session["messages"],
            model=LLM_MODELS.get("agent", "claude-3-5-haiku-20241022"),
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

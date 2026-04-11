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
from models.borrower_state import BorrowerContext
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

def _init_demo_session(session_id: str) -> None:
    # Default fallback data
    demo_data = {
        "name": "John Doe",
        "phone": "+10000000000",
        "ssn_last_4": "0000",
        "balance": 4000.0
    }
    
    # Try to load from demo_user.json
    try:
        import json
        demo_file_path = os.path.join(os.path.dirname(__file__), "demo_user.json")
        if os.path.exists(demo_file_path):
            with open(demo_file_path, "r") as f:
                loaded_data = json.load(f)
                demo_data.update(loaded_data)
    except Exception as e:
        print(f"Failed to load demo_user.json: {e}")

    sessions[session_id] = {
        "messages": [],
        "phase": 1,
        "borrower_context": BorrowerContext(
            name=demo_data["name"],
            phone=demo_data["phone"],
            balance=float(demo_data["balance"]),
            hardship_detected=False,
            agent2_summary={
                "prior_outcome": "no_deal",
                "offers_rejected": [
                    {"type": "lump_sum", "details": "25% discount"}
                ],
                "objections": ["Please don't call me anymore."],
            },
            agent2_offers_made=[
                {"offer_type": "lump_sum", "details": "25% discount"}
            ],
        ),
        "demo_data": demo_data,
        "agent2_handoff": "Borrower failed to accept terms smoothly over the phone.",
        "transcript_ready": False,
    }

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
        _init_demo_session(req.session_id)

    session = sessions[req.session_id]
    session["messages"].append({"role": "user", "content": req.message})

    if req.phase == 1:
        ctx: BorrowerContext = session.get("borrower_context")
        demo_data = session.get("demo_data", {})
        balance = ctx.balance if ctx else 4000.0
        ssn = demo_data.get("ssn_last_4", "0000")
        
        # Inject the balance and verification details into the system prompt
        sys_prompt = AGENT1_PROMPT + (
            f"\n\nCRITICAL INSTRUCTION: The borrower's outstanding balance is ${balance:,.2f}. "
            f"Their identity should be verified using the last 4 digits of their SSN: {ssn}. "
            "Before transferring them to the resolution team, you MUST explicitly state their outstanding balance."
        )
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
        trigger_call = False
        if any(word in response_text.lower() for word in ["call", "resolution team", "transfer", "phone"]):
            trigger_call = True
            session["phase"] = 2

        return {
            "reply": response_text,
            "trigger_call": trigger_call,
            "phase": session["phase"]
        }

    if req.phase == 3:
        ctx: BorrowerContext = session.get("borrower_context")
        
        # Build the system prompt exactly like how Agent 3 natively does
        if ctx:
            import json
            handoff = ctx.agent2_summary or {}
            guarded_handoff = json.dumps(handoff)
            sys_prompt = AGENT3_PROMPT + f"\n\nCONTEXT FROM PRIOR INTERACTIONS:\n{guarded_handoff}"
            
            outcome = str(handoff.get("prior_outcome", "")).lower()
            deal = handoff.get("deal_terms") or {}
            
            # Robust deal detection: Must have 'agree' or 'deal' in outcome AND not be 'no_deal'
            is_deal = ("agree" in outcome or "deal_agreed" in outcome) and "no_deal" not in outcome
            
            if is_deal and deal.get("amount"):
                amount = deal.get('amount')
                deal_desc = f"a settlement of ${amount:,.2f}"
                
                sys_prompt += (
                    f"\n\nCRITICAL INSTRUCTION: The borrower JUST ACCEPTED a deal ({deal_desc}) over the phone! "
                    "DO NOT THREATEN THEM. DO NOT offer a new discount. "
                    "DO NOT USE PLACEHOLDERS like [AMOUNT] or [DATE]. "
                    "YOUR ONLY TASK is to: "
                    "1. Warmly congratulate them on resolving their debt. "
                    f"2. Confirm the exact terms reached: {deal_desc}. "
                    "3. Explain that a formal agreement and payment instructions will be emailed to them immediately. "
                    "4. Be professional and supportive."
                )
            else:
                sys_prompt += f"\n\nINSTRUCTION: No deal was reached. The final balance is ${ctx.balance:,.2f}. Offer a 20% discount as a final lump sum if paid within 7 days. Be firm about the consequences of non-payment (credit reporting, legal referral)."
        else:
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
        session["phase"] = 3

        return {
            "reply": response_text,
            "trigger_call": False,
            "phase": session["phase"]
        }

    # Default fallback for unsupported phases
    return {
        "reply": "I cannot handle that phase yet.",
        "trigger_call": False,
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
    balance = 4000.0
    
    if session_id and session_id in sessions:
        session = sessions[session_id]
        history = session.get("messages", [])
        # Summarise last few turns for the voice agent (keep under 500 chars)
        excerpt = " | ".join(
            f"{m['role'].upper()}: {m['content'][:120]}" for m in history[-6:]
        )
        context_str = excerpt[:500]
        
        ctx = session.get("borrower_context")
        if ctx:
            balance = ctx.balance

    # Calculate settlement options to provide to the voice agent
    lump_sum_discount = 0.30
    lump_sum_amount = balance * (1 - lump_sum_discount)
    payment_plan_months = 6
    payment_plan_monthly = balance / payment_plan_months

    # Explicitly define the system prompt for the override to inject dynamic variables
    system_prompt = (
        "You are the Resolution Voice Agent for a debt collection company. "
        "You are a transactional dealmaker.\n\n"
        f"BORROWER ACCOUNT BALANCE: ${balance:,.2f}\n\n"
        "SETTLEMENT OPTIONS YOU MUST OFFER:\n"
        f"1. LUMP SUM: ${lump_sum_amount:,.2f} ({int(lump_sum_discount*100)}% discount) if paid within 7 days.\n"
        f"2. PAYMENT PLAN: ${payment_plan_monthly:,.2f} per month for {payment_plan_months} months.\n\n"
        f"CONTEXT FROM PRIOR CHAT:\n{context_str}\n\n"
        "INSTRUCTIONS:\n"
        "1. OPENING: Reference the prior chat interaction and explicitly state their balance.\n"
        "2. NO RE-VERIFICATION: Do not re-ask for identity.\n"
        "3. NEGOTIATE: Present the Lump Sum option first. If rejected, offer the Payment Plan. "
        "DO NOT use generic placeholders like '5000 dollars' or 'calculate amount'. USE THE EXACT NUMBERS PROVIDED ABOVE.\n"
        "4. COMMITMENT: If they agree, confirm the exact amount and tell them a settlement agreement will be sent to their email."
    )

    raw_server_url = os.getenv("SERVER_URL", "")
    # Derive webhook URL and custom-LLM base from SERVER_URL
    webhook_url = raw_server_url if raw_server_url.endswith("/vapi-webhook") else raw_server_url.rstrip("/") + "/vapi-webhook"
    base_url = raw_server_url.replace("/vapi-webhook", "").rstrip("/")
    custom_llm_url = f"{base_url}/chat/completions" if base_url else ""

    if webhook_url:
        webhook_url = f"{webhook_url}?web_session_id={session_id}"

    assistant_config = {
        "name": "Resolution Agent",
        "firstMessage": f"Hi, this is the resolution team calling about your ${balance:,.2f} balance. I understand you were just speaking with our team.",
        "model": {
            "provider": "custom-llm",
            "url": custom_llm_url,
            "model": get_model("agent"),
            "systemPrompt": system_prompt,
        },
        "metadata": {
            "web_session_id": session_id
        }
    }
    
    # We only override the transcriber and voice if not using an assistant ID, 
    # to avoid blowing away the dashboard settings for those components.
    if not VAPI_ASSISTANT_ID:
        assistant_config["voice"] = {
            "provider": "playht",
            "voiceId": "jennifer",
        }
        assistant_config["transcriber"] = {
            "provider": "deepgram",
            "model": "nova-2",
            "language": "en",
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

class WebDemoTranscriptRequest(BaseModel):
    session_id: str
    analysis_result: dict

@app.post("/api/save-web-transcript")
async def save_web_transcript(req: WebDemoTranscriptRequest):
    if req.session_id in sessions:
        ctx: BorrowerContext = sessions[req.session_id]["borrower_context"]
        r = req.analysis_result
        print(f"DEBUG: Saving transcript for session {req.session_id}. Outcome: {r.get('outcome')}, Deal: {r.get('deal_terms')}")
        ctx.agent2_summary = {
            "prior_outcome": r.get("outcome", "no_deal"),
            "offers_rejected": r.get("offers_made", []),
            "offers_accepted": [r.get("deal_terms")] if r.get("deal_terms") else [],
            "objections": r.get("objections", []),
            "transcript_summary": r.get("outcome_reasoning", ""),
            "deal_terms": r.get("deal_terms"),
        }
        sessions[req.session_id]["transcript_ready"] = True
    return {"status": "ok"}

@app.get("/api/session-status")
async def get_session_status(session_id: str):
    if session_id in sessions:
        return {"transcript_ready": sessions[session_id].get("transcript_ready", False)}
    return {"transcript_ready": False}

from fastapi import Request
from fastapi.responses import JSONResponse

@app.post("/vapi-webhook")
async def forward_vapi_webhook(request: Request):
    """
    Because Ngrok exposes this web-portal (port 8000), VAPI's end-of-call webhooks 
    hit this server. This simply proxies the webhook internal network over to port 8001.
    """
    try:
        body = await request.json()
        query_params = dict(request.query_params)
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "http://voice-webhook:8001/vapi-webhook", 
                json=body, 
                params=query_params,
                timeout=30.0
            )
            return JSONResponse(status_code=resp.status_code, content=resp.json())
    except Exception as e:
        logger.error(f"Failed to forward webhook from web-portal to voice-webhook: {e}")
        return JSONResponse({"status": "error", "message": "Failed to proxy internal network"}, status_code=500)

@app.post("/chat/completions")
async def forward_chat_completions(request: Request):
    """
    Proxy custom LLM endpoint requests from VAPI natively to the voice-webhook container.
    This guarantees VAPI voice calls work whether Ngrok points to 8000 or 8001.
    """
    try:
        body = await request.json()
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.post("http://voice-webhook:8001/chat/completions", json=body, timeout=30.0)
            return JSONResponse(status_code=resp.status_code, content=resp.json())
    except Exception as e:
        logger.error(f"Failed to forward chat completion proxy: {e}")
        return JSONResponse({"status": "error"}, status_code=500)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.server:app", host="0.0.0.0", port=8000, reload=True)

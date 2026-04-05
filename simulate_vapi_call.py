#!/usr/bin/env python3
"""
VAPI Call Simulation — Full End-to-End
Simulates the full Agent 2 (voice resolution) pipeline without Temporal or real VAPI infrastructure:

  [BorrowerContext] → ResolutionAgent (LLM) ↔ Auto-Borrower ↔ Transcript
                    → VAPI end-of-call-report webhook payload
                    → Local webhook handler
                    → Outcome signal (would normally resume Temporal)
"""

import sys
import os
import json
import asyncio
import logging
from datetime import datetime

# Silence noisy logs
logging.basicConfig(level=logging.WARNING)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models.borrower_state import BorrowerContext
from agents.agent2_resolution import ResolutionAgent
from voice.webhook import app   # FastAPI app with /vapi-webhook

# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────
DIVIDER = "─" * 60

def header(title):
    print(f"\n{DIVIDER}")
    print(f"  {title}")
    print(DIVIDER)

def log(label, value=""):
    print(f"  {label}{': ' + str(value) if value else ''}")


# ─────────────────────────────────────────────────────────────
# 1. Build Borrower Context (simulates Agent 1 handoff)
# ─────────────────────────────────────────────────────────────
header("STEP 1 — Build Borrower Context (simulated Agent 1 handoff)")

BORROWER_PERSONA = "cooperative"   # change to: combative | evasive | distressed
WORKFLOW_ID      = f"sim-workflow-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

ctx = BorrowerContext(
    name="John Smith",
    phone="+15551234567",
    workflow_id=WORKFLOW_ID,
    balance=4_800.00,
    identity_verified=True,
    employment_status="employed",
    income=3_500.0,
    ability_to_pay="partial",
    hardship_detected=False,
    agent1_summary="Borrower verified. Balance $4,800. Employed, partial ability to pay. Open to settlement.",
    current_stage="resolution",
)

log("Borrower",    ctx.name)
log("Balance",     f"${ctx.balance:,.2f}")
log("Persona",     BORROWER_PERSONA)
log("WorkflowID",  WORKFLOW_ID)
log("Agent1 summary", ctx.agent1_summary)
print()


# ─────────────────────────────────────────────────────────────
# Automatic borrower response function by persona
# ─────────────────────────────────────────────────────────────
PERSONA_SCRIPTS = {
    "cooperative": [
        "I understand. Can you tell me more about the settlement options?",
        "The lump sum sounds reasonable. What's the exact amount?",
        "Okay, I can do the 25% discount. Yes, I agree to the deal.",
    ],
    "combative": [
        "I'm not paying anything. This debt is not mine.",
        "No. I refuse your offers.",
        "No deal. Stop calling me.",
    ],
    "evasive": [
        "I'll have to call you back, I'm busy right now.",
        "I'm not sure, let me think about it.",
        "Maybe. I need to talk to my spouse first.",
    ],
    "distressed": [
        "I've lost my job and I can't afford anything right now.",
        "I'm going through hardship, please help.",
        "Okay I'll try the hardship program if that's an option.",
    ],
}

script = PERSONA_SCRIPTS.get(BORROWER_PERSONA, PERSONA_SCRIPTS["cooperative"])
script_index = [0]

def auto_borrower_response(turn: int, agent_response: str, state: dict) -> str:
    """Deterministic persona-driven borrower responses for simulation."""
    idx = min(script_index[0], len(script) - 1)
    reply = script[idx]
    script_index[0] += 1
    print(f"  [Borrower turn {turn}] → {reply}")
    return reply

ctx.test_borrower_response_fn = auto_borrower_response


# ─────────────────────────────────────────────────────────────
# 2. Run ResolutionAgent (live LLM conversation)
# ─────────────────────────────────────────────────────────────
header("STEP 2 — ResolutionAgent (LLM) running negotiation")
print("  (LLM responses below — each turn uses real API calls)\n")

agent = ResolutionAgent()

try:
    result = agent.run_resolution_agent(ctx)
    outcome  = result.get("outcome", "unknown")
    deal     = result.get("deal_terms")
    offers   = result.get("offers_made", [])
    transcript_text = result.get("transcript", "")
except Exception as e:
    print(f"  [ERROR] ResolutionAgent failed: {e}")
    sys.exit(1)

print()
log("Outcome",      outcome)
log("Deal terms",   json.dumps(deal, indent=4) if deal else "None")
log("Offers made",  len(offers))


# ─────────────────────────────────────────────────────────────
# 3. Build VAPI end-of-call-report payload
# ─────────────────────────────────────────────────────────────
header("STEP 3 — Build VAPI end-of-call-report webhook payload")

vapi_payload = {
    "message": {
        "type": "end-of-call-report",
        "transcript": transcript_text,
        "call": {
            "id": "sim-call-001",
            "status": "ended",
            "endedReason": "assistant-ended-call",
            "metadata": {
                "temporal_workflow_id": WORKFLOW_ID
            },
            "phoneNumberId": os.environ.get("VAPI_PHONE_ID", "b9660968-0bd7-4953-a7fc-c11450fb900d"),
            "customer": {"number": ctx.phone},
        }
    }
}

print("  Payload (truncated):")
preview = json.dumps(vapi_payload, indent=4)
print("\n".join(f"    {l}" for l in preview.splitlines()[:30]))
if len(preview.splitlines()) > 30:
    print("    ...")


# ─────────────────────────────────────────────────────────────
# 4. Fire webhook handler locally (without real Temporal)
# ─────────────────────────────────────────────────────────────
header("STEP 4 — Fire webhook handler (local, no Temporal)")

from fastapi.testclient import TestClient

client = TestClient(app)

try:
    resp = client.post("/vapi-webhook", json=vapi_payload)
    webhook_result = resp.json()
    log("HTTP status",     resp.status_code)
    log("Webhook response", json.dumps(webhook_result, indent=4))
except Exception as e:
    log("Webhook test error", str(e))
    # Temporal not running is expected — parse signal would fail
    webhook_result = {"status": "expected_temporal_error", "error": str(e)}


# ─────────────────────────────────────────────────────────────
# 5. Outcome parsing (mimics what workflow.signal('voice_done') receives)
# ─────────────────────────────────────────────────────────────
header("STEP 5 — Signal payload (what Temporal would receive)")

signal_payload = {
    "transcript": transcript_text,
    "outcome": "deal_agreed" if "deal" in transcript_text.lower() else "no_deal",
    "offers_made": offers,
}

print("  signal('voice_done') payload:")
for k, v in signal_payload.items():
    if k == "transcript":
        lines = v.splitlines()
        print(f"    transcript ({len(lines)} lines):")
        for line in lines[:8]:
            print(f"      {line}")
        if len(lines) > 8:
            print(f"      ... ({len(lines)-8} more lines)")
    else:
        print(f"    {k}: {json.dumps(v)}")


# ─────────────────────────────────────────────────────────────
# 6. Final summary
# ─────────────────────────────────────────────────────────────
header("SIMULATION COMPLETE — Summary")

log("Borrower persona",    BORROWER_PERSONA)
log("Negotiation outcome", outcome.upper())
log("Deal agreed",         "YES" if outcome == "deal_agreed" else "NO")
if deal:
    log("Deal type",    deal.get("type"))
    log("Deal details", deal.get("details"))
log("Compliance violations", len(ctx.compliance_violations))
if ctx.compliance_violations:
    for v in ctx.compliance_violations:
        print(f"    ⚠  [{v['severity'].upper()}] {v['type']}: {v['message']}")
log("Webhook status",      webhook_result.get("status", "unknown"))

print()
print("  Next step in real system:")
print("    Temporal receives voice_done signal → Agent 3 Final Notice")
print(DIVIDER)

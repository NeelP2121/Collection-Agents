#!/usr/bin/env python3
"""
VAPI Call Simulation — Full End-to-End

Simulates the complete Agent 2 (voice resolution) pipeline:

  Mode A (--live):   Triggers a real VAPI outbound call via the API.
                     Requires VAPI_API_KEY, VAPI_PHONE_ID, and a running
                     voice-webhook server (ngrok).

  Mode B (default):  Runs the resolution agent as a local chat simulation
                     with scripted borrower personas. Tests the full pipeline:
                     LLM negotiation → transcript analysis → webhook payload.

Usage:
  python simulate_vapi_call.py                        # Local simulation
  python simulate_vapi_call.py --live --phone +1555...  # Real VAPI call
  python simulate_vapi_call.py --persona combative    # Change persona
"""

import sys
import os
import json
import asyncio
import argparse
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models.borrower_state import BorrowerContext
from agents.agent2_resolution import ResolutionAgent
from voice.voice_handler import VapiHandler
from voice.transcript_analyzer import analyze_transcript

DIVIDER = "─" * 60


def header(title):
    print(f"\n{DIVIDER}")
    print(f"  {title}")
    print(DIVIDER)


def log(label, value=""):
    print(f"  {label}{': ' + str(value) if value else ''}")


# ─────────────────────────────────────────────────────────────
# Borrower persona scripts for simulation
# ─────────────────────────────────────────────────────────────

PERSONA_SCRIPTS = {
    "cooperative": [
        "Yes, I remember the chat. What options do you have for me?",
        "The lump sum sounds reasonable. What exactly would the amount be?",
        "Okay, I can do that. Yes, I agree to the lump sum settlement.",
    ],
    "combative": [
        "I don't think I owe this. Who are you people?",
        "No. I'm not paying that. Your numbers are wrong.",
        "I said no. Stop calling me about this.",
    ],
    "evasive": [
        "I'm kind of busy right now, can you call back?",
        "I'm not sure about any of this. Let me think about it.",
        "Maybe. I need to talk to my family first. Can you send something in writing?",
    ],
    "distressed": [
        "I lost my job two months ago. I really can't pay anything right now.",
        "I'm going through a really hard time. Is there any help available?",
        "Yes, please connect me with the hardship program. That would help.",
    ],
    "confused": [
        "Wait, what debt? I thought this was already handled.",
        "I don't understand these options. Can you explain more simply?",
        "So if I do the payment plan, how much per month exactly?",
    ],
}


def build_borrower_context(persona: str, workflow_id: str) -> BorrowerContext:
    """Build a realistic borrower context simulating Agent 1 output."""
    ctx = BorrowerContext(
        name="John Smith",
        phone="+15551234567",
        workflow_id=workflow_id,
        balance=4_800.00,
        identity_verified=True,
        employment_status="employed" if persona != "distressed" else "unemployed",
        income=3_500.0 if persona != "distressed" else 0.0,
        ability_to_pay="partial" if persona not in ("distressed", "combative") else "none",
        hardship_detected=persona == "distressed",
        agent1_summary=json.dumps({
            "summary": f"Borrower verified as John Smith. Balance $4,800. "
                       f"{'Employed, partial ability to pay.' if persona != 'distressed' else 'Unemployed, hardship detected.'} "
                       f"Persona: {persona}. Open to discussion.",
            "identity_verified": True,
            "employment_status": "employed" if persona != "distressed" else "unemployed",
            "ability_to_pay": "partial" if persona not in ("distressed", "combative") else "none",
            "hardship_detected": persona == "distressed",
        }),
        current_stage="resolution",
    )
    return ctx


def run_local_simulation(persona: str):
    """Run local chat-based simulation of the voice agent."""
    workflow_id = f"sim-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    ctx = build_borrower_context(persona, workflow_id)

    header("STEP 1 — Borrower Context (simulated Agent 1 handoff)")
    log("Borrower", ctx.name)
    log("Balance", f"${ctx.balance:,.2f}")
    log("Persona", persona)
    log("Workflow ID", workflow_id)
    log("Hardship", ctx.hardship_detected)

    # Set up scripted borrower responses
    script = PERSONA_SCRIPTS.get(persona, PERSONA_SCRIPTS["cooperative"])
    script_index = [0]

    def auto_borrower_response(turn, agent_response, state):
        idx = min(script_index[0], len(script) - 1)
        reply = script[idx]
        script_index[0] += 1
        print(f"  [Borrower turn {turn}] {reply}")
        return reply

    ctx.test_borrower_response_fn = auto_borrower_response

    header("STEP 2 — Resolution Agent Negotiation (LLM-powered)")
    agent = ResolutionAgent()
    try:
        result = agent.run_resolution_agent(ctx)
    except Exception as e:
        print(f"  [ERROR] Resolution agent failed: {e}")
        sys.exit(1)

    outcome = result.get("outcome", "unknown")
    transcript = result.get("transcript", "")
    offers = result.get("offers_made", [])
    deal = result.get("deal_terms")

    log("Outcome", outcome)
    log("Offers made", len(offers))
    if deal:
        log("Deal type", deal.get("type"))

    header("STEP 3 — Transcript Analysis (LLM-powered)")
    analysis = analyze_transcript(
        transcript,
        borrower_context={
            "name": ctx.name,
            "balance": ctx.balance,
            "handoff_summary": ctx.agent1_summary,
        },
    )

    log("Analyzed outcome", analysis.get("outcome"))
    log("Reasoning", analysis.get("outcome_reasoning", "")[:100])
    if analysis.get("deal_terms"):
        log("Deal terms", json.dumps(analysis["deal_terms"], indent=2))
    if analysis.get("borrower_state"):
        log("Borrower state", json.dumps(analysis["borrower_state"], indent=2))
    if analysis.get("compliance_flags"):
        for flag in analysis["compliance_flags"]:
            print(f"  [COMPLIANCE {flag.get('severity', '').upper()}] {flag.get('concern')}")

    header("STEP 4 — Simulated VAPI Webhook Payload")
    vapi_payload = {
        "message": {
            "type": "end-of-call-report",
            "transcript": transcript,
            "endedReason": "assistant-ended-call",
            "call": {
                "id": f"sim-call-{workflow_id}",
                "status": "ended",
                "metadata": {"temporal_workflow_id": workflow_id},
            },
            "artifact": {
                "transcript": transcript,
            },
        }
    }
    preview = json.dumps(vapi_payload, indent=2)
    for line in preview.splitlines()[:25]:
        print(f"    {line}")
    if len(preview.splitlines()) > 25:
        print("    ...")

    header("STEP 5 — Signal Payload (what Temporal receives)")
    signal = {
        "call_id": f"sim-call-{workflow_id}",
        "transcript": f"({len(transcript.splitlines())} lines)",
        "outcome": analysis.get("outcome", outcome),
        "deal_terms": analysis.get("deal_terms"),
        "offers_made": analysis.get("offers_made", offers),
        "borrower_state": analysis.get("borrower_state"),
    }
    print(json.dumps(signal, indent=2, default=str))

    header("SIMULATION COMPLETE")
    log("Persona", persona)
    log("Negotiation outcome", outcome.upper())
    log("Analyzed outcome", analysis.get("outcome", "").upper())
    log("Compliance violations", len(ctx.compliance_violations))
    for v in ctx.compliance_violations:
        print(f"    [{v['severity'].upper()}] {v['type']}: {v['message']}")
    print()


def run_live_call(phone: str, persona: str):
    """Trigger a real VAPI outbound call."""
    workflow_id = f"live-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    ctx = build_borrower_context(persona, workflow_id)
    ctx.phone = phone

    header("LIVE VAPI CALL")
    log("Phone", phone)
    log("Workflow ID", workflow_id)
    log("Borrower", ctx.name)
    log("Balance", f"${ctx.balance:,.2f}")

    handoff = json.loads(ctx.agent1_summary)
    handler = VapiHandler()
    call_id = handler.initiate_call(
        phone=phone,
        agent1_handoff=handoff,
        workflow_id=workflow_id,
        borrower_name=ctx.name,
        balance=ctx.balance,
        hardship_detected=ctx.hardship_detected,
    )

    if call_id:
        log("VAPI Call ID", call_id)
        log("Status", "Call initiated — VAPI will handle the conversation")
        log("Webhook", "End-of-call report will be sent to /vapi-webhook")
        print()
        print("  The call is now in progress. When it ends, the webhook will")
        print("  analyze the transcript and signal Temporal (if running).")
    else:
        print("  [ERROR] Failed to create VAPI call. Check API key and phone number.")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VAPI Call Simulation")
    parser.add_argument(
        "--persona",
        choices=list(PERSONA_SCRIPTS.keys()),
        default="cooperative",
        help="Borrower persona for simulation",
    )
    parser.add_argument("--live", action="store_true", help="Trigger a real VAPI call")
    parser.add_argument("--phone", type=str, help="Phone number for live call (E.164)")
    args = parser.parse_args()

    if args.live:
        if not args.phone:
            print("ERROR: --phone required for live calls (e.g. --phone +15551234567)")
            sys.exit(1)
        run_live_call(args.phone, args.persona)
    else:
        run_local_simulation(args.persona)

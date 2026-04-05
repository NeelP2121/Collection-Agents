#!/usr/bin/env python3
"""
VAPI Voice Agent Validation Script
Tests:
1. VAPI credentials (API key + phone number ID)
2. VAPI account/org info
3. Phone number validity
4. VapiHandler class integration
5. Webhook endpoint structure
"""

import sys
import os
import json
import requests

# Make sure we can import project modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.config import VAPI_API_KEY, VAPI_PHONE_ID, VAPI_PUBLIC_KEY

VAPI_BASE = "https://api.vapi.ai"
HEADERS = {"Authorization": f"Bearer {VAPI_API_KEY}"}

def section(title):
    print(f"\n{'='*50}")
    print(f"  {title}")
    print('='*50)

def ok(msg):  print(f"  [PASS] {msg}")
def fail(msg): print(f"  [FAIL] {msg}")
def info(msg): print(f"  [INFO] {msg}")


# ── 1. Credentials loaded ─────────────────────────────
section("1. Credentials")

if VAPI_API_KEY and VAPI_API_KEY != "your-vapi-api-key":
    ok(f"VAPI_API_KEY loaded  ({VAPI_API_KEY[:8]}...)")
else:
    fail("VAPI_API_KEY missing or placeholder")
    sys.exit(1)

if VAPI_PHONE_ID:
    ok(f"VAPI_PHONE_ID loaded ({VAPI_PHONE_ID})")
else:
    fail("VAPI_PHONE_ID missing")

if VAPI_PUBLIC_KEY:
    ok(f"VAPI_PUBLIC_KEY loaded ({VAPI_PUBLIC_KEY[:8]}...)")
else:
    info("VAPI_PUBLIC_KEY not set (optional for server-side calls)")


# ── 2. Account connectivity ───────────────────────────
section("2. Account Connectivity (GET /account)")
try:
    r = requests.get(f"{VAPI_BASE}/account", headers=HEADERS, timeout=10)
    if r.status_code == 200:
        acct = r.json()
        ok(f"Authenticated as: {acct.get('name', acct.get('id', 'unknown'))}")
        info(f"Full response: {json.dumps(acct, indent=4)}")
    else:
        fail(f"HTTP {r.status_code}: {r.text[:300]}")
except Exception as e:
    fail(f"Request failed: {e}")


# ── 3. Phone number validation ────────────────────────
section("3. Phone Number Validation (GET /phone-number/{id})")
try:
    r = requests.get(f"{VAPI_BASE}/phone-number/{VAPI_PHONE_ID}", headers=HEADERS, timeout=10)
    if r.status_code == 200:
        phone = r.json()
        ok(f"Phone number ID valid: {phone.get('number', phone.get('id'))}")
        info(f"Provider: {phone.get('provider')}")
        info(f"Name:     {phone.get('name')}")
        info(f"Status:   {phone.get('status', 'n/a')}")
    else:
        fail(f"HTTP {r.status_code}: {r.text[:300]}")
except Exception as e:
    fail(f"Request failed: {e}")


# ── 4. List recent calls ──────────────────────────────
section("4. Recent Calls (GET /call?limit=3)")
try:
    r = requests.get(f"{VAPI_BASE}/call?limit=3", headers=HEADERS, timeout=10)
    if r.status_code == 200:
        calls = r.json()
        call_list = calls if isinstance(calls, list) else calls.get("results", [])
        ok(f"Fetched {len(call_list)} recent call(s)")
        for c in call_list:
            info(f"  id={c.get('id')}  status={c.get('status')}  ended={c.get('endedReason','?')}")
    else:
        fail(f"HTTP {r.status_code}: {r.text[:300]}")
except Exception as e:
    fail(f"Request failed: {e}")


# ── 5. VapiHandler class (dry-run) ────────────────────
section("5. VapiHandler Class (mock / dry-run)")
try:
    from voice.voice_handler import VapiHandler

    handler = VapiHandler()
    # Build a sample handoff dict like agent1 would produce
    sample_handoff = {
        "borrower_name": "Test User",
        "outstanding_balance": 5000,
        "last_interaction": "borrower expressed willingness to pay"
    }

    # Patch key to force mock path so no real call is placed
    import voice.voice_handler as vh_module
    original_key = vh_module.VAPI_API_KEY
    vh_module.VAPI_API_KEY = "your-vapi-api-key"   # forces mock branch

    import logging
    logging.basicConfig(level=logging.WARNING)  # suppress noise

    result = handler.initiate_call(
        phone="+10000000000",
        agent1_handoff=sample_handoff,
        workflow_id="test-workflow-001"
    )

    vh_module.VAPI_API_KEY = original_key  # restore

    if result == "mock_call_id":
        ok("VapiHandler.initiate_call() returned mock_call_id as expected")
    else:
        fail(f"Unexpected return value: {result}")
except Exception as e:
    fail(f"VapiHandler import/init error: {e}")


# ── 6. Webhook module import ──────────────────────────
section("6. Webhook Module Import Check")
try:
    from voice.webhook import app
    routes = [r.path for r in app.routes]
    if "/vapi-webhook" in routes:
        ok("FastAPI app imported, /vapi-webhook route registered")
    else:
        fail(f"Route /vapi-webhook not found. Routes: {routes}")
except Exception as e:
    fail(f"Webhook import error: {e}")


# ── Summary ───────────────────────────────────────────
section("Summary")
print("  VAPI validation complete.")
print("  To place a real call, run via the workflow or call VapiHandler.initiate_call()")
print("  with a real phone number and workflow_id (requires ngrok + Temporal running).")

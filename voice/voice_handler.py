"""
VAPI Voice Handler — Outbound Call Management

Creates outbound phone calls via the VAPI API with a Custom LLM configuration.
The Custom LLM routes all conversation turns through our /chat/completions endpoint
where we run Claude with the resolution agent's system prompt + handoff context,
apply compliance checks, and enforce token budgets.

Architecture:
  1. Temporal activity calls initiate_call() with handoff context
  2. We build a system prompt = resolution agent prompt + token-guarded handoff ledger
  3. We create a VAPI call with Custom LLM pointing to our /chat/completions
  4. VAPI handles STT (Deepgram) → our LLM → TTS (11Labs) loop
  5. On call end, VAPI POSTs end-of-call-report to /vapi-webhook
  6. Webhook analyzes transcript, signals Temporal to resume
"""

import json
import logging
import os
import requests
import yaml
import tiktoken
from pathlib import Path
from typing import Dict, Any, Optional

from utils.config import (
    VAPI_API_KEY,
    VAPI_PHONE_ID,
    TOKEN_BUDGET_CONFIG,
    SETTLEMENT_OFFER_RANGES,
)
from voice.call_state import CallRecord, get_call_store

logger = logging.getLogger(__name__)

VAPI_BASE_URL = "https://api.vapi.ai"

# Token encoder for budget enforcement — same cl100k_base used by BaseAgent
# and summarizer.token_counter.  cl100k_base over-counts by ~5-10% vs Claude,
# giving a conservative safety margin.  One tokenizer across the entire codebase.
# In production, validate via Anthropic's /v1/messages/count_tokens endpoint.
_encoder = tiktoken.get_encoding("cl100k_base")
_SAFETY_FACTOR = 0.90  # same margin as base_agent.py


def _count_tokens(text: str) -> int:
    return len(_encoder.encode(text))


def _load_resolution_prompt() -> str:
    """Load the resolution agent's system prompt from the registry."""
    registry_path = Path(__file__).parent.parent / "registry" / "active_prompts.yaml"
    with open(registry_path, "r") as f:
        registry = yaml.safe_load(f)
    return registry["resolution"]["prompt"]


def _build_system_prompt(
    handoff_summary: Dict[str, Any],
    borrower_name: str,
    balance: float,
    hardship_detected: bool,
) -> str:
    """
    Build the full system prompt for the voice resolution agent.

    Combines the registry prompt with handoff context, settlement options,
    and compliance rules — all within the 2000-token budget.

    Token budget:
      - System prompt (base):  ~400 tokens
      - Handoff context:       ≤500 tokens (hard limit)
      - Settlement/compliance: ~200 tokens
      - Remaining:             for conversation turns
    """
    base_prompt = _load_resolution_prompt()

    # Token-guard the handoff summary to 500 tokens max
    handoff_str = json.dumps(handoff_summary) if isinstance(handoff_summary, dict) else str(handoff_summary)
    handoff_tokens = _count_tokens(handoff_str)
    if handoff_tokens > TOKEN_BUDGET_CONFIG["handoff_max"]:
        logger.warning(
            f"Handoff context exceeds budget ({handoff_tokens} > {TOKEN_BUDGET_CONFIG['handoff_max']}). Truncating."
        )
        encoded = _encoder.encode(handoff_str)
        handoff_str = _encoder.decode(encoded[: TOKEN_BUDGET_CONFIG["handoff_max"]])

    # Settlement options based on balance
    lump_sum = balance * (1 - 0.25)  # 25% discount
    plan_6 = balance / 6
    plan_12 = balance / 12

    system_prompt = f"""{base_prompt}

COMPLIANCE RULES (MANDATORY):
1. You are an AI agent — disclose this at the start of the call.
2. This call is being recorded — disclose this at the start.
3. Never threaten arrest, wage garnishment, or legal action unless it is a documented next step.
4. If the borrower mentions hardship, medical emergency, or distress, offer the hardship program.
5. If the borrower asks to stop being contacted, acknowledge and end the call.
6. Stay professional regardless of borrower behavior.
7. Use only partial identifiers — never state full account numbers.

CONTEXT FROM PRIOR CHAT ASSESSMENT:
{handoff_str}

BORROWER: {borrower_name}
OUTSTANDING BALANCE: ${balance:,.2f}
HARDSHIP DETECTED: {"Yes" if hardship_detected else "No"}

SETTLEMENT OPTIONS (present in order):
1. Lump sum: ${lump_sum:,.2f} (25% discount) — payment within 7 days
2. Payment plan: 6 monthly payments of ${plan_6:,.2f} — first due in 10 days
3. Extended plan: 12 monthly payments of ${plan_12:,.2f}
{"4. Hardship program referral — reduced payments based on financial review" if hardship_detected else ""}

POLICY RANGES:
- Lump sum discount: {SETTLEMENT_OFFER_RANGES['lump_sum_discount_min_pct']*100:.0f}%-{SETTLEMENT_OFFER_RANGES['lump_sum_discount_max_pct']*100:.0f}%
- Plan duration: {SETTLEMENT_OFFER_RANGES['payment_plan_months_min']}-{SETTLEMENT_OFFER_RANGES['payment_plan_months_max']} months

CALL STRUCTURE:
1. Open by referencing the prior chat — do NOT re-verify identity.
2. Present the lump sum option first (best for company).
3. Handle objections by restating terms, not by comforting.
4. If rejected, move to the next option.
5. Push for a verbal commitment with a clear deadline.
6. If all options exhausted with no deal, end professionally."""

    # Compliance pre-check on the built system prompt
    from compliance.checker import verify_prompt_safety
    is_safe, prompt_violations = verify_prompt_safety(system_prompt)
    if not is_safe:
        logger.error(f"Voice system prompt failed compliance check: {prompt_violations}")
        # Strip the violating section rather than blocking the call entirely
        for v in prompt_violations:
            logger.warning(f"  Violation: {v['reason']}")

    # Final token budget check
    total_tokens = _count_tokens(system_prompt)
    max_system = TOKEN_BUDGET_CONFIG["agent2_system_prompt"]
    if total_tokens > max_system:
        logger.warning(
            f"System prompt exceeds budget ({total_tokens} > {max_system}). "
            "Trimming compliance section."
        )
        # In practice this shouldn't happen with well-sized prompts,
        # but we degrade gracefully by trimming the policy ranges section
        system_prompt = system_prompt.replace(
            f"\nPOLICY RANGES:\n- Lump sum discount: {SETTLEMENT_OFFER_RANGES['lump_sum_discount_min_pct']*100:.0f}%-{SETTLEMENT_OFFER_RANGES['lump_sum_discount_max_pct']*100:.0f}%\n- Plan duration: {SETTLEMENT_OFFER_RANGES['payment_plan_months_min']}-{SETTLEMENT_OFFER_RANGES['payment_plan_months_max']} months",
            "",
        )

    return system_prompt


class VapiHandler:
    """Manages outbound VAPI voice calls for the Resolution Agent."""

    def __init__(self):
        self.api_key = VAPI_API_KEY
        self.phone_id = VAPI_PHONE_ID
        self.server_url = os.getenv("SERVER_URL", "")
        self.store = get_call_store()

    def _get_webhook_url(self) -> str:
        """Resolve the webhook URL (ngrok or direct)."""
        url = self.server_url.rstrip("/")
        if url and not url.endswith("/vapi-webhook"):
            url = f"{url}/vapi-webhook"
        return url

    def _get_custom_llm_url(self) -> str:
        """Resolve the Custom LLM endpoint URL."""
        base = self.server_url.rstrip("/")
        if base.endswith("/vapi-webhook"):
            base = base.replace("/vapi-webhook", "")
        return f"{base}/chat/completions"

    @staticmethod
    def _is_within_calling_hours(timezone_str: str = "US/Eastern") -> bool:
        """
        FDCPA § 805(a)(1): Calls must be placed between 8:00 AM and 9:00 PM
        in the borrower's local time.  Defaults to US/Eastern as conservative
        fallback when borrower timezone is unknown.
        """
        from datetime import datetime
        try:
            import zoneinfo
            tz = zoneinfo.ZoneInfo(timezone_str)
        except Exception:
            # zoneinfo unavailable (Python <3.9) — use UTC offset approximation
            from datetime import timezone, timedelta
            tz = timezone(timedelta(hours=-5))  # EST fallback
        now = datetime.now(tz)
        return 8 <= now.hour < 21  # 8:00 AM to 8:59 PM

    def initiate_call(
        self,
        phone: str,
        agent1_handoff: Dict[str, Any],
        workflow_id: str,
        borrower_name: str = "Borrower",
        balance: float = 0.0,
        hardship_detected: bool = False,
    ) -> Optional[str]:
        """
        Create an outbound VAPI phone call.

        FDCPA § 805(a)(1) enforced: calls are blocked outside 8 AM – 9 PM
        in the borrower's local timezone.

        Args:
            phone: Borrower's phone number (E.164 format)
            agent1_handoff: Handoff ledger from Agent 1 (≤500 tokens)
            workflow_id: Temporal workflow ID for signal routing
            borrower_name: Borrower's name from assessment
            balance: Outstanding debt balance
            hardship_detected: Whether Agent 1 flagged hardship

        Returns:
            VAPI call ID, or None on failure
        """
        # FDCPA time-of-day restriction
        if not self._is_within_calling_hours():
            logger.warning(
                "FDCPA: Call blocked — outside permitted hours (8 AM – 9 PM). "
                f"Borrower: {borrower_name}, workflow: {workflow_id}"
            )
            return None
        # Build the full system prompt
        system_prompt = _build_system_prompt(
            agent1_handoff, borrower_name, balance, hardship_detected
        )

        logger.info(
            f"System prompt built: {_count_tokens(system_prompt)} tokens "
            f"(budget: {TOKEN_BUDGET_CONFIG['agent2_system_prompt']})"
        )

        # First message references the prior chat naturally
        first_message = (
            f"Hello {borrower_name}, this is the resolution team following up on our "
            f"earlier chat regarding your account. I'm an AI agent, and I want to let "
            f"you know this call is being recorded. This is an attempt to collect a debt "
            f"and any information obtained will be used for that purpose. I have some "
            f"options that could help resolve the outstanding balance — do you have a "
            f"few minutes to discuss?"
        )

        # VAPI assistant configuration with Custom LLM
        assistant_config = {
            "model": {
                "provider": "custom-llm",
                "url": self._get_custom_llm_url(),
                "model": "claude-haiku-4-5-20251001",
                "messages": [{"role": "system", "content": system_prompt}],
            },
            "voice": {
                "provider": "11labs",
                "voiceId": "pFZP5JQG7iQjIQuC4Bku",  # 11Labs "Lily" — professional female
                "stability": 0.6,
                "similarityBoost": 0.75,
            },
            "transcriber": {
                "provider": "deepgram",
                "model": "nova-3",
                "language": "en",
            },
            "firstMessage": first_message,
            "endCallMessage": "Thank you for your time. We'll follow up with the details in writing. Goodbye.",
            "serverUrl": self._get_webhook_url(),
            "silenceTimeoutSeconds": 20,
            "maxDurationSeconds": 600,  # 10 min max
            "backgroundSound": "off",
            "endCallFunctionEnabled": True,
            "metadata": {
                "temporal_workflow_id": workflow_id,
                "borrower_name": borrower_name,
                "balance": str(balance),
            },
        }

        payload = {
            "assistant": assistant_config,
            "phoneNumberId": self.phone_id,
            "customer": {"number": phone},
        }

        # Register call state before making the API call
        call_record = CallRecord(
            call_id="pending",  # Updated after API response
            workflow_id=workflow_id,
            borrower_name=borrower_name,
            borrower_phone=phone,
            balance=balance,
            handoff_summary=json.dumps(agent1_handoff),
            system_prompt=system_prompt,
        )

        # Idempotency: check if a call for this workflow already exists.
        # On activity retry, this prevents duplicate outbound calls.
        existing = self.store.get_by_workflow_id(workflow_id)
        if existing and existing.call_id and existing.call_id != "pending":
            logger.info(
                f"Idempotency: call already exists for workflow {workflow_id} "
                f"(call_id={existing.call_id}). Returning existing."
            )
            return existing.call_id

        # Guard: skip if no real API key
        if not self.api_key or self.api_key in ("your-vapi-api-key", ""):
            logger.warning("VAPI API key not configured — returning mock call ID")
            call_record.call_id = f"mock-{workflow_id}"
            self.store.register(call_record)
            return call_record.call_id

        try:
            logger.info(
                f"Creating VAPI outbound call: phone={phone}, workflow={workflow_id}"
            )
            resp = requests.post(
                f"{VAPI_BASE_URL}/call",
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=30,
            )
            resp.raise_for_status()

            call_data = resp.json()
            call_id = call_data.get("id", f"unknown-{workflow_id}")
            call_record.call_id = call_id
            self.store.register(call_record)

            logger.info(
                f"VAPI call created: id={call_id}, status={call_data.get('status')}"
            )
            return call_id

        except requests.exceptions.HTTPError as e:
            error_body = ""
            try:
                error_body = e.response.text
            except Exception:
                pass
            logger.error(f"VAPI API error: {e.response.status_code} — {error_body}")
            return None
        except requests.exceptions.Timeout:
            logger.error("VAPI API timeout (30s)")
            return None
        except Exception as e:
            logger.error(f"VAPI call creation failed: {e}")
            return None

    def get_call_status(self, call_id: str) -> Optional[Dict]:
        """Poll VAPI for call status (for debugging / monitoring)."""
        if not self.api_key or self.api_key in ("your-vapi-api-key", ""):
            return {"id": call_id, "status": "mock"}

        try:
            resp = requests.get(
                f"{VAPI_BASE_URL}/call/{call_id}",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Failed to get call status: {e}")
            return None

"""
Agent 2: Resolution (Voice)
Role: Transactional dealmaker. Present settlement options, handle objections, push for commitment.
Operates via voice (Vapi integration) but also supports chat-based simulation.
"""

import json
import logging
from typing import Dict, List, Optional
from utils.llm import call_llm
from utils.config import get_model, SETTLEMENT_OFFER_RANGES
from compliance.checker import check_message_compliance
from agents.base_agent import BaseAgent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ResolutionAgent(BaseAgent):
    def __init__(self):
        super().__init__("resolution")

    def _get_borrower_response(self, borrower_context, turn: int, agent_msg: str, state: dict) -> str:
        """Get borrower response from test harness or stdin."""
        if hasattr(borrower_context, "test_borrower_response_fn"):
            return borrower_context.test_borrower_response_fn(turn, agent_msg, state)
        print(f"\n  Agent: {agent_msg}")
        return input(f"  Borrower (turn {turn}): ").strip()

    def run_resolution_agent(self, borrower_context) -> Dict:
        """Run resolution agent negotiation loop."""
        messages: List[Dict] = []
        offers_made: List[Dict] = []
        deal_terms = None
        deal_agreed = False
        turns = 0
        MAX_TURNS = 15

        borrower_name = borrower_context.name
        balance = borrower_context.balance
        handoff_summary = borrower_context.agent1_summary or {}
        hardship_detected = borrower_context.hardship_detected

        # System prompt with token-guarded handoff context
        guarded_handoff = self.enforce_token_guard(json.dumps(handoff_summary))
        system_prompt = self.system_prompt + f"\n\nCONTEXT FROM PRIOR CHAT:\n{guarded_handoff}"

        # Settlement options to present in order
        settlement_options = [
            {
                "type": "lump_sum",
                "discount_pct": 0.25,
                "details": f"Settlement of ${balance * 0.75:.2f} (25% discount) if paid within 7 days",
            },
            {
                "type": "payment_plan",
                "months": 6,
                "monthly": balance / 6,
                "details": f"6 monthly payments of ${balance / 6:.2f}, first due in 10 days",
            },
            {
                "type": "hardship_referral" if hardship_detected else "payment_plan_extended",
                "details": (
                    "Hardship program — reduced payments based on financial review"
                    if hardship_detected
                    else f"12 monthly payments of ${balance / 12:.2f}"
                ),
            },
        ]

        current_option_index = 0

        # Opening message (includes compliance disclosures)
        opening = (
            f"Hi {borrower_name}, this is the resolution team calling regarding "
            f"the ${balance:,.2f} balance we discussed via chat. I'm an AI agent, "
            f"and this call is being recorded. This is an attempt to collect a debt "
            f"and any information obtained will be used for that purpose. I have some "
            f"settlement options that could help resolve this — do you have a moment?"
        )
        messages.append({"role": "assistant", "content": opening})

        # Get initial borrower response
        user_msg = self._get_borrower_response(
            borrower_context, 0, opening, {"offers": offers_made}
        )
        if not user_msg:
            user_msg = "Go ahead."
        messages.append({"role": "user", "content": user_msg})

        # ── Negotiation loop ──
        # Invariant: messages always ends with a "user" role before calling LLM
        while turns < MAX_TURNS and not deal_agreed:
            turns += 1

            # Check for immediate exit conditions BEFORE calling LLM
            user_msg_lower = messages[-1]["content"].lower()

            # Stop-contact request (FDCPA mandatory)
            if any(phrase in user_msg_lower for phrase in ["stop calling", "leave me alone", "do not contact", "stop contacting"]):
                closing = (
                    "I understand and I'll note your request immediately. No further "
                    "calls will be made. You may receive a written notice for your records. "
                    "Thank you for your time."
                )
                messages.append({"role": "assistant", "content": closing})
                borrower_context.mark_stop_contact()
                break

            # Hardship detection
            if any(phrase in user_msg_lower for phrase in ["hardship", "lost my job", "can't afford", "medical emergency", "crisis"]):
                closing = (
                    "I hear that you're in a difficult situation. We have a hardship "
                    "program that can help with reduced payments based on your financial "
                    "review. Let me connect you with that team right away."
                )
                messages.append({"role": "assistant", "content": closing})
                break

            # Agreement detection
            if any(word in user_msg_lower for word in ["yes", "agree", "deal", "accept", "i'll take", "works for me", "fine"]):
                deal_agreed = True
                deal_terms = settlement_options[min(current_option_index, len(settlement_options) - 1)].copy()
                deal_terms["agreed_turn"] = turns
                # Let LLM confirm the deal naturally
                confirm_prompt = system_prompt + "\n\nThe borrower just agreed. Confirm the deal terms briefly and thank them."
                budgeted_messages = self.enforce_message_budget(messages)
                response = call_llm(
                    system=confirm_prompt,
                    messages=budgeted_messages,
                    model=get_model("agent"),
                    max_tokens=150,
                    context_category="voice_resolution",
                )
                messages.append({"role": "assistant", "content": response})
                logger.info(f"Deal agreed on {deal_terms['type']}")
                break

            # Rejection — advance to next option
            if any(word in user_msg_lower for word in ["no", "refuse", "not paying", "won't", "can't do"]):
                current_option_index += 1
                if current_option_index >= len(settlement_options):
                    closing = (
                        "I understand. We've gone through all available options. Your account "
                        "will proceed to the next stage, and you'll receive written notice of "
                        "the next steps. Thank you for your time."
                    )
                    messages.append({"role": "assistant", "content": closing})
                    break

            # Generate LLM response for this turn
            # Inject current settlement context into system prompt
            opt = settlement_options[min(current_option_index, len(settlement_options) - 1)]
            turn_system = system_prompt + f"\n\nCURRENT OFFER TO PRESENT: {opt['details']}"

            # Hard-enforce 2000-token budget before every LLM dispatch
            budgeted_messages = self.enforce_message_budget(messages)

            response = call_llm(
                system=turn_system,
                messages=budgeted_messages,
                model=get_model("agent"),
                max_tokens=200,
                context_category="voice_resolution",
            )

            # Compliance check
            context = {
                "turn_number": turns,
                "borrower_last_message": messages[-1]["content"],
                "settlement_offer": opt,
                "policy_ranges": SETTLEMENT_OFFER_RANGES,
            }
            is_compliant, violations = check_message_compliance(
                response, agent_name="resolution", context=context
            )
            for v in violations:
                borrower_context.add_compliance_violation(v["type"], v["severity"], v["reason"])
            if not is_compliant:
                logger.warning(f"Agent 2 compliance violation(s) on turn {turns}: {violations}")
                # Hard stop: if any CRITICAL violation, replace response with safe fallback
                critical = [v for v in violations if v["severity"] == "critical"]
                if critical:
                    logger.error(f"Agent 2 CRITICAL violation — blocking message: {critical[0]['type']}")
                    response = (
                        "I apologize — let me rephrase. I'm an AI agent and this call is "
                        "being recorded. This is an attempt to collect a debt. "
                        "Let me explain the available settlement options."
                    )
                # Conversation-level hard stop: 3+ critical violations → terminate
                total_critical = sum(
                    1 for v in borrower_context.compliance_violations
                    if v.get("severity") == "critical"
                )
                if total_critical >= 3:
                    logger.error(
                        f"Agent 2 CONVERSATION TERMINATED: {total_critical} critical "
                        "violations exceeded safety threshold."
                    )
                    closing = (
                        "I apologize, but I need to end this call. A supervisor will "
                        "follow up with you. Thank you for your time."
                    )
                    messages.append({"role": "assistant", "content": closing})
                    borrower_context.agent2_transcript = "\n".join(
                        f"{m['role'].upper()}: {m['content']}" for m in messages
                    )
                    return {
                        "result": {"outcome": "compliance_terminated", "turns": turns},
                        "transcript": borrower_context.agent2_transcript,
                        "offers_made": offers_made,
                        "outcome": "compliance_terminated",
                        "deal_terms": None,
                    }

            messages.append({"role": "assistant", "content": response})

            # Track offers mentioned
            if any(kw in response.lower() for kw in ["settlement", "option", "offer", "payment", "lump"]):
                offers_made.append({
                    "offer_type": opt["type"],
                    "details": opt["details"],
                    "turn": turns,
                })

            # Get next borrower response
            user_msg = self._get_borrower_response(
                borrower_context, turns, response, {"offers": offers_made}
            )
            if not user_msg:
                break
            messages.append({"role": "user", "content": user_msg})

        # ── Build result ──
        borrower_context.agent2_transcript = "\n".join(
            f"{msg['role'].upper()}: {msg['content']}" for msg in messages
        )
        borrower_context.agent2_offers_made = offers_made

        # Set agent2_summary so Agent 3 gets a real handoff (not empty dict)
        borrower_context.agent2_summary = {
            "prior_outcome": "deal_agreed" if deal_agreed else (
                "stop_contact" if borrower_context.stop_contact_requested else "no_deal"
            ),
            "offers_rejected": [o for o in offers_made if not deal_agreed],
            "offers_accepted": [settlement_options[min(current_option_index, len(settlement_options) - 1)]] if deal_agreed else [],
            "objections": [
                m["content"] for m in messages
                if m["role"] == "user" and any(
                    w in m["content"].lower() for w in ["no", "refuse", "can't", "won't", "expensive"]
                )
            ][:5],
            "hardship_detected": hardship_detected,
            "turns": turns,
            "deal_terms": deal_terms,
        }

        if deal_agreed:
            outcome = "deal_agreed"
            borrower_context.final_outcome = "resolved_voice"
        elif borrower_context.stop_contact_requested:
            outcome = "stop_contact"
        elif any(
            "hardship program" in msg.get("content", "").lower()
            for msg in messages
            if msg["role"] == "assistant"
        ):
            outcome = "hardship_referral"
        elif turns >= MAX_TURNS:
            outcome = "max_turns_exceeded"
        else:
            outcome = "no_deal"

        return {
            "result": {
                "offers_made": offers_made,
                "outcome": outcome,
                "deal_terms": deal_terms,
                "turns": turns,
            },
            "messages": messages,
            "transcript": borrower_context.agent2_transcript,
            "offers_made": offers_made,
            "outcome": outcome,
            "deal_terms": deal_terms,
        }

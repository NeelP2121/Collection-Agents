"""
Agent 3: Final Notice (Chat)
Role: Consequence-driven, deadline-focused. States what happens next: credit reporting, legal referral, asset recovery.
"""

import json
import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from utils.llm import call_llm
from utils.config import get_model
from compliance.checker import check_message_compliance
from agents.base_agent import BaseAgent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class FinalNoticeAgent(BaseAgent):
    def __init__(self):
        super().__init__("final_notice")
        
    def run_final_notice_agent(self, borrower_context) -> Dict:
        """
        Run final notice agent (last collection attempt).
        """
        final_message = ""
        final_offer = None
        compliance_violations = []
        turns = 0
        resolved = False
        
        borrower_name = borrower_context.name
        balance = borrower_context.balance
        handoff_summary = borrower_context.agent2_summary or {}
        hardship_detected = borrower_context.hardship_detected
        offers_made = borrower_context.agent2_offers_made
        
        guarded_handoff = self.enforce_token_guard(json.dumps(handoff_summary))
        system_prompt = self.system_prompt + f"\n\nCONTEXT FROM PRIOR INTERACTIONS:\n{guarded_handoff}"

        MAX_TURNS = 8

        deadline = (datetime.utcnow() + timedelta(days=7)).strftime("%B %d, %Y")

        final_settlement_amount = balance * 0.80
        final_offer = {
            "type": "final_lump_sum",
            "amount": final_settlement_amount,
            "deadline": deadline,
            "discount_pct": 0.20,
        }

        # Build narrative-continuous opening that references prior interactions
        voice_outcome = str(handoff_summary.get("prior_outcome", handoff_summary.get("outcome", ""))).lower()
        deal = handoff_summary.get("deal_terms") or {}
        
        # Robust deal detection: Must have 'agree' or 'deal' in outcome AND not be 'no_deal'
        is_deal = ("agree" in voice_outcome or "deal_agreed" in voice_outcome) and "no_deal" not in voice_outcome
        
        if is_deal and deal.get("amount"):
            amount = deal.get('amount')
            deal_desc = f"a settlement of ${amount:,.2f}"
            resolved = True # Mark as resolved to trigger success message logic
            
            sys_prompt = self.system_prompt + (
                f"\n\nCRITICAL INSTRUCTION: The borrower JUST ACCEPTED a deal ({deal_desc}) over the phone! "
                "DO NOT THREATEN THEM. DO NOT offer a new discount. "
                "YOUR ONLY TASK is to: "
                "1. Warmly congratulate them on resolving their debt. "
                f"2. Confirm the exact terms reached: {deal_desc}. "
                "3. Explain that a formal agreement and payment instructions will be emailed to them immediately. "
                "4. Be professional and supportive."
            )
            opening = f"I am so glad we could reach an agreement during our call. To confirm, you have agreed to {deal_desc} to resolve this account. We will send the formal agreement to your email address on file immediately."
        else:
            prior_offers = handoff_summary.get("offers_rejected", offers_made) or offers_made
            prior_objections = handoff_summary.get("objections", [])

            continuity_parts = [
                "I am an AI agent and this conversation is being recorded. "
                "This is an attempt to collect a debt and any information obtained "
                "will be used for that purpose."
            ]

            if voice_outcome == "no_deal" and prior_offers:
                offer_labels = []
                for o in prior_offers[:3]:
                    if isinstance(o, str):
                        offer_labels.append(o)
                    elif isinstance(o, dict):
                        offer_labels.append(o.get("type", "settlement option"))
                continuity_parts.append(
                    f"Following up on our phone call — I understand you were unable to "
                    f"reach an agreement on the options discussed ({', '.join(offer_labels)})."
                )
                if prior_objections:
                    obj_text = "; ".join(str(o) for o in prior_objections[:2])
                    continuity_parts.append(f"Your concerns were noted: {obj_text}.")
            elif voice_outcome:
                continuity_parts.append(
                    "This continues from our previous chat and phone conversations about your account."
                )
            else:
                continuity_parts.append(
                    "This follows up on our prior communications regarding your account."
                )

            if hardship_detected:
                continuity_parts.append(
                    "We are aware of the financial difficulty you mentioned, and our final "
                    "offer reflects that."
                )

            continuity_intro = " ".join(continuity_parts)

            opening = (
                f"{continuity_intro}\n\n"
                f"Regarding your ${balance:,.2f} outstanding balance — this is your final "
                f"opportunity to resolve this before additional collection actions begin.\n\n"
                f"FINAL SETTLEMENT OFFER:\n"
                f"We can settle your debt for ${final_settlement_amount:,.2f} "
                f"({int(final_offer['discount_pct'] * 100)}% discount) if received by {deadline}.\n\n"
                f"If we do not receive payment or commitment by {deadline}, we will:\n"
                f"1. Report this debt to all major credit bureaus\n"
                f"2. Refer your account for legal proceedings\n\n"
                f"Please respond with your decision."
            )
            sys_prompt = self.system_prompt + f"\n\nCONTEXT FROM PRIOR INTERACTIONS:\n{guarded_handoff}"

        # Start with user greeting so messages alternate correctly for LLM calls
        messages = [
            {"role": "user", "content": "I received your notice. What is this about?"},
            {"role": "assistant", "content": opening},
        ]
        final_message = opening

        while turns < MAX_TURNS:
            turns += 1

            if hasattr(borrower_context, 'test_borrower_response_fn'):
                user_msg = borrower_context.test_borrower_response_fn(turns, final_message, {"offers": offers_made})
            else:
                import sys
                if sys.stdin.isatty():
                    user_msg = input(f"Borrower response (turn {turns}): ").strip()
                else:
                    user_msg = ""

            if not user_msg:
                break

            messages.append({"role": "user", "content": user_msg})
            user_msg_lower = user_msg.lower()

            if any(word in user_msg_lower for word in ["yes", "agree", "pay", "settle", "deal", "accept"]):
                resolved = True
                response = f"Thank you for confirming. We'll send payment instructions to you. Payment is due by {deadline}. Once received, your account will be marked as resolved."
                messages.append({"role": "assistant", "content": response})
                final_message = response
                logger.info("Final notice: Borrower agreed to settlement")
                break

            elif any(word in user_msg_lower for word in ["stop", "leave me alone", "do not contact"]):
                response = "Acknowledged. No further contact will be made. You will receive a final written notice for your records."
                messages.append({"role": "assistant", "content": response})
                final_message = response
                borrower_context.mark_stop_contact()
                break

            elif any(word in user_msg_lower for word in ["hardship", "emergency", "crisis", "medical", "can't afford"]):
                response = "I understand you're in a difficult situation. We can connect you with our hardship program for reduced payment options based on your financial situation."
                messages.append({"role": "assistant", "content": response})
                final_message = response

            elif any(word in user_msg_lower for word in ["no", "refuse", "won't", "can't"]):
                response = f"Understood. The offer of ${final_settlement_amount:,.2f} stands until {deadline}. After that date, your account will proceed to credit reporting and legal referral. Contact us if you change your mind."
                messages.append({"role": "assistant", "content": response})
                final_message = response
                break

            else:
                # Hard-enforce 2000-token budget before every LLM dispatch
                budgeted_messages = self.enforce_message_budget(messages)

                response = call_llm(
                    system=system_prompt,
                    messages=budgeted_messages,
                    model=get_model("agent"),
                    max_tokens=200,
                    context_category="final_notice",
                )

                context = {
                    "turn_number": turns,
                    "borrower_last_message": user_msg,
                }
                is_compliant, violations = check_message_compliance(response, agent_name="final_notice", context=context)
                for violation in violations:
                    borrower_context.add_compliance_violation(
                        violation["type"], violation["severity"], violation["reason"]
                    )

                if not is_compliant:
                    logger.warning(f"Agent 3 compliance violation(s): {violations}")
                    critical = [v for v in violations if v["severity"] == "critical"]
                    if critical:
                        logger.error(f"Agent 3 CRITICAL violation — blocking message: {critical[0]['type']}")
                        response = (
                            "I am an AI agent and this conversation is being recorded. "
                            "This is an attempt to collect a debt and any information "
                            "obtained will be used for that purpose. I apologize for the "
                            "confusion. Let me clarify the settlement options available."
                        )
                    # Conversation-level hard stop: 3+ critical violations → terminate
                    total_critical = sum(
                        1 for v in borrower_context.compliance_violations
                        if v.get("severity") == "critical"
                    )
                    if total_critical >= 3:
                        logger.error(
                            f"Agent 3 CONVERSATION TERMINATED: {total_critical} critical "
                            "violations exceeded safety threshold."
                        )
                        messages.append({"role": "assistant", "content": response})
                        borrower_context.agent3_messages = messages
                        borrower_context.final_outcome = "compliance_terminated"
                        return {
                            "result": {"outcome": "compliance_terminated", "turns": turns},
                            "messages": messages,
                            "outcome": "compliance_terminated",
                        }

                messages.append({"role": "assistant", "content": response})
                final_message = response
        
        borrower_context.agent3_messages = messages
        
        outcome = "resolved" if resolved else "unresolved"
        if turns == 0 or not messages:
            outcome = "no_response"
        
        borrower_context.final_outcome = outcome
        
        return {
            "result": {
                "final_offer": final_offer,
                "deadline": deadline,
                "outcome": outcome,
                "turns": turns,
            },
            "messages": messages,
            "outcome": outcome,
        }
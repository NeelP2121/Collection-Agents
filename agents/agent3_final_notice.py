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
        
        opening = f"Dear {borrower_name},\n\nThis is a final notice regarding your {balance:.2f} outstanding debt. We have made multiple settlement offers. This is your final opportunity to resolve this before we proceed with additional collection actions.\n\nFINAL SETTLEMENT OFFER:\nWe can settle your debt for {final_settlement_amount:.2f} ({int(final_offer['discount_pct'] * 100)}% discount) if received by {deadline}.\n\nIf we do not receive payment or commitment by {deadline}, we will:\n1. Report this debt to all credit agencies\n2. Refer your account for legal proceedings\n\nYour next step: Contact us with your response by {deadline}."
        
        messages = [{"role": "assistant", "content": opening}]
        final_message = opening
        
        while turns < MAX_TURNS:
            turns += 1
            
            if hasattr(borrower_context, 'test_borrower_response_fn'):
                user_msg = borrower_context.test_borrower_response_fn(turns, opening, {"offers": offers_made})
            else:
                user_msg = input(f"Borrower response (turn {turns}): ").strip()
            
            if not user_msg:
                break
            
            messages.append({"role": "user", "content": user_msg})
            user_msg_lower = user_msg.lower()
            
            if any(word in user_msg_lower for word in ["yes", "agree", "pay", "settle", "deal"]):
                resolved = True
                response = f"Thank you for confirming. We'll send you payment instructions. Please send payment by {deadline}."
                messages.append({"role": "assistant", "content": response})
                final_message = response
                logger.info("Final notice: Borrower agreed to settlement")
                break
            
            elif any(word in user_msg_lower for word in ["hardship", "emergency", "crisis", "medical", "help"]):
                response = "I understand you're in a difficult situation. Our hardship program has options that might help."
                messages.append({"role": "assistant", "content": response})
                final_message = response
            
            elif "no" in user_msg_lower or "refuse" in user_msg_lower or "can't" in user_msg_lower:
                response = f"I understand. The offer stands until {deadline}. If you change your mind, contact us."
                messages.append({"role": "assistant", "content": response})
                final_message = response
                break
            
            else:
                response = call_llm(
                    system=system_prompt,
                    messages=messages,
                    model=get_model("agent"),
                    max_tokens=200
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
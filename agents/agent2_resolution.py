"""
Agent 2: Resolution (Voice)
Role: Transactional dealmaker. Present settlement options, handle objections, push for commitment.
Operates via voice (Vapi integration) but also supports chat-based simulation.
"""

import json
import logging
from typing import Dict, List, Optional
from utils.llm import call_llm
from utils.config import LLM_MODELS, SETTLEMENT_OFFER_RANGES
from compliance.checker import check_message_compliance
from agents.base_agent import BaseAgent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ResolutionAgent(BaseAgent):
    def __init__(self):
        super().__init__("resolution")
        
    def run_resolution_agent(self, borrower_context) -> Dict:
        """
        Run resolution agent (voice negotiation).
        """
        messages = []
        offers_made = []
        deal_terms = None
        deal_agreed = False
        compliance_violations = []
        turns = 0
        
        borrower_name = borrower_context.name
        balance = borrower_context.balance
        handoff_summary = borrower_context.agent1_summary or {}
        hardship_detected = borrower_context.hardship_detected
        ability_to_pay = borrower_context.ability_to_pay
        
        # Prepare system prompt with context and guarded handoff
        guarded_handoff = self.enforce_token_guard(json.dumps(handoff_summary))
        system_prompt = self.system_prompt + f"\n\nCONTEXT FROM PRIOR CHAT:\n{guarded_handoff}"
        
        MAX_TURNS = 15
        
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
                "details": "Hardship program or extended 12-month plan" if hardship_detected else "12 monthly payments of ${:.2f}".format(balance / 12),
            }
        ]
        
        opening = f"Hi {borrower_name}, this is [Company] calling regarding the ${balance:.2f} debt we discussed via chat. I have some settlement options to present that could work better for you."
        messages.append({"role": "assistant", "content": opening})
        offers_presented_count = 0
        current_option_index = 0
        
        while turns < MAX_TURNS and not deal_agreed and current_option_index < len(settlement_options):
            turns += 1
            
            response = call_llm(
                system=system_prompt,
                messages=messages,
                model=LLM_MODELS["agent"],
                max_tokens=250
            )
            
            context = {
                "turn_number": turns,
                "borrower_last_message": messages[-1]["content"] if len(messages) > 1 else "",
                "settlement_offer": settlement_options[current_option_index] if current_option_index < len(settlement_options) else None,
                "policy_ranges": SETTLEMENT_OFFER_RANGES,
            }
            is_compliant, violations = check_message_compliance(response, context)
            for violation in violations:
                borrower_context.add_compliance_violation(
                    violation["type"], violation["severity"], violation["reason"]
                )
            
            if not is_compliant:
                logger.warning(f"Agent 2 compliance violation(s): {violations}")
            
            messages.append({"role": "assistant", "content": response})
            
            if "option" in response.lower() or "settlement" in response.lower():
                offers_made.append({
                    "offer_type": settlement_options[current_option_index]["type"],
                    "details": settlement_options[current_option_index]["details"],
                    "turn": turns,
                })
                offers_presented_count += 1
            
            if hasattr(borrower_context, 'test_borrower_response_fn'):
                user_msg = borrower_context.test_borrower_response_fn(turns, response, {"offers": offers_made})
            else:
                user_msg = input(f"Borrower voice response (turn {turns}): ").strip()
            
            if not user_msg:
                break
            
            messages.append({"role": "user", "content": user_msg})
            user_msg_lower = user_msg.lower()
            
            if any(word in user_msg_lower for word in ["yes", "agree", "okay", "deal", "works", "fine"]):
                deal_agreed = True
                deal_terms = settlement_options[current_option_index].copy()
                deal_terms["agreed_turn"] = turns
                logger.info(f"Deal agreed on {settlement_options[current_option_index]['type']}")
                break
            
            elif any(word in user_msg_lower for word in ["no", "don't", "can't", "refuse"]):
                current_option_index += 1
                if current_option_index < len(settlement_options):
                    response = "I understand. Let me present another option..."
                    messages.append({"role": "assistant", "content": response})
            
            elif "hardship" in user_msg_lower or "emergency" in user_msg_lower or "crisis" in user_msg_lower:
                response = "I hear that you're in a difficult situation. We have a hardship program that might help. Let me connect you with that team."
                messages.append({"role": "assistant", "content": response})
                break
        
        borrower_context.agent2_transcript = "\n".join([f"{msg['role'].upper()}: {msg['content']}" for msg in messages])
        borrower_context.agent2_offers_made = offers_made
        
        if deal_agreed:
            outcome = "deal_agreed"
            borrower_context.final_outcome = "resolved_voice"
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
            "transcript": borrower_context.agent2_transcript,
            "offers_made": offers_made,
            "outcome": outcome,
            "deal_terms": deal_terms,
        }
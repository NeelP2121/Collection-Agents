"""
Agent 1: Assessment (Chat)
Role: Cold, clinical, information-gathering. Verify identity, assess financial situation, detect hardship.
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

class AssessmentAgent(BaseAgent):
    def __init__(self):
        super().__init__("assessment")

    def run_assessment_agent(self, borrower_context) -> Dict:
        """
        Run assessment agent with a borrower.
        """
        messages = []
        compliance_violations = []
        
        borrower_name = borrower_context.name
        borrower_phone = borrower_context.phone
        
        state = {
            "identity_attempts": 0,
            "debt_acknowledged": False,
            "employment_gathered": False,
            "income_gathered": False,
            "hardship_status": None,
            "payment_capability": None,
        }
        
        debt_data = {
            "balance": 4200.00,
            "balance_partial": "...7391",
            "zip_partial": "94102",
            "due_date": "2025-05-01",
        }
        
        MAX_TURNS = 10
        turn = 0
        
        while turn < MAX_TURNS:
            turn += 1
            
            response = call_llm(
                system=self.system_prompt,
                messages=messages,
                model=LLM_MODELS["agent"],
                max_tokens=300
            )
            
            context = {
                "turn_number": turn,
                "borrower_stop_requested": borrower_context.stop_contact_requested,
                "borrower_last_message": messages[-1]["content"] if messages else ""
            }
            is_compliant, violations = check_message_compliance(response, context)
            for violation in violations:
                borrower_context.add_compliance_violation(
                    violation["type"], violation["severity"], violation["reason"]
                )
            
            if not is_compliant:
                logger.warning(f"Agent 1 compliance violation(s): {violations}")
            
            messages.append({"role": "assistant", "content": response})
            
            if hasattr(borrower_context, 'test_borrower_response_fn'):
                user_msg = borrower_context.test_borrower_response_fn(turn, response, state)
            else:
                user_msg = input(f"Borrower (turn {turn}): ").strip()
            
            if not user_msg:
                break
            
            messages.append({"role": "user", "content": user_msg})
            user_msg_lower = user_msg.lower()
            
            if "stop" in user_msg_lower or "don't call" in user_msg_lower:
                borrower_context.mark_stop_contact()
                break
            
            if not borrower_context.identity_verified:
                state["identity_attempts"] += 1
                if debt_data["balance_partial"].replace(".", "").split("7391")[-1] in user_msg and debt_data["zip_partial"] in user_msg:
                    borrower_context.mark_identity_verified()
                    state["debt_acknowledged"] = True
                elif state["identity_attempts"] >= 2:
                    break
            
            if borrower_context.identity_verified and not state["employment_gathered"]:
                if any(word in user_msg_lower for word in ["employed", "unemployed", "retired", "disabled", "self-employed"]):
                    state["employment_gathered"] = True
                    if "employed" in user_msg_lower and "un" not in user_msg_lower:
                        borrower_context.employment_status = "employed"
                    elif "unemployed" in user_msg_lower or "lost job" in user_msg_lower:
                        borrower_context.employment_status = "unemployed"
                        borrower_context.mark_hardship()
                    elif "retired" in user_msg_lower:
                        borrower_context.employment_status = "retired"
                    elif "disabled" in user_msg_lower:
                        borrower_context.employment_status = "disabled"
            
            hardship_keywords = ["lost job", "medical", "emergency", "no income", "can't pay", "homeless", "hospital"]
            if any(kw in user_msg_lower for kw in hardship_keywords):
                borrower_context.mark_hardship()
            
            if "can pay" in user_msg_lower or "can afford" in user_msg_lower:
                borrower_context.ability_to_pay = "can_pay"
            elif "partial" in user_msg_lower:
                borrower_context.ability_to_pay = "partial"
            elif "cannot" in user_msg_lower or "can't" in user_msg_lower:
                borrower_context.ability_to_pay = "cannot_pay"
        
        borrower_context.balance = debt_data["balance"]
        borrower_context.agent1_messages = messages
        
        if borrower_context.stop_contact_requested:
            outcome = "stop_requested"
        elif not borrower_context.identity_verified:
            outcome = "failed_verification"
        elif turn >= MAX_TURNS:
            outcome = "max_turns_exceeded"
        else:
            outcome = "completed"
        
        return {
            "result": {
                "identity_verified": borrower_context.identity_verified,
                "balance": borrower_context.balance,
                "employment_status": borrower_context.employment_status,
                "ability_to_pay": borrower_context.ability_to_pay,
                "hardship_detected": borrower_context.hardship_detected,
                "stop_contact_requested": borrower_context.stop_contact_requested,
            },
            "messages": messages,
            "outcome": outcome,
        }
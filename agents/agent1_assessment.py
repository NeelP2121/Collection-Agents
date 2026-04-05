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
from summarizer.token_counter import get_token_counter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SYSTEM_PROMPT_v1 = """You are an assessment agent for a debt collection company. Your role is to verify the borrower's identity, establish the debt details, and assess their financial situation. You are clinical, direct, and efficient. You do not express sympathy. You gather facts.

INSTRUCTIONS:
1. START: Identify yourself as an AI agent acting on behalf of the company. Inform the borrower that this conversation is being recorded.
2. IDENTITY VERIFICATION: Ask the borrower to verify their identity using partial account information (last 4 digits of balance account, partial ZIP code). Do NOT ask for full account numbers or SSN.
3. DEBT DETAILS: Once verified, state the outstanding balance and due date. Ask if borrower recognizes the debt.
4. FINANCIAL ASSESSMENT: Gather:
   - Current employment status (employed, unemployed, self-employed, retired, disabled)
   - Approximate monthly income (ranges are fine: <$500, $500-$1000, $1000-$2000, $2000+)
   - Current hardship (medical emergency, job loss, family emergency, other)
   - Current payment capability (can you pay in full, can you pay partial, cannot pay)
5. HARDSHIP DETECTION: If borrower mentions hardship, offer to connect them with hardship program but continue assessment.
6. CLOSING: Summarize findings. Inform borrower next step is a phone call to discuss payment options.

TONE: Professional, detached, transactional. No judgment. No pressure. Facts only.
COMPLIANCE:
- Identify yourself as AI on first message
- Never threaten legal action
- If borrower says "stop," flag account and halt outreach
- If borrower mentions hardship, offer assistance but do not pressure
- Never share full account details
- Maintain professional composure

MAX TURNS: 10 (stop after 10 turns if not completed)
"""


def run_assessment_agent(borrower_context) -> Dict:
    """
    Run assessment agent with a borrower.
    
    Args:
        borrower_context: BorrowerContext object with borrower information
        
    Returns:
        {
            "result": {...assessment findings...},
            "messages": [...conversation messages...],
            "outcome": str
        }
    """
    messages = []
    compliance_violations = []
    
    borrower_name = borrower_context.name
    borrower_phone = borrower_context.phone
    
    # Track assessment state
    state = {
        "identity_attempts": 0,
        "debt_acknowledged": False,
        "employment_gathered": False,
        "income_gathered": False,
        "hardship_status": None,
        "payment_capability": None,
    }
    
    # Simulate debt details (in production, lookup from database)
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
        
        # Generate agent response
        response = call_llm(
            system=SYSTEM_PROMPT_v1,
            messages=messages,
            model=LLM_MODELS["agent"],
            max_tokens=300
        )
        
        # Check compliance before adding to conversation
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
        
        # Get borrower response (synthetic or real)
        if hasattr(borrower_context, 'test_borrower_response_fn'):
            # Synthetic test borrower
            user_msg = borrower_context.test_borrower_response_fn(turn, response, state)
        else:
            # In production, would get real user input
            user_msg = input(f"Borrower (turn {turn}): ").strip()
        
        if not user_msg:
            break
        
        messages.append({"role": "user", "content": user_msg})
        user_msg_lower = user_msg.lower()
        
        # Parse borrower responses
        if "stop" in user_msg_lower or "don't call" in user_msg_lower:
            borrower_context.mark_stop_contact()
            logger.info("Borrower requested no further contact")
            break
        
        # Identity verification
        if not borrower_context.identity_verified:
            state["identity_attempts"] += 1
            # Check if borrower provided partial identifiers
            if debt_data["balance_partial"].replace(".", "").split("7391")[-1] in user_msg and debt_data["zip_partial"] in user_msg:
                borrower_context.mark_identity_verified()
                state["debt_acknowledged"] = True
                logger.info("Identity verified")
            elif state["identity_attempts"] >= 2:
                logger.info("Identity verification failed after 2 attempts")
                break
        
        # Gather employment
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
        
        # Detect hardship
        hardship_keywords = ["lost job", "medical", "emergency", "no income", "can't pay", "homeless", "hospital"]
        if any(kw in user_msg_lower for kw in hardship_keywords):
            borrower_context.mark_hardship()
        
        # Note payment capability
        if "can pay" in user_msg_lower or "can afford" in user_msg_lower:
            borrower_context.ability_to_pay = "can_pay"
        elif "partial" in user_msg_lower:
            borrower_context.ability_to_pay = "partial"
        elif "cannot" in user_msg_lower or "can't" in user_msg_lower:
            borrower_context.ability_to_pay = "cannot_pay"
    
    # Update borrower context with assessment results
    borrower_context.balance = debt_data["balance"]
    borrower_context.agent1_messages = messages
    
    # Determine final outcome
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
"""
Agent 3: Final Notice (Chat)
Role: Consequence-driven, deadline-focused. States what happens next: credit reporting, legal referral, asset recovery.
"""

import json
import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from utils.llm import call_llm
from utils.config import LLM_MODELS
from compliance.checker import check_message_compliance
from summarizer.token_counter import get_token_counter, count_tokens

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SYSTEM_PROMPT_v1 = """You are the final notice agent for a debt collection company. Your role is to make one last attempt: state facts, present one final offer, set a hard deadline, and communicate consequences clearly. You are not sympathetic. You are clear.

CONTEXT FROM PRIOR INTERACTIONS:
{handoff_summary}

INSTRUCTIONS:
1. RECAP: Reference what happened in prior stages. "We contacted you via chat and phone regarding your {balance} debt. Here's the status."
2. PRIOR OFFERS: Summarize what was offered. "We presented {offer1} and {offer2}."
3. FINAL OFFER: Present one last settlement option with a hard deadline. "We can settle for {amount} if paid by {deadline}."
4. CONSEQUENCES: State clearly what happens if no payment:
   - "Your account will be reported to all credit bureaus"
   - "Your debt may be referred for legal proceedings"
   - "Collection actions may include wage garnishment or asset recovery" (only if documented)
5. CALL TO ACTION: "Confirm your decision by {date}. Here's how to reach us."
6. TONE: Professional, factual, final. No negotiation. No new pressure tactics.

COMPLIANCE:
- Do NOT threaten unless it's documented next step in workflow
- Do NOT pressure someone in crisis; refer to hardship program
- Maintain professional language
- Reference what was actually discussed, don't fabricate
- Set realistic deadlines (7-14 days)

This is the last communication. Make it clear and unambiguous.
"""


def run_final_notice_agent(borrower_context) -> Dict:
    """
    Run final notice agent (last collection attempt).
    
    Args:
        borrower_context: BorrowerContext object with complete borrower history
        
    Returns:
        {
            "result": {...final notice results...},
            "messages": [...conversation messages...],
            "outcome": str
        }
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
    
    # Prepare system prompt with context
    system_prompt = SYSTEM_PROMPT_v1.format(
        handoff_summary=json.dumps(handoff_summary)[:500],
        balance=f"${balance:.2f}"
    )
    
    MAX_TURNS = 8
    
    # Calculate deadline (7 days from now)
    deadline = (datetime.utcnow() + timedelta(days=7)).strftime("%B %d, %Y")
    
    # Final offer (typically 20% discount, 7-day deadline)
    final_settlement_amount = balance * 0.80
    final_offer = {
        "type": "final_lump_sum",
        "amount": final_settlement_amount,
        "deadline": deadline,
        "discount_pct": 0.20,
    }
    
    # Opening message  
    opening = f"Dear {borrower_name},\n\n" + \
f"This is a final notice regarding your {balance:.2f} outstanding debt. We have made multiple settlement offers, most recently via phone call. This is your final opportunity to resolve this before we proceed with additional collection actions.\n\n" + \
f"FINAL SETTLEMENT OFFER:\n" + \
f"We can settle your debt for {final_settlement_amount:.2f} ({int(final_offer['discount_pct'] * 100)}% discount off the original amount) if received by {deadline}.\n\n" + \
f"If we do not receive payment or commitment by {deadline}, we will:\n" + \
f"1. Report this debt to all credit reporting agencies\n" + \
f"2. Refer your account for legal collection proceedings\n" + \
f"3. Explore wage garnishment and asset recovery options\n\n" + \
f"Your next step: Contact us with your response by {deadline}. Call [Company] at [Phone] or reply to this message.\n\n" + \
f"This is your final opportunity."
    
    messages.append({"role": "assistant", "content": opening})
    final_message = opening
    
    # Wait brief moment for borrower response
    while turns < MAX_TURNS:
        turns += 1
        
        # Get borrower response
        if hasattr(borrower_context, 'test_borrower_response_fn'):
            user_msg = borrower_context.test_borrower_response_fn(turns, opening, {"offers": offers_made})
        else:
            user_msg = input(f"Borrower response to final notice (turn {turns}, or press Enter to skip): ").strip()
        
        if not user_msg:
            # No response; outcome is unresolved
            break
        
        messages.append({"role": "user", "content": user_msg})
        user_msg_lower = user_msg.lower()
        
        # Parse response
        if any(word in user_msg_lower for word in ["yes", "agree", "pay", "settle", "deal"]):
            resolved = True
            response = f"Thank you for confirming. We'll send you payment instructions. Please send payment by {deadline}."
            messages.append({"role": "assistant", "content": response})
            final_message = response
            logger.info("Final notice: Borrower agreed to settlement")
            break
        
        elif any(word in user_msg_lower for word in ["hardship", "emergency", "crisis", "medical", "help"]):
            # Offer hardship program one more time
            response = f"I understand you're in a difficult situation. Our hardship program has options that might help. Would you like me to connect you with that team?"
            messages.append({"role": "assistant", "content": response})
            final_message = response
            cost_usd += 0.0008
        
        elif "no" in user_msg_lower or "refuse" in user_msg_lower or "can't" in user_msg_lower:
            # Acknowledge but reiterate deadline
            response = f"I understand. The offer stands until {deadline}. If you change your mind or can negotiate, please contact us immediately."
            messages.append({"role": "assistant", "content": response})
            final_message = response
            break
        
        else:
            # Generate contextual response
            response = call_llm(
                system=system_prompt,
                messages=messages,
                model=LLM_MODELS["agent"],
                max_tokens=200
            )
            cost_usd += 0.0008
            
            # Compliance check
            context = {
                "turn_number": turns,
                "borrower_last_message": user_msg,
            }
            is_compliant, violations = check_message_compliance(response, context)
            for violation in violations:
                borrower_context.add_compliance_violation(
                    violation["type"], violation["severity"], violation["reason"]
                )
            
            if not is_compliant:
                logger.warning(f"Agent 3 compliance violation(s): {violations}")
            
            messages.append({"role": "assistant", "content": response})
            final_message = response
    
    # Update borrower context
    borrower_context.agent3_messages = messages
    
    # Determine outcome
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
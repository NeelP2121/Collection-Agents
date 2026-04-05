from agents.agent1_assessment import run_assessment_agent
from agents.agent2_resolution import run_resolution_agent
from agents.agent3_final_notice import run_final_notice_agent
from summarizer.summarizer import Summarizer
from models.borrower_state import BorrowerContext

summarizer = Summarizer()

async def run_assessment_agent(borrower_context: BorrowerContext):
    """Run Agent 1: Chat-based identity verification and assessment"""
    result = run_agent1(borrower_context)
    return result

async def summarize_agent1_to_agent2(conversation_history: list, borrower_context: BorrowerContext):
    """Summarize Agent 1 conversation for Agent 2 handoff (max 500 tokens)"""
    summary = summarizer.summarize_agent1_to_agent2(conversation_history, borrower_context.to_dict())
    return summary

async def run_voice_resolution_agent(handoff_summary: dict, borrower_context: BorrowerContext):
    """Run Agent 2: Triggers remote VAPI Voice integration loop"""
    from voice.voice_handler import VapiHandler
    
    # Update borrower context with handoff information inline for tracking
    borrower_context.update_from_handoff(handoff_summary)
    
    handler = VapiHandler()
    call_id = handler.initiate_call(borrower_context.phone, handoff_summary, borrower_context.workflow_id)
    
    return {"call_id": call_id, "status": "initiated"}

async def summarize_agent2_to_agent3(agent1_handoff: dict, agent2_conversation: list, borrower_context: BorrowerContext):
    """Summarize combined Agent 1 + Agent 2 data for Agent 3 handoff (max 500 tokens)"""
    combined_data = {
        "agent1_handoff": agent1_handoff,
        "agent2_conversation": agent2_conversation
    }
    summary = summarizer.summarize_agent2_to_agent3(combined_data, borrower_context.to_dict())
    return summary

async def run_final_notice_agent(handoff_summary: dict, borrower_context: BorrowerContext):
    """Run Agent 3: Final consequence-driven collection attempt"""
    # Update borrower context with final handoff information
    borrower_context.update_from_handoff(handoff_summary)
    result = run_agent3(borrower_context)
    return result
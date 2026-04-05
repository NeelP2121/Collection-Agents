from models.borrower_state import BorrowerContext
from temporalio import activity
import json
import logging
from typing import Dict, Any

from agents.agent1_assessment import AssessmentAgent
from agents.agent2_resolution import ResolutionAgent
from agents.agent3_final_notice import FinalNoticeAgent
from utils.llm import call_llm
from utils.config import LLM_MODELS

logger = logging.getLogger(__name__)

@activity.defn
async def run_assessment_agent(borrower_context: BorrowerContext) -> Dict:
    agent = AssessmentAgent()
    return agent.run_assessment_agent(borrower_context)

@activity.defn
async def generate_handoff_ledger(conversation: list) -> dict:
    """Condenses raw transcript into JSON strictly under 500 tokens."""
    prompt = "Summarize this debt collection chat logically. Output strict JSON with key 'summary'."
    
    # We enforce token checking natively here as well or just generate <500 natively.
    # LLM itself returns it.
    response = call_llm(
        system=prompt,
        messages=[{"role": "user", "content": json.dumps(conversation)}],
        model=LLM_MODELS["agent"],
        max_tokens=450  # buffer to absolutely guarantee <500
    )
    
    try:
        # Heuristic extraction of JSON if wrapped in markdown
        if "```json" in response:
            clean = response.split("```json")[1].split("```")[0].strip()
        elif "```" in response:
            clean = response.split("```")[1].split("```")[0].strip()
        else:
            clean = response.strip()
        return json.loads(clean)
    except Exception:
        # Fallback empty structural JSON if parsing fails perfectly
        return {"summary": response[:1000]}

@activity.defn
async def run_voice_resolution_agent(handoff_summary: dict, borrower_context: BorrowerContext) -> Dict:
    # Just initiate webhook trigger using VAPI
    from voice.voice_handler import VapiHandler
    borrower_context.update_from_handoff(handoff_summary)
    
    handler = VapiHandler()
    call_id = handler.initiate_call(borrower_context.phone, handoff_summary, borrower_context.workflow_id)
    return {"call_id": call_id, "status": "initiated"}

@activity.defn
async def run_final_notice_agent(handoff_summary: dict, borrower_context: BorrowerContext) -> Dict:
    # Agent 3 text channel agent
    agent = FinalNoticeAgent()
    # Update borrower context with final handoff information
    borrower_context.update_from_handoff(handoff_summary)
    return agent.run_final_notice_agent(borrower_context)
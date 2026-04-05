import logging
from typing import Dict, List
from utils.llm import call_llm
from utils.config import LLM_MODELS
from agents.agent1_assessment import AssessmentAgent
from models.borrower_state import BorrowerContext

logger = logging.getLogger(__name__)

class SyntheticBorrower:
    def __init__(self, persona: str):
        self.persona = persona
        self.history = []
        
    def generate_response(self, turn: int, agent_message: str, state: dict) -> str:
        self.history.append({"role": "user", "content": agent_message}) # Agent is user to us
        
        system = f"You are a synthetic borrower acting out this persona: {self.persona}. Respond to the debt collector naturally. Be brief."
        
        response = call_llm(
            system=system,
            messages=self.history,
            model=LLM_MODELS["evaluation"],
            max_tokens=150
        )
        
        self.history.append({"role": "assistant", "content": response})
        return response

def run_simulation(persona: str, max_turns: int = 10) -> Dict:
    borrower = SyntheticBorrower(persona)
    agent = AssessmentAgent()
    context = BorrowerContext(name="John Doe", phone="555-0199", workflow_id="sim_1")
    
    # We dynamically map the hook Agent 1 uses to hit the LLM internally
    context.test_borrower_response_fn = borrower.generate_response
    
    result = agent.run_assessment_agent(context)
    return {
        "transcript": context.agent1_messages,
        "outcome": result["outcome"],
        "context": context
    }

def run_parallel_simulations() -> List[Dict]:
    personas = [
        "Cooperative but completely broke, recently disabled.",
        "Angry, defensive, demands proof of debt and threatens to sue.",
        "Confused elderly person who doesn't recognize the debt.",
        "Slippery negotiator who tries to lowball immediately.",
        "Panicked individual experiencing a medical emergency right now."
    ]
    
    results = []
    for p in personas:
        logger.info(f"Running simulation for persona: {p[:30]}...")
        res = run_simulation(p)
        results.append(res)
        
    return results

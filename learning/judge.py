import logging
import re
from typing import Dict, List
from utils.llm import call_llm
from utils.config import LLM_MODELS

logger = logging.getLogger(__name__)

FORBIDDEN_PHRASES = [
    r"lawsuit", r"police", r"arrest", r"prison", r"jail", r"garnishment"
]

def score_transcript(transcript: List[Dict]) -> Dict:
    # 1. Offline hardcoded checks
    transcript_text = "\n".join([f"{m['role']}: {m['content']}" for m in transcript])
    
    compliance_score = 1.0
    for phrase in FORBIDDEN_PHRASES:
        if re.search(phrase, transcript_text, re.IGNORECASE):
            compliance_score = 0.0
            logger.warning(f"Failed offline hard rule: Used forbidden phrase '{phrase}'")
            break
            
    # 2. LLM Goal Achievement score
    system = """You are an expert debt collection judge. Evaluate the Agent's performance (role: assistant).
Score Goal Achievement strictly from 0.0 to 1.0. Did they verify identity? Assess hardship? Be professional?
Return PURE JSON only: {"goal_score": 0.8, "reasoning": "..."}"""

    response = call_llm(
        system=system,
        messages=[{"role": "user", "content": transcript_text}],
        model=LLM_MODELS["evaluation"],
        max_tokens=200
    )
    
    try:
        import json
        if "```json" in response:
            clean = response.split("```json")[1].split("```")[0].strip()
        elif "```" in response:
            clean = response.split("```")[1].split("```")[0].strip()
        else:
            clean = response.strip()
        data = json.loads(clean)
        goal_score = float(data.get("goal_score", 0.0))
        reasoning = data.get("reasoning", "")
    except Exception as e:
        goal_score = 0.0
        reasoning = f"Failed to parse judge output: {e}"

    # 3. Token Efficiency
    turns = sum(1 for m in transcript if m['role'] == 'assistant')
    eff_score = max(0.0, 1.0 - (turns / 15.0))
    
    composite = (compliance_score * 0.5) + (goal_score * 0.4) + (eff_score * 0.1)
    
    return {
        "composite_score": composite,
        "compliance_score": compliance_score,
        "goal_score": goal_score,
        "efficiency_score": eff_score,
        "reasoning": reasoning
    }

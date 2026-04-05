import logging
import json
from pathlib import Path
from typing import List, Dict
from utils.llm import call_llm
from utils.config import LLM_MODELS

logger = logging.getLogger(__name__)

def evaluate_false_positives(passed_transcripts: List[List[Dict]]) -> str:
    system = """You are the Gödel Meta-Evaluator mapping the 'Darwin-Gödel Debt Agent'.
Review these highly-scored transcripts and see if the Agent found a 'loophole' or gamed our simple rubric.
Did they technically pass but explicitly violate the spirit of professional debt collection using evasive logic blocks?
If YES, output exactly ONE new sentence rule describing the evasion (e.g. 'DO NOT MENTION LEGAL THREATS').
If NO, output exactly 'PASS'."""

    transcript_texts = "\n---\n".join(["\n".join([f"{m['role']}: {m['content']}" for m in t]) for t in passed_transcripts])
    
    response = call_llm(
        system=system,
        messages=[{"role": "user", "content": transcript_texts[:10000]}],  # truncation safety
        model=LLM_MODELS["godel"],
        max_tokens=200
    )
    
    return response.strip()

def rewrite_judge_rubric(new_rule: str):
    logger.warning(f"Gödel Monitor caught an evasion logic! Appending new strict rule: {new_rule}")
    
    judge_path = Path(__file__).parent / "judge.py"
    with open(judge_path, 'r') as f:
        content = f.read()
        
    target = 'Score Goal Achievement strictly from 0.0 to 1.0. Did they verify identity? Assess hardship? Be professional?'
    replacement = target + f'\nCRITICAL BLIND SPOT RULE: {new_rule}'
    
    new_content = content.replace(target, replacement)
    
    with open(judge_path, 'w') as f:
        f.write(new_content)
        
    logger.info("judge.py has been natively modified. The DNA of the evaluator has evolved.")

def run_godel_monitor(sim_results: List[Dict]):
    passed = [r["transcript"] for r in sim_results if r.get("composite_score", 1.0) >= 0.7]
    if not passed:
        logger.info("No passing transcripts to analyze.")
        return
        
    logger.info("Gödel Monitor analyzing passing traces for metric gaming...")
    result = evaluate_false_positives(passed)
    
    if result != "PASS" and len(result) > 10:
        rewrite_judge_rubric(result)
    else:
        logger.info("Meta-Evaluator found no blind spots.")

import logging
import yaml
from pathlib import Path
from utils.llm import call_llm
from utils.config import LLM_MODELS

logger = logging.getLogger(__name__)

def run_surgical_improver(agent_id: str, failed_transcripts: list, current_prompt: str) -> str:
    system = """You are a prompt engineer optimizer (Karpathy-style surgical improver).
You will receive a current prompt and a set of failed transcripts and judge reasons.
Output ONLY the new YAML prompt string for this agent (do not output the `version` or `tokens` keys, ONLY the string belonging to the `prompt` key.
Make exactly ONE surgical change to fix the biggest failure reason. Do not rewrite everything."""

    content = f"CURRENT PROMPT:\n{current_prompt}\n\nFAILURES:\n" + str(failed_transcripts)

    response = call_llm(
        system=system,
        messages=[{"role": "user", "content": content}],
        model=LLM_MODELS["improver"],
        max_tokens=1000
    )
    
    return response.strip()

def apply_improvement(agent_id: str, new_prompt: str, win_rate: float):
    if win_rate <= 0.05:
        logger.info("Improver yield too low (<5% win rate improvement vs champion). Rejecting.")
        return
        
    registry_path = Path(__file__).parent.parent / "registry" / "active_prompts.yaml"
    with open(registry_path, 'r') as f:
        registry = yaml.safe_load(f)
        
    history_dir = Path(__file__).parent.parent / "registry" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    with open(history_dir / f"{agent_id}_v{registry[agent_id].get('version', 1)}.txt", "w") as f:
        f.write(registry[agent_id]["prompt"])
        
    registry[agent_id]["prompt"] = new_prompt
    registry[agent_id]["version"] = registry[agent_id].get("version", 1) + 1
    
    with open(registry_path, 'w') as f:
        yaml.dump(registry, f, default_flow_style=False)
        
    logger.info(f"Surgical Improver replaced champion. Version bumped to {registry[agent_id]['version']}.")

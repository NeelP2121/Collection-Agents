import yaml
import logging
import tiktoken
from pathlib import Path

logger = logging.getLogger(__name__)

class BaseAgent:
    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        registry_path = Path(__file__).parent.parent / "registry" / "active_prompts.yaml"
        
        try:
            with open(registry_path, 'r') as f:
                registry = yaml.safe_load(f)
        except Exception as e:
            logger.error(f"Failed to load prompt registry: {e}")
            raise
            
        if agent_id not in registry:
            raise ValueError(f"Agent '{agent_id}' not found in active_prompts.yaml")
            
        self.version = registry[agent_id].get("version", 1)
        self.system_prompt = registry[agent_id]["prompt"]
        self.allocated_tokens = registry[agent_id].get("tokens", 1500)
        self.encoder = tiktoken.encoding_for_model("gpt-4o-mini")

    def enforce_token_guard(self, ledger_str: str, max_total_tokens: int = 2000) -> str:
        """
        Guards against exceeding maximum context window limits.
        If prompt + ledger > 2000, explicitly truncates the ledger.
        """
        if not ledger_str:
            return ""
            
        prompt_tokens = len(self.encoder.encode(self.system_prompt))
        ledger_tokens = self.encoder.encode(ledger_str)
        
        total = prompt_tokens + len(ledger_tokens)
        if total > max_total_tokens:
            logger.warning(f"[{self.agent_id}] Context limit exceeded ({total} > {max_total_tokens}). Truncating ledger.")
            allowed_ledger_len = max_total_tokens - prompt_tokens
            if allowed_ledger_len <= 0:
                logger.error(f"[{self.agent_id}] System prompt is too large! Over {max_total_tokens} tokens.")
                return ""
            # Keep the most recent data by slicing from the end
            truncated_tokens = ledger_tokens[-allowed_ledger_len:]
            return self.encoder.decode(truncated_tokens)
        
        return ledger_str

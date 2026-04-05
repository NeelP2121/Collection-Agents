import json
import logging
import os
import threading
from typing import Dict, Any

logger = logging.getLogger(__name__)

class BudgetExceededError(Exception):
    pass

class CostTracker:
    """
    Singleton CostTracker to enforce the global $20 limit for the Learning Loop.
    Persists data to a local JSON file to span across multiple executions.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, limit_usd: float = 19.5, ledger_path: str = "llm_spend_ledger.json"):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(CostTracker, cls).__new__(cls)
                cls._instance._init(limit_usd, ledger_path)
            return cls._instance

    def _init(self, limit_usd: float, ledger_path: str):
        from utils.config import MODEL_PRICING
        self.limit_usd = limit_usd
        self.ledger_path = ledger_path
        self.pricing = MODEL_PRICING
        self.data = self._load()

    def _load(self) -> Dict[str, Any]:
        """Load spend dictionary from disk."""
        if os.path.exists(self.ledger_path):
            try:
                with open(self.ledger_path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load ledger: {e}")
        return {
            "total_spend_usd": 0.0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "breakdown_by_model": {},
            "breakdown_by_category": {}
        }

    def _save(self):
        """Save spend dictionary to disk."""
        try:
            with open(self.ledger_path, 'w') as f:
                json.dump(self.data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save ledger: {e}")

    def calculate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Calculate cost in USD."""
        rates = self.pricing.get(model, {"input": 0.0, "output": 0.0})
        input_cost = ((input_tokens or 0) / 1_000_000.0) * rates["input"]
        output_cost = ((output_tokens or 0) / 1_000_000.0) * rates["output"]
        return input_cost + output_cost

    def check_budget(self):
        """Raise error if we are above the pre-configured budget threshold."""
        with self._lock:
            if self.data["total_spend_usd"] >= self.limit_usd:
                raise BudgetExceededError(
                    f"LLM Budget exceeded: ${self.data['total_spend_usd']:.4f} >= limit ${self.limit_usd:.2f}"
                )

    def record_call_cost(self, model: str, input_tokens: int, output_tokens: int, category: str = "general") -> float:
        """Record the token usage and cost for an API call."""
        input_tokens = input_tokens or 0
        output_tokens = output_tokens or 0
        cost = self.calculate_cost(model, input_tokens, output_tokens)
        
        with self._lock:
            self.data["total_spend_usd"] += cost
            self.data["total_input_tokens"] += input_tokens
            self.data["total_output_tokens"] += output_tokens

            # By Model
            if model not in self.data["breakdown_by_model"]:
                self.data["breakdown_by_model"][model] = {"tokens": 0, "cost": 0.0}
            self.data["breakdown_by_model"][model]["tokens"] += (input_tokens + output_tokens)
            self.data["breakdown_by_model"][model]["cost"] += cost

            # By Category
            if category not in self.data["breakdown_by_category"]:
                self.data["breakdown_by_category"][category] = {"tokens": 0, "cost": 0.0}
            self.data["breakdown_by_category"][category]["tokens"] += (input_tokens + output_tokens)
            self.data["breakdown_by_category"][category]["cost"] += cost

            self._save()
            return cost

    def get_spend_report(self) -> Dict[str, Any]:
        """Return the complete dictionary mapping of the costs."""
        with self._lock:
            return dict(self.data)

def get_cost_tracker() -> CostTracker:
    return CostTracker()

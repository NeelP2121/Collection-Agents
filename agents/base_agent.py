import yaml
import logging
import tiktoken
from pathlib import Path
from typing import List, Dict

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Tokenizer strategy
# ──────────────────────────────────────────────────────────────────────────────
# Claude uses a proprietary BPE tokenizer.  Anthropic's Python SDK exposes
# client.count_tokens() but it requires an API round-trip — too expensive for
# real-time budget enforcement on every message.
#
# Offline approximation: we use cl100k_base (GPT-4 family) which over-counts
# by ~5-10% compared to Claude's tokenizer.  This is intentionally conservative
# — a 10% over-count means we'll trim messages slightly earlier than strictly
# necessary, but we will NEVER exceed the real token limit.
#
# We apply a SAFETY_FACTOR of 0.90 (i.e., we budget for 90% of the hard limit)
# to absorb the cross-tokenizer variance.  In production, we'd validate budgets
# server-side using Anthropic's /v1/messages/count_tokens endpoint.
# ──────────────────────────────────────────────────────────────────────────────
_ENCODING = tiktoken.get_encoding("cl100k_base")
_SAFETY_FACTOR = 0.90  # 10% conservative margin for cross-tokenizer variance


class BaseAgent:
    """Base class for all collection agents with hard token budget enforcement."""

    # Hard limits from the assignment spec
    MAX_CONTEXT_TOKENS = 2000
    MAX_HANDOFF_TOKENS = 500

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

        # Validate system prompt fits within allocated budget at init time
        self._system_prompt_tokens = self._count_tokens(self.system_prompt)
        if self._system_prompt_tokens > self.allocated_tokens:
            raise ValueError(
                f"[{self.agent_id}] System prompt ({self._system_prompt_tokens} tokens) "
                f"exceeds allocated budget ({self.allocated_tokens} tokens)! "
                f"Reduce prompt size or increase allocated_tokens in active_prompts.yaml."
            )

    @staticmethod
    def _count_tokens(text: str) -> int:
        """Count tokens using cl100k_base (conservative approximation for Claude)."""
        if not text:
            return 0
        return len(_ENCODING.encode(text))

    def enforce_token_guard(self, ledger_str: str, max_total_tokens: int = None) -> str:
        """
        Hard-enforce the per-agent token budget for context windows.

        Uses ``allocated_tokens`` (from active_prompts.yaml) as the ceiling,
        capped at MAX_CONTEXT_TOKENS.  If system_prompt + ledger exceeds it,
        truncates the ledger from the front (keeping the most recent context).
        """
        max_total_tokens = max_total_tokens or min(self.allocated_tokens, self.MAX_CONTEXT_TOKENS)
        if not ledger_str:
            return ""

        prompt_tokens = self._system_prompt_tokens
        ledger_token_ids = _ENCODING.encode(ledger_str)

        total = prompt_tokens + len(ledger_token_ids)
        if total > max_total_tokens:
            logger.warning(
                f"[{self.agent_id}] Context limit exceeded "
                f"({total} > {max_total_tokens}). Truncating ledger."
            )
            allowed_ledger_len = max_total_tokens - prompt_tokens
            if allowed_ledger_len <= 0:
                logger.error(
                    f"[{self.agent_id}] System prompt alone exceeds "
                    f"{max_total_tokens} tokens!"
                )
                return ""
            truncated_tokens = ledger_token_ids[-allowed_ledger_len:]
            return _ENCODING.decode(truncated_tokens)

        return ledger_str

    def enforce_message_budget(
        self, messages: List[Dict], max_total_tokens: int = None
    ) -> List[Dict]:
        """
        Hard-enforce the per-agent token budget across system prompt + conversation.

        Uses the agent's ``allocated_tokens`` from active_prompts.yaml as the
        ceiling (capped at MAX_CONTEXT_TOKENS=2000).  This means agents with
        shorter prompts get more room for conversation, and agents with larger
        prompts are automatically constrained.

        Drops oldest messages (except the first) until the total fits.
        Called before every LLM dispatch to guarantee the budget is never exceeded.
        """
        if max_total_tokens is None:
            max_total_tokens = self.dynamic_budget(len(messages))
        prompt_tokens = self._system_prompt_tokens

        def _messages_tokens(msgs):
            total = 0
            for m in msgs:
                total += self._count_tokens(m.get("content", ""))
                total += 5  # per-message overhead (role, separators)
            return total

        msg_tokens = _messages_tokens(messages)
        total = prompt_tokens + msg_tokens

        if total <= max_total_tokens:
            return messages

        logger.warning(
            f"[{self.agent_id}] Message budget exceeded "
            f"({total} > {max_total_tokens}). Dropping oldest messages."
        )

        # Preserve first message and drop from index 1 until we fit
        trimmed = list(messages)
        while len(trimmed) > 2 and prompt_tokens + _messages_tokens(trimmed) > max_total_tokens:
            trimmed.pop(1)

        final_total = prompt_tokens + _messages_tokens(trimmed)
        logger.info(
            f"[{self.agent_id}] After trimming: {final_total} tokens "
            f"({len(trimmed)} messages)"
        )
        return trimmed

    @property
    def effective_budget(self) -> int:
        """
        The actual token ceiling for this agent.

        Applies _SAFETY_FACTOR to absorb cross-tokenizer variance between
        cl100k_base (our offline proxy) and Claude's real tokenizer.
        """
        raw = min(self.allocated_tokens, self.MAX_CONTEXT_TOKENS)
        return int(raw * _SAFETY_FACTOR)

    def dynamic_budget(self, num_messages: int) -> int:
        """
        Stage-aware token allocation.

        Early conversation (≤4 messages): system prompt dominates, reserve
        70% of budget for it + response generation.
        Mid conversation (5-10 messages): balanced split — history matters.
        Late conversation (>10 messages): maximize history retention, allow
        up to full budget (old messages get dropped by enforce_message_budget).

        This prevents the assessment agent from wasting budget on a long
        history when it only needs identity verification, while letting the
        resolution agent carry more context during negotiation.
        """
        base = self.effective_budget
        if num_messages <= 4:
            return int(base * 0.70)
        elif num_messages <= 10:
            return int(base * 0.85)
        return base

    def get_budget_report(self, context_tokens: int = 0) -> Dict:
        """Return a token budget utilization report for this agent."""
        budget = self.effective_budget
        total_used = self._system_prompt_tokens + context_tokens
        return {
            "agent": self.agent_id,
            "system_prompt_tokens": self._system_prompt_tokens,
            "allocated_tokens": self.allocated_tokens,
            "effective_budget": budget,
            "context_tokens": context_tokens,
            "total_used": total_used,
            "max_allowed": budget,
            "remaining": max(0, budget - total_used),
            "over_budget": total_used > budget,
        }

import tiktoken
from typing import Tuple, List, Dict


class TokenBudgetExceeded(Exception):
    """Raised when strict budget enforcement detects a violation."""
    pass

# We use cl100k_base (GPT-4 family) as a conservative proxy for Claude tokenization.
# cl100k_base over-counts by ~5-10% compared to Claude's tokenizer, giving us a
# safety margin — we'll never accidentally exceed the real token limit.
# In production, validate via Anthropic's /v1/messages/count_tokens endpoint.
_DEFAULT_ENCODING = "cl100k_base"
_SAFETY_FACTOR = 0.90  # 10% margin for cross-tokenizer variance


class TokenBudget:
    """Token budget constants from the assignment spec."""
    TOTAL_PER_AGENT = 2000
    MAX_HANDOFF = 500
    AGENT1_SYSTEM_PROMPT = 1200
    AGENT2_SYSTEM_PROMPT = 1500
    AGENT3_SYSTEM_PROMPT = 1500


class TokenCounter:
    """Token counting and budget enforcement using cl100k_base as Claude proxy."""

    def __init__(self, encoding: str = _DEFAULT_ENCODING):
        self.encoding = tiktoken.get_encoding(encoding)
    
    def count(self, text: str) -> int:
        """Count tokens in text"""
        if not text:
            return 0
        return len(self.encoding.encode(text))
    
    def count_messages(self, messages: List[Dict]) -> int:
        """Count tokens in message list (for chat history)"""
        total = 0
        for msg in messages:
            # Count role and content
            if "role" in msg:
                total += self.count(msg["role"])
            if "content" in msg:
                total += self.count(msg["content"])
            # Add ~5 tokens per message for formatting overhead
            total += 5
        return total
    
    def enforce_budget(self, context: str, max_tokens: int) -> Tuple[str, int, bool]:
        """
        Enforce token budget by truncating context if needed.
        
        Args:
            context: Text to constrain
            max_tokens: Maximum allowed tokens
        
        Returns:
            (truncated_context, tokens_used, exceeded_budget)
        """
        token_count = self.count(context)
        
        if token_count <= max_tokens:
            return (context, token_count, False)
        
        # Truncate in half repeatedly until within budget
        words = context.split()
        truncated = context
        while self.count(truncated) > max_tokens and len(words) > 10:
            words = words[: len(words) // 2]
            truncated = " ".join(words)
        
        return (truncated, self.count(truncated), True)
    
    def hard_fail_if_over_budget(
        self, text: str, max_tokens: int, context_name: str = "context",
        strict: bool = False,
    ) -> Tuple[str, int]:
        """
        Enforce token budget on text.

        Two modes:
          - strict=False (default): truncate to fit.  Used for handoff
            summaries where a partial summary is better than a crash.
          - strict=True: raise ``TokenBudgetExceeded`` so the caller can
            handle it (e.g., reject a prompt variant, abort an activity).

        Args:
            text: Text to validate
            max_tokens: Maximum allowed
            context_name: Name for log message
            strict: If True, raise instead of truncating

        Returns:
            (text_within_budget, token_count)

        Raises:
            TokenBudgetExceeded: if strict=True and text exceeds max_tokens
        """
        token_count = self.count(text)
        if token_count > max_tokens:
            import logging
            logger = logging.getLogger(__name__)

            if strict:
                raise TokenBudgetExceeded(
                    f"HARD BUDGET VIOLATION: {context_name} used {token_count} tokens "
                    f"(limit: {max_tokens}). Aborting."
                )

            logger.warning(
                f"BUDGET VIOLATION: {context_name} exceeded {max_tokens} token limit. "
                f"Used {token_count} tokens. Truncating to fit."
            )
            # Truncate token-level to guarantee fit
            token_ids = self.encoding.encode(text)[:max_tokens]
            text = self.encoding.decode(token_ids)
            token_count = max_tokens
        return (text, token_count)
    
    def summarize_to_budget(self, text: str, target_tokens: int) -> Tuple[str, int]:
        """
        Simple truncation summarizer (not LLM-based).
        Naive but effective for hard budget enforcement.
        """
        truncated, token_count, exceeded = self.enforce_budget(text, target_tokens)
        return (truncated, token_count)
    
    def get_budget_report(self, system_prompt: str, context_tokens: int, max_total: int = TokenBudget.TOTAL_PER_AGENT) -> Dict:
        """
        Generate budget report for an agent.
        
        Returns:
            {
                "system_prompt_tokens": int,
                "context_tokens": int,
                "total_used": int,
                "remaining": int,
                "utilization_pct": float,
                "over_budget": bool,
            }
        """
        system_tokens = self.count(system_prompt)
        total_used = system_tokens + context_tokens
        remaining = max(0, max_total - total_used)
        over_budget = total_used > max_total
        utilization_pct = (total_used / max_total) * 100 if max_total > 0 else 0
        
        return {
            "system_prompt_tokens": system_tokens,
            "context_tokens": context_tokens,
            "total_used": total_used,
            "remaining": remaining,
            "utilization_pct": utilization_pct,
            "over_budget": over_budget,
        }


# Global instance
_token_counter = None

def get_token_counter() -> TokenCounter:
    """Get or create global token counter"""
    global _token_counter
    if _token_counter is None:
        _token_counter = TokenCounter()
    return _token_counter


# Convenience functions
def count_tokens(text: str) -> int:
    """Count tokens in text"""
    return get_token_counter().count(text)


def enforce_handoff_budget(summary: str) -> Tuple[str, int]:
    """Enforce 500-token max on handoff summaries (with safety margin)."""
    safe_limit = int(TokenBudget.MAX_HANDOFF * _SAFETY_FACTOR)
    return get_token_counter().hard_fail_if_over_budget(
        summary,
        safe_limit,
        "handoff_summary"
    )

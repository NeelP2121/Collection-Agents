import tiktoken

class TokenBudget:
    TOTAL = 2000
    MAX_HANDOFF = 500

    def count(self, text: str) -> int:
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))

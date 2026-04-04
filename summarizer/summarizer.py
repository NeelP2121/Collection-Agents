import json
from utils.llm import call_llm
from summarizer.token_counter import TokenBudget

class Summarizer:
    def __init__(self):
        self.budget = TokenBudget()

    def summarize(self, conversation, stage):
        response = call_llm(
            system="Compress to JSON under 400 tokens",
            messages=[{"role": "user", "content": str(conversation)}],
            model="claude-3-5-haiku-20241022"
        )

        try:
            summary = json.loads(response)
        except:
            summary = {"raw": response}

        return summary

from utils.llm import call_llm

SYSTEM_PROMPT = """You are DebtBot..."""

def run_agent1(borrower):
    messages = []

    response = call_llm(
        system=SYSTEM_PROMPT,
        messages=messages,
        model="claude-3-5-haiku-20241022"
    )

    return {
        "conversation": messages,
        "outcome": "completed"
    }

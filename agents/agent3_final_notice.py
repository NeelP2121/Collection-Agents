from utils.llm import call_llm

SYSTEM_PROMPT = "You are a final collections agent. Push for resolution."

def run_agent3(handoff: dict):
    response = call_llm(
        SYSTEM_PROMPT,
        [{"role": "user", "content": str(handoff)}]
    )

    return {
        "message": response,
        "outcome": "unresolved"
    }

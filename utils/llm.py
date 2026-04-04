from anthropic import Anthropic
from utils.config import ANTHROPIC_API_KEY

client = Anthropic(api_key=ANTHROPIC_API_KEY)

def call_llm(system: str, messages: list, model: str, max_tokens=500):
    response = client.messages.create(
        model=model,
        system=system,
        messages=messages,
        max_tokens=max_tokens
    )
    return response.content[0].text

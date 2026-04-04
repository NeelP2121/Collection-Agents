import requests
from utils.config import VAPI_API_KEY, VAPI_PHONE_ID

class VapiHandler:
    def initiate_call(self, phone, ctx):
        payload = {
            "assistant": {
                "model": {
                    "provider": "anthropic",
                    "model": "claude-3-5-haiku-20241022",
                    "systemPrompt": "Voice agent system prompt",
                },
                "firstMessage": "Follow-up call..."
            },
            "phoneNumberId": VAPI_PHONE_ID,
            "customer": {"number": phone}
        }

        r = requests.post(
            "https://api.vapi.ai/call/phone",
            json=payload,
            headers={"Authorization": f"Bearer {VAPI_API_KEY}"}
        )

        return r.json().get("id")

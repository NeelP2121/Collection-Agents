import requests
import json
import logging
from typing import Dict, Any
from utils.config import VAPI_API_KEY, VAPI_PHONE_ID

logger = logging.getLogger(__name__)

class VapiHandler:
    def initiate_call(self, phone: str, agent1_handoff: Dict[str, Any], workflow_id: str):
        """
        Trigger an asynchronous webRTC/PSTN call to the borrower.
        Injects the Temporal workflow ID into the metadata so the webhook can map the signal back.
        """
        context_str = json.dumps(agent1_handoff)[:500] if agent1_handoff else ""
        
        system_prompt = f"""You are the Resolution Voice Agent for a debt collection company. You are a transactional dealmaker.
CONTEXT FROM PRIOR CHAT:
{context_str}

INSTRUCTIONS:
1. OPENING: Reference prior chat interaction.
2. NO RE-VERIFICATION: Do not re-ask for identity.
3. NEGOTIATE SETTLEMENT AND LOCK IN DEAL.
"""
        payload = {
            "assistant": {
                "model": {
                    "provider": "anthropic",
                    "model": "claude-3-5-haiku-20241022",
                    "messages": [{"role": "system", "content": system_prompt}],
                },
                "firstMessage": "Hi, this is the resolution team calling."
            },
            "phoneNumberId": VAPI_PHONE_ID,
            "customer": {"number": phone},
            "metadata": {
                "temporal_workflow_id": workflow_id
            }
        }

        # Safe exception handling for environments without real api keys loaded
        try:
            logger.info(f"Triggering asynchronous VAPI call for phone {phone} mapping to Temporal Workflow {workflow_id}")
            if VAPI_API_KEY == "your-vapi-api-key" or not VAPI_API_KEY:
                # Local mock execution without key
                logger.warning("VAPI API Key not configured. Skipping raw POST.")
                return "mock_call_id"
                
            r = requests.post(
                "https://api.vapi.ai/call/phone",
                json=payload,
                headers={"Authorization": f"Bearer {VAPI_API_KEY}"}
            )
            r.raise_for_status()
            return r.json().get("id")
        except Exception as e:
            logger.error(f"VAPI HTTP Trigger Failed: {e}")
            return None

import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
VAPI_API_KEY = os.getenv("VAPI_API_KEY")
VAPI_PHONE_ID = os.getenv("VAPI_PHONE_ID")
TEMPORAL_HOST = os.getenv("TEMPORAL_HOST", "localhost:7233")

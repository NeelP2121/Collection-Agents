import os
from dotenv import load_dotenv

load_dotenv()

def _read_secret(filename: str) -> str:
    """Read a secret from the secrets/ directory, return empty string if not found."""
    path = os.path.join("secrets", filename)
    if os.path.exists(path):
        with open(path, "r") as f:
            return f.read().strip()
    return ""

# --- API Keys (env vars take priority, secrets/ files as fallback) ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY") or _read_secret("anthropic_key.txt")
OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY")    or _read_secret("openai_key.txt")
GOOGLE_API_KEY    = os.getenv("GOOGLE_API_KEY")    or _read_secret("google_key.txt")
VAPI_API_KEY      = os.getenv("VAPI_API_KEY")      or _read_secret("vapi_key.txt")
VAPI_PHONE_ID     = os.getenv("VAPI_PHONE_ID")     or _read_secret("vapi_phone_id.txt")
VAPI_PUBLIC_KEY   = os.getenv("VAPI_PUBLIC_KEY")   or _read_secret("vapi_public_key.txt")
VAPI_ASSISTANT_ID = os.getenv("VAPI_ASSISTANT_ID") or ""

# --- Provider Selection ---
# Set LLM_PROVIDER in .env to one of: anthropic | openai | gemini | ollama
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic").lower()
USE_OLLAMA = LLM_PROVIDER == "ollama"
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")

# --- Provider-Specific Models (real, production model IDs) ---
LLM_MODELS = {
    "anthropic": {
        "agent": "claude-4-5-haiku",       # Current fastest Claude
        "evaluation": "claude-4-6-sonnet", # Current industry standard
        "improver": "claude-4-6-sonnet",
        "godel": "claude-4-6-opus"         # Most intelligent
    },
    "openai": {
        "agent": "gpt-5.4-mini",           # Updated mini model
        "evaluation": "gpt-5.4-thinking",  # Standard reasoning model
        "improver": "gpt-5.4-thinking",
        "godel": "gpt-5.4-pro"
    },
    "gemini": {
        "agent": "gemini-2.0-flash",
        "evaluation": "gemini-2.5-pro-preview-03-25",
        "improver": "gemini-2.5-pro-preview-03-25",
        "godel": "gemini-2.5-pro-preview-03-25"
    },
    "ollama": {
        "agent":      os.getenv("OLLAMA_MODEL", "gemma4"),
        "evaluation": os.getenv("OLLAMA_MODEL", "gemma4"),
        "improver":   os.getenv("OLLAMA_MODEL", "gemma4"),
        "godel":      os.getenv("OLLAMA_MODEL", "gemma4"),
    },
}

def get_model(role: str = "agent") -> str:
    """Return the correct model ID for the active LLM_PROVIDER and role.
    
    Usage anywhere in the codebase:
        from utils.config import get_model
        model = get_model("agent")      # -> e.g. "gemini-2.0-flash"
        model = get_model("improver")   # -> e.g. "gemini-3.1-pro"
    """
    provider_models = LLM_MODELS.get(LLM_PROVIDER, LLM_MODELS["anthropic"])
    return provider_models.get(role, next(iter(provider_models.values())))

# --- Pricing per 1M tokens (USD) ---
MODEL_PRICING = {
    # Anthropic
    "claude-haiku-4-5-20251001": {"input": 0.80,  "output": 4.00},
    "claude-sonnet-4-6":         {"input": 3.00,  "output": 15.00},
    "claude-opus-4-6":           {"input": 15.00, "output": 75.00},
    # OpenAI
    "gpt-4o-mini":                {"input": 0.15,  "output": 0.60},
    "gpt-4o":                     {"input": 5.00,  "output": 15.00},
    # Gemini
    "gemini-2.0-flash":               {"input": 0.10,  "output": 0.40},
    "gemini-2.5-pro-preview-03-25":   {"input": 1.25,  "output": 10.00},
    "gemini-3.1-flash":               {"input": 0.10,  "output": 0.40},
    "gemini-3.1-pro":                 {"input": 1.25,  "output": 10.00},
    # Local (free)
    "gemma4":   {"input": 0.0, "output": 0.0},
    "llama3.1": {"input": 0.0, "output": 0.0},
}

# --- Temporal ---
TEMPORAL_HOST = os.getenv("TEMPORAL_HOST", "localhost:7233")
TEMPORAL_TASK_QUEUE = "collections"

# --- Database ---
DB_PATH = os.getenv("DB_PATH", "./collections_agents.db")

# --- Token Budget (hard limits, enforced by BaseAgent via tiktoken) ---
TOKEN_BUDGET_CONFIG = {
    "total_per_agent": 2000,
    "handoff_max": 500,
    "agent1_system_prompt": 1200,
    "agent2_system_prompt": 1500,
    "agent3_system_prompt": 1500,
}

# --- Workflow Timeouts (seconds) ---
WORKFLOW_TIMEOUTS = {
    "assessment":    300,
    "voice":         300,
    "final_notice":  300,
    "summarization": 120,
}

# --- Self-Learning Loop ---
LEARNING_CONFIG = {
    "max_iterations":            5,
    "conversations_per_eval":    25,
    "effect_size_threshold":     0.5,   # Cohen's d
    "improvement_threshold_pct": 0.15,  # 15% required improvement
    "max_variance_ratio":        0.25,
    "max_budget_usd":            19.5,  # $0.50 buffer before $20 ceiling
    "seed":                      42,
}

# --- Compliance ---
COMPLIANCE_RULES = {
    "identity_disclosure":    {"enabled": True, "severity": "critical"},
    "no_false_threats":       {"enabled": True, "severity": "critical"},
    "no_harassment":          {"enabled": True, "severity": "critical"},
    "no_misleading_terms":    {"enabled": True, "severity": "critical"},
    "sensitive_situations":   {"enabled": True, "severity": "warning"},
    "recording_disclosure":   {"enabled": True, "severity": "critical"},
    "professional_composure": {"enabled": True, "severity": "warning"},
    "data_privacy":           {"enabled": True, "severity": "critical"},
}

# --- Settlement Policy Ranges ---
SETTLEMENT_OFFER_RANGES = {
    "lump_sum_discount_min_pct":  0.15,
    "lump_sum_discount_max_pct":  0.40,
    "payment_plan_months_min":    3,
    "payment_plan_months_max":    24,
    "hardship_referral_threshold": 0.80,
}

# --- Test Harness Personas ---
BORROWER_PERSONAS = [
    "cooperative", "combative", "evasive",
    "confused", "distressed", "financially_capable",
]
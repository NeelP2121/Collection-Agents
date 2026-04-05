import os
from dotenv import load_dotenv

load_dotenv()

# API Keys
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
VAPI_API_KEY = os.getenv("VAPI_API_KEY")
VAPI_PHONE_ID = os.getenv("VAPI_PHONE_ID")

# Temporal Configuration
TEMPORAL_HOST = os.getenv("TEMPORAL_HOST", "localhost:7233")
TEMPORAL_TASK_QUEUE = "collections"

# Database
DB_PATH = os.getenv("DB_PATH", "./collections_agents.db")

# Token Budget Configuration (hard limits)
TOKEN_BUDGET_CONFIG = {
    "total_per_agent": 2000,           # Max tokens per agent (system prompt + context)
    "handoff_max": 500,                # Max tokens summarizer can use for handoffs
    "agent1_system_prompt": 1200,      # Agent 1 system prompt budget (no handoff history needed)
    "agent2_system_prompt": 1500,      # Agent 2 system prompt budget (1500 + 500 handoff = 2000)
    "agent3_system_prompt": 1500,      # Agent 3 system prompt budget (1500 + 500 handoff = 2000)
}

# LLM Model Configuration
LLM_MODELS = {
    "agent": "claude-3-5-sonnet-20241022",           # For agent conversations (better quality)
    "evaluation": "claude-3-5-haiku-20241022",       # For evaluation scoring (cheaper)
    "summary": "claude-3-5-haiku-20241022",          # For summaries (cheaper)
    "mutation": "claude-3-5-haiku-20241022",         # For prompt mutations (cheaper)
}

# Context Window Sizes (tokens)
CONTEXT_WINDOWS = {
    "haiku": 200000,
    "sonnet": 200000,
}

# Workflow Timeouts
WORKFLOW_TIMEOUTS = {
    "assessment": 300,           # 5 minutes
    "voice": 300,                # 5 minutes
    "final_notice": 300,         # 5 minutes
    "summarization": 120,        # 2 minutes
}

# Learning Loop Configuration
LEARNING_CONFIG = {
    "max_iterations": 5,
    "conversations_per_eval": 25,
    "effect_size_threshold": 0.5,               # Cohen's d threshold for adoption
    "improvement_threshold_pct": 0.15,          # 15% improvement threshold
    "max_variance_ratio": 0.25,                 # Max stdev/mean ratio
    "max_budget_usd": 19.5,                     # Halt at 19.5 to leave 0.5 buffer before $20
    "seed": 42,                                 # Fixed seed for reproducibility
}

# Compliance Configuration
COMPLIANCE_RULES = {
    "identity_disclosure": {"enabled": True, "severity": "critical"},
    "no_false_threats": {"enabled": True, "severity": "critical"},
    "no_harassment": {"enabled": True, "severity": "critical"},
    "no_misleading_terms": {"enabled": True, "severity": "critical"},
    "sensitive_situations": {"enabled": True, "severity": "warning"},
    "recording_disclosure": {"enabled": True, "severity": "critical"},
    "professional_composure": {"enabled": True, "severity": "warning"},
    "data_privacy": {"enabled": True, "severity": "critical"},
}

# Settlement Offer Ranges (policy-defined)
SETTLEMENT_OFFER_RANGES = {
    "lump_sum_discount_min_pct": 0.15,      # Minimum 15% discount
    "lump_sum_discount_max_pct": 0.40,      # Maximum 40% discount
    "payment_plan_months_min": 3,
    "payment_plan_months_max": 24,
    "hardship_referral_threshold": 0.80,    # If balance > 80% of monthly income, refer
}

# Borrower Persona Types (for test harness)
BORROWER_PERSONAS = [
    "cooperative",
    "combative",
    "evasive",
    "confused",
    "distressed",
    "financially_capable",
]
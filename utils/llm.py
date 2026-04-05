"""
LLM Interface - Anthropic Claude API
"""

from anthropic import Anthropic
from utils.config import ANTHROPIC_API_KEY, LLM_MODELS
from utils.cost_tracker import get_cost_tracker
import logging

logger = logging.getLogger(__name__)

client = Anthropic(api_key=ANTHROPIC_API_KEY)


def call_llm(system: str, messages: list, model: str = None, max_tokens: int = 300, context_category: str = "general") -> str:
    """
    Call Claude API with system prompt and messages.
    
    Args:
        system: System prompt
        messages: List of {role, content} dicts
        model: Model name (defaults to agent model)
        max_tokens: Max response length
        context_category: Budget category
    
    Returns:
        Response text
    """
    if model is None:
        model = LLM_MODELS.get("agent", "claude-3-5-sonnet-20241022")
    
    try:
        get_cost_tracker().check_budget()
        
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages
        )
        
        get_cost_tracker().record_call_cost(
            model=model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            category=context_category
        )
        
        return response.content[0].text
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        raise


def call_llm_structured(system: str, messages: list, model: str = None, max_tokens: int = 1000, context_category: str = "general") -> dict:
    """
    Call Claude API and expect JSON response (for structured outputs).
    
    Args:
        system: System prompt
        messages: List of {role, content} dicts
        model: Model name
        max_tokens: Max response length
    
    Returns:
        Parsed JSON dict
    """
    import json
    
    if model is None:
        model = LLM_MODELS.get("agent", "claude-3-5-sonnet-20241022")
    
    response = call_llm(system, messages, model, max_tokens, context_category)
    
    try:
        return json.loads(response)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON from LLM response: {e}")
        logger.error(f"Response was: {response}")
        # Try to extract JSON if response contains extra text
        try:
            start = response.find('{')
            end = response.rfind('}') + 1
            if start >= 0 and end > start:
                return json.loads(response[start:end])
        except:
            pass
        raise


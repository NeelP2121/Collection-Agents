"""
LLM Interface - Provider Agnostic
"""
import os
import json
import anthropic
import google.genai as genai
from openai import OpenAI
import logging
from utils.config import (
    LLM_MODELS, LLM_PROVIDER, USE_OLLAMA, OLLAMA_BASE_URL,
    ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_API_KEY
)
from utils.cost_tracker import get_cost_tracker

logger = logging.getLogger(__name__)

# Global client cache
_clients = {}

def get_provider():
    """Centralized logic to determine which provider to use."""
    if USE_OLLAMA:
        return "ollama"
    return os.getenv("LLM_PROVIDER", LLM_PROVIDER).lower()

def get_client(provider):
    """Get or create client for the specified provider."""
    if provider in _clients:
        return _clients[provider]
    
    if provider == "ollama":
        _clients["ollama"] = OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")
    elif provider == "anthropic":
        _clients["anthropic"] = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    elif provider == "openai":
        _clients["openai"] = OpenAI(api_key=OPENAI_API_KEY)
    elif provider == "gemini":
        _clients["gemini"] = genai.Client(api_key=GOOGLE_API_KEY)
    else:
        raise ValueError(f"Unsupported provider: {provider}")
    
    return _clients[provider]

def _map_future_model(model: str, provider: str) -> str:
    """Map future 2026 model names to current stable ones for compatibility."""
    # Anthropic
    if provider == "anthropic":
        if "claude-4-5-haiku" in model:   return "claude-haiku-4-5-20251001"
        if "claude-4-6-sonnet" in model:  return "claude-sonnet-4-6"
        if "claude-4-6-opus" in model:    return "claude-opus-4-6"
    # OpenAI
    elif provider == "openai":
        if "gpt-5.4-mini" in model:      return "gpt-4o-mini"
        if "gpt-5.4-thinking" in model:  return "o1-mini"
        if "gpt-5.4-pro" in model:       return "gpt-4o"
    # Gemini
    elif provider == "gemini":
        pass # Route exactly to the models requested without mapping
    
    return model

def call_llm(system: str, messages: list, model: str = None, max_tokens: int = 300, context_category: str = "general") -> str:
    current_provider = get_provider()
    client = get_client(current_provider)
    
    # Fallback to config models if none provided
    if model is None:
        model = LLM_MODELS.get(current_provider, {}).get("agent")
    
    # Apply Compatibility Mapping for future models
    model = _map_future_model(model, current_provider)
    
    try:
        get_cost_tracker().check_budget()
        
        # --- OPENAI & OLLAMA (Shared OpenAI Schema) ---
        if current_provider in ["openai", "ollama"]:
            oai_messages = [{"role": "system", "content": system}] + messages
            response = client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                messages=oai_messages
            )
            
            get_cost_tracker().record_call_cost(
                model=model,
                input_tokens=response.usage.prompt_tokens,
                output_tokens=response.usage.completion_tokens,
                category=context_category
            )
            return response.choices[0].message.content
        
        # --- ANTHROPIC ---
        elif current_provider == "anthropic":
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
        
        # --- GEMINI ---
        elif current_provider == "gemini":
            contents = []
            for msg in messages:
                role = "user" if msg["role"] == "user" else "model"
                contents.append({"role": role, "parts": [{"text": msg["content"]}]})
            
            # Gemini SDK requires at least one content item
            if not contents:
                contents = [{"role": "user", "parts": [{"text": "Begin."}]}]
            
            response = client.models.generate_content(
                model=model,
                contents=contents,
                config={
                    "system_instruction": system,
                    "max_output_tokens": max_tokens,
                }
            )
            
            # Use actual usage metadata from Google's GenAI SDK
            usage = response.usage_metadata
            get_cost_tracker().record_call_cost(
                model=model,
                input_tokens=usage.prompt_token_count,
                output_tokens=usage.candidates_token_count,
                category=context_category
            )
            return response.text
        
        else:
            raise ValueError(f"Provider {current_provider} implementation missing.")
            
    except Exception as e:
        logger.error(f"LLM call failed on {current_provider}: {e}")
        raise

def call_llm_structured(system: str, messages: list, model: str = None, max_tokens: int = 1000, context_category: str = "general") -> dict:
    response_text = call_llm(system, messages, model, max_tokens, context_category)
    
    # Strip markdown code blocks if the LLM wrapped JSON in ```json ... ```
    clean_text = response_text.strip()
    if clean_text.startswith("```"):
        clean_text = clean_text.split("\n", 1)[-1].rsplit("\n", 1)[0].strip()
        if clean_text.startswith("json"): # handle ```json
             clean_text = clean_text[4:].strip()

    try:
        return json.loads(clean_text)
    except json.JSONDecodeError:
        logger.warning(f"Failed to parse JSON response: {clean_text[:100]}...")
        return {"response": response_text}
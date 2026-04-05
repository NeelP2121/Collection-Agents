#!/usr/bin/env python3
"""
Test script to verify API keys for all supported LLM providers.
Run: python test_key.py
"""

import os
import sys
from dotenv import load_dotenv

load_dotenv()

def _read_secret(filename: str) -> str:
    path = os.path.join("secrets", filename)
    if os.path.exists(path):
        with open(path) as f:
            return f.read().strip()
    return ""

def test_anthropic() -> bool:
    key = os.getenv("ANTHROPIC_API_KEY") or _read_secret("anthropic_key.txt")
    if not key:
        print("  ⚠️  No key found (ANTHROPIC_API_KEY or secrets/anthropic_key.txt)")
        return False
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=15,
            messages=[{"role": "user", "content": "Reply with ACTIVE only."}]
        )
        text = resp.content[0].text.strip()
        print(f"  Response: {text}")
        return True
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return False

def test_openai() -> bool:
    key = os.getenv("OPENAI_API_KEY") or _read_secret("openai_key.txt")
    if not key:
        print("  ⚠️  No key found (OPENAI_API_KEY or secrets/openai_key.txt)")
        return False
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=15,
            messages=[
                {"role": "system", "content": "You are a validator."},
                {"role": "user", "content": "Reply with ACTIVE only."}
            ]
        )
        text = resp.choices[0].message.content.strip()
        print(f"  Response: {text}")
        return True
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return False

def test_gemini() -> bool:
    key = os.getenv("GOOGLE_API_KEY") or _read_secret("google_key.txt")
    if not key:
        print("  ⚠️  No key found (GOOGLE_API_KEY or secrets/google_key.txt)")
        return False
    try:
        import google.genai as genai
        client = genai.Client(api_key=key)
        resp = client.models.generate_content(
            model="gemini-2.0-flash",
            contents="Reply with ACTIVE only.",
            config={"max_output_tokens": 15}
        )
        text = resp.text.strip()
        print(f"  Response: {text}")
        return True
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return False

def test_ollama() -> bool:
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    model = os.getenv("OLLAMA_MODEL", "gemma4")
    try:
        from openai import OpenAI
        client = OpenAI(base_url=base_url, api_key="ollama")
        resp = client.chat.completions.create(
            model=model,
            max_tokens=15,
            messages=[
                {"role": "system", "content": "You are a validator."},
                {"role": "user", "content": "Reply with ACTIVE only."}
            ]
        )
        text = resp.choices[0].message.content.strip()
        print(f"  Response: {text}")
        return True
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return False

TESTS = {
    "anthropic": test_anthropic,
    "openai":    test_openai,
    "gemini":    test_gemini,
    "ollama":    test_ollama,
}

def main():
    # Run only specified providers, or all if none given
    targets = sys.argv[1:] if sys.argv[1:] else list(TESTS.keys())
    results = {}

    print("🔑 API Provider Health Check")
    print("=" * 40)

    for provider in targets:
        if provider not in TESTS:
            print(f"Unknown provider: {provider}. Options: {list(TESTS.keys())}")
            continue
        print(f"\n🧪 Testing {provider.upper()}...")
        ok = TESTS[provider]()
        results[provider] = ok
        status = "✅ ONLINE" if ok else "❌ OFFLINE"
        print(f"  Status: {status}")

    print("\n" + "=" * 40)
    print("📊 Summary:")
    for provider, ok in results.items():
        icon = "✅" if ok else "❌"
        print(f"  {icon} {provider.upper()}")

    return 0 if all(results.values()) else 1

if __name__ == "__main__":
    sys.exit(main())
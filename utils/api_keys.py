"""
API key rotation and multi-provider fallback.

Manages multiple API keys per provider and rotates on rate-limit errors.
Provides a unified chat_completion() that falls through:
  Groq → Cerebras → Gemini → OpenRouter → SambaNova
"""
import os
import json
import time
import requests
from dotenv import load_dotenv

load_dotenv()

# ── Load keys ──────────────────────────────────────────────────────
def _split_keys(env_var: str) -> list:
    raw = os.getenv(env_var, "")
    return [k.strip() for k in raw.split(",") if k.strip()]

GROQ_KEYS      = _split_keys("GROQ_API_KEYS")
CEREBRAS_KEYS  = _split_keys("CEREBRAS_API_KEYS")
GEMINI_KEY     = os.getenv("GEMINI_API_KEY", "")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")
SAMBANOVA_KEY  = os.getenv("SAMBANOVA_API_KEY", "")

GROQ_MODEL      = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
CEREBRAS_MODEL  = os.getenv("CEREBRAS_MODEL", "llama3.1-70b")
GEMINI_MODEL    = os.getenv("GEMINI_MODEL", "gemini-2.0-flash-lite")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "mistralai/mistral-7b-instruct:free")
SAMBANOVA_MODEL = os.getenv("SAMBANOVA_MODEL", "Meta-Llama-3.1-70B-Instruct")

import random as _random


def _next_key(provider: str, keys: list) -> str:
    return _random.choice(keys)


# ── Provider implementations ────────────────────────────────────────

def _groq_chat(messages: list, max_tokens: int = 4096, temperature: float = 0.7) -> str:
    for attempt in range(len(GROQ_KEYS)):
        key = _next_key("groq", GROQ_KEYS)
        try:
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"model": GROQ_MODEL, "messages": messages,
                      "max_tokens": max_tokens, "temperature": temperature},
                timeout=60,
            )
            if r.status_code == 429:
                time.sleep(2)
                continue
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            if attempt == len(GROQ_KEYS) - 1:
                raise
            time.sleep(1)
    raise RuntimeError("All Groq keys exhausted")


def _cerebras_chat(messages: list, max_tokens: int = 4096, temperature: float = 0.7) -> str:
    for attempt in range(len(CEREBRAS_KEYS)):
        key = _next_key("cerebras", CEREBRAS_KEYS)
        try:
            r = requests.post(
                "https://api.cerebras.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"model": CEREBRAS_MODEL, "messages": messages,
                      "max_tokens": max_tokens, "temperature": temperature},
                timeout=60,
            )
            if r.status_code == 429:
                time.sleep(2)
                continue
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            if attempt == len(CEREBRAS_KEYS) - 1:
                raise
            time.sleep(1)
    raise RuntimeError("All Cerebras keys exhausted")


def _gemini_chat(messages: list, max_tokens: int = 4096, temperature: float = 0.7) -> str:
    # Convert OpenAI-style messages to Gemini format
    parts = []
    for msg in messages:
        role = "user" if msg["role"] in ("user", "system") else "model"
        parts.append({"role": role, "parts": [{"text": msg["content"]}]})
    
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
        params={"key": GEMINI_KEY},
        json={"contents": parts,
              "generationConfig": {"maxOutputTokens": max_tokens, "temperature": temperature}},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()


def _openrouter_chat(messages: list, max_tokens: int = 4096, temperature: float = 0.7) -> str:
    r = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"},
        json={"model": OPENROUTER_MODEL, "messages": messages,
              "max_tokens": max_tokens, "temperature": temperature},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def _sambanova_chat(messages: list, max_tokens: int = 4096, temperature: float = 0.7) -> str:
    r = requests.post(
        "https://api.sambanova.ai/v1/chat/completions",
        headers={"Authorization": f"Bearer {SAMBANOVA_KEY}", "Content-Type": "application/json"},
        json={"model": SAMBANOVA_MODEL, "messages": messages,
              "max_tokens": max_tokens, "temperature": temperature},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


# ── Public API ──────────────────────────────────────────────────────

PROVIDER_CHAIN = [
    ("groq",       _groq_chat,       GROQ_KEYS),
    ("cerebras",   _cerebras_chat,   CEREBRAS_KEYS),
    ("gemini",     _gemini_chat,     [GEMINI_KEY]),
    ("openrouter", _openrouter_chat, [OPENROUTER_KEY]),
    ("sambanova",  _sambanova_chat,  [SAMBANOVA_KEY]),
]


def chat_completion(messages: list, max_tokens: int = 4096,
                    temperature: float = 0.7) -> dict:
    """
    Try each AI provider in order. Returns {"text": ..., "provider": ...}.
    Falls through Groq → Cerebras → Gemini → OpenRouter → SambaNova.
    """
    errors = []
    for name, fn, keys in PROVIDER_CHAIN:
        if not keys or not keys[0]:
            continue
        try:
            text = fn(messages, max_tokens, temperature)
            return {"text": text, "provider": name}
        except Exception as e:
            errors.append(f"{name}: {e}")
            continue

    raise RuntimeError(f"All AI providers failed:\n" + "\n".join(errors))

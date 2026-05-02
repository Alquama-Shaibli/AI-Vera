"""
LLM Client — multi-provider with fallback chain.
Primary: OpenAI → Anthropic → Gemini
All calls: temperature=0, deterministic output.
Response cache: same input → same output.
"""

from __future__ import annotations

import hashlib
import json
from typing import Optional

from loguru import logger

from app.core.config import (
    LLM_PROVIDER, LLM_MODEL,
    OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY,
    LLM_TEMPERATURE, CACHE_LLM_RESPONSES,
)


class LLMClient:
    """Multi-provider LLM client with in-process response caching."""

    MAX_TOKENS = 1024

    def __init__(self):
        self._cache: dict[str, str] = {}
        self._provider = LLM_PROVIDER
        self._model = LLM_MODEL
        logger.info(f"LLMClient: provider={self._provider}, model={self._model}")

    def is_available(self) -> bool:
        """Check if any valid API key is available for the current or fallback providers."""
        keys = {
            "openai": OPENAI_API_KEY,
            "anthropic": ANTHROPIC_API_KEY,
            "gemini": GEMINI_API_KEY,
        }
        # Check current
        key = keys.get(self._provider, "")
        if key and not key.startswith("sk-...") and key != "...":
            return True
        # Check fallbacks
        for k in keys.values():
            if k and not k.startswith("sk-...") and k != "...":
                return True
        return False

    def _validate(self):
        if not self.is_available():
            raise ValueError(f"No valid API key found for any provider.")

    def complete(self, system: str, user: str) -> Optional[str]:
        """Call the LLM with system + user prompt. Returns text or None."""
        cache_key = self._make_key(system, user)
        if CACHE_LLM_RESPONSES and cache_key in self._cache:
            logger.debug("LLM cache hit")
            return self._cache[cache_key]

        result = None
        for attempt in range(2):
            try:
                result = self._call(system, user)
                if result:
                    break
            except Exception as e:
                logger.warning(f"LLM attempt {attempt+1} failed: {e}")
                if attempt == 0:
                    result = self._fallback(system, user)
                    if result:
                        break

        if result and CACHE_LLM_RESPONSES:
            self._cache[cache_key] = result
        return result

    def _call(self, system: str, user: str) -> Optional[str]:
        if self._provider == "openai":
            return self._openai(system, user)
        elif self._provider == "anthropic":
            return self._anthropic(system, user)
        elif self._provider == "gemini":
            return self._gemini(system, user)
        return None

    def _fallback(self, system: str, user: str) -> Optional[str]:
        """Try next provider in chain."""
        chain = ["openai", "anthropic", "gemini"]
        current = chain.index(self._provider) if self._provider in chain else 0
        for prov in chain[current + 1:]:
            try:
                logger.info(f"Falling back to {prov}")
                if prov == "openai" and OPENAI_API_KEY:
                    return self._openai(system, user, override_model="gpt-4o-mini")
                elif prov == "anthropic" and ANTHROPIC_API_KEY:
                    return self._anthropic(system, user, override_model="claude-3-haiku-20240307")
                elif prov == "gemini" and GEMINI_API_KEY:
                    return self._gemini(system, user, override_model="gemini-1.5-flash")
            except Exception as e:
                logger.warning(f"Fallback {prov} failed: {e}")
        return None

    def _openai(self, system: str, user: str, override_model: str = "") -> Optional[str]:
        import httpx
        model = override_model or self._model
        response = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "temperature": LLM_TEMPERATURE,
                "max_tokens": self.MAX_TOKENS,
            },
            timeout=20,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

    def _anthropic(self, system: str, user: str, override_model: str = "") -> Optional[str]:
        import httpx
        model = override_model or self._model
        response = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "system": system,
                "messages": [{"role": "user", "content": user}],
                "max_tokens": self.MAX_TOKENS,
            },
            timeout=20,
        )
        response.raise_for_status()
        return response.json()["content"][0]["text"]

    def _gemini(self, system: str, user: str, override_model: str = "") -> Optional[str]:
        import httpx
        model = override_model or self._model
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": LLM_TEMPERATURE,
                "topP": 1.0,
                "candidateCount": 1,
                "maxOutputTokens": self.MAX_TOKENS,
            },
        }
        response = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}",
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=25,
        )
        response.raise_for_status()
        data = response.json()
        candidates = data.get("candidates", [])
        if not candidates:
            logger.warning(f"Gemini returned no candidates: {data}")
            return None
        return candidates[0]["content"]["parts"][0]["text"]

    def _make_key(self, system: str, user: str) -> str:
        h = hashlib.md5(f"{system}||{user}".encode()).hexdigest()
        return h

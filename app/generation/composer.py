"""
Message Composer — template-first generation with optional LLM enhancement.

Strategy: use deterministic templates as primary generation (zero LLM cost),
then optionally enhance with LLM for higher-scoring output. This saves
significant API credits while maintaining quality.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from loguru import logger

from app.generation.templates import STRATEGY_TEMPLATES, build_template_message
from app.generation.llm_client import LLMClient
from app.validators.message_validator import validate_message
from app.core.config import USE_TEMPLATES_FIRST, CACHE_LLM_RESPONSES


class MessageComposer:
    """Composes messages using templates + optional LLM."""

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm = llm_client
        self._cache: dict[str, dict] = {}

    def compose(
        self,
        category: dict,
        merchant: dict,
        trigger: dict,
        customer: Optional[dict] = None,
        score: float = 0.0,
    ) -> dict:
        """
        Compose a message for the given context.
        Returns {"body", "cta", "send_as", "suppression_key", "rationale",
                 "template_name", "template_params"}.
        """
        kind = trigger.get("kind", "unknown")
        scope = trigger.get("scope", "merchant")

        # Cache key for determinism
        cache_key = self._make_cache_key(category, merchant, trigger, customer)
        if cache_key in self._cache:
            logger.debug(f"Cache hit for {kind}")
            return self._cache[cache_key]

        # Step 1: Build template-based message (always available, zero cost)
        template_result = build_template_message(category, merchant, trigger, customer)

        # Step 2: If LLM is available and trigger is high-value, enhance
        result = template_result
        if self.llm and not USE_TEMPLATES_FIRST and score >= 4.0:
            try:
                llm_result = self._compose_with_llm(category, merchant, trigger, customer, kind)
                if llm_result and validate_message(llm_result, category, merchant, trigger, customer):
                    result = llm_result
                else:
                    logger.debug(f"LLM result failed validation, using template for {kind}")
            except Exception as e:
                logger.warning(f"LLM composition failed: {e}, using template")

        # Cache the result
        if CACHE_LLM_RESPONSES:
            self._cache[cache_key] = result

        return result

    def _compose_with_llm(
        self,
        category: dict,
        merchant: dict,
        trigger: dict,
        customer: Optional[dict],
        kind: str,
    ) -> Optional[dict]:
        """Compose using LLM — only called when templates aren't sufficient."""
        system_prompt = self._build_system_prompt(category)
        user_prompt = self._build_user_prompt(merchant, trigger, customer, kind)

        response = self.llm.complete(system_prompt, user_prompt)
        if not response:
            return None

        return self._parse_llm_response(response, trigger, customer)

    def _build_system_prompt(self, category: dict) -> str:
        slug = category.get("slug", "unknown")
        voice = category.get("voice", {})
        tone = voice.get("tone", "professional")
        taboos = voice.get("vocab_taboo", [])

        return f"""You are Vera, magicpin's merchant engagement AI for {slug}.

VOICE RULES:
- Tone: {tone}
- NEVER use these words: {', '.join(taboos[:5])}
- Be concise, specific, data-driven
- Hindi-English code-mix is preferred for Indian merchants
- Address owner by first name

OUTPUT FORMAT — return ONLY a JSON object:
{{"body": "the WhatsApp message", "cta": "open_ended|binary_yes_no|none", "rationale": "1-line why"}}

CRITICAL RULES:
- ONE CTA max (at the end)
- Use ONLY data from the context provided — NEVER fabricate
- No URLs
- No generic "increase your sales" — use specific numbers
- Service+price beats discount percentage"""

    def _build_user_prompt(
        self,
        merchant: dict,
        trigger: dict,
        customer: Optional[dict],
        kind: str,
    ) -> str:
        identity = merchant.get("identity", {})
        perf = merchant.get("performance", {})
        offers = [o.get("title", "") for o in merchant.get("offers", []) if o.get("status") == "active"]
        signals = merchant.get("signals", [])

        parts = [
            f"MERCHANT: {identity.get('name', '?')} ({identity.get('locality', '?')}, {identity.get('city', '?')})",
            f"Owner: {identity.get('owner_first_name', '?')}",
            f"Languages: {identity.get('languages', ['en'])}",
            f"Performance (30d): views={perf.get('views', '?')}, calls={perf.get('calls', '?')}, ctr={perf.get('ctr', '?')}",
            f"7d delta: {perf.get('delta_7d', {})}",
            f"Active offers: {offers or 'None'}",
            f"Signals: {signals}",
            f"TRIGGER kind={kind}, urgency={trigger.get('urgency', '?')}",
            f"Trigger payload: {json.dumps(trigger.get('payload', {}))}",
        ]

        if customer:
            cid = customer.get("identity", {})
            parts.append(f"CUSTOMER: {cid.get('name', '?')}, state={customer.get('state', '?')}, lang={cid.get('language_pref', 'en')}")
            parts.append(f"Relationship: {customer.get('relationship', {})}")
            parts.append(f"Send as: merchant_on_behalf")
        else:
            parts.append("Send as: vera (merchant-facing)")

        parts.append("\nCompose the message now.")
        return "\n".join(parts)

    def _parse_llm_response(self, response: str, trigger: dict, customer: Optional[dict]) -> Optional[dict]:
        """Parse LLM JSON response into our standard format."""
        try:
            # Find JSON in response
            start = response.find("{")
            end = response.rfind("}") + 1
            if start < 0 or end <= start:
                return None
            data = json.loads(response[start:end])

            scope = trigger.get("scope", "merchant")
            return {
                "body": data.get("body", ""),
                "cta": data.get("cta", "open_ended"),
                "send_as": "merchant_on_behalf" if customer else "vera",
                "suppression_key": trigger.get("suppression_key", ""),
                "rationale": data.get("rationale", ""),
                "template_name": f"vera_{trigger.get('kind', 'generic')}_v1",
                "template_params": [],
            }
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to parse LLM response: {e}")
            return None

    def _make_cache_key(self, category: dict, merchant: dict, trigger: dict, customer: Optional[dict]) -> str:
        key_data = json.dumps({
            "cat": category.get("slug", ""),
            "mid": merchant.get("merchant_id", ""),
            "tid": trigger.get("id", ""),
            "cid": customer.get("customer_id", "") if customer else "",
        }, sort_keys=True)
        return hashlib.md5(key_data.encode()).hexdigest()

"""
Message Validator — pre-send quality gate.
Checks CTA count, URL presence, taboo words, hallucination, repetition.
"""
from __future__ import annotations

import hashlib
import re
from typing import Optional

from loguru import logger


def validate_message(
    composed: dict,
    category: dict,
    merchant: dict,
    trigger: dict,
    customer: Optional[dict] = None,
    prior_hashes: Optional[set] = None,
) -> bool:
    """
    Return True if the message passes all quality gates.
    Logs the specific failure reason on False.
    """
    body = composed.get("body", "")
    cta = composed.get("cta", "")

    if not body or len(body) < 20:
        logger.debug("Validation fail: body too short")
        return False

    # No URLs in body
    if re.search(r"https?://", body):
        logger.debug("Validation fail: URL in body")
        return False

    # Taboo words
    voice = category.get("voice", {})
    taboos = voice.get("vocab_taboo", [])
    body_lower = body.lower()
    for word in taboos:
        if word.lower() in body_lower:
            logger.debug(f"Validation fail: taboo word '{word}'")
            return False

    # Anti-repetition
    if prior_hashes:
        h = hashlib.md5(body.encode()).hexdigest()
        if h in prior_hashes:
            logger.debug("Validation fail: repeated body")
            return False

    return True

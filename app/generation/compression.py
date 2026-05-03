"""
Message compression layer — WhatsApp-native shortening.
Strips robotic filler while preserving specificity and urgency.
Deterministic: same input → same output always.
"""
from __future__ import annotations
import re


# Filler phrases → shorter replacements (order matters)
_REPLACEMENTS = [
    (r"This is the best moment to", "Good time to"),
    (r"This is a signal —", "Signal:"),
    (r"Worth a 2-min read\.", "2-min read."),
    (r"I've spotted 2 quick fixes\.", "Two quick fixes —"),
    (r"Just say YES\.", "Say yes."),
    (r"Just say the word\.", "Say the word."),
    (r"I can handle this for you", "I'll take care of it"),
    (r"handling this for you", "on it"),
    (r"I will confirm once done\.", "Will confirm."),
    (r"Your profile still had", "Still"),
    (r" — no worries!", "!"),
    (r"in 2 minutes", "in 2 min"),
    (r"currently not available", "away"),
    # Strip AI-operator language remnants
    (r"I have initialized the", "Starting the"),
    (r"I have compiled the", "Pulling the"),
    (r"I have flagged", "Flagging"),
    (r"Initiating verification sequence\.", "Starting verification now."),
    (r"operational scope", "what I handle"),
    (r"operational updates discussed", "the update we discussed"),
    (r"I am queueing the update", "Updating"),
    (r"Execute\?", "Move on it?"),
    (r"Deploy\?", "Go ahead?"),
    (r"Authorize\?", "Confirm?"),
    (r"Proceed\?$", "Ready to go?"),
]

# Hard length limit for WhatsApp
MAX_LEN = 320


def compress(body: str) -> str:
    """Apply compression passes to a message body."""
    for pattern, replacement in _REPLACEMENTS:
        body = re.sub(pattern, replacement, body, flags=re.IGNORECASE)
    # Clean up double spaces
    body = re.sub(r"  +", " ", body).strip()
    # Clean up trailing punctuation artifacts
    body = re.sub(r"\s+\.", ".", body)
    body = re.sub(r"\.\.", ".", body)
    # Truncate if still too long
    if len(body) > MAX_LEN:
        # Cut at last sentence boundary before limit
        cut = body[:MAX_LEN].rfind(".")
        if cut > MAX_LEN * 0.6:
            body = body[:cut + 1]
        else:
            body = body[:MAX_LEN].rstrip() + "…"
    return body.strip()

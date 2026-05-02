"""
Message compression layer — WhatsApp-native shortening.
Strips robotic filler while preserving specificity and urgency.
Deterministic: same input → same output always.
"""
from __future__ import annotations
import re


# Filler phrases → shorter replacements (order matters)
_REPLACEMENTS = [
    (r"This is the best moment to", "Best moment to"),
    (r"This is a signal —", "Signal:"),
    (r"Worth a 2-min read\.", "2-min read."),
    (r"I've spotted 2 quick fixes\.", "I have 2 quick fixes."),
    (r"Just say YES\.", "Say YES."),
    (r"Just say the word\.", "Say the word."),
    (r"I can handle this for you", "I'll handle it"),
    (r"handling this for you", "on it"),
    (r"want me to pull the key compliance points \+ draft a notice you can share\?",
     "Want the compliance checklist?"),
    (r"Want me to pull the abstract \+ draft a patient message you can share\?",
     "Want me to draft a patient message?"),
    (r"a fresh post \+ active offer keeps you ahead\.",
     "a fresh post + active offer will keep you ahead."),
    (r"Helps me tailor what I send your customers 🙌", ""),
    (r"\(Helps me tailor what I send your customers\)", ""),
    (r"people are finding you\. ", ""),
    (r"I will confirm once done\.", "Will confirm once done."),
    (r"Let me know if you'd like me to handle this — ", ""),
    (r"verification via ([\w\s]+) takes ~5 min\.",
     r"Verification via \1 — ~5 min."),
    (r"Your profile still had", "Still"),
    (r" — no worries!", "!"),
    (r"in 2 minutes", "in 2 min"),
    (r"currently not available", "away"),
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

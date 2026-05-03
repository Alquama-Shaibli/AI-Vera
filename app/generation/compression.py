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
    (r"I'll take care of it", "I'll handle it"),
    (r"on it", "ready"),
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
    (r"visibility decay", "drop in people seeing you"),
    (r"traffic anomaly", "dip in calls"),
    (r"anomaly", "shift"),
    (r"engagement momentum", "recent interest"),
    (r"momentum optimization", "growth check"),
    (r"conversion optimization", "getting more calls"),
    (r"strategic deployment", "listing update"),
    (r"automated guidance", "guidance"),
    (r"strategic alignment", "plan"),
    (r"optimization protocol", "update"),
    (r"protocol", "steps"),
    (r"merchant profile analysis", "profile check"),
    (r"algorithmic boost", "visibility lift"),
    (r"algorithmic", "data-driven"),
    (r"I will wait for your confirmation", "Let me know when you're ready"),
    (r"Awaiting your reply", "Talk soon"),
    (r"Happy to help", "Sure"),
    (r"I can assist", "Sure"),
    (r"Shall I", "Ready to"),
    (r"Want me to", "Ready to"),
    (r"Would you like me to", "I can"),
    (r"I will prepare", "I'll pull"),
    (r"I can execute", "I'll handle"),
    (r"Execute", "Handle"),
    (r"Deploy", "Start"),
    (r"operational update", "update"),
    (r"workflow update", "update"),
    (r"workflow", "steps"),
    (r"implementation sequence", "steps"),
    (r"implementation ready", "ready to start"),
    (r"implementation", "setup"),
    (r"Execute\?", "Move on it?"),
    (r"Deploy\?", "Go ahead?"),
    (r"Authorize\?", "Confirm?"),
    (r"Proceed\?$", "Ready to go?"),
    (r"campaign execution", "starting the campaign"),
    (r"operational alert", "heads up"),
    (r"operational block", "delay"),
    (r"system generated", "sent"),
    (r"automated", "ready"),
    (r"processing", "working on it"),
    (r"Anything else\?", "Ready?"),
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

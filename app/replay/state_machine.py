"""
Replay State Machine — handles multi-turn merchant conversations.
Detects: auto-replies, intent transitions, hostile messages, off-topic.
"""
from __future__ import annotations

import re
from typing import Optional

from loguru import logger

from app.models.schemas import ReplyResponse


# ── Intent detection patterns ──────────────────────────────────────────

AUTO_REPLY_PATTERNS = [
    r"thank you for contacting",
    r"aapki madad ke liye shukriya",
    r"our team will respond",
    r"hamari team.{0,30}pahuncha",
    r"automated (message|assistant|response)",
    r"we will get back to you",
    r"wapas aayenge",
    r"i am (currently )?unavailable",
    r"out of office",
    r"auto.?reply",
    r"currently not available",
    r"aapka sandesh mil gaya",
]

COMMITMENT_PATTERNS = [
    r"\byes\b", r"\bha[anh]\b", r"\bji\b", r"\bठीक है\b",
    r"let'?s do it", r"go ahead", r"sounds good", r"ok let'?s",
    r"proceed", r"confirm", r"chalega", r"theek hai",
    r"whats? next", r"next step", r"tell me more",
    r"i'?m interested", r"karo", r"kar do",
]

HOSTILE_PATTERNS = [
    r"stop (mess?aging|contact|spam)",
    r"do not (contact|message|call)",
    r"spam", r"waste of time", r"not interested",
    r"remove (me|my number)", r"unsubscribe",
    r"band karo", r"mat karo", r"nahin chahiye",
    r"leave me alone", r"block", r"report",
]

OFF_TOPIC_PATTERNS = [
    r"weather", r"cricket", r"ipl score",
    r"loan", r"insurance", r"job",
    r"who are you", r"aap kaun",
]


def _detect_intent(message: str) -> str:
    """Classify a merchant message into an intent category."""
    msg = message.lower().strip()

    for pat in AUTO_REPLY_PATTERNS:
        if re.search(pat, msg, re.IGNORECASE):
            return "auto_reply"

    for pat in HOSTILE_PATTERNS:
        if re.search(pat, msg, re.IGNORECASE):
            return "hostile"

    for pat in COMMITMENT_PATTERNS:
        if re.search(pat, msg, re.IGNORECASE):
            return "commitment"

    for pat in OFF_TOPIC_PATTERNS:
        if re.search(pat, msg, re.IGNORECASE):
            return "off_topic"

    if "?" in msg or len(msg.split()) > 5:
        return "engaged"

    return "neutral"


# ── Graceful responses ─────────────────────────────────────────────────

GRACEFUL_EXIT = (
    "Samajh gaya — koi baat nahi. Jab bhi zaroorat ho, main yahan hoon. "
    "Best wishes for your business! 🙏"
)

HOSTILE_EXIT = (
    "Understood — I'll stop reaching out. Sorry for the interruption. "
    "If you ever need help with your profile, we're here 🙏"
)

ACTION_RESPONSE = (
    "Perfect! I'm on it — I'll handle this for you and confirm once done. "
    "Anything else while I'm at it?"
)

AUTO_REPLY_PROBE = (
    "Looks like that may have been an auto-reply — no worries! "
    "If you're the owner, happy to walk you through this in 2 minutes. Still interested?"
)

OFF_TOPIC_REDIRECT = (
    "Good question! Though that's outside what I can help with — "
    "I'm focused on growing your business profile and customer engagement. "
    "Want to pick up where we left off?"
)


class ReplayStateMachine:
    """Manages multi-turn conversation flow for merchant replies."""

    MAX_AUTO_REPLIES = 2  # end after this many consecutive auto-replies

    def __init__(self, context_store, conversation_store, suppression_store):
        self._ctx = context_store
        self._convs = conversation_store
        self._supp = suppression_store

    def handle_reply(
        self,
        conversation_id: str,
        merchant_id: str,
        customer_id: Optional[str],
        message: str,
        turn_number: int,
        composer=None,
    ) -> ReplyResponse:
        """Process a merchant reply and return the bot's next action."""

        # Get or create conversation state
        conv = self._convs.get(conversation_id)
        if not conv:
            conv = self._convs.create(
                conv_id=conversation_id,
                merchant_id=merchant_id,
                trigger_id="unknown",
                customer_id=customer_id,
            )

        # Already ended
        if self._convs.is_ended(conversation_id):
            return ReplyResponse(action="end", rationale="Conversation already closed")

        # Record turn
        self._convs.add_turn(conversation_id, "merchant", message)

        intent = _detect_intent(message)
        logger.info(f"conv={conversation_id} turn={turn_number} intent={intent}")

        # ── Auto-reply hell ────────────────────────────────────────────
        if intent == "auto_reply":
            count = self._convs.increment_auto_reply(conversation_id)
            if count >= self.MAX_AUTO_REPLIES:
                self._convs.set_state(conversation_id, "ended")
                logger.info(f"Auto-reply limit reached for {conversation_id}")
                return ReplyResponse(
                    action="end",
                    rationale=f"Detected {count} consecutive auto-replies — ending gracefully",
                )
            if count == 1:
                # Probe once
                body = AUTO_REPLY_PROBE
                self._convs.add_turn(conversation_id, "vera", body)
                return ReplyResponse(
                    action="send",
                    body=body,
                    cta="binary_yes_no",
                    rationale="Auto-reply detected — probing once before exit",
                )
            return ReplyResponse(action="wait", wait_seconds=3600,
                                 rationale="Second auto-reply — waiting")

        # ── Hostile / stop ─────────────────────────────────────────────
        if intent == "hostile":
            self._convs.set_state(conversation_id, "ended")
            self._convs.add_turn(conversation_id, "vera", HOSTILE_EXIT)
            return ReplyResponse(
                action="end",
                body=HOSTILE_EXIT,
                rationale="Hostile message — graceful exit",
            )

        # ── Commitment → action mode ───────────────────────────────────
        if intent == "commitment":
            self._convs.set_state(conversation_id, "action_mode")
            self._convs.add_turn(conversation_id, "vera", ACTION_RESPONSE)
            return ReplyResponse(
                action="send",
                body=ACTION_RESPONSE,
                cta="open_ended",
                rationale="Commitment detected — switching to action mode",
            )

        # ── Off-topic → redirect ───────────────────────────────────────
        if intent == "off_topic":
            self._convs.add_turn(conversation_id, "vera", OFF_TOPIC_REDIRECT)
            return ReplyResponse(
                action="send",
                body=OFF_TOPIC_REDIRECT,
                cta="open_ended",
                rationale="Off-topic — polite redirect",
            )

        # ── Engaged reply — continue conversation ──────────────────────
        body = self._generate_continuation(conversation_id, merchant_id, message, composer)
        self._convs.add_turn(conversation_id, "vera", body)
        return ReplyResponse(
            action="send",
            body=body,
            cta="open_ended",
            rationale="Engaged reply — continuing thread",
        )

    def _generate_continuation(
        self,
        conversation_id: str,
        merchant_id: str,
        message: str,
        composer,
    ) -> str:
        """Generate a contextual continuation response."""
        merchant = self._ctx.get("merchant", merchant_id) or {}
        owner = merchant.get("identity", {}).get("owner_first_name", "")
        conv = self._convs.get(conversation_id) or {}

        # Count turns to avoid dragging on
        turns = conv.get("turns", [])
        if len(turns) >= 8:
            self._convs.set_state(conversation_id, "ended")
            return GRACEFUL_EXIT

        # Simple follow-up with context
        offers = [o.get("title", "") for o in merchant.get("offers", []) if o.get("status") == "active"]
        if offers:
            return (
                f"{'Thanks ' + owner + '! ' if owner else ''}Here's what I can activate for you: "
                f"{offers[0]}. Should I set it live now?"
            )
        return (
            f"{'Thanks ' + owner + '! ' if owner else ''}Let me know what works best and I'll take care of it."
        )

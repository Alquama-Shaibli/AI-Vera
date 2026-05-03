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
    r"i'?m interested", r"karo", r"kar do", r"need help", r"book it",
]

HOSTILE_PATTERNS = [
    r"stop (mess?aging|contact|spam)",
    r"do not (contact|message|call|text)",
    r"spam", r"waste of time", r"not interested",
    r"remove (me|my number)", r"unsubscribe",
    r"band karo", r"mat karo", r"nahin chahiye",
    r"leave me alone", r"block", r"report", r"don'?t text", r"no thanks"
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

GRACEFUL_EXIT = ""  # Hard terminal state - no follow up

HOSTILE_EXIT = ""  # Hard terminal state - no persuasion

AUTO_REPLY_PROBE = (
    "Looks like that may have been an auto-reply. "
    "If you're the owner, I'm here to handle the operational updates discussed. Proceed?"
)

OFF_TOPIC_REDIRECT = (
    "That's outside my operational scope. "
    "I'm here to execute profile and engagement updates. Ready to proceed with the planned update?"
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
            return ReplyResponse(action="end", body="", rationale="Conversation already closed")

        # Set strategy locking on first merchant reply
        if not conv.get("current_strategy"):
            trigger = self._ctx.get("trigger", conv.get("trigger_id", ""))
            kind = trigger.get("kind", "unknown") if trigger else "unknown"
            conv["current_strategy"] = kind

        # Record turn
        self._convs.add_turn(conversation_id, "merchant", message)

        intent = _detect_intent(message)
        logger.info(f"conv={conversation_id} turn={turn_number} intent={intent} strategy={conv.get('current_strategy')}")

        # ── Auto-reply hell ────────────────────────────────────────────
        if intent == "auto_reply":
            count = self._convs.increment_auto_reply(conversation_id)
            if count >= self.MAX_AUTO_REPLIES:
                self._convs.set_state(conversation_id, "ended")
                logger.info(f"Auto-reply limit reached for {conversation_id}")
                return ReplyResponse(
                    action="end",
                    body="",
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

        # ── Hostile / stop (HARD TERMINAL STATE) ────────────────────────
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
            action_body = self._generate_action_mode_response(conv, merchant_id, customer_id)
            self._convs.add_turn(conversation_id, "vera", action_body)
            return ReplyResponse(
                action="send",
                body=action_body,
                cta="none",
                rationale="Commitment detected — operational execution",
            )
            
        # ── Soft decline (Wait) ─────────────────────────────────────────
        if any(x in message.lower() for x in ["next week", "later", "not now", "busy"]):
             self._convs.set_state(conversation_id, "waiting")
             body = "Understood. I will pause this execution for now."
             self._convs.add_turn(conversation_id, "vera", body)
             return ReplyResponse(
                 action="wait",
                 wait_seconds=86400 * 7,
                 body=body,
                 rationale="Soft decline — pausing execution"
             )

        # ── Off-topic → redirect ───────────────────────────────────────
        if intent == "off_topic":
            self._convs.add_turn(conversation_id, "vera", OFF_TOPIC_REDIRECT)
            return ReplyResponse(
                action="send",
                body=OFF_TOPIC_REDIRECT,
                cta="binary_yes_no",
                rationale="Off-topic — operational redirect",
            )

        # ── Engaged reply — continue conversation ──────────────────────
        body = self._generate_continuation(conv, merchant_id, customer_id, message, composer)
        self._convs.add_turn(conversation_id, "vera", body)
        return ReplyResponse(
            action="send",
            body=body,
            cta="open_ended",
            rationale="Engaged reply — continuing locked strategy",
        )
        
    def _generate_action_mode_response(self, conv: dict, merchant_id: str, customer_id: Optional[str]) -> str:
        """Generate an operational task-advancement response, strictly adhering to the strategy."""
        strategy = conv.get("current_strategy", "unknown")
        
        # Operational task-advancement responses
        if strategy == "regulation_change":
            return "I will prepare the compliance checklist and SOP notes first so your staff can review them."
        elif strategy == "supply_alert":
            return "I have flagged the affected stock batches on your profile. Operations team notified."
        elif strategy == "gbp_unverified":
            return "Initiating verification sequence. Look out for the postcard/call from Google shortly."
        elif strategy == "review_theme_emerged":
            return "Drafting a professional public response now. Will execute in 1 hour."
        elif customer_id and strategy in ["recall_due", "trial_followup", "appointment_tomorrow"]:
            return "Done. The slot has been blocked. Clinic confirmation usually goes out shortly."
            
        return "Noted. I am queueing the update for your profile now."

    def _generate_continuation(
        self,
        conv: dict,
        merchant_id: str,
        customer_id: Optional[str],
        message: str,
        composer,
    ) -> str:
        """Generate a contextual continuation response while strictly maintaining the strategy lock."""
        conversation_id = conv["conversation_id"]
        merchant = self._ctx.get("merchant", merchant_id) or {}
        owner = merchant.get("identity", {}).get("owner_first_name", "")
        
        # Count turns to avoid dragging on
        turns = conv.get("turns", [])
        if len(turns) >= 8:
            self._convs.set_state(conversation_id, "ended")
            return GRACEFUL_EXIT

        strategy = conv.get("current_strategy", "unknown")
        
        # Semantic lock enforcement
        if strategy == "regulation_change":
            return "This requires DCI documentation. Shall I list out the required SOP items?"
        elif strategy == "supply_alert":
            return "We need to ensure compliance immediately. Shall I post the stock update?"
        elif strategy == "cde_opportunity":
            return "I can add the schedule to your calendar to secure your CDE credits."
        elif strategy == "perf_dip":
            return "We need to counteract the visibility drop today. Ready to proceed with the profile update?"
        elif strategy == "competitor_opened":
            return "It is critical to maintain impression share. Shall I deploy the targeted response?"
            
        # Fallback operational response
        return "Understood. Should I proceed with the execution?"

"""
Replay State Machine — multi-turn merchant conversations.

Designed to feel like an experienced human account strategist:
- Selective, not chatty
- Contextually aware across turns
- Momentum-based, not repetitive
- Calm authority, not robotic compliance
- Hard exits on hostility, soft pause on hesitation
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
    r"\bspam\b", r"waste of time", r"not interested",
    r"remove (me|my number)", r"unsubscribe",
    r"band karo", r"mat karo", r"nahin chahiye",
    r"leave me alone", r"\bblock\b", r"\breport\b", r"don'?t text", r"no thanks",
]

HESITATION_PATTERNS = [
    r"next week", r"later", r"not now", r"\bbusy\b",
    r"thoda baad", r"abhi nahi", r"let me check",
    r"will think", r"sochna padega", r"maybe", r"not sure",
    r"let me talk", r"discuss with",
]

OFF_TOPIC_PATTERNS = [
    r"weather", r"cricket score", r"ipl score",
    r"loan", r"insurance", r"\bjob\b",
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

    # Check hesitation before commitment — "maybe not now" should be hesitation
    for pat in HESITATION_PATTERNS:
        if re.search(pat, msg, re.IGNORECASE):
            return "hesitation"

    for pat in COMMITMENT_PATTERNS:
        if re.search(pat, msg, re.IGNORECASE):
            return "commitment"

    for pat in OFF_TOPIC_PATTERNS:
        if re.search(pat, msg, re.IGNORECASE):
            return "off_topic"

    if "?" in msg or len(msg.split()) > 5:
        return "engaged"

    return "neutral"


# ── Helper: operator-tone merchant greeting ────────────────────────────

def _first_name(merchant: dict) -> str:
    return merchant.get("identity", {}).get("owner_first_name", "")


def _locality(merchant: dict) -> str:
    return merchant.get("identity", {}).get("locality", "")


def _category_slug(merchant: dict) -> str:
    return merchant.get("category_slug", "")


class ReplayStateMachine:
    """Manages multi-turn conversation flow for merchant replies."""

    MAX_AUTO_REPLIES = 2

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

        # Already ended — hard wall
        if self._convs.is_ended(conversation_id):
            return ReplyResponse(action="end", body="", rationale="Conversation already closed")

        # Lock strategy on first merchant reply
        if not conv.get("current_strategy"):
            trigger = self._ctx.get("trigger", conv.get("trigger_id", ""))
            kind = trigger.get("kind", "unknown") if trigger else "unknown"
            conv["current_strategy"] = kind

        # Record turn
        self._convs.add_turn(conversation_id, "merchant", message)

        intent = _detect_intent(message)
        merchant = self._ctx.get("merchant", merchant_id) or {}
        logger.info(
            f"conv={conversation_id} turn={turn_number} intent={intent} "
            f"strategy={conv.get('current_strategy')}"
        )

        # ── Auto-reply ─────────────────────────────────────────────────
        if intent == "auto_reply":
            count = self._convs.increment_auto_reply(conversation_id)
            if count >= self.MAX_AUTO_REPLIES:
                self._convs.set_state(conversation_id, "ended")
                return ReplyResponse(
                    action="end",
                    body="",
                    rationale=f"Auto-reply limit ({count}) reached — ending",
                )
            # Probe once — natural, not corporate
            name = _first_name(merchant)
            body = (
                f"Looks like that went to an auto-reply{f', {name}' if name else ''}. "
                f"If you're available, I had a quick update on your profile — worth 2 minutes?"
            )
            self._convs.add_turn(conversation_id, "vera", body)
            return ReplyResponse(
                action="send",
                body=body,
                cta="binary_yes_no",
                rationale="Auto-reply — probing once",
            )

        # ── Hostile / stop — HARD TERMINAL, empty body ─────────────────
        if intent == "hostile":
            self._convs.set_state(conversation_id, "ended")
            return ReplyResponse(action="end", body="", rationale="Hostile — hard exit")

        # ── Hesitation — read timing, reduce pressure ───────────────────
        if intent == "hesitation":
            body = self._generate_hesitation_response(conv, merchant, message)
            self._convs.set_state(conversation_id, "waiting")
            self._convs.add_turn(conversation_id, "vera", body)
            return ReplyResponse(
                action="wait",
                wait_seconds=86400 * 3,
                body=body,
                rationale="Hesitation — reducing pressure, noting timing",
            )

        # ── Commitment → operational execution ─────────────────────────
        if intent == "commitment":
            self._convs.set_state(conversation_id, "action_mode")
            body = self._generate_action_mode_response(conv, merchant, customer_id)
            self._convs.add_turn(conversation_id, "vera", body)
            return ReplyResponse(
                action="send",
                body=body,
                cta="none",
                rationale="Commitment — operational execution",
            )

        # ── Off-topic — minimal redirect, not preachy ──────────────────
        if intent == "off_topic":
            name = _first_name(merchant)
            body = (
                f"That's outside what I track{f', {name}' if name else ''}. "
                f"Picking up where we left off — want me to move forward?"
            )
            self._convs.add_turn(conversation_id, "vera", body)
            return ReplyResponse(
                action="send",
                body=body,
                cta="binary_yes_no",
                rationale="Off-topic — minimal redirect",
            )

        # ── Engaged — contextual continuation ──────────────────────────
        body = self._generate_continuation(conv, merchant, customer_id, message)
        self._convs.add_turn(conversation_id, "vera", body)
        return ReplyResponse(
            action="send",
            body=body,
            cta="open_ended",
            rationale="Engaged — continuing with strategy context",
        )

    # ── Hesitation response ────────────────────────────────────────────

    def _generate_hesitation_response(
        self, conv: dict, merchant: dict, message: str
    ) -> str:
        """
        Interpret the hesitation and acknowledge it with timing intelligence.
        Reduces pressure without abandoning the opportunity.
        """
        strategy = conv.get("current_strategy", "")
        name = _first_name(merchant)
        slug = _category_slug(merchant)
        msg_lower = message.lower()

        name_prefix = f"{name}, " if name else ""

        # Detect timing cue
        if "next week" in msg_lower:
            when = "next week"
        elif "busy" in msg_lower:
            when = "later this week"
        elif "later" in msg_lower or "baad" in msg_lower:
            when = "when it's a better time"
        else:
            when = "when you're ready"

        # Strategy-aware timing context
        time_notes = {
            "festival_upcoming": f"Worth keeping in mind — the window closes about 2 days before the festival.",
            "perf_dip": f"I'll hold it for now. The profile will keep running at current settings.",
            "renewal_due": f"Your subscription is still active — I'll check in before the expiry date.",
            "competitor_opened": f"Noted. I'll monitor the local picture and flag anything material.",
            "review_theme_emerged": f"Your ratings are stable for now — no urgency here.",
            "supply_alert": f"The compliance notice is still relevant — I'll flag when it gets closer to deadline.",
        }
        context_note = time_notes.get(strategy, "")

        body = (
            f"{name_prefix}Understood — I'll hold this until {when}. "
            f"{context_note}".strip()
        )
        return body.rstrip()

    # ── Action mode: operational execution response ────────────────────

    def _generate_action_mode_response(
        self, conv: dict, merchant: dict, customer_id: Optional[str]
    ) -> str:
        """
        Respond to a commitment with a natural, operational next step.
        Feels like a strategist confirming they've picked up the task.
        NOT robotic, NOT corporate IT language.
        """
        strategy = conv.get("current_strategy", "unknown")
        name = _first_name(merchant)
        loc = _locality(merchant)
        slug = _category_slug(merchant)

        loc_str = f" in {loc}" if loc else ""

        responses = {
            "regulation_change": (
                f"On it. I'll compile the key protocol points and a staff notice — "
                f"should be ready before clinic hours tomorrow."
            ),
            "supply_alert": (
                f"Flagging the affected batches now. "
                f"I'll also update your profile status so customers{loc_str} see the advisory."
            ),
            "gbp_unverified": (
                f"Starting the verification steps. "
                f"You'll likely get a call or postcard from Google within a few days — "
                f"keep an eye out for it."
            ),
            "review_theme_emerged": (
                f"I'll draft the response based on your usual tone. "
                f"Worth a quick read before it goes live."
            ),
            "perf_dip": (
                f"Updating your listing timing and offer priority now. "
                f"Should start showing in local results by this evening."
            ),
            "competitor_opened": (
                f"Adjusting your positioning and refreshing the offer. "
                f"I'll track how it affects your local search rank this week."
            ),
            "milestone_reached": (
                f"Queuing the post now — evening tends to get the most engagement{loc_str}. "
                f"I'll let you know once it's live."
            ),
            "festival_upcoming": (
                f"Locking in the offer before the search traffic picks up. "
                f"I'll update the listing tonight."
            ),
            "renewal_due": (
                f"Sending the renewal link now. "
                f"Your current visibility settings stay intact through the transition."
            ),
            "winback_eligible": (
                f"Building the customer list now. "
                f"I'll keep the message short and personalised — should go out this evening."
            ),
        }

        # Customer-context strategies (appointment, recall, etc.)
        if customer_id and strategy in ["recall_due", "trial_followup", "appointment_tomorrow"]:
            if slug == "dentists":
                return "Slot confirmed. I'll send the appointment reminder an hour before."
            elif slug == "gyms":
                return "Session noted. I'll send the confirmation now."
            else:
                return "Confirmed. I'll send the booking details shortly."

        body = responses.get(strategy, f"Moving on it now. I'll update you once it's done.")
        return body

    # ── Engaged continuation: momentum-based, not repetitive ──────────

    def _generate_continuation(
        self,
        conv: dict,
        merchant: dict,
        customer_id: Optional[str],
        message: str,
    ) -> str:
        """
        Continue the conversation naturally.
        - Reads actual turns for momentum
        - References merchant context
        - Avoids repeating previous questions or CTAs
        - Knows when to wrap up
        """
        conversation_id = conv["conversation_id"]
        turns = conv.get("turns", [])
        strategy = conv.get("current_strategy", "unknown")
        name = _first_name(merchant)
        slug = _category_slug(merchant)
        loc = _locality(merchant)

        # Hard exit if conversation running long
        if len(turns) >= 8:
            self._convs.set_state(conversation_id, "ended")
            return ""

        loc_str = f" in {loc}" if loc else ""
        name_prefix = f"{name}, " if name else ""

        # Check what the merchant said — look for questions or context
        msg_lower = message.lower()
        vera_turns = [t["body"] for t in turns if t["role"] == "vera"]
        last_vera = vera_turns[-1] if vera_turns else ""

        # Detect if merchant is asking about pricing
        if any(w in msg_lower for w in ["price", "cost", "kitna", "how much", "charge", "fee"]):
            if slug == "dentists":
                return (
                    f"{name_prefix}Pricing for most recall and cleaning packages is visible on your profile. "
                    f"Want me to review the listed rates to make sure they reflect current clinic pricing?"
                )
            elif slug == "gyms":
                return (
                    f"{name_prefix}Your membership tiers are on the profile. "
                    f"Worth checking if the trial pricing is still competitive with nearby studios."
                )
            else:
                return (
                    f"{name_prefix}Your current listed pricing should be visible to nearby customers. "
                    f"Want me to check it's up to date?"
                )

        # Detect if merchant is asking about timing
        if any(w in msg_lower for w in ["when", "kab", "how long", "kitne din", "timeline"]):
            timing_map = {
                "festival_upcoming": "Typically takes about an hour to show in local search — worth doing it today.",
                "perf_dip": "Profile updates usually reflect within a few hours. Evening is the best window.",
                "renewal_due": "Renewal links go through immediately — no delay in visibility.",
                "gbp_unverified": "Google verification usually takes 5-7 days depending on the method.",
            }
            return timing_map.get(
                strategy,
                f"{name_prefix}Updates typically show in local search within a few hours. "
                f"Best to go live before evening traffic picks up{loc_str}."
            )

        # Strategy-specific contextual continuations
        continuations = {
            "regulation_change": (
                f"{name_prefix}The key item is updating your SOP before the deadline. "
                f"Do you have staff who handle the documentation side, or should I keep it simple?"
            ),
            "supply_alert": (
                f"{name_prefix}The main thing is the customer-facing notice — "
                f"that protects you if anyone asks. Ready to go?"
            ),
            "perf_dip": (
                f"{name_prefix}The visibility gap is mainly in peak-hour local search{loc_str}. "
                f"Fixing the listing timing and reactivating one offer should close most of it."
            ),
            "competitor_opened": (
                f"{name_prefix}The fastest counter is usually a refreshed offer and a post this week. "
                f"Anything you'd want to lead with?"
            ),
            "review_theme_emerged": (
                f"{name_prefix}The pattern in the reviews suggests customers want faster follow-up. "
                f"A short response addressing that typically shifts the perception."
            ),
            "milestone_reached": (
                f"{name_prefix}A post now will catch the evening browsing window{loc_str}. "
                f"Want me to keep the caption short, or include a current offer?"
            ),
            "gbp_unverified": (
                f"{name_prefix}The quickest route is usually the postcard — takes about 5 days. "
                f"Want me to walk you through the steps right now?"
            ),
            "festival_upcoming": (
                f"{name_prefix}The search spike usually starts 2-3 days before. "
                f"What service or deal makes most sense to lead with this time?"
            ),
        }

        body = continuations.get(
            strategy,
            f"{name_prefix}Happy to take the next step — what would be most useful right now?"
        )
        return body

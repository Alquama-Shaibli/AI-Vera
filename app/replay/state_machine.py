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
    r"^\s*stop\s*$",              # bare word STOP
    r"stop (mess?aging|contact|spam|send)",
    r"do not (contact|message|call|text)",
    r"don'?t (message|text|contact|call|send)",
    r"\bspam\b", r"waste of time", r"not interested",
    r"remove (me|my number)", r"unsubscribe",
    r"band karo", r"mat karo", r"nahin chahiye",
    r"leave me alone", r"\bblock\b", r"\breport\b", r"no thanks",
]

HESITATION_PATTERNS = [
    r"next week", r"later", r"not now", r"\bbusy\b",
    r"thoda baad", r"abhi nahi", r"let me check",
    r"will think", r"sochna padega", r"maybe", r"not sure",
    r"let me talk", r"discuss with",
    r"after diwali", r"after holi", r"after eid", r"after the weekend",
    r"after the match", r"next month", r"give me (a|some) time",
]

OFF_TOPIC_PATTERNS = [
    r"weather", r"cricket score", r"ipl score",
    r"loan", r"insurance", r"\bjob\b",
    r"who are you", r"aap kaun",
]


SKEPTICAL_PATTERNS = [r"does.*work", r"really help", r"fake", r"bots", r"not real", r"magic", r"kaam karega", r"serious?", r"pakka?"]
PRICING_PATTERNS = [r"cost", r"price", r"how much", r"expensive", r"₹", r"rupees", r"paisa", r"kharcha", r"rate", r"charge"]
TRUST_CHECK_PATTERNS = [r"who are you", r"how.*know", r"from magicpin", r"official", r"kahan se", r"address", r"identity", r"proof"]
ROI_QUESTION_PATTERNS = [r"roi", r"return", r"how many calls", r"guarantee", r"worth it", r"faida", r"profit", r"benefit"]
ALREADY_TRIED_PATTERNS = [r"already tried", r"did.*before", r"tried that", r"didn't work", r"pehle kiya", r"not useful"]
COMPARISON_PATTERNS = [r"competitor", r"others", r"better than", r"instead of", r"comparison", r"justdial", r"practo"]
TIMING_QUESTION_PATTERNS = [r"when", r"how long", r"timing", r"how much time", r"kab tak", r"shuru", r"delay"]
BUSY_PATTERNS = [r"busy", r"meeting", r"clinic full", r"rush", r"later", r"call back", r"driving", r"busy now"]
UNCERTAIN_PATTERNS = [r"maybe", r"not sure", r"will see", r"don'?t know", r"thinking", r"not decided"]
SOFT_DECLINE_PATTERNS = [r"not interested now", r"maybe later", r"next time", r"not today", r"don'?t need it"]
DETAIL_REQUEST_PATTERNS = [r"more details", r"send info", r"explain", r"details please", r"batao", r"samjhao"]

def _detect_intent(message: str) -> str:
    """Classify a merchant message into an intent category."""
    msg = message.lower().strip()

    for pat in AUTO_REPLY_PATTERNS:
        if re.search(pat, msg, re.IGNORECASE):
            return "auto_reply"

    for pat in HOSTILE_PATTERNS:
        if re.search(pat, msg, re.IGNORECASE):
            return "hostile"

    # Check for specific objections/intents (Phase 1)
    if any(re.search(p, msg, re.IGNORECASE) for p in PRICING_PATTERNS): return "pricing"
    if any(re.search(p, msg, re.IGNORECASE) for p in SKEPTICAL_PATTERNS): return "skeptical"
    if any(re.search(p, msg, re.IGNORECASE) for p in TRUST_CHECK_PATTERNS): return "trust_check"
    if any(re.search(p, msg, re.IGNORECASE) for p in ROI_QUESTION_PATTERNS): return "roi_question"
    if any(re.search(p, msg, re.IGNORECASE) for p in ALREADY_TRIED_PATTERNS): return "already_tried"
    if any(re.search(p, msg, re.IGNORECASE) for p in COMPARISON_PATTERNS): return "comparison"
    if any(re.search(p, msg, re.IGNORECASE) for p in TIMING_QUESTION_PATTERNS): return "timing_question"
    if any(re.search(p, msg, re.IGNORECASE) for p in BUSY_PATTERNS): return "busy"
    if any(re.search(p, msg, re.IGNORECASE) for p in UNCERTAIN_PATTERNS): return "uncertain"
    if any(re.search(p, msg, re.IGNORECASE) for p in SOFT_DECLINE_PATTERNS): return "soft_decline"
    if any(re.search(p, msg, re.IGNORECASE) for p in DETAIL_REQUEST_PATTERNS): return "detail_request"

    # Check hesitation before commitment
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
                f"If you're available later, I had a quick update on your profile — worth 2 minutes?"
            )
            self._convs.add_turn(conversation_id, "vera", body)
            return ReplyResponse(
                action="send",
                body=body,
                cta="binary_yes_no",
                rationale="Auto-reply — probing once",
            )

        # ── Strategic Silence (Phase 7) ─────────────────────────────────
        if intent in ("busy", "soft_decline"):
            self._convs.set_state(conversation_id, "waiting")
            return ReplyResponse(
                action="wait",
                wait_seconds=86400 * 3,
                body="",
                rationale=f"Strategic silence ({intent}) — merchant busy or soft decline",
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

        # ── Commitment → operational execution (Phase 4) ───────────────
        if intent == "commitment":
            self._convs.set_state(conversation_id, "action_mode")
            body = self._generate_action_mode_response(conv, merchant, customer_id, message)
            self._convs.add_turn(conversation_id, "vera", body)
            return ReplyResponse(
                action="send",
                body=body,
                cta="none",
                rationale="Commitment — operational execution",
            )

        # ── Engaged / Objections / Questions (Phase 1 & 5) ────────────
        body = self._generate_continuation(conv, merchant, customer_id, message)
        self._convs.add_turn(conversation_id, "vera", body)
        return ReplyResponse(
            action="send",
            body=body,
            cta="binary_yes_no" if "?" in body else "open_ended",
            rationale=f"Engaged ({intent}) — human continuation",
        )

        # ── Off-topic — minimal redirect, not preachy ──────────────────
        if intent == "off_topic":
            name = _first_name(merchant)
            body = (
                f"That's outside what I track{f', {name}' if name else ''}. "
                f"Picking up where we were — ready to start?"
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
        self,
        conv: dict,
        merchant: dict,
        customer_id: Optional[str],
        message: str = "",
    ) -> str:
        """
        Calm, operational confirmation of an action.
        - Strategy-aware
        - Locality-aware
        - Human operator voice
        """
        strategy = conv.get("current_strategy", "unknown")
        name = _first_name(merchant)
        slug = _category_slug(merchant)
        loc = _locality(merchant)
        n = f"{name}, " if name else ""
        loc_str = f" around {loc}" if loc else ""
        person = {"dentists": "patients", "gyms": "members",
                  "pharmacies": "customers", "salons": "clients"}.get(slug, "customers")

        ACTION_MODE_MAP = {
            "gbp_unverified": (
                f"{n}first thing is getting the postcard request in. "
                f"Google usually delivers it in 3–5 days{loc_str}."
            ),
            "regulation_change": (
                f"{n}the key thing is documenting the setup before the deadline. "
                f"Most {slug} keep this inside their SOP records."
            ),
            "recall_due": (
                f"{n}I'll send the recall reminders this evening when open rates are usually higher."
            ),
            "perf_dip": (
                f"{n}I'll refresh the listing photos and reactivate the offer now. "
                f"Visibility usually recovers by tomorrow morning."
            ),
            "competitor_opened": (
                f"{n}I'll have the fresh post and offer live today. "
                f"Stops {person} from comparing you with the new place too much."
            ),
            "review_theme_emerged": (
                f"{n}I'll have a short, direct response to the recent reviews ready shortly. "
                f"Better to address the feedback publicly than ignore it."
            ),
            "milestone_reached": (
                f"{n}I'll have the milestone post ready shortly. "
                f"It'll mention the achievement naturally without looking like an ad."
            ),
            "festival_upcoming": (
                f"{n}I'll have the festive update live today. Search traffic starts spiking 2 days before."
            ),
            "research_digest": (
                f"{n}I'll draft the brief takeaway to share. "
                f"Usually 3-4 sentences is enough to build trust."
            ),
            "winback_eligible": (
                f"{n}I'll build the list and keep the message short. "
                f"Personalised notes land better than formal ones."
            ),
            "cde_opportunity": (
                f"{n}I'll pull the registration link and add the details to your notes."
            ),
            "supply_alert": (
                f"{n}I'll have a short notice for your profile ready to keep you covered."
            ),
        }

        # Customer-scoped recalls and bookings
        if customer_id and strategy in ["recall_due", "trial_followup", "appointment_tomorrow"]:
            if slug == "dentists":
                return f"{n}slot confirmed. I'll send the reminder the morning of the appointment."
            elif slug == "gyms":
                return f"{n}session logged. Confirmation will go out shortly."
            else:
                return f"{n}noted. Booking details going out now."

        return ACTION_MODE_MAP.get(
            strategy,
            f"{n}I'll have the first update ready before the evening rush."
        )

    # ── Engaged continuation: momentum-based, not repetitive ──────────

    def _generate_continuation(
        self,
        conv: dict,
        merchant: dict,
        customer_id: Optional[str],
        message: str,
    ) -> str:
        """
        Continue the conversation like an experienced growth manager:
        - Answers merchant questions directly, no redirection
        - Maintains strategy topic continuity
        - Uses business intuition, not meta-questions
        - Knows when to wrap up cleanly
        """
        conversation_id = conv["conversation_id"]
        turns = conv.get("turns", [])
        strategy = conv.get("current_strategy", "unknown")
        name = _first_name(merchant)
        slug = _category_slug(merchant)
        loc = _locality(merchant)

        # Hard exit if conversation running long (Phase 8)
        if len(turns) >= 8:
            self._convs.set_state(conversation_id, "ended")
            return ""

        n = f"{name}, " if name else ""
        loc_str = f" in {loc}" if loc else ""
        msg_lower = message.lower()
        person = {"dentists": "patients", "gyms": "members",
                  "pharmacies": "customers", "salons": "clients"}.get(slug, "customers")

        # ── Question-answering mode: answer directly, never redirect (Phase 5) ──

        # Trust check / Who are you
        if any(re.search(p, msg_lower) for p in TRUST_CHECK_PATTERNS):
             return f"{n}I'm handling the profile growth side for the business. The data I'm seeing{loc_str} suggests we're missing some calls, so I'm just here to tighten up the listing."

        # Skeptical
        if any(re.search(p, msg_lower) for p in SKEPTICAL_PATTERNS):
             return f"{n}usually the fastest lift comes from fixing the listing first. Most businesses see calls recover before ads even matter."

        # Already tried
        if any(re.search(p, msg_lower) for p in ALREADY_TRIED_PATTERNS):
             return f"{n}fair enough. Usually when it doesn't work, it's a timing issue — like running the offer when search traffic is low. This week looks much stronger{loc_str}."

        # Comparison
        if any(re.search(p, msg_lower) for p in COMPARISON_PATTERNS):
             return f"{n}we focus more on the local conversion than just visibility. Most systems just blast traffic; we're trying to get people to actually call or visit."

        # ROI / Worth it
        if any(re.search(p, msg_lower) for p in ROI_QUESTION_PATTERNS):
            cat_roi = {
                "dentists": f"{n}for clinics, the biggest impact comes from recall consistency and real photos. {person.capitalize()} trust what they see before they book.",
                "gyms": f"{n}for gyms, trial conversion is the gap. A clear offer and fast response to enquiries moves the needle most.",
                "restaurants": f"{n}visibility at 6-7pm when people are deciding where to eat is worth a lot. Timing matters more than the discount."
            }
            return cat_roi.get(slug, f"{n}the impact is usually visible within a week. The key is catching the traffic while the search window is open.")

        # Post / content questions
        if any(w in msg_lower for w in ["what kind of post", "which post", "what post", "post work", "content"]):
            cat_posts = {
                "dentists": f"{n}Tuesday evenings work well for before/after cases. {person.capitalize()} browse after work and compare nearby options.",
                "salons": f"{n}Transformation posts and look previews get the most saves. Pair it with an offer and it drives DMs.",
                "restaurants": f"{n}Evening posts at 6-7pm work best. A dish photo with the best-seller price outperforms any promo copy.",
                "gyms": f"{n}Member transformations and workout tips get the best reach. \"30 days later\" style converts trial enquiries best.",
            }
            return cat_posts.get(slug, f"{n}Evening posts around 6-7pm usually get the most reach. Keep it practical and simple.")

        # Pricing questions
        if any(re.search(p, msg_lower) for p in PRICING_PATTERNS):
            return f"{n}your current listed pricing is what {person} see when comparing you{loc_str}. Worth making sure it's accurate for your best-value services."

        # Timing questions
        if any(re.search(p, msg_lower) for p in TIMING_QUESTION_PATTERNS):
            timing_map = {
                "festival_upcoming": f"{n}search traffic picks up 2-3 days before the festival. Worth getting this live today.",
                "perf_dip": f"{n}listing updates usually reflect within a few hours. Evening is the best window to go live.",
                "gbp_unverified": f"{n}Google verification takes 3-5 days for the postcard, then 2 minutes to enter the code.",
            }
            return timing_map.get(strategy, f"{n}updates show in local search within a few hours. Best to go live before the evening traffic picks up.")

        # Plan / Next steps
        if any(w in msg_lower for w in ["what should we do", "what is the plan", "whats the plan", "what next", "how to start"]):
            return f"{n}the first step is usually refreshing the profile content and the active offer. That gets the fastest visibility boost{loc_str}."

        # Detail request
        if any(re.search(p, msg_lower) for p in DETAIL_REQUEST_PATTERNS):
            return f"{n}I'll send over the brief outline. It covers the 2-3 things that'll have the biggest impact on your calls this week."

        # ── Strategy-specific continuations (no Q detected) ────────────
        STRATEGY_CONTINUATIONS = {
            "regulation_change": f"{n}the SOP and consent form updates are what matter most. I'll pull the checklist so your team can get started.",
            "supply_alert": f"{n}the customer-facing part is usually a short note on the shelf. I'll have that draft ready shortly.",
            "perf_dip": f"{n}the visibility gap is mostly in evening search. Refreshing the listing photos usually closes most of it.",
            "competitor_opened": f"{n}the fastest way to hold your position is a fresh post and a visible offer this week.",
            "review_theme_emerged": f"{n}a direct public response to the recent reviews shifts the perception quickly. I'll have that ready shortly.",
            "milestone_reached": f"{n}a post around the milestone tends to get good organic reach{loc_str}. I'll have it ready shortly.",
            "gbp_unverified": f"{n}verified profiles get surfaced much more in map results. The postcard route is the most reliable.",
            "festival_upcoming": f"{n}the search window before a festival is usually 2-3 days. Better to get the occasion-specific offer live today.",
            "research_digest": f"{n}sharing a brief takeaway from the study builds trust. Usually 3-4 sentences is enough.",
            "winback_eligible": f"{n}lapsed {person} respond better to a personalised check-in than a promotion. I'll build the list now.",
            "renewal_due": f"{n}the main thing is not to let the profile go inactive mid-month — it takes a few days to recover visibility.",
            "ipl_match_today": f"{n}match nights are a high-volume window{loc_str}. An offer live by 5pm covers the peak perfectly.",
            "cde_opportunity": f"{n}professional credits aside, these sessions help with protocol updates. Worth blocking the time.",
            "active_planning_intent": f"{n}the outline I've drafted focuses on the services that {person} are searching for most right now.",
        }

        return STRATEGY_CONTINUATIONS.get(
            strategy,
            f"{n}what's the most pressing thing on your end right now? I'll focus there first."
        )

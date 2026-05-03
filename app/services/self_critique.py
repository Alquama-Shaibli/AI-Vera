"""
Judge-Aware Self-Critique Pass — v3.0 (Human Realism Edition).

Scores the output on 6 dimensions including human realism.
The core question: "Would a real merchant account manager send this?"
"""
from __future__ import annotations
import re
from typing import Optional


# ── Dimension scorers (0-10 each) ─────────────────────────────────────

def _score_specificity(body: str, merchant: dict, trigger: dict, category: dict) -> float:
    score = 3.0
    perf = merchant.get("performance", {})
    if str(perf.get("views", "")) in body:
        score += 1.5
    if str(perf.get("calls", "")) in body:
        score += 1.0
    if re.search(r"\d+[\.,]\d*%", body):
        score += 1.0
    if re.search(r"₹[\d,]+", body):
        score += 1.0
    loc = merchant.get("identity", {}).get("locality", "")
    if loc and loc in body:
        score += 1.0
    if re.search(r"\d+ (reviews|days|km|calls|views|members|enquiries)", body, re.I):
        score += 0.5
    return min(10.0, score)


def _score_category_fit(body: str, category: dict) -> float:
    slug = category.get("slug", "")
    taboo = category.get("voice", {}).get("vocab_taboo", [])
    score = 7.0
    body_low = body.lower()
    for t in taboo:
        if t.lower() in body_low:
            score -= 2.0
    good_words = {
        "dentists":   ["recall", "clinic", "patients", "DCI", "IDA", "treatment", "scaling"],
        "salons":     ["booking", "salon", "bridal", "festival", "service", "session"],
        "restaurants":["menu", "delivery", "covers", "match", "traffic", "footfall"],
        "gyms":       ["members", "trial", "membership", "session", "coach", "enquiries"],
        "pharmacies": ["refill", "stock", "compliance", "molecule", "supply", "advisory"],
    }
    for w in good_words.get(slug, []):
        if w.lower() in body_low:
            score = min(10.0, score + 0.3)
    return min(10.0, score)


def _score_merchant_fit(body: str, merchant: dict) -> float:
    score = 5.0
    owner = merchant.get("identity", {}).get("owner_first_name", "")
    biz = merchant.get("identity", {}).get("name", "")
    if owner and owner in body:
        score += 2.0
    if biz and biz in body:
        score += 1.0
    offers = [o.get("title", "") for o in merchant.get("offers", []) if o.get("status") == "active"]
    for off in offers:
        if off and off in body:
            score += 1.5
    return min(10.0, score)


def _score_trigger_relevance(body: str, trigger: dict) -> float:
    kind = trigger.get("kind", "")
    payload = trigger.get("payload", {})
    score = 5.0
    for v in payload.values():
        if isinstance(v, str) and len(v) > 3 and v in body:
            score = min(10.0, score + 1.0)
        elif isinstance(v, int) and v > 0 and str(v) in body:
            score = min(10.0, score + 0.5)
    kind_keywords = {
        "perf_dip":          ["dip", "down", "drop", "CTR", "listing", "fixes", "slowed"],
        "perf_spike":        ["up", "spike", "calls", "window", "traffic"],
        "recall_due":        ["recall", "due", "slot", "appointment"],
        "competitor_opened": ["listed", "google", "nearby", "refreshed"],
        "festival_upcoming": ["days out", "festival", "traffic", "search"],
        "supply_alert":      ["advisory", "stock", "batches", "notice"],
        "regulation_change": ["guidelines", "deadline", "checklist", "staff"],
        "renewal_due":       ["renew", "plan", "days", "visibility"],
        "research_digest":   ["study", "research", "patients", "findings"],
        "milestone_reached": ["reviews", "milestone", "crossed", "peers"],
        "winback_eligible":  ["lapsed", "bringing back", "drifted", "personalised"],
        "gbp_unverified":   ["verified", "Google", "postcard", "verification"],
        "ipl_match_today":  ["match", "IPL", "delivery", "night"],
        "category_seasonal": ["seasonal", "demand", "shifting", "surge"],
        "active_planning_intent": ["outline", "idea", "package", "look"],
        "wedding_package_followup": ["wedding", "💐", "lock in", "schedule"],
    }
    for kw in kind_keywords.get(kind, []):
        if kw.lower() in body.lower():
            score = min(10.0, score + 0.4)
    return min(10.0, score)


def _score_engagement(body: str, cta: str) -> float:
    score = 5.0
    body_low = body.lower()

    # Penalize multi-question / over-persuasion
    q_count = body_low.count("?")
    if q_count > 1:
        score -= 1.5

    # Penalize AI-speak and bot energy (Phase 1)
    ai_phrases = [
        "operational alert", "authorize", "execute protocol", "initiating",
        "deploy immediately", "operational block", "impression share",
        "bleeding traffic", "execute the", "operational scope",
        "queueing the update", "i have compiled", "implementation sequence",
        "workflow update", "strategic deployment", "algorithmic boost",
    ]
    for phrase in ai_phrases:
        if phrase in body_low:
            score -= 1.0

    # Reward natural timing and business-grounded language
    human_hooks = [
        "tonight", "this week", "this evening", "before the", "worth doing",
        "typically", "usually", "good window", "keeps you visible", "hold the momentum",
        "worth a try", "2-3 days", "a few hours", "move on it", "around",
    ]
    for h in human_hooks:
        if h in body_low:
            score = min(10.0, score + 0.6)

    # Length check — WhatsApp sweet spot 60-240 chars
    n = len(body)
    if 60 <= n <= 240:
        score = min(10.0, score + 1.0)
    elif n > 320:
        score -= 1.0
    return min(10.0, score)


def _score_human_realism(body: str, merchant: dict, category: dict) -> float:
    """
    Core question: 'Would a real WhatsApp account manager send this?'
    Rewards: natural language, timing awareness, local grounding.
    Penalizes: corporate-speak, AI-style phrasing, generic urgency.
    """
    score = 5.0
    body_low = body.lower()

    # Penalize robot / IT / corporate language (Search & Destroy List)
    robot_phrases = [
        "execute", "deploy", "authorize", "protocol", "operational",
        "implementation", "compliance checklist", "mandate", "procedure",
        "queueing", "flagging", "initiating", "activated", "sequence",
        "workflow", "process flow", "action sequence", "deployment",
        "anomaly", "momentum optimization", "campaign execution",
        "automated", "system generated", "processing",
    ]
    for rp in robot_phrases:
        if rp in body_low:
            score -= 1.0

    # Penalize AI-assistant energy
    ai_energy = [
        "happy to help", "let me know", "anything else", "feel free",
        "i can assist", "great choice", "sounds good", "glad to",
        "absolutely", "no worries", "of course", "want me to",
    ]
    for ae in ai_energy:
        if ae in body_low:
            score -= 1.5

    # Reward human account-manager signals
    human_signals = [
        "heads up", "quick check", "worth", "typically", "usually",
        "good window", "move on it", "keep an eye", "a few", "this week",
        "should get you", "tracking well", "people are checking",
        "shift", "around", "looks like", "worth doing",
    ]
    for hs in human_signals:
        if hs in body_low:
            score = min(10.0, score + 0.7)

    # Reward owner name usage (personal = human)
    owner = merchant.get("identity", {}).get("owner_first_name", "")
    if owner and owner in body:
        score = min(10.0, score + 1.5)

    # Reward local specificity
    loc = merchant.get("identity", {}).get("locality", "")
    if loc and loc in body:
        score = min(10.0, score + 1.0)

    return max(0.0, min(10.0, score))


# ── Public utility: human-realism gate ────────────────────────────────

def sounds_like_real_whatsapp_manager(message: str) -> bool:
    """
    Binary gate: returns True if the message reads like it was sent by
    a real WhatsApp-based merchant growth manager, not an AI or CRM tool.
    """
    body_low = message.lower()

    # Hard fail: robot language present (Search & Destroy List)
    robot_hard_fails = [
        "operational alert", "execute the protocol", "authorize deployment",
        "initiating verification", "bleeding traffic", "deployment sequence",
        "compliance enforcement", "workflow execution", "action sequence",
        "queueing the update", "i have compiled the sop", "automated message",
        "system generated", "implement setup", "momentum optimization",
        "campaign execution", "ready to proceed", "visibility decay",
    ]
    for rf in robot_hard_fails:
        if rf in body_low:
            return False

    # Soft fail: too many questions (multi-CTA)
    if body_low.count("?") > 1:
        return False

    # Soft fail: too long for WhatsApp
    if len(message) > 350:
        return False

    # Soft fail: AI-assistant opener
    ai_openers = [
        "happy to help", "let me know", "feel free to", "i can assist",
        "want me to", "would you like", "shall i",
    ]
    for ao in ai_openers:
        if body_low.startswith(ao) or f". {ao}" in body_low:
            return False

    # Must have at least one human signal
    human_signals = [
        "usually", "typically", "tends to", "tends", "this week",
        "tonight", "this evening", "before", "after", "a few days",
        "people", "patients", "members", "clients", "customers",
        "nearby", "local", "compare", "browse", "decide",
        "heads up", "worth", "check back", "around",
    ]
    has_human_signal = any(hs in body_low for hs in human_signals)

    return has_human_signal


# ── Main critique function ─────────────────────────────────────────────

THRESHOLD = 33.0   # out of 60 (6 dimensions × 10)
DIMENSION_WEIGHTS = {
    "specificity": 10, "category_fit": 10, "merchant_fit": 10,
    "trigger_relevance": 10, "engagement": 10, "human_realism": 10,
}


def critique(
    composed: dict,
    category: dict,
    merchant: dict,
    trigger: dict,
    customer: Optional[dict] = None,
) -> dict:
    """
    Score the composed message on 6 dimensions.
    Returns augmented dict with predicted_score.
    If score < THRESHOLD, sets 'rejected': True.
    """
    body = composed.get("body", "")
    cta = composed.get("cta", "open_ended")

    s1 = _score_specificity(body, merchant, trigger, category)
    s2 = _score_category_fit(body, category)
    s3 = _score_merchant_fit(body, merchant)
    s4 = _score_trigger_relevance(body, trigger)
    s5 = _score_engagement(body, cta)
    s6 = _score_human_realism(body, merchant, category)

    total = s1 + s2 + s3 + s4 + s5 + s6

    composed["_critique"] = {
        "specificity":      round(s1, 2),
        "category_fit":     round(s2, 2),
        "merchant_fit":     round(s3, 2),
        "trigger_relevance":round(s4, 2),
        "engagement":       round(s5, 2),
        "human_realism":    round(s6, 2),
        "predicted_total":  round(total, 2),
        "sounds_human":     sounds_like_real_whatsapp_manager(body),
    }
    composed["rejected"] = total < THRESHOLD
    return composed

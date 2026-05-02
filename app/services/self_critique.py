"""
Judge-Aware Self-Critique Pass.

After message generation, scores the output on the 5 judge dimensions
and rejects messages that fall below threshold.
"""
from __future__ import annotations
import re
from typing import Optional


# ── Dimension scorers (0-10 each) ─────────────────────────────────────

def _score_specificity(body: str, merchant: dict, trigger: dict, category: dict) -> float:
    score = 3.0  # base
    perf = merchant.get("performance", {})
    if str(perf.get("views", "")) in body:
        score += 1.5
    if str(perf.get("calls", "")) in body:
        score += 1.0
    if re.search(r"\d+[\.,]\d*%", body):   # percentage present
        score += 1.0
    if re.search(r"₹[\d,]+", body):        # price present
        score += 1.0
    loc = merchant.get("identity", {}).get("locality", "")
    if loc and loc in body:
        score += 1.0
    if re.search(r"\d+ (reviews|days|km|calls|views|members)", body, re.I):
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
    # Category-specific good words
    good_words = {
        "dentists": ["scaling", "fluoride", "recall", "caries", "DCI", "JIDA", "IDA", "patients"],
        "salons": ["booking", "service", "salon", "bridal", "festival", "trend"],
        "restaurants": ["menu", "delivery", "covers", "match", "traffic"],
        "gyms": ["members", "trial", "membership", "session", "coach"],
        "pharmacies": ["refill", "stock", "compliance", "molecule", "supply"],
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
    offers = [o.get("title","") for o in merchant.get("offers",[]) if o.get("status")=="active"]
    for off in offers:
        if off and off in body:
            score += 1.5
    return min(10.0, score)


def _score_trigger_relevance(body: str, trigger: dict) -> float:
    kind = trigger.get("kind", "")
    payload = trigger.get("payload", {})
    score = 5.0
    # Check that key payload values appear in body
    for v in payload.values():
        if isinstance(v, str) and len(v) > 3 and v in body:
            score = min(10.0, score + 1.0)
        elif isinstance(v, int) and v > 0 and str(v) in body:
            score = min(10.0, score + 0.5)
    # Kind-specific keyword checks
    kind_keywords = {
        "perf_dip": ["dip", "down", "drop", "CTR", "fix"],
        "perf_spike": ["up", "spike", "traffic", "calls"],
        "recall_due": ["recall", "due", "slot", "appointment"],
        "competitor_opened": ["competitor", "opened", "km", "ahead"],
        "festival_upcoming": ["days away", "festival", "traffic", "rush"],
        "supply_alert": ["alert", "batch", "stock", "supply"],
        "regulation_change": ["compliance", "deadline", "authority", "update"],
        "renewal_due": ["renew", "subscription", "days", "visibility"],
        "research_digest": ["trial", "study", "research", "findings"],
        "milestone_reached": ["reviews", "milestone", "crossed", "away"],
    }
    for kw in kind_keywords.get(kind, []):
        if kw.lower() in body.lower():
            score = min(10.0, score + 0.4)
    return min(10.0, score)


def _score_engagement(body: str, cta: str) -> float:
    score = 5.0
    body_low = body.lower()
    # Single CTA check
    cta_count = sum(1 for q in ["?", "want me", "shall i", "should i"] if q in body_low)
    if cta_count > 2:
        score -= 1.0
    # Engagement hooks
    hooks = ["heads up", "just crossed", "spotted", "urgent", "missed you",
             "just {", "spike", "dropped", "only", "today", "this week", "before the rush",
             "best moment", "right now", "just say yes"]
    for h in hooks:
        if h.lower() in body_low:
            score = min(10.0, score + 0.5)
    # Length check — WhatsApp sweet spot 50-200 chars
    n = len(body)
    if 50 <= n <= 200:
        score = min(10.0, score + 1.0)
    elif n > 350:
        score -= 1.0
    return min(10.0, score)


# ── Main critique function ─────────────────────────────────────────────

THRESHOLD = 30.0   # out of 50
DIMENSION_WEIGHTS = {
    "specificity": 10, "category_fit": 10,
    "merchant_fit": 10, "trigger_relevance": 10, "engagement": 10,
}


def critique(
    composed: dict,
    category: dict,
    merchant: dict,
    trigger: dict,
    customer: Optional[dict] = None,
) -> dict:
    """
    Score the composed message. Returns augmented dict with predicted_score.
    If score < THRESHOLD, sets 'rejected': True.
    """
    body = composed.get("body", "")
    cta = composed.get("cta", "open_ended")

    s1 = _score_specificity(body, merchant, trigger, category)
    s2 = _score_category_fit(body, category)
    s3 = _score_merchant_fit(body, merchant)
    s4 = _score_trigger_relevance(body, trigger)
    s5 = _score_engagement(body, cta)

    total = s1 + s2 + s3 + s4 + s5

    composed["_critique"] = {
        "specificity": round(s1, 2),
        "category_fit": round(s2, 2),
        "merchant_fit": round(s3, 2),
        "trigger_relevance": round(s4, 2),
        "engagement": round(s5, 2),
        "predicted_total": round(total, 2),
    }
    composed["rejected"] = total < THRESHOLD
    return composed

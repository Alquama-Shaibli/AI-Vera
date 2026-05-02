"""
Spam phrase blacklist + soft CTA detector.
Blocks AI-marketing language that kills merchant realism.
"""
from __future__ import annotations

SPAM_PHRASES = [
    "boost your sales", "increase engagement", "special offer for you",
    "limited time opportunity", "grow your business", "maximize revenue",
    "unlock your potential", "take your business to the next level",
    "don't miss out", "act now", "exclusive deal", "amazing offer",
    "best in class", "world class", "industry leading",
    "guaranteed results", "proven strategy", "skyrocket",
    "viral offer", "crazy deal", "instant recovery", "miracle cure",
    "guaranteed transformation", "100% results",
]

CATEGORY_TABOO = {
    "dentists": ["crazy deal", "viral offer", "miracle", "100% safe", "guaranteed cure",
                 "best dentist", "top rated"],
    "salons": ["miracle treatment", "100% results", "guaranteed glow"],
    "gyms": ["guaranteed transformation", "lose weight fast", "instant results"],
    "pharmacies": ["miracle cure", "instant recovery", "100% effective", "guaranteed relief"],
    "restaurants": ["best food in city", "amazing taste", "world class"],
}

# Patterns that count as hidden secondary CTAs
MULTI_CTA_PHRASES = [
    "i can also", "additionally", "also, i can", "as well as",
    "on top of that", "furthermore", "besides this",
]


def contains_spam(body: str) -> list[str]:
    """Returns list of spam phrases found."""
    body_low = body.lower()
    return [p for p in SPAM_PHRASES if p in body_low]


def contains_category_taboo(body: str, slug: str) -> list[str]:
    body_low = body.lower()
    return [t for t in CATEGORY_TABOO.get(slug, []) if t.lower() in body_low]


def has_multi_cta(body: str) -> bool:
    body_low = body.lower()
    q_count = body_low.count("?")
    if q_count > 1:
        return True
    return any(p in body_low for p in MULTI_CTA_PHRASES)


def validate_spam_free(body: str, slug: str = "") -> bool:
    if contains_spam(body):
        return False
    if slug and contains_category_taboo(body, slug):
        return False
    return True

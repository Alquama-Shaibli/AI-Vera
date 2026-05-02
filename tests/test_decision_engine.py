"""
Tests for decision engine: scoring, prioritization, suppression.
"""
from __future__ import annotations

import pytest
from app.decision.scoring_engine import ScoringEngine, TriggerPrioritizer
from app.storage.context_store import ContextStore, ConversationStore, SuppressionStore


@pytest.fixture
def engine():
    return ScoringEngine()


@pytest.fixture
def sample_trigger():
    return {
        "id": "t001", "kind": "perf_dip", "scope": "merchant",
        "source": "internal", "merchant_id": "m001",
        "urgency": 3, "suppression_key": "perf_dip:m001:w17",
        "expires_at": "2027-01-01T00:00:00Z", "payload": {},
    }


@pytest.fixture
def sample_merchant():
    return {
        "merchant_id": "m001", "category_slug": "dentists",
        "identity": {"name": "Test Clinic", "owner_first_name": "Dr. A", "locality": "Lajpat Nagar"},
        "subscription": {"status": "active", "days_remaining": 90},
        "performance": {"views": 2000, "calls": 15, "ctr": 0.021,
                        "delta_7d": {"views_pct": -0.20, "calls_pct": -0.25}},
        "signals": ["ctr_below_peer_median", "stale_posts"],
        "offers": [], "customer_aggregate": {}, "review_themes": [],
    }


@pytest.fixture
def sample_category():
    return {
        "slug": "dentists",
        "peer_stats": {"avg_ctr": 0.030, "avg_reviews": 62, "avg_rating": 4.4},
        "voice": {"tone": "clinical", "vocab_taboo": ["guaranteed"]},
    }


def test_score_returns_float(engine, sample_trigger, sample_merchant, sample_category):
    score = engine.score(sample_trigger, sample_merchant, sample_category)
    assert isinstance(score, float)
    assert 0.0 <= score <= 10.0


def test_score_is_deterministic(engine, sample_trigger, sample_merchant, sample_category):
    s1 = engine.score(sample_trigger, sample_merchant, sample_category)
    s2 = engine.score(sample_trigger, sample_merchant, sample_category)
    assert s1 == s2


def test_high_urgency_scores_higher(engine, sample_trigger, sample_merchant, sample_category):
    low = dict(sample_trigger, urgency=1)
    high = dict(sample_trigger, urgency=5)
    assert engine.score(high, sample_merchant, sample_category) > engine.score(low, sample_merchant, sample_category)


def test_expired_trigger_suppressed():
    ctx = ContextStore()
    supp = SuppressionStore()
    conv = ConversationStore()

    ctx.push("category", "dentists", 1, {
        "slug": "dentists", "peer_stats": {}, "voice": {},
    })
    ctx.push("merchant", "m001", 1, {
        "merchant_id": "m001", "category_slug": "dentists",
        "identity": {}, "subscription": {}, "performance": {"delta_7d": {}},
        "signals": [], "offers": [],
    })
    ctx.push("trigger", "t_expired", 1, {
        "id": "t_expired", "kind": "perf_dip", "scope": "merchant",
        "merchant_id": "m001", "urgency": 5,
        "suppression_key": "perf_dip:m001:old",
        "expires_at": "2020-01-01T00:00:00Z",  # already expired
        "payload": {},
    })

    prioritizer = TriggerPrioritizer(ScoringEngine())
    results = prioritizer.prioritize(["t_expired"], ctx, supp, conv)
    assert results == []


def test_suppressed_key_skipped():
    ctx = ContextStore()
    supp = SuppressionStore()
    conv = ConversationStore()

    ctx.push("category", "dentists", 1, {"slug": "dentists", "peer_stats": {}, "voice": {}})
    ctx.push("merchant", "m001", 1, {
        "merchant_id": "m001", "category_slug": "dentists",
        "identity": {}, "subscription": {}, "performance": {"delta_7d": {}},
        "signals": [], "offers": [],
    })
    ctx.push("trigger", "t001", 1, {
        "id": "t001", "kind": "perf_dip", "scope": "merchant",
        "merchant_id": "m001", "urgency": 3,
        "suppression_key": "perf_dip:m001:week",
        "expires_at": "2027-01-01T00:00:00Z", "payload": {},
    })

    supp.suppress("perf_dip:m001:week")
    prioritizer = TriggerPrioritizer(ScoringEngine())
    results = prioritizer.prioritize(["t001"], ctx, supp, conv)
    assert results == []


def test_one_action_per_merchant_per_tick():
    ctx = ContextStore()
    supp = SuppressionStore()
    conv = ConversationStore()

    ctx.push("category", "dentists", 1, {"slug": "dentists", "peer_stats": {}, "voice": {}})
    ctx.push("merchant", "m001", 1, {
        "merchant_id": "m001", "category_slug": "dentists",
        "identity": {}, "subscription": {}, "performance": {"delta_7d": {}},
        "signals": [], "offers": [],
    })
    for i in range(3):
        ctx.push("trigger", f"t{i}", 1, {
            "id": f"t{i}", "kind": "perf_dip", "scope": "merchant",
            "merchant_id": "m001", "urgency": i + 1,
            "suppression_key": f"perf_dip:m001:{i}",
            "expires_at": "2027-01-01T00:00:00Z", "payload": {},
        })

    prioritizer = TriggerPrioritizer(ScoringEngine())
    results = prioritizer.prioritize([f"t{i}" for i in range(3)], ctx, supp, conv)
    merchant_ids = [r["merchant_id"] for r in results]
    assert len(set(merchant_ids)) == len(merchant_ids)  # no duplicates
    assert len(results) <= 1

"""
Tests for all 5 API endpoints.
Run: pytest tests/test_endpoints.py -v
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app, _context_store, _suppression_store

client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_stores():
    _context_store.clear()
    _suppression_store.clear()
    yield


# ── /v1/healthz ────────────────────────────────────────────────────────

def test_healthz_returns_ok():
    r = client.get("/v1/healthz")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "uptime_seconds" in data
    assert "contexts_loaded" in data


# ── /v1/metadata ───────────────────────────────────────────────────────

def test_metadata_returns_team_info():
    r = client.get("/v1/metadata")
    assert r.status_code == 200
    data = r.json()
    assert "team_name" in data
    assert "model" in data
    assert "approach" in data


# ── /v1/context ────────────────────────────────────────────────────────

SAMPLE_PAYLOAD = {"slug": "dentists", "peer_stats": {"avg_ctr": 0.030}}


def test_context_push_accepted():
    r = client.post("/v1/context", json={
        "scope": "category",
        "context_id": "dentists",
        "version": 1,
        "payload": SAMPLE_PAYLOAD,
        "delivered_at": "2026-05-01T00:00:00Z",
    })
    assert r.status_code == 200
    assert r.json()["accepted"] is True


def test_context_idempotent_same_version():
    for _ in range(2):
        r = client.post("/v1/context", json={
            "scope": "category", "context_id": "salons",
            "version": 1, "payload": {}, "delivered_at": "2026-05-01T00:00:00Z",
        })
    # Second push with same version should return 409
    assert r.status_code == 409


def test_context_higher_version_replaces():
    client.post("/v1/context", json={
        "scope": "merchant", "context_id": "m001",
        "version": 1, "payload": {"name": "old"}, "delivered_at": "2026-05-01T00:00:00Z",
    })
    r = client.post("/v1/context", json={
        "scope": "merchant", "context_id": "m001",
        "version": 2, "payload": {"name": "new"}, "delivered_at": "2026-05-01T00:00:00Z",
    })
    assert r.status_code == 200
    assert r.json()["accepted"] is True


# ── /v1/tick ───────────────────────────────────────────────────────────

def _push_minimal_context():
    """Push minimal valid context for a tick test."""
    client.post("/v1/context", json={
        "scope": "category", "context_id": "dentists",
        "version": 1,
        "payload": {
            "slug": "dentists",
            "peer_stats": {"avg_ctr": 0.030, "avg_reviews": 62, "avg_rating": 4.4},
            "voice": {"tone": "clinical", "vocab_taboo": ["guaranteed", "cure"]},
            "offer_catalog": [], "digest": [], "seasonal_beats": [], "trend_signals": [],
        },
        "delivered_at": "2026-05-01T00:00:00Z",
    })
    client.post("/v1/context", json={
        "scope": "merchant", "context_id": "m_test_001",
        "version": 1,
        "payload": {
            "merchant_id": "m_test_001",
            "category_slug": "dentists",
            "identity": {"name": "Test Clinic", "owner_first_name": "Dr. Test",
                         "locality": "Lajpat Nagar", "city": "Delhi", "languages": ["en", "hi"]},
            "subscription": {"status": "active", "days_remaining": 90},
            "performance": {"views": 2410, "calls": 18, "ctr": 0.021,
                            "delta_7d": {"views_pct": -0.15, "calls_pct": -0.20}},
            "offers": [], "signals": ["ctr_below_peer_median"], "conversation_history": [],
            "customer_aggregate": {"total_unique_ytd": 200},
            "review_themes": [],
        },
        "delivered_at": "2026-05-01T00:00:00Z",
    })
    client.post("/v1/context", json={
        "scope": "trigger", "context_id": "trg_test_001",
        "version": 1,
        "payload": {
            "id": "trg_test_001", "kind": "perf_dip", "scope": "merchant",
            "source": "internal", "merchant_id": "m_test_001", "customer_id": None,
            "payload": {}, "urgency": 3,
            "suppression_key": "perf_dip:m_test_001:test",
            "expires_at": "2027-01-01T00:00:00Z",
        },
        "delivered_at": "2026-05-01T00:00:00Z",
    })


def test_tick_returns_actions():
    _push_minimal_context()
    r = client.post("/v1/tick", json={
        "now": "2026-05-01T10:00:00Z",
        "available_triggers": ["trg_test_001"],
    })
    assert r.status_code == 200
    data = r.json()
    assert "actions" in data
    assert isinstance(data["actions"], list)


def test_tick_empty_triggers_returns_empty():
    r = client.post("/v1/tick", json={
        "now": "2026-05-01T10:00:00Z",
        "available_triggers": [],
    })
    assert r.status_code == 200
    assert r.json()["actions"] == []


def test_tick_suppresses_duplicate():
    _push_minimal_context()
    r1 = client.post("/v1/tick", json={
        "now": "2026-05-01T10:00:00Z",
        "available_triggers": ["trg_test_001"],
    })
    r2 = client.post("/v1/tick", json={
        "now": "2026-05-01T10:01:00Z",
        "available_triggers": ["trg_test_001"],
    })
    # Second tick with same trigger should return 0 actions (suppressed)
    assert r2.json()["actions"] == []


# ── /v1/reply ──────────────────────────────────────────────────────────

def test_reply_hostile_ends():
    r = client.post("/v1/reply", json={
        "conversation_id": "conv_hostile_test",
        "merchant_id": "m_test_001",
        "from_role": "merchant",
        "message": "Stop messaging me. This is spam.",
        "received_at": "2026-05-01T10:00:00Z",
        "turn_number": 2,
    })
    assert r.status_code == 200
    data = r.json()
    assert data["action"] == "end"


def test_reply_commitment_switches_to_action():
    r = client.post("/v1/reply", json={
        "conversation_id": "conv_commit_test",
        "merchant_id": "m_test_001",
        "from_role": "merchant",
        "message": "Ok let's do it. What's next?",
        "received_at": "2026-05-01T10:00:00Z",
        "turn_number": 2,
    })
    assert r.status_code == 200
    data = r.json()
    assert data["action"] == "send"
    body_lower = data.get("body", "").lower()
    # Should NOT contain qualifying language
    qualifying = ["would you", "do you want", "can you tell me", "what if"]
    assert not any(q in body_lower for q in qualifying)


def test_reply_auto_reply_first_probes():
    r = client.post("/v1/reply", json={
        "conversation_id": "conv_auto_test",
        "merchant_id": "m_test_001",
        "from_role": "merchant",
        "message": "Thank you for contacting us! Our team will respond shortly.",
        "received_at": "2026-05-01T10:00:00Z",
        "turn_number": 2,
    })
    assert r.status_code == 200
    data = r.json()
    assert data["action"] in ("send", "wait", "end")


def test_reply_auto_reply_third_ends():
    conv_id = "conv_auto_end_test"
    auto_msg = "Thank you for contacting us. Our team will get back to you."
    for i in range(3):
        r = client.post("/v1/reply", json={
            "conversation_id": conv_id,
            "merchant_id": "m_test_001",
            "from_role": "merchant",
            "message": auto_msg,
            "received_at": "2026-05-01T10:00:00Z",
            "turn_number": i + 2,
        })
    assert r.json()["action"] == "end"

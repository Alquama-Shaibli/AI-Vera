"""
Tests for replay state machine: auto-reply, intent, hostile, off-topic.
"""
from __future__ import annotations

import pytest
from app.replay.state_machine import ReplayStateMachine, _detect_intent
from app.storage.context_store import ContextStore, ConversationStore, SuppressionStore


@pytest.fixture
def sm():
    return ReplayStateMachine(ContextStore(), ConversationStore(), SuppressionStore())


# ── Intent detection ───────────────────────────────────────────────────

def test_detect_auto_reply():
    assert _detect_intent("Thank you for contacting us! Our team will respond.") == "auto_reply"
    assert _detect_intent("Aapki madad ke liye shukriya, hamari team pahuncha degi.") == "auto_reply"
    assert _detect_intent("This is an automated message.") == "auto_reply"


def test_detect_hostile():
    assert _detect_intent("Stop messaging me. This is spam.") == "hostile"
    assert _detect_intent("Do not contact me again.") == "hostile"
    assert _detect_intent("band karo yeh sab") == "hostile"


def test_detect_commitment():
    assert _detect_intent("Yes, let's do it!") == "commitment"
    assert _detect_intent("Ok let's go ahead") == "commitment"
    assert _detect_intent("Sounds good, proceed") == "commitment"
    assert _detect_intent("haan karo") == "commitment"


def test_detect_engaged():
    assert _detect_intent("What kind of post would you recommend?") == "engaged"


# ── State machine flows ────────────────────────────────────────────────

def test_hostile_ends_conversation(sm):
    r = sm.handle_reply("c1", "m001", None, "Stop messaging me. This is spam.", 2)
    assert r.action == "end"


def test_commitment_sends_action(sm):
    r = sm.handle_reply("c2", "m001", None, "Yes, let's do it! What's next?", 2)
    assert r.action == "send"
    body_lower = r.body.lower()
    assert any(w in body_lower for w in ["noted", "on it", "first", "start", "draft", "ready", "update", "sending"])


def test_auto_reply_first_probes(sm):
    r = sm.handle_reply("c3", "m001", None,
                        "Thank you for contacting us! Our team will respond shortly.", 2)
    assert r.action in ("send", "wait")


def test_auto_reply_limit_ends(sm):
    conv_id = "c_auto_end"
    auto_msg = "Thank you for contacting us. Our team will get back to you."
    final = None
    for i in range(3):
        final = sm.handle_reply(conv_id, "m001", None, auto_msg, i + 2)
    assert final.action == "end"


def test_ended_conversation_stays_ended(sm):
    conv_id = "c_ended"
    sm.handle_reply(conv_id, "m001", None, "Stop messaging me.", 2)
    r = sm.handle_reply(conv_id, "m001", None, "Yes actually let's do it", 3)
    assert r.action == "end"


def test_off_topic_redirects(sm):
    r = sm.handle_reply("c_off", "m001", None,
                        "What's the cricket score today?", 2)
    assert r.action == "send"
    body_lower = r.body.lower()
    assert any(w in body_lower for w in ["outside", "not", "business", "profile", "help"])

"""
Context Store — versioned, idempotent storage for all 4 context scopes.
Uses in-memory dicts with optional Redis backup.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from typing import Any, Optional

from loguru import logger


class ContextStore:
    """Thread-safe, versioned context store."""

    def __init__(self):
        # (scope, context_id) -> {"version": int, "payload": dict}
        self._store: dict[tuple[str, str], dict[str, Any]] = {}
        self._lock = threading.Lock()
        logger.info("ContextStore initialized (in-memory)")

    # ── Public API ─────────────────────────────────────────────────────

    def push(
        self, scope: str, context_id: str, version: int, payload: dict
    ) -> tuple[bool, Optional[str], Optional[int]]:
        """
        Store a context. Returns (accepted, reason, current_version).
        - Idempotent by (scope, context_id, version).
        - Higher version replaces atomically.
        """
        key = (scope, context_id)
        with self._lock:
            existing = self._store.get(key)
            if existing and existing["version"] >= version:
                return False, "stale_version", existing["version"]
            self._store[key] = {"version": version, "payload": payload}
        logger.debug(f"Stored {scope}/{context_id} v{version}")
        return True, None, None

    def get(self, scope: str, context_id: str) -> Optional[dict]:
        """Get the payload for a given (scope, context_id)."""
        entry = self._store.get((scope, context_id))
        return entry["payload"] if entry else None

    def get_version(self, scope: str, context_id: str) -> Optional[int]:
        entry = self._store.get((scope, context_id))
        return entry["version"] if entry else None

    def get_all_by_scope(self, scope: str) -> dict[str, dict]:
        """Return {context_id: payload} for all items of a given scope."""
        result = {}
        for (s, cid), entry in self._store.items():
            if s == scope:
                result[cid] = entry["payload"]
        return result

    def count_by_scope(self) -> dict[str, int]:
        """Count contexts per scope for healthz."""
        counts = {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}
        for (scope, _) in self._store:
            counts[scope] = counts.get(scope, 0) + 1
        return counts

    def get_merchant_category(self, merchant_id: str) -> Optional[dict]:
        """Convenience: get the category context for a merchant."""
        merchant = self.get("merchant", merchant_id)
        if not merchant:
            return None
        cat_slug = merchant.get("category_slug", "")
        return self.get("category", cat_slug)

    def clear(self):
        """Wipe all state (for teardown)."""
        with self._lock:
            self._store.clear()
        logger.info("ContextStore cleared")


class ConversationStore:
    """Tracks active conversations and their state."""

    def __init__(self):
        self._conversations: dict[str, dict] = {}
        self._lock = threading.Lock()

    def create(self, conv_id: str, merchant_id: str, trigger_id: str,
               customer_id: Optional[str] = None) -> dict:
        with self._lock:
            conv = {
                "conversation_id": conv_id,
                "merchant_id": merchant_id,
                "customer_id": customer_id,
                "trigger_id": trigger_id,
                "state": "active",
                "turns": [],
                "auto_reply_count": 0,
                "body_hashes": set(),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            self._conversations[conv_id] = conv
            return conv

    def get(self, conv_id: str) -> Optional[dict]:
        return self._conversations.get(conv_id)

    def add_turn(self, conv_id: str, role: str, body: str):
        conv = self._conversations.get(conv_id)
        if conv:
            conv["turns"].append({"role": role, "body": body})

    def get_body_hashes(self, conv_id: str) -> set:
        conv = self._conversations.get(conv_id)
        return conv["body_hashes"] if conv else set()

    def add_body_hash(self, conv_id: str, h: str):
        conv = self._conversations.get(conv_id)
        if conv:
            conv["body_hashes"].add(h)

    def set_state(self, conv_id: str, state: str):
        conv = self._conversations.get(conv_id)
        if conv:
            conv["state"] = state

    def increment_auto_reply(self, conv_id: str) -> int:
        conv = self._conversations.get(conv_id)
        if conv:
            conv["auto_reply_count"] += 1
            return conv["auto_reply_count"]
        return 0

    def get_auto_reply_count(self, conv_id: str) -> int:
        conv = self._conversations.get(conv_id)
        return conv["auto_reply_count"] if conv else 0

    def is_ended(self, conv_id: str) -> bool:
        conv = self._conversations.get(conv_id)
        return conv["state"] == "ended" if conv else False

    def all_active_for_merchant(self, merchant_id: str) -> list[str]:
        return [
            cid for cid, c in self._conversations.items()
            if c["merchant_id"] == merchant_id and c["state"] == "active"
        ]


# ── Suppression Store ──────────────────────────────────────────────────

class SuppressionStore:
    """Tracks suppression keys to prevent duplicate sends."""

    def __init__(self):
        self._suppressed: set[str] = set()

    def is_suppressed(self, key: str) -> bool:
        return key in self._suppressed

    def suppress(self, key: str):
        self._suppressed.add(key)

    def clear(self):
        self._suppressed.clear()

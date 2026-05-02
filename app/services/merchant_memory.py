"""
Merchant Memory Engine — tracks per-merchant behavioral signals.
Used by scoring and strategy selection to personalize.
"""
from __future__ import annotations
import threading
import hashlib
import time
from typing import Optional


class MerchantMemory:
    """Thread-safe in-process memory for per-merchant behavioral tracking."""

    def __init__(self):
        self._lock = threading.Lock()
        self._store: dict[str, dict] = {}

    def _init(self, mid: str) -> dict:
        return {
            "merchant_id": mid,
            "strategy_history": [],       # list of {kind, sent_at, cta}
            "auto_reply_count": 0,
            "commitment_count": 0,
            "last_strategy": None,
            "last_sent_at": None,
            "body_hashes": set(),
            "total_messages_sent": 0,
        }

    def get(self, merchant_id: str) -> dict:
        with self._lock:
            return dict(self._store.get(merchant_id, self._init(merchant_id)))

    def record_sent(self, merchant_id: str, kind: str, body: str, cta: str):
        h = hashlib.md5(body.encode()).hexdigest()
        with self._lock:
            if merchant_id not in self._store:
                self._store[merchant_id] = self._init(merchant_id)
            m = self._store[merchant_id]
            m["strategy_history"].append({"kind": kind, "sent_at": time.time(), "cta": cta})
            m["strategy_history"] = m["strategy_history"][-20:]
            m["last_strategy"] = kind
            m["last_sent_at"] = time.time()
            m["body_hashes"].add(h)
            m["total_messages_sent"] += 1

    def is_repeated_body(self, merchant_id: str, body: str) -> bool:
        h = hashlib.md5(body.encode()).hexdigest()
        with self._lock:
            return h in self._store.get(merchant_id, {}).get("body_hashes", set())

    def recent_strategies(self, merchant_id: str, n: int = 3) -> list:
        with self._lock:
            hist = self._store.get(merchant_id, {}).get("strategy_history", [])
            return [s["kind"] for s in hist[-n:]]

    def is_fatigued(self, merchant_id: str, cooldown_secs: int = 3600) -> bool:
        with self._lock:
            m = self._store.get(merchant_id)
            if not m:
                return False
            
            last = m.get("last_sent_at")
            if not last:
                return False

            # Time-based decay: fatigue decreases as time passes
            elapsed = time.time() - last
            if elapsed < cooldown_secs:
                # Still within hard cooldown
                return True
            
            # Additional logic: if they've sent many messages, increase cooldown
            total = m.get("total_messages_sent", 0)
            if total > 5 and elapsed < (cooldown_secs * 2):
                return True
                
            return False

    def update_summary(self, merchant_id: str, key: str, value: Any):
        with self._lock:
            if merchant_id not in self._store:
                self._store[merchant_id] = self._init(merchant_id)
            if "summary" not in self._store[merchant_id]:
                self._store[merchant_id]["summary"] = {
                    "merchant_interested": None,
                    "pricing_sensitive": None,
                    "declined_discount": None,
                    "prefers_direct_cta": None
                }
            self._store[merchant_id]["summary"][key] = value

    def get_summary(self, merchant_id: str) -> dict:
        with self._lock:
            return self._store.get(merchant_id, {}).get("summary", {})

    def record_auto_reply(self, merchant_id: str) -> int:
        with self._lock:
            if merchant_id not in self._store:
                self._store[merchant_id] = self._init(merchant_id)
            self._store[merchant_id]["auto_reply_count"] += 1
            return self._store[merchant_id]["auto_reply_count"]

    def clear(self):
        with self._lock:
            self._store.clear()


# Singleton
_memory = MerchantMemory()


def get_memory() -> MerchantMemory:
    return _memory

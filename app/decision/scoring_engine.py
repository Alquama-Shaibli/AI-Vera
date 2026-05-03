"""
Decision Engine — deterministic opportunity scoring and trigger prioritisation.

This is the CORE of the system. It scores every available trigger against
merchant context and selects the highest-value actions to take per tick.
No LLM calls here — pure deterministic scoring.

Strategic silence: returns empty list when no trigger clears the confidence
threshold (CONFIDENCE_FLOOR = 3.5). This improves realism dramatically.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from loguru import logger


# ── Weight configuration ───────────────────────────────────────────────

WEIGHTS = {
    "merchant_need": 0.38,       # 1. Merchant pain — highest weight
    "trigger_relevance": 0.25,   # 2. Immediate opportunity
    "urgency": 0.17,             # 3. Timing
    "customer_match": 0.15,      # 4. Actionability — raised for specificity
    "category_alignment": 0.05,  # 5. Reduced — category is context not primary signal
}

# Strategic silence threshold: skip triggers scoring below this
# Set at 3.8 — filters noise but allows all real operational triggers through
CONFIDENCE_FLOOR = 3.8

# trigger.kind → base relevance score (0-10)
KIND_RELEVANCE = {
    "supply_alert": 10,
    "regulation_change": 9,
    "recall_due": 9,
    "chronic_refill_due": 9,
    "perf_dip": 8,
    "renewal_due": 8,
    "active_planning_intent": 8,
    "review_theme_emerged": 7,
    "competitor_opened": 7,
    "customer_lapsed_hard": 7,
    "perf_spike": 6,
    "milestone_reached": 6,
    "winback_eligible": 6,
    "customer_lapsed_soft": 6,
    "ipl_match_today": 6,
    "wedding_package_followup": 6,
    "trial_followup": 6,
    "gbp_unverified": 7,
    "research_digest": 6,
    "cde_opportunity": 6,
    "category_seasonal": 6,
    "seasonal_perf_dip": 5,
    "festival_upcoming": 6,
    "curious_ask_due": 4,
    "dormant_with_vera": 6,
    "appointment_tomorrow": 7,
}

# Signal → merchant need score boost
SIGNAL_SCORES = {
    "perf_dip_severe": 3,
    "perf_dip_post_expiry": 2,
    "renewal_due_soon": 3,
    "dormant_with_vera": 2,
    "no_active_offers": 1,
    "unverified_gbp": 1,
    "winback_eligible": 2,
    "ctr_below_peer_median": 1,
    "stale_posts": 1,
    "trial_ending_soon": 2,
    "new_merchant": 1,
    "high_risk_adult_cohort": 1,
    "compliance_aware": 1,
    "no_recent_conversation": 1,
    "seasonal_dip": 1,
}

# Category-kind affinity scores (which kinds matter most for which categories)
CATEGORY_AFFINITY = {
    "dentists": {"research_digest": 9, "regulation_change": 10, "cde_opportunity": 7, "recall_due": 9},
    "salons": {"festival_upcoming": 8, "wedding_package_followup": 9, "curious_ask_due": 7},
    "restaurants": {"ipl_match_today": 9, "festival_upcoming": 8, "review_theme_emerged": 8},
    "gyms": {"seasonal_perf_dip": 7, "customer_lapsed_hard": 8, "trial_followup": 7},
    "pharmacies": {"supply_alert": 10, "chronic_refill_due": 9, "category_seasonal": 7},
}


class ScoringEngine:
    """Deterministic scoring engine for trigger–merchant opportunity pairs."""

    def score(
        self,
        trigger: dict,
        merchant: dict,
        category: dict,
        customer: Optional[dict] = None,
    ) -> float:
        """
        Compute composite decision score for a (trigger, merchant, category, customer?) tuple.
        Returns 0-10 float.
        """
        s_trigger = self._score_trigger_relevance(trigger)
        s_merchant = self._score_merchant_need(merchant)
        s_urgency = self._score_urgency(trigger)
        s_category = self._score_category_alignment(trigger, category)
        s_customer = self._score_customer_match(trigger, customer)

        composite = (
            s_trigger * WEIGHTS["trigger_relevance"]
            + s_merchant * WEIGHTS["merchant_need"]
            + s_urgency * WEIGHTS["urgency"]
            + s_category * WEIGHTS["category_alignment"]
            + s_customer * WEIGHTS["customer_match"]
        )

        # Time-of-day adjustment
        try:
            from app.services.time_intelligence import get_tod_multiplier
            tod = get_tod_multiplier(category.get("slug", ""), trigger.get("kind", ""))
            composite = composite * tod
        except Exception:
            pass

        return round(min(10.0, composite), 3)

    def _score_trigger_relevance(self, trigger: dict) -> float:
        kind = trigger.get("kind", "")
        base = KIND_RELEVANCE.get(kind, 3)
        # Boost for rich payloads
        payload = trigger.get("payload", {})
        if len(payload) > 3:
            base = min(10, base + 1)
        return float(base)

    def _score_merchant_need(self, merchant: dict) -> float:
        score = 4.0  # baseline
        signals = merchant.get("signals", [])
        for sig in signals:
            sig_key = sig.split(":")[0] if ":" in sig else sig
            score += SIGNAL_SCORES.get(sig_key, 0)
        # Subscription urgency
        sub = merchant.get("subscription", {})
        if sub.get("status") == "expired":
            score += 2
        elif sub.get("status") == "trial":
            score += 1
        days_rem = sub.get("days_remaining", 999)
        if isinstance(days_rem, (int, float)) and days_rem < 15:
            score += 1
        # Performance dip
        perf = merchant.get("performance", {})
        delta = perf.get("delta_7d", {})
        if delta.get("views_pct", 0) < -0.20:
            score += 1
        if delta.get("calls_pct", 0) < -0.30:
            score += 1
        return min(10.0, score)

    def _score_urgency(self, trigger: dict) -> float:
        raw = trigger.get("urgency", 2)
        return min(10.0, float(raw) * 2)

    def _score_category_alignment(self, trigger: dict, category: dict) -> float:
        kind = trigger.get("kind", "")
        slug = category.get("slug", "")
        affinity = CATEGORY_AFFINITY.get(slug, {})
        if kind in affinity:
            return float(affinity[kind])
        # Default: moderate alignment
        return 5.0

    def _score_customer_match(self, trigger: dict, customer: Optional[dict]) -> float:
        if trigger.get("scope") != "customer" or not customer:
            return 5.0  # neutral
        state = customer.get("state", "active")
        state_scores = {
            "lapsed_hard": 9, "lapsed_soft": 8, "churned": 7,
            "active": 5, "new": 6,
        }
        score = float(state_scores.get(state, 5))
        # Consent boost
        consent = customer.get("consent", {})
        if consent.get("scope") and len(consent["scope"]) > 0:
            score = min(10, score + 1)
        return score


class TriggerPrioritizer:
    """Ranks triggers and selects the best actions for a tick."""

    def __init__(self, scoring_engine: ScoringEngine):
        self.engine = scoring_engine

    def prioritize(
        self,
        available_trigger_ids: list[str],
        context_store,
        suppression_store,
        conversation_store,
        max_actions: int = 20,
    ) -> list[dict]:
        """
        Score and rank all available triggers.
        Returns list of {"trigger_id", "merchant_id", "customer_id", "score", "trigger", "merchant", "category", "customer"}
        sorted by score descending, deduplicated per merchant.
        """
        from app.services.merchant_memory import get_memory
        memory = get_memory()
        scored = []
        seen_merchants = set()

        for tid in available_trigger_ids:
            trigger = context_store.get("trigger", tid)
            if not trigger:
                continue

            # Suppression check
            supp_key = trigger.get("suppression_key", "")
            if supp_key and suppression_store.is_suppressed(supp_key):
                continue

            # Expiry check
            expires = trigger.get("expires_at", "")
            if expires:
                try:
                    exp_dt = datetime.fromisoformat(expires.replace("Z", "+00:00"))
                    if exp_dt < datetime.now(timezone.utc):
                        continue
                except (ValueError, TypeError):
                    pass

            merchant_id = trigger.get("merchant_id", "")
            merchant = context_store.get("merchant", merchant_id)
            if not merchant:
                continue

            # Merchant fatigue check (strategic silence)
            if memory.is_fatigued(merchant_id):
                logger.debug(f"Merchant {merchant_id} fatigued — skipping")
                continue

            cat_slug = merchant.get("category_slug", "")
            category = context_store.get("category", cat_slug)
            if not category:
                continue

            customer_id = trigger.get("customer_id")
            customer = context_store.get("customer", customer_id) if customer_id else None

            score = self.engine.score(trigger, merchant, category, customer)

            # Strategic silence — skip low-confidence triggers
            if score < CONFIDENCE_FLOOR:
                logger.debug(f"Trigger {tid} score {score:.2f} below floor {CONFIDENCE_FLOOR} — skip")
                continue

            scored.append({
                "trigger_id": tid,
                "merchant_id": merchant_id,
                "customer_id": customer_id,
                "score": score,
                "trigger": trigger,
                "merchant": merchant,
                "category": category,
                "customer": customer,
            })

        # Sort by score descending
        scored.sort(key=lambda x: x["score"], reverse=True)

        # Deduplicate: one action per merchant per tick
        results = []
        for item in scored:
            mid = item["merchant_id"]
            if mid not in seen_merchants:
                # Also skip if recent strategy repeated
                recent = memory.recent_strategies(mid, n=2)
                kind = item["trigger"].get("kind", "")
                if kind in recent and item["score"] < 6.0:
                    logger.debug(f"Repeated strategy {kind} for {mid} — skip")
                    continue
                seen_merchants.add(mid)
                results.append(item)
                if len(results) >= max_actions:
                    break

        return results

"""
Time-of-day scoring intelligence.
Adjusts urgency scores based on current hour and category patterns.
Fully deterministic — no randomness.
"""
from __future__ import annotations
from datetime import datetime, timezone


# category_slug → {hour_range: multiplier}
# Hours in IST (0-23)
TOD_MULTIPLIERS = {
    "restaurants": {
        (11, 14): 1.4,   # lunch rush
        (18, 22): 1.5,   # dinner + IPL
        (7,  10): 0.7,   # dead morning
    },
    "gyms": {
        (5,  9):  1.5,   # morning workout
        (17, 21): 1.4,   # evening workout
        (11, 16): 0.7,   # midday slump
    },
    "salons": {
        (10, 13): 1.3,   # late morning bookings
        (15, 19): 1.4,   # evening appointments
        (20, 23): 0.8,   # winding down
    },
    "dentists": {
        (9,  13): 1.3,   # morning clinic
        (16, 19): 1.2,   # post-work
        (13, 15): 0.8,   # post-lunch lull
    },
    "pharmacies": {
        (8,  11): 1.3,   # morning prescriptions
        (18, 21): 1.2,   # evening refills
        (23, 6):  0.6,   # overnight
    },
}

# Kind-specific urgency boost by time
KIND_TIME_BOOST = {
    "ipl_match_today":   {(17, 23): 2.0},
    "festival_upcoming": {(8, 22):  1.2},
    "perf_dip":          {(9, 18):  1.1},
    "renewal_due":       {(9, 17):  1.2},
}


def _ist_hour() -> int:
    now = datetime.now(timezone.utc)
    # IST = UTC + 5:30
    return (now.hour + 5) % 24


def get_tod_multiplier(category_slug: str, trigger_kind: str) -> float:
    hour = _ist_hour()
    mult = 1.0
    for (h_start, h_end), m in TOD_MULTIPLIERS.get(category_slug, {}).items():
        if h_start <= hour < h_end:
            mult = m
            break
    for (h_start, h_end), km in KIND_TIME_BOOST.get(trigger_kind, {}).items():
        if h_start <= hour < h_end:
            mult *= km
            break
    # Floor: never suppress valid triggers below 92% — prevents over-silencing
    return round(max(0.92, mult), 2)

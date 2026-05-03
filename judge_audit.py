"""
Full Judge Audit — Vera AI Engine
Executes real HTTP calls, captures outputs, scores each dimension.
"""
import json
import time
import requests

BASE = "http://127.0.0.1:8099"
results = {}

def post(path, payload, label=""):
    t0 = time.time()
    try:
        r = requests.post(BASE + path, json=payload, timeout=10)
        ms = int((time.time() - t0) * 1000)
        return r.status_code, r.json(), ms
    except Exception as e:
        return 0, {"error": str(e)}, 0

def get(path):
    t0 = time.time()
    try:
        r = requests.get(BASE + path, timeout=10)
        ms = int((time.time() - t0) * 1000)
        return r.status_code, r.json(), ms
    except Exception as e:
        return 0, {"error": str(e)}, 0

def sep(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)

def show(label, status, data, ms=0):
    print(f"\n[{label}] {status} ({ms}ms)")
    body = json.dumps(data, indent=2, ensure_ascii=False)
    print(body[:1200] + ("..." if len(body) > 1200 else ""))

# ── PHASE 1: Endpoint Health ───────────────────────────────────────────
sep("PHASE 1 — ENDPOINT HEALTH")

s, d, ms = get("/")
show("GET /", s, d, ms)
results["root"] = s == 200

s, d, ms = get("/v1/healthz")
show("GET /v1/healthz", s, d, ms)
results["healthz_uptime"] = "uptime_seconds" in d
results["healthz_contexts"] = "contexts_loaded" in d

s, d, ms = get("/v1/metadata")
show("GET /v1/metadata", s, d, ms)
results["metadata_team"] = "team_name" in d
results["metadata_approach"] = "approach" in d

# ── PHASE 2: Context Push ──────────────────────────────────────────────
sep("PHASE 2 — CONTEXT PUSH (All 4 scopes)")

CAT = {
    "slug": "dentists",
    "peer_stats": {"avg_ctr": 0.032, "avg_reviews": 68, "avg_rating": 4.4},
    "voice": {"tone": "clinical", "vocab_taboo": ["guaranteed cure", "best dentist", "miracle"]},
    "digest": [
        {"id": "d1", "title": "ADA fluoride protocol update 2024", "source": "ADA",
         "trial_n": 3200, "patient_segment": "adults_over_40", "actionable": "Update consent forms"}
    ],
    "offer_catalog": [], "seasonal_beats": [], "trend_signals": []
}
MERCHANT = {
    "merchant_id": "m_001",
    "category_slug": "dentists",
    "identity": {"name": "Sunshine Dental", "owner_first_name": "Priya",
                 "locality": "Koramangala", "city": "Bangalore", "languages": ["en", "hi"]},
    "subscription": {"status": "active", "plan": "Pro", "days_remaining": 12, "renewal_amount": 8500},
    "performance": {"views": 3842, "calls": 24, "ctr": 0.019,
                    "delta_7d": {"views_pct": -0.28, "calls_pct": -0.35}},
    "offers": [{"title": "Free X-Ray with Cleaning", "status": "active"}],
    "signals": ["perf_dip_severe", "ctr_below_peer_median", "renewal_due_soon"],
    "conversation_history": [],
    "customer_aggregate": {"total_unique_ytd": 340, "lapsed_count": 28},
    "review_themes": []
}
CUSTOMER = {
    "customer_id": "cust_001",
    "identity": {"name": "Rahul Mehta", "language_pref": "en"},
    "state": "lapsed_soft",
    "relationship": {"visit_count": 3, "last_visit_days_ago": 45},
    "consent": {"scope": ["whatsapp"]},
}

for scope, cid, payload in [
    ("category", "dentists", CAT),
    ("merchant",  "m_001", MERCHANT),
    ("customer",  "cust_001", CUSTOMER),
]:
    s, d, ms = post("/v1/context", {
        "scope": scope, "context_id": cid, "version": 1,
        "payload": payload, "delivered_at": "2026-05-03T09:00:00Z"
    })
    print(f"  context/{scope} → {s} ({ms}ms) accepted={d.get('accepted')}")
    results[f"ctx_{scope}"] = s == 200 and d.get("accepted")

# ── PHASE 3: Trigger Coverage ──────────────────────────────────────────
sep("PHASE 3 — TRIGGER COVERAGE (10 kinds)")

TRIGGERS = [
    ("perf_dip", {"metric": "calls", "delta_pct": -0.35, "vs_baseline": 24}),
    ("regulation_change", {"topic_item_id": "d1", "top_item_id": "d1", "deadline_iso": "2026-06-01T00:00:00Z"}),
    ("recall_due", {"service_due": "6_month_recall", "available_slots": [{"label": "Thu 2pm"}, {"label": "Fri 10am"}]}, "cust_001"),
    ("gbp_unverified", {"estimated_uplift_pct": 0.34, "verification_path": "postcard"}),
    ("research_digest", {"top_item_id": "d1"}),
    ("cde_opportunity", {"digest_item_id": "d1"}),
    ("renewal_due", {"days_remaining": 12, "renewal_amount": 8500, "plan": "Pro"}),
    ("review_theme_emerged", {"theme": "waiting_time", "occurrences_30d": 7, "common_quote": "waited 40 min"}),
    ("competitor_opened", {"competitor_name": "SmileCare", "distance_km": 0.8, "their_offer": "₹499 cleaning"}),
    ("chronic_refill_due", {"molecule_list": ["Metformin 500", "Amlodipine 5mg"], "delivery_address_saved": True}, "cust_001"),
]

trigger_ids = []
for i, t in enumerate(TRIGGERS):
    kind = t[0]; p = t[1]; cust_id = t[2] if len(t) > 2 else None
    tid = f"trg_{kind}_{i}"
    trg_payload = {
        "id": tid, "kind": kind, "scope": "customer" if cust_id else "merchant",
        "source": "internal", "merchant_id": "m_001",
        "customer_id": cust_id,
        "payload": p, "urgency": 4,
        "suppression_key": f"{kind}:m_001:{i}",
        "expires_at": "2027-01-01T00:00:00Z"
    }
    s, d, ms = post("/v1/context", {
        "scope": "trigger", "context_id": tid, "version": 1,
        "payload": trg_payload, "delivered_at": "2026-05-03T09:00:00Z"
    })
    trigger_ids.append(tid)

# Run tick
s, tick_data, ms = post("/v1/tick", {
    "now": "2026-05-03T10:30:00Z",
    "available_triggers": trigger_ids
})
show("POST /v1/tick", s, tick_data, ms)
actions = tick_data.get("actions", [])
results["tick_status"] = s == 200
results["tick_actions_count"] = len(actions)
print(f"\n  Total actions returned: {len(actions)}")
for a in actions:
    body = a.get("body", "")
    kind = a.get("trigger_id", "?")
    print(f"\n  [{kind}]")
    print(f"  body: {body}")
    print(f"  cta: {a.get('cta')} | rationale: {a.get('rationale','')}")

# ── PHASE 4: Replay Engine Stress Test ────────────────────────────────
sep("PHASE 4 — REPLAY ENGINE STRESS TEST")

STOP_INPUTS = [
    ("stop", "stop"),
    ("STOP", "STOP"),
    ("dont_message", "don't message me"),
    ("unsubscribe", "unsubscribe me now"),
    ("leave_me", "leave me alone please"),
    ("hostile", "stop spamming me, this is useless"),
    ("no_thanks", "no thanks, not interested"),
]

print("\n--- A) STOP Handling ---")
for conv_id, msg in STOP_INPUTS:
    s, d, ms = post("/v1/reply", {
        "conversation_id": f"stop_{conv_id}",
        "merchant_id": "m_001", "from_role": "merchant",
        "message": msg, "received_at": "2026-05-03T10:00:00Z", "turn_number": 2
    })
    action = d.get("action"); body = d.get("body", "MISSING")
    ok = action == "end" and body == ""
    print(f"  '{msg}' → action={action} body={repr(body)} {'✓' if ok else '✗ FAIL'}")
    results[f"stop_{conv_id}"] = ok

print("\n--- B) Auto-Reply Loop ---")
auto_msg = "Thank you for contacting Sunshine Dental. Our team will respond shortly."
for i in range(1, 4):
    s, d, ms = post("/v1/reply", {
        "conversation_id": "auto_loop_test",
        "merchant_id": "m_001", "from_role": "merchant",
        "message": auto_msg, "received_at": "2026-05-03T10:00:00Z", "turn_number": i+1
    })
    print(f"  Turn {i+1}: action={d.get('action')} body={repr(d.get('body','')[:80])}")

print("\n--- C) Commitment → Action Mode ---")
conv = "commit_test_01"
s, d, ms = post("/v1/reply", {
    "conversation_id": conv, "merchant_id": "m_001", "from_role": "merchant",
    "message": "Yes please go ahead", "received_at": "2026-05-03T10:00:00Z", "turn_number": 2
})
body = d.get("body", "")
print(f"  action={d.get('action')} body={repr(body)}")
has_ai_speak = any(w in body.lower() for w in ["operational", "execute", "deploy", "authorize", "queueing"])
print(f"  AI-speak detected: {'YES ✗' if has_ai_speak else 'NO ✓'}")
results["commitment_no_ai_speak"] = not has_ai_speak

print("\n--- D) Soft Hesitation ---")
for msg in ["maybe next week", "busy right now", "after Diwali, let's talk"]:
    s, d, ms = post("/v1/reply", {
        "conversation_id": f"hes_{msg[:8].replace(' ','_')}",
        "merchant_id": "m_001", "from_role": "merchant",
        "message": msg, "received_at": "2026-05-03T10:00:00Z", "turn_number": 2
    })
    action = d.get("action"); body = d.get("body", "")
    robotic = any(w in body.lower() for w in ["execution", "operational", "protocol", "queueing"])
    print(f"  '{msg}' → action={action}")
    print(f"  body: {repr(body[:100])}")
    print(f"  Robotic language: {'YES ✗' if robotic else 'NO ✓'}")

print("\n--- E) Engaged Continuation ---")
s, d, ms = post("/v1/reply", {
    "conversation_id": "engage_test_01", "merchant_id": "m_001", "from_role": "merchant",
    "message": "What kind of post do you recommend for a Tuesday evening?",
    "received_at": "2026-05-03T10:00:00Z", "turn_number": 2
})
print(f"  action={d.get('action')} body={repr(d.get('body','')[:150])}")

# ── PHASE 5: Message Realism Analysis ─────────────────────────────────
sep("PHASE 5 — HUMAN REALISM ANALYSIS")

robot_terms = ["operational", "execute", "deploy", "authorize", "queueing",
               "protocol", "initiate", "operational block", "execution sequence",
               "bleeding traffic", "impression share is slipping"]

if actions:
    print("\nAnalyzing tick actions for robot language:")
    clean = 0
    for a in actions:
        body = a.get("body", "")
        found = [t for t in robot_terms if t in body.lower()]
        if found:
            print(f"  ✗ [{a.get('trigger_id')}] Contains: {found}")
            print(f"    body: {body[:100]}")
        else:
            clean += 1
    print(f"\n  Clean messages: {clean}/{len(actions)}")
    results["realism_clean_pct"] = round(clean / len(actions) * 100) if actions else 0

# ── FINAL SUMMARY ──────────────────────────────────────────────────────
sep("FINAL TEST SUMMARY")
passed = sum(1 for v in results.values() if v is True or (isinstance(v, int) and v > 0))
total  = len(results)
print(f"\nResults: {results}")
print(f"\nPassed checks: {passed}/{total}")

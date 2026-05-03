import json
import time
import httpx

BOT_URL = "https://ai-vera-production-9d79.up.railway.app"

def test_endpoint(method, path, payload=None):
    url = f"{BOT_URL}{path}"
    print(f"Testing {method} {url}...")
    try:
        if method == "GET":
            resp = httpx.get(url, timeout=30)
        else:
            resp = httpx.post(url, json=payload, timeout=30)
        
        print(f"  Status: {resp.status_code}")
        print(f"  Response: {resp.text[:200]}")
        return resp
    except Exception as e:
        print(f"  Error: {e}")
        return None

def run_simulation():
    print("="*60)
    print("Vera AI — Judge Simulator & Deployment Readiness")
    print("="*60)

    # 1. GET /
    test_endpoint("GET", "/")

    # 2. GET /v1/healthz
    test_endpoint("GET", "/v1/healthz")

    # 3. GET /v1/metadata
    test_endpoint("GET", "/v1/metadata")

    # 4. POST /v1/context (Merchant)
    context_payload = {
      "scope": "merchant",
      "context_id": "m_test_001",
      "version": 1,
      "delivered_at": "2026-05-02T18:00:00Z",
      "payload": {
        "merchant_name": "Dr Bharat Dental",
        "category": "dentist",
        "offers": [{"title": "Dental Checkup", "price": 299}]
      }
    }
    test_endpoint("POST", "/v1/context", context_payload)

    # 5. POST /v1/tick
    tick_payload = {
      "tick_id": "tick_001",
      "timestamp": "2026-05-02T18:00:00Z",
      "now": "2026-05-02T18:00:00Z",
      "available_triggers": ["trg_test_001"]
    }
    test_endpoint("POST", "/v1/tick", tick_payload)

    # 6. POST /v1/reply (Replay Scenarios)
    now = "2026-05-02T18:00:00Z"
    scenarios = [
        ("Soft Decline", {"conversation_id": "conv_soft", "merchant_id": "m_test_001", "message": "maybe next week", "turn_number": 2, "received_at": now}),
        ("Hostile", {"conversation_id": "conv_hostile", "merchant_id": "m_test_001", "message": "stop messaging me", "turn_number": 2, "received_at": now}),
        ("Auto Reply", {"conversation_id": "conv_auto", "merchant_id": "m_test_001", "message": "Thank you for contacting us. We will get back shortly.", "turn_number": 2, "received_at": now}),
        ("Engaged", {"conversation_id": "conv_engaged", "merchant_id": "m_test_001", "message": "What offer should I run today?", "turn_number": 2, "received_at": now})
    ]

    for name, payload in scenarios:
        print(f"\n--- Scenario: {name} ---")
        test_endpoint("POST", "/v1/reply", payload)

    print("\n" + "="*60)
    print("Simulation Complete.")
    print("="*60)

if __name__ == "__main__":
    run_simulation()

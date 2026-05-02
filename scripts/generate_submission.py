"""
Generate submission.jsonl — 30 canonical test pair responses.

Usage:
    python scripts/generate_submission.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DATASET_DIR = ROOT / "dataset" / "expanded"
SEED_DIR = ROOT / "dataset"


def load_data():
    cats, merchants, customers, triggers = {}, {}, {}, {}

    # Try expanded first, fall back to seeds
    cat_dir = DATASET_DIR / "categories" if DATASET_DIR.exists() else SEED_DIR / "categories"
    for f in cat_dir.glob("*.json"):
        d = json.loads(f.read_text(encoding="utf-8"))
        cats[d.get("slug", f.stem)] = d

    def load_list(path, id_key):
        out = {}
        if path.exists():
            for f in path.glob("*.json"):
                d = json.loads(f.read_text(encoding="utf-8"))
                out[d.get(id_key, f.stem)] = d
        return out

    if DATASET_DIR.exists():
        merchants = load_list(DATASET_DIR / "merchants", "merchant_id")
        customers = load_list(DATASET_DIR / "customers", "customer_id")
        triggers = load_list(DATASET_DIR / "triggers", "id")
    else:
        for name, container, id_key in [
            ("merchants_seed.json", "merchants", "merchant_id"),
            ("customers_seed.json", "customers", "customer_id"),
            ("triggers_seed.json", "triggers", "id"),
        ]:
            path = SEED_DIR / name
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                for item in data.get(container, []):
                    if id_key in item:
                        {"merchants": merchants, "customers": customers, "triggers": triggers}[container][item[id_key]] = item

    return cats, merchants, customers, triggers


def load_test_pairs():
    pair_file = DATASET_DIR / "test_pairs.json"
    if pair_file.exists():
        return json.loads(pair_file.read_text(encoding="utf-8")).get("pairs", [])
    # Fallback: generate 30 pairs from available triggers
    return []


def generate_pairs_from_triggers(triggers, max_pairs=30):
    """Generate test pairs if test_pairs.json doesn't exist."""
    pairs = []
    seen_kinds = {}
    for i, (tid, t) in enumerate(triggers.items()):
        kind = t.get("kind", "")
        if seen_kinds.get(kind, 0) >= 2:
            continue
        pairs.append({
            "test_id": f"T{len(pairs)+1:02d}",
            "trigger_id": tid,
            "merchant_id": t.get("merchant_id", ""),
            "customer_id": t.get("customer_id"),
        })
        seen_kinds[kind] = seen_kinds.get(kind, 0) + 1
        if len(pairs) >= max_pairs:
            break
    return pairs


def main():
    from bot import compose

    print("Loading dataset…")
    cats, merchants, customers, triggers = load_data()
    print(f"  {len(cats)} categories, {len(merchants)} merchants, "
          f"{len(customers)} customers, {len(triggers)} triggers")

    pairs = load_test_pairs()
    if not pairs:
        print("  No test_pairs.json found — generating from triggers")
        pairs = generate_pairs_from_triggers(triggers)

    print(f"  {len(pairs)} test pairs to process")

    out_path = ROOT / "submission.jsonl"
    written = 0

    with open(out_path, "w", encoding="utf-8") as f:
        for pair in pairs[:30]:
            tid = pair["trigger_id"]
            mid = pair["merchant_id"]
            cid = pair.get("customer_id")

            trigger = triggers.get(tid)
            merchant = merchants.get(mid)
            customer = customers.get(cid) if cid else None

            if not trigger or not merchant:
                print(f"  [SKIP] {pair['test_id']}: missing data")
                continue

            cat_slug = merchant.get("category_slug", "")
            category = cats.get(cat_slug)
            if not category:
                print(f"  [SKIP] {pair['test_id']}: no category '{cat_slug}'")
                continue

            try:
                result = compose(category, merchant, trigger, customer)
                line = {
                    "test_id": pair["test_id"],
                    "trigger_id": tid,
                    "merchant_id": mid,
                    "body": result.get("body", ""),
                    "cta": result.get("cta", "open_ended"),
                    "send_as": result.get("send_as", "vera"),
                    "suppression_key": result.get("suppression_key", ""),
                    "rationale": result.get("rationale", ""),
                }
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
                written += 1
                print(f"  [{pair['test_id']}] {mid[:20]} / {trigger.get('kind','?')} — {len(result.get('body',''))} chars")
            except Exception as e:
                print(f"  [ERROR] {pair['test_id']}: {e}")

    print(f"\nDone — {written} entries written to {out_path}")


if __name__ == "__main__":
    main()

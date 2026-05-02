# Vera AI — magicpin Merchant Engagement Engine

A production-grade AI decision engine for the magicpin AI Challenge.

## Architecture

```
FastAPI (5 endpoints)
  └── Decision Engine (deterministic scoring, no LLM)
  └── Template Engine (15+ strategies, zero cost)
  └── LLM Enhancer (optional, temperature=0, cached)
  └── Replay State Machine (auto-reply, intent, hostile)
  └── Validation Pipeline (CTA, taboos, URL, repetition)
```

## Quick Start

```bash
# 1. Install deps
pip install -r requirements.txt

# 2. Copy and fill env
cp .env.example .env
# Edit .env with your LLM API key

# 3. Expand dataset
cd dataset && python generate_dataset.py --out ./expanded && cd ..

# 4. Run server
python -m uvicorn app.main:app --host 0.0.0.0 --port 8080

# 5. Run tests
pytest tests/ -v

# 6. Generate submission
python scripts/generate_submission.py
```

## Approach

**Template-first, LLM-enhanced:**
1. Deterministic templates cover 15+ trigger kinds with specificity baked in (real numbers from context, peer stats, deltas).
2. LLM (temperature=0) enhances when API key is available — same prompt → same output, cached by input hash.
3. Validation pipeline blocks hallucination, URLs, taboo words, repeated bodies.

**Decision Engine (no LLM):**
```
score = trigger_relevance×0.30 + merchant_need×0.25 + urgency×0.20
      + category_alignment×0.15 + customer_match×0.10
```

**Replay State Machine:**
- `auto_reply` → probe once → wait → end (max 2 auto-replies)
- `hostile/stop` → graceful exit immediately  
- `commitment` → action mode (no re-qualifying)
- `off_topic` → polite redirect

## Scoring Design

| Dimension | Design decision |
|---|---|
| Specificity | Numbers from context: views, calls, CTR, delta%, trial N |
| Category fit | Per-category system prompts + taboo enforcement |
| Merchant fit | Owner name, locality, language pref, active offers |
| Trigger relevance | Every template starts from trigger payload data |
| Engagement compulsion | Loss aversion / curiosity / social proof / single CTA |

## What Would Have Helped

- Real-time GBP data (verified vs unverified, actual missing fields)
- Historical conversation corpus per merchant (to calibrate follow-up timing)
- Actual customer appointment data (for more precise recall timing)

import sys
sys.path.insert(0,'.')
from app.decision.scoring_engine import ScoringEngine, TriggerPrioritizer
from app.storage.context_store import ContextStore, ConversationStore, SuppressionStore

ctx = ContextStore()
conv = ConversationStore()
supp = SuppressionStore()

cat = {"slug":"dentists","peer_stats":{"avg_ctr":0.032,"avg_reviews":68},"voice":{"tone":"clinical","vocab_taboo":[]},"digest":[],"offer_catalog":[],"seasonal_beats":[],"trend_signals":[]}
ctx.push("category","dentists",1,cat)
m = {"merchant_id":"m_001","category_slug":"dentists","identity":{"name":"Sunshine","owner_first_name":"Priya","locality":"Koramangala","city":"Bangalore","languages":["en"]},"subscription":{"status":"active","days_remaining":12},"performance":{"views":3842,"calls":24,"ctr":0.019,"delta_7d":{"views_pct":-0.28,"calls_pct":-0.35}},"offers":[],"signals":["perf_dip_severe"],"conversation_history":[],"customer_aggregate":{},"review_themes":[]}
ctx.push("merchant","m_001",1,m)

kinds = ["perf_dip","regulation_change","recall_due","gbp_unverified","research_digest","renewal_due","review_theme_emerged","competitor_opened","milestone_reached","winback_eligible"]
for kind in kinds:
    tid = "trg_" + kind
    trg = {"id":tid,"kind":kind,"scope":"merchant","source":"internal","merchant_id":"m_001","customer_id":None,"payload":{},"urgency":4,"suppression_key":kind+":m_001:x","expires_at":"2027-01-01T00:00:00Z"}
    ctx.push("trigger",tid,1,trg)

eng = ScoringEngine()
pri = TriggerPrioritizer(eng)
tids = ["trg_"+k for k in kinds]
scored = pri.prioritize(tids, ctx, supp, conv, 20)
print("Triggers passed scoring floor:", len(scored))
for s in scored:
    print(" ", s["trigger_id"], "score=", round(s["score"],2))
if not scored:
    print("ALL filtered out. Checking raw scores:")
    for tid in tids:
        trg = ctx.get("trigger", tid) or {}
        raw = eng.score(trg, m, cat, None)
        print(" ", tid, "raw=", round(raw,2))

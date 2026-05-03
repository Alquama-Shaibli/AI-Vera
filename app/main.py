"""
Vera AI — magicpin Merchant Engagement Engine
FastAPI server with all 5 required endpoints.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.core.config import (
    BOT_HOST, BOT_PORT, TEAM_NAME, TEAM_MEMBERS, CONTACT_EMAIL,
    LLM_PROVIDER, LLM_MODEL, VERSION, MAX_ACTIONS_PER_TICK,
)
from app.models.schemas import (
    ContextPushRequest, ContextPushResponse,
    TickRequest, TickResponse, TickAction,
    ReplyRequest, ReplyResponse,
    HealthResponse, ContextCounts, MetadataResponse,
)
from app.storage.context_store import ContextStore, ConversationStore, SuppressionStore
from app.decision.scoring_engine import ScoringEngine, TriggerPrioritizer
from app.generation.composer import MessageComposer
from app.generation.llm_client import LLMClient
from app.replay.state_machine import ReplayStateMachine

# ── Globals ────────────────────────────────────────────────────────────

_start_time = time.time()
_context_store = ContextStore()
_conversation_store = ConversationStore()
_suppression_store = SuppressionStore()
_scoring_engine = ScoringEngine()
_prioritizer = TriggerPrioritizer(_scoring_engine)
_replay_sm = ReplayStateMachine(_context_store, _conversation_store, _suppression_store)

# Lazy-init LLM client
_llm_client: Optional[LLMClient] = None
_composer: Optional[MessageComposer] = None


def _get_composer() -> MessageComposer:
    global _llm_client, _composer
    if _composer is None:
        try:
            _llm_client = LLMClient()
            logger.info(f"LLM client initialized: {LLM_PROVIDER}/{LLM_MODEL}")
        except Exception as e:
            logger.warning(f"LLM client unavailable: {e}; using templates only")
            _llm_client = None
        _composer = MessageComposer(llm_client=_llm_client)
    return _composer


# ── Lifespan ───────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Vera AI starting up (Instant Mode)…")
    yield
    logger.info("Vera AI shutting down.")


# ── App ────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Vera AI — Merchant Engagement Engine",
    version=VERSION,
    description="magicpin AI Challenge submission — Vera merchant assistant",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Root ───────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {"status": "online", "team": "Vera-Elite"}


# ── /v1/healthz ────────────────────────────────────────────────────────
@app.get("/v1/healthz")
def healthz():
    return {
        "status": "ok",
        "uptime_seconds": int(time.time() - _start_time),
        "contexts_loaded": _context_store.count_by_scope()
    }


# ── /v1/metadata ───────────────────────────────────────────────────────
@app.get("/v1/metadata")
def metadata():
    return {
        "name": "Vera AI",
        "team_name": TEAM_NAME,
        "team_members": TEAM_MEMBERS,
        "version": VERSION,
        "provider": LLM_PROVIDER,
        "model": LLM_MODEL,
        "approach": "deterministic",
        "deterministic": True,
        "status": "running"
    }


# ── /v1/context ────────────────────────────────────────────────────────

@app.post("/v1/context", response_model=ContextPushResponse)
async def push_context(req: ContextPushRequest):
    accepted, reason, current_version = _context_store.push(
        scope=req.scope,
        context_id=req.context_id,
        version=req.version,
        payload=req.payload,
    )
    if not accepted and reason == "stale_version":
        raise HTTPException(
            status_code=409,
            detail={
                "accepted": False,
                "reason": "stale_version",
                "current_version": current_version,
            },
        )
    return ContextPushResponse(
        accepted=accepted,
        ack_id=f"ack_{req.scope}_{req.context_id}_v{req.version}",
        stored_at=datetime.now(timezone.utc).isoformat(),
        reason=reason,
        current_version=req.version if accepted else current_version,
    )


# ── /v1/tick ───────────────────────────────────────────────────────────

@app.post("/v1/tick", response_model=TickResponse)
async def tick(req: TickRequest):
    start = time.time()
    composer = _get_composer()

    scored = _prioritizer.prioritize(
        available_trigger_ids=req.available_triggers,
        context_store=_context_store,
        suppression_store=_suppression_store,
        conversation_store=_conversation_store,
        max_actions=MAX_ACTIONS_PER_TICK,
    )

    actions: list[TickAction] = []
    for item in scored:
        trigger = item["trigger"]
        merchant = item["merchant"]
        category = item["category"]
        customer = item["customer"]

        # Compose message
        try:
            composed = composer.compose(
                category=category,
                merchant=merchant,
                trigger=trigger,
                customer=customer,
                score=item["score"],
            )
        except Exception as e:
            logger.error(f"Compose failed for {item['trigger_id']}: {e}")
            continue

        body = composed.get("body", "")
        if not body:
            continue

        # Generate conversation ID
        conv_id = f"conv_{item['trigger_id']}_{item['merchant_id'][:12]}"

        # Register conversation
        _conversation_store.create(
            conv_id=conv_id,
            merchant_id=item["merchant_id"],
            trigger_id=item["trigger_id"],
            customer_id=item.get("customer_id"),
        )

        # Suppress this key
        supp_key = composed.get("suppression_key", trigger.get("suppression_key", ""))
        if supp_key:
            _suppression_store.suppress(supp_key)

        actions.append(TickAction(
            conversation_id=conv_id,
            merchant_id=item["merchant_id"],
            customer_id=item.get("customer_id"),
            send_as=composed.get("send_as", "vera"),
            trigger_id=item["trigger_id"],
            template_name=composed.get("template_name", "vera_generic_v1"),
            template_params=composed.get("template_params", []),
            body=body,
            cta=composed.get("cta", "open_ended"),
            suppression_key=supp_key,
            rationale=composed.get("rationale", ""),
        ))

        elapsed = time.time() - start
        if elapsed > 8.0:  # leave buffer for 10s budget
            logger.warning(f"Tick budget nearly exhausted at {elapsed:.1f}s, stopping early")
            break

    logger.info(f"Tick: {len(scored)} scored → {len(actions)} actions in {(time.time()-start)*1000:.0f}ms")
    return TickResponse(actions=actions)


# ── /v1/reply ──────────────────────────────────────────────────────────

@app.post("/v1/reply", response_model=ReplyResponse)
async def reply(req: ReplyRequest):
    response = _replay_sm.handle_reply(
        conversation_id=req.conversation_id,
        merchant_id=req.merchant_id or "",
        customer_id=req.customer_id,
        message=req.message,
        turn_number=req.turn_number,
        composer=_get_composer(),
    )
    return response


# ── Entry point ────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.getenv("PORT", BOT_PORT))
    uvicorn.run("app.main:app", host=BOT_HOST, port=port, reload=False)

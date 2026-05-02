"""Pydantic v2 models for all API request/response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# ── /v1/context ────────────────────────────────────────────────────────

class ContextPushRequest(BaseModel):
    scope: Literal["category", "merchant", "customer", "trigger"]
    context_id: str
    version: int
    payload: dict[str, Any]
    delivered_at: str


class ContextPushResponse(BaseModel):
    accepted: bool
    ack_id: Optional[str] = None
    stored_at: Optional[str] = None
    reason: Optional[str] = None
    current_version: Optional[int] = None
    details: Optional[str] = None


# ── /v1/tick ───────────────────────────────────────────────────────────

class TickRequest(BaseModel):
    now: str
    available_triggers: list[str] = Field(default_factory=list)


class TickAction(BaseModel):
    conversation_id: str
    merchant_id: str
    customer_id: Optional[str] = None
    send_as: Literal["vera", "merchant_on_behalf"] = "vera"
    trigger_id: str
    template_name: str = "vera_generic_v1"
    template_params: list[str] = Field(default_factory=list)
    body: str
    cta: str = "open_ended"
    suppression_key: str = ""
    rationale: str = ""


class TickResponse(BaseModel):
    actions: list[TickAction] = Field(default_factory=list)


# ── /v1/reply ──────────────────────────────────────────────────────────

class ReplyRequest(BaseModel):
    conversation_id: str
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    from_role: str = "merchant"
    message: str
    received_at: str
    turn_number: int


class ReplyResponse(BaseModel):
    action: Literal["send", "wait", "end"]
    body: Optional[str] = None
    cta: Optional[str] = None
    wait_seconds: Optional[int] = None
    rationale: str = ""


# ── /v1/healthz ────────────────────────────────────────────────────────

class ContextCounts(BaseModel):
    category: int = 0
    merchant: int = 0
    customer: int = 0
    trigger: int = 0


class HealthResponse(BaseModel):
    status: str = "ok"
    uptime_seconds: int = 0
    contexts_loaded: ContextCounts = Field(default_factory=ContextCounts)


# ── /v1/metadata ───────────────────────────────────────────────────────

class MetadataResponse(BaseModel):
    team_name: str
    team_members: list[str]
    model: str
    approach: str
    contact_email: str
    version: str
    submitted_at: str

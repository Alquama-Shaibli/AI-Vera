"""
bot.py — submission interface. compose() and respond().
Calls hardened templates.py directly + optional LLM enhancement.
"""
from __future__ import annotations
import re
from typing import Optional
from app.generation.templates import build_template_message


def compose(category: dict, merchant: dict, trigger: dict, customer: Optional[dict] = None) -> dict:
    """Main composition interface — called by judge."""
    from app.services.self_critique import critique
    from app.generation.templates import _curious_ask, build_template_message

    # Step 1: Deterministic template build
    result = build_template_message(category, merchant, trigger, customer)
    
    # Step 2: Try LLM enhancement
    try:
        from app.generation.llm_client import LLMClient
        from app.generation.composer import MessageComposer
        llm = LLMClient()
        if llm.is_available():
            c = MessageComposer(llm_client=llm)
            enhanced = c.compose(category, merchant, trigger, customer, score=7.0)
            if enhanced and len(enhanced.get("body", "")) > 30:
                result = enhanced
    except Exception:
        pass

    # Step 3: Self-Critique & Validation
    result = critique(result, category, merchant, trigger, customer)
    
    # If rejected or has URLs, fallback to a safe, hardened curious_ask
    body = result.get("body", "")
    if result.get("rejected") or not body or re.search(r"https?://", body):
        fallback = _curious_ask(category, merchant, trigger, customer)
        # Re-critique the fallback to ensure it passes
        result = critique(fallback, category, merchant, trigger, customer)
        result["rationale"] = f"Fallback due to quality rejection: {result.get('rationale')}"

    return result


# ── Multi-turn handler ─────────────────────────────────────────────────

_AUTO = [r"thank you for contacting", r"our team will respond", r"automated (message|assistant)",
         r"auto.?reply", r"aapki madad ke liye", r"we will get back", r"currently not available"]
_COMMIT = [r"\byes\b", r"\bha[anh]\b", r"let'?s do it", r"go ahead", r"ok let'?s",
           r"proceed", r"confirm", r"chalega", r"karo", r"sounds good"]
_HOSTILE = [r"stop mess?aging", r"do not contact", r"\bspam\b", r"not interested",
            r"remove my number", r"unsubscribe", r"band karo", r"nahin chahiye"]
_OFF = [r"\bweather\b", r"\bcricket score\b", r"\bjob\b", r"\bloan\b",
        r"who are you", r"aap kaun"]


def respond(state: dict, merchant_message: str) -> dict:
    """Multi-turn reply handler — now uses ReplayStateMachine for elite realism."""
    from app.replay.state_machine import ReplayStateMachine
    from app.storage.context_store import ContextStore, ConversationStore, SuppressionStore
    
    # Initialize components
    context_store = ContextStore()
    conversation_store = ConversationStore()
    suppression_store = SuppressionStore()
    rsm = ReplayStateMachine(context_store, conversation_store, suppression_store)
    
    conversation_id = state.get("conversation_id", "default")
    merchant_id = state.get("merchant_id", "unknown")
    customer_id = state.get("customer_id")
    turn = state.get("turn", 2)
    
    # Process through state machine
    res = rsm.handle_reply(
        conversation_id=conversation_id,
        merchant_id=merchant_id,
        customer_id=customer_id,
        message=merchant_message,
        turn_number=turn
    )
    
    # Convert ReplyResponse schema to judge-compatible dict
    out = {
        "action": res.action,
        "rationale": res.rationale
    }
    if res.body:
        out["body"] = res.body
    if res.cta and res.cta != "none":
        out["cta"] = res.cta
    if res.wait_seconds:
        out["wait_seconds"] = res.wait_seconds
        
    return out

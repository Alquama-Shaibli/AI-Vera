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
    
    # Step 2: Try LLM enhancement if score is high enough or if template is weak
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
    """Multi-turn reply handler with momentum and memory."""
    msg = merchant_message.lower()
    mid = state.get("merchant_id", "unknown")
    auto_cnt = state.get("auto_reply_count", 0)
    turn = state.get("turn", 2)
    
    from app.services.merchant_memory import get_memory
    from app.generation.compression import compress
    memory = get_memory()

    # Helper to return compressed response
    def _resp(action, body=None, cta="none", rationale=""):
        res = {"action": action, "rationale": rationale}
        if body:
            res["body"] = compress(body)
        if cta != "none":
            res["cta"] = cta
        return res

    # Detect intent and update summary
    for p in _HOSTILE:
        if re.search(p, msg, re.I):
            memory.update_summary(mid, "merchant_interested", False)
            return _resp("end", "Understood — I'll stop reaching out. Here if you need help anytime 🙏",
                         rationale="Hostile — graceful exit")

    for p in _AUTO:
        if re.search(p, msg, re.I):
            if auto_cnt >= 2:
                return _resp("end", rationale="Auto-reply limit")
            if auto_cnt == 1:
                return {"action": "wait", "wait_seconds": 3600, "rationale": "Second auto-reply"}
            return _resp("send", "Looks like an auto-reply! If you're the owner, happy to chat later. Still interested?",
                         cta="binary_yes_no", rationale="Auto-reply probe")

    for p in _COMMIT:
        if re.search(p, msg, re.I):
            memory.update_summary(mid, "merchant_interested", True)
            return _resp("send", "Perfect! I'm on it. Will confirm once done. Anything else?",
                         cta="open_ended", rationale="Commitment — action mode")

    # Soft decline / Objections
    if any(x in msg for x in ["next week", "later", "not now", "busy"]):
        memory.update_summary(mid, "merchant_interested", "maybe_later")
        return {"action": "wait", "wait_seconds": 86400 * 7,
                "body": compress("No problem! I'll check back next week. Focus on your rush for now 🙏"),
                "rationale": "Soft decline — momentum reduction"}

    for p in _OFF:
        if re.search(p, msg, re.I):
            return _resp("send", "That's outside what I can help with, but I'm here for your growth. Pick up where we left off?",
                         cta="open_ended", rationale="Off-topic redirect")

    if turn >= 6:
        return _resp("end", "Koi baat nahi — jab zaroorat ho main yahan hoon 🙏",
                     rationale="Max turns")

    # Adaptive momentum based on summary
    summary = memory.get_summary(mid)
    if summary.get("merchant_interested") == "maybe_later":
         return {"action": "wait", "wait_seconds": 86400, "rationale": "Respecting delay"}

    return _resp("send", "Got it! Happy to handle this whenever you're ready. Just say the word.",
                 cta="open_ended", rationale="Engaged — continuing")

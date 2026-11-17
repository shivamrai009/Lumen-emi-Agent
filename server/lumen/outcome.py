"""The structured outcome record written at the end of every call."""

from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

from loguru import logger

from lumen.state import CallState

OUTCOMES_DIR = Path(__file__).resolve().parent.parent / "outcomes"

# Outcomes the agent may record. "no_response" and "call_dropped" are also set by
# code (caller went silent / hung up before the agent closed the call).
OUTCOMES = [
    "paid_already",
    "will_pay_on_time",
    "promise_to_pay",
    "hardship",
    "dispute",
    "callback_requested",
    "wrong_number",
    "third_party_answered",
    "verification_failed",
    "declined_to_talk",
    "no_response",
]
# Outcomes that only make sense after the caller is verified.
NEEDS_VERIFICATION = {"paid_already", "will_pay_on_time", "promise_to_pay", "hardship", "dispute"}
# Guardrail: these always go to a human, whatever the LLM asked for.
ALWAYS_ESCALATE = {"hardship", "dispute"}


def _p90(xs: list[float]) -> float | None:
    if not xs:
        return None
    if len(xs) == 1:
        return xs[0]
    return statistics.quantiles(xs, n=10, method="inclusive")[-1]


def write_outcome(
    state: CallState,
    *,
    outcome: str,
    promise_to_pay_date: str | None = None,
    callback_time: str | None = None,
    escalate_to_human: bool = False,
    escalation_reason: str | None = None,
    notes: str = "",
    ended_by: str = "agent",
) -> dict:
    record = {
        "borrower_id": state.borrower.id,
        "verified": state.verified,
        "outcome": outcome,
        "promise_to_pay_date": promise_to_pay_date,
        "callback_time": callback_time,
        "payment_link_sent": state.payment_link_sent,
        "escalate_to_human": escalate_to_human or outcome in ALWAYS_ESCALATE,
        "escalation_reason": escalation_reason,
        "language_at_end": state.language,
        "notes": notes,
    }
    lat = state.latencies_secs
    call = {
        "run_id": state.run_id,
        "ended_by": ended_by,
        "duration_secs": round(time.time() - state.started_at, 1),
        "user_turns": sum(1 for t in state.transcript if t["role"] == "user"),
        "agent_turns": sum(1 for t in state.transcript if t["role"] == "assistant"),
        "verify_attempts": state.verify_attempts,
        "latency_secs": {
            "first_speech": state.first_speech_latency_secs,
            "per_turn": [round(x, 3) for x in lat],
            "median": round(statistics.median(lat), 3) if lat else None,
            "p90": round(_p90(lat), 3) if lat else None,
        },
        "tool_events": state.tool_events,
        "llm_fallbacks": state.llm_fallbacks,
        "llm_requests": state.llm_requests,
        "llm_all_limited": state.llm_all_limited,
        "stt_redetections": state.stt_redetections,
        "transcript": state.transcript,
    }
    OUTCOMES_DIR.mkdir(exist_ok=True)
    path = OUTCOMES_DIR / f"{state.run_id}.json"
    path.write_text(json.dumps({"outcome": record, "call": call}, indent=2, ensure_ascii=False))
    state.outcome_written = True
    logger.info(f"Outcome recorded -> {path}: {json.dumps(record, ensure_ascii=False)}")
    return record

"""Per-call state shared by the tool handlers and the bot's event handlers.

Fields the outcome record must get right (who was called, whether they were
verified, whether a link went out) are tracked here by code, never taken from
the LLM's say-so.
"""

from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass, field

from lumen.data import Borrower

MAX_VERIFY_ATTEMPTS = 3


@dataclass
class CallState:
    borrower: Borrower
    today: dt.date
    run_id: str
    language: str = "en"
    verified: bool = False
    verify_attempts: int = 0
    payment_link_sent: bool = False
    payment_link_attempts: int = 0
    link_failure_mode: str = "never"  # "never" | "first" | "always" (mock fault injection)
    outcome_written: bool = False
    idle_prompts: int = 0
    started_at: float = field(default_factory=time.time)
    transcript: list[dict] = field(default_factory=list)
    latencies_secs: list[float] = field(default_factory=list)
    first_speech_latency_secs: float | None = None
    tool_events: list[dict] = field(default_factory=list)
    # LLM turns answered by the fallback model because the primary was rate-limited.
    llm_fallbacks: list[dict] = field(default_factory=list)
    # How many LLM requests each model answered, and how often every model was limited.
    llm_requests: dict[str, int] = field(default_factory=dict)
    llm_all_limited: int = 0
    # Utterances Whisper heard as a language other than English or Hindi (re-transcribed).
    stt_redetections: int = 0
    # end_call came with no spoken goodbye: hang up after the agent's next reply.
    hang_up_after_reply: bool = False

    @property
    def verification_locked(self) -> bool:
        return not self.verified and self.verify_attempts >= MAX_VERIFY_ATTEMPTS

    def log(self, role: str, text: str) -> None:
        self.transcript.append(
            {"t": round(time.time() - self.started_at, 2), "role": role, "text": text}
        )

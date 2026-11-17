"""Tools the agent can call, and their mock backends.

Each handler reads the per-call CallState from ``params.app_resources``. The
lookups are mocks with realistic delays (and optional fault injection) so the
"no dead air" and "tool failure" behaviour can be exercised and measured.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import os
import random
import re
import time

from loguru import logger
from pipecat.adapters.llm.schemas.function_schema import FunctionSchema
from pipecat.frames.frames import (
    EndWorkerFrame,
    FunctionCallResultProperties,
    TTSSpeakFrame,
    TTSUpdateSettingsFrame,
)
from pipecat.services.kokoro.tts import KokoroTTSService
from pipecat.services.llm_service import FunctionCallParams
from pipecat.transcriptions.language import Language

from lumen import speech
from lumen.data import loan_facts
from lumen.outcome import NEEDS_VERIFICATION, OUTCOMES, write_outcome
from lumen.parse import MONTHS, parse_date, parse_digits
from lumen.parse import _norm as _norm_word
from lumen.state import MAX_VERIFY_ATTEMPTS, CallState

LOOKUP_DELAY = float(os.getenv("MOCK_LOOKUP_DELAY_SECS", "0.6"))
LINK_DELAY = float(os.getenv("MOCK_LINK_DELAY_SECS", "2.5"))
# If a tool is still running after this long, the agent says a short filler line
# so the caller never sits in silence.
FILLER_AFTER = float(os.getenv("FILLER_AFTER_SECS", "1.2"))

FILLERS = {
    "en": ["Just a second, it's going through.", "Almost there, one moment."],
    "hi": ["बस एक सेकंड, भेज रही हूँ।", "बस एक पल।"],
}

BRIDGES = {
    "en": "Thanks, one moment while I check that.",
    "hi": "धन्यवाद, एक पल, मैं चेक कर लेती हूँ।",
}


def _state(params: FunctionCallParams) -> CallState:
    return params.app_resources


def _record(state: CallState, name: str, **data) -> None:
    state.tool_events.append({"t": round(time.time() - state.started_at, 2), "tool": name, **data})


async def _with_filler(params: FunctionCallParams, coro):
    """Run a slow backend call; if it overruns FILLER_AFTER, speak a filler line."""
    state = _state(params)
    task = asyncio.ensure_future(coro)
    done, _ = await asyncio.wait({task}, timeout=FILLER_AFTER)
    if not done:
        line = random.choice(FILLERS.get(state.language, FILLERS["en"]))
        await params.llm.push_frame(TTSSpeakFrame(line, append_to_context=False))
        _record(state, "filler", text=line)
    return await task


# --- verify_identity ---------------------------------------------------------


def _normalise_digits(s: str | None) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())


def _has_date_or_digits(text: str) -> bool:
    return bool(parse_digits(text)) or any(
        _norm_word(w) in MONTHS for w in re.split(r"[\s,.]+", text)
    )


def _heard_from_caller(params: FunctionCallParams) -> str | None:
    """What the caller actually said, read from the call transcript rather than the LLM.

    Seen in evals: the fallback model called verify_identity before the caller had given
    anything, with caller_words it made up ("I was born on twenty two May nineteen ninety
    six"). That used an attempt and the agent then read a stranger's date of birth back.
    So the words come from the transcript: the caller's latest turn, or their last two
    joined when a date was given in pieces. None if there is no transcript to read
    (unit tests), or "" if the caller hasn't said a date or digits yet.
    """
    context = getattr(params, "context", None)
    if context is None:
        return None
    said = [
        m["content"]
        for m in context.get_messages()
        if isinstance(m, dict) and m.get("role") == "user" and isinstance(m.get("content"), str)
    ]
    last = said[-1].strip() if said else ""
    both = " ".join(said[-2:]).strip()
    if parse_date(last) is not None:
        return last
    # A date given in pieces ("fourteenth of March" ... "nineteen eighty-eight"): join the
    # two turns, but only when the earlier one was an unfinished date.
    if len(said) > 1 and parse_date(said[-2]) is None and parse_date(both) is not None:
        return both
    # Four digits given in pieces ("four eight" ... "two one"): seen on live calls, where
    # a pause mid-number ended the caller's turn.
    if len(said) > 1 and 0 < len(parse_digits(last)) < 4 and len(parse_digits(both)) >= 4:
        return both
    return last if _has_date_or_digits(last) else ""


def _what_to_check(args: dict, heard: str | None = None) -> tuple[dict | None, str | None]:
    """Decide what to verify from the caller's own words; returns (checked, problem).

    The caller's words are parsed by code (lumen/parse.py). The LLM's own conversion
    (date_of_birth / phone_last4) is used only when the words hold numbers the parser
    can't read, and a value the caller never said is refused: in evals the LLM turned
    "तीस जनवरी, उन्नीस सौ उन्यासी" into 1985-01-15 and invented phone_last4 "1234".

    ``heard`` is the caller's words from the transcript; when given it replaces the
    LLM's caller_words, so the model can't supply words the caller never said.
    """
    words = (args.get("caller_words") or "").strip() if heard is None else heard
    llm_dob = (args.get("date_of_birth") or "").strip()
    llm_last4 = _normalise_digits(args.get("phone_last4"))
    if heard == "":
        return None, (
            "The caller hasn't said a date of birth or any digits yet, so nothing was checked "
            "and no attempt was used. Ask them for it and wait for their answer."
        )
    if not words:
        return None, (
            "Pass caller_words: the caller's exact words with their date of birth or digits. "
            "Nothing was checked and no attempt was used."
        )
    said_digits = parse_digits(words)
    said_month = any(_norm_word(w) in MONTHS for w in re.split(r"[\s,.]+", words))
    if (d := parse_date(words)) is not None:
        return {"date_of_birth": d.isoformat(), "read_by": "code"}, None
    if len(said_digits) >= 4 and not said_month:
        return {"phone_last4": said_digits[-4:], "read_by": "code"}, None
    if not said_digits and not said_month:
        return None, (
            "The caller's words contain no date or digits, so nothing was checked and no attempt "
            "was used. Ask them for it; never fill in a value they didn't say."
        )
    if llm_dob and said_month:
        return {"date_of_birth": llm_dob, "read_by": "llm"}, None
    if llm_last4 and len(llm_last4) == 4 and said_digits:
        return {"phone_last4": llm_last4, "read_by": "llm"}, None
    return None, (
        "Couldn't make out a full date of birth (day, month and year) or four digits from "
        "that, so nothing was checked and no attempt was used. Ask them to say it again."
    )


def _spoken_check(checked: dict, language: str) -> str:
    if "date_of_birth" in checked:
        d = dt.date.fromisoformat(checked["date_of_birth"])
        return speech.dob_hi(d) if language == "hi" else speech.dob_en(d)
    digits = checked["phone_last4"]
    return speech.digits_hi(digits) if language == "hi" else speech.digits_en(digits)


async def verify_identity(params: FunctionCallParams):
    state = _state(params)
    b = state.borrower

    if state.verified:
        await params.result_callback({"verified": True, "loan": loan_facts(b, state.today)})
        return
    if state.verification_locked:
        await params.result_callback(
            {
                "verified": False,
                "attempts_remaining": 0,
                "instruction": "Attempts exhausted. End the call (verification_failed) without sharing any details.",
            }
        )
        return

    checked, problem = _what_to_check(params.arguments, _heard_from_caller(params))
    if problem or checked is None:
        await params.result_callback({"checked": None, "error": problem})
        return

    if not getattr(params.llm, "spoke_in_current_response", True):
        # The prompt asks for a bridge line before this tool, but the model often calls it
        # with no words. In the voice evals that made this the slowest turn of the call
        # (4.9 s of silence: end-of-turn wait, transcription, two LLM requests and the
        # lookup). So the bridge is spoken from here, as soon as the check starts.
        line = BRIDGES.get(state.language, BRIDGES["en"])
        await params.llm.push_frame(TTSSpeakFrame(line, append_to_context=False))
        _record(state, "bridge", text=line)
    await asyncio.sleep(LOOKUP_DELAY)  # mock CRM lookup
    match = checked.get("date_of_birth") == b.date_of_birth or (
        checked.get("phone_last4") == b.phone_last4
    )
    state.verify_attempts += 1
    _record(state, "verify_identity", **checked, match=match)

    if match:
        state.verified = True
        await params.result_callback({"verified": True, "loan": loan_facts(b, state.today)})
        return

    remaining = MAX_VERIFY_ATTEMPTS - state.verify_attempts
    heard = _spoken_check(checked, state.language)
    result = {"verified": False, "attempts_remaining": remaining, "checked_said_as": heard}
    if remaining <= 0:
        result["instruction"] = (
            "Attempts exhausted. Share no details. Say you can't continue without verification, "
            "suggest they call Lumen Finance from their registered number, and end the call (verification_failed)."
        )
    else:
        result["instruction"] = (
            f"That didn't match. Read back exactly what was checked, \"{heard}\", and ask if that's "
            "what they said. If not, call verify_identity again with their corrected words. If it "
            "was right, say it doesn't match, without revealing the correct value, and ask for the "
            "other option (date of birth, or last four digits of the registered mobile)."
        )
    await params.result_callback(result)


VERIFY_IDENTITY = FunctionSchema(
    name="verify_identity",
    description=(
        "Check the caller's identity. Call after they confirm their name and give either their "
        "date of birth or the last four digits of their registered mobile number. On success it "
        "returns the loan details to discuss, with amounts and dates already written as words to say."
    ),
    properties={
        "caller_words": {
            "type": "string",
            "description": "The caller's exact words that contain their date of birth or the "
            "digits, copied as they said them (any language). Code reads the value from these.",
        },
        "date_of_birth": {
            "type": ["string", "null"],
            "description": "Your reading of the date as YYYY-MM-DD (used only if the words can't be read).",
        },
        "phone_last4": {
            "type": ["string", "null"],
            "description": "Your reading of the last four digits (used only if the words can't be read).",
        },
    },
    required=["caller_words"],
    handler=verify_identity,
)


# --- send_payment_link -------------------------------------------------------


class PaymentGatewayError(Exception):
    pass


LINK_WORDS = re.compile(r"link|sms|text me|लिंक|एसएमएस|मैसेज", re.I)


def _link_was_discussed(params: FunctionCallParams) -> bool:
    """Whether a payment link has come up on the call: offered by the agent in an earlier
    turn, or asked for by the caller. True when there is no transcript to read (unit tests).
    """
    context = getattr(params, "context", None)
    if context is None:
        return True
    return any(
        isinstance(m, dict)
        and m.get("role") in ("user", "assistant")
        and isinstance(m.get("content"), str)
        and LINK_WORDS.search(m["content"])
        for m in context.get_messages()
    )


async def _mock_send_link(state: CallState) -> str:
    await asyncio.sleep(LINK_DELAY)
    mode = state.link_failure_mode
    if mode == "always" or (mode == "first" and state.payment_link_attempts == 1):
        raise PaymentGatewayError("SMS gateway timeout")
    return f"https://pay.lumen.example/{state.borrower.id.lower()}-{state.run_id[:6]}"


async def send_payment_link(params: FunctionCallParams):
    state = _state(params)
    if not state.verified:
        await params.result_callback(
            {"sent": False, "error": "Not allowed before the caller is verified."}
        )
        return
    if state.payment_link_sent:
        await params.result_callback(
            {"sent": True, "note": "Already sent on this call; don't send again."}
        )
        return

    if not _link_was_discussed(params):
        # Seen in a voice eval: the caller said "fine, I'll pay on Friday" and the agent
        # sent a link nobody had mentioned. Sending an SMS needs the caller's yes.
        await params.result_callback(
            {
                "sent": False,
                "error": "Nothing was sent: the caller hasn't been offered a payment link yet. "
                "Ask whether they'd like one by SMS, and send it only if they say yes.",
            }
        )
        return

    state.payment_link_attempts += 1
    try:
        url = await _with_filler(params, _mock_send_link(state))
    except PaymentGatewayError as e:
        _record(state, "send_payment_link", ok=False, error=str(e))
        await params.result_callback(
            {"sent": False, "error": "The SMS didn't go through (gateway timeout)."}
        )
        return
    state.payment_link_sent = True
    _record(state, "send_payment_link", ok=True, url=url)
    await params.result_callback({"sent": True, "channel": "sms", "to": "registered mobile number"})


SEND_PAYMENT_LINK = FunctionSchema(
    name="send_payment_link",
    description="Send a secure payment link by SMS to the borrower's registered mobile number. Only after verification and after they agree to receive it.",
    properties={},
    required=[],
    handler=send_payment_link,
)


# --- set_language ------------------------------------------------------------


async def set_language(params: FunctionCallParams):
    state = _state(params)
    lang = params.arguments.get("language")
    if lang not in ("en", "hi"):
        await params.result_callback({"error": "language must be 'en' or 'hi'"})
        return
    if lang != state.language:
        state.language = lang
        tts_lang = Language.HI if lang == "hi" else Language.EN
        await params.llm.push_frame(
            TTSUpdateSettingsFrame(delta=KokoroTTSService.Settings(language=tts_lang))
        )
        _record(state, "set_language", language=lang)
    hint = (
        "Continue in Hindi (Devanagari), using the spoken_hi amounts and dates."
        if lang == "hi"
        else "Continue in English."
    )
    await params.result_callback({"language": lang, "instruction": hint})


SET_LANGUAGE = FunctionSchema(
    name="set_language",
    description="Switch the language you speak in. Call when the caller switches to or asks for Hindi or English.",
    properties={"language": {"type": "string", "enum": ["en", "hi"]}},
    required=["language"],
    handler=set_language,
)


# --- end_call ----------------------------------------------------------------


async def end_call(params: FunctionCallParams):
    state = _state(params)
    a = params.arguments
    outcome = a.get("outcome")
    ptp = a.get("promise_to_pay_date") or None

    if state.outcome_written:
        # Already recorded (e.g. the agent was asked to say goodbye first): just hang up.
        await params.result_callback(
            {"ended": True}, properties=FunctionCallResultProperties(run_llm=False)
        )
        await params.llm.push_frame(EndWorkerFrame())
        return

    # Validate, and hand problems back to the LLM so it can fix them on the call.
    problem = None
    if outcome not in OUTCOMES:
        problem = f"Unknown outcome {outcome!r}."
    elif outcome in NEEDS_VERIFICATION and not state.verified:
        problem = f"'{outcome}' needs a verified caller, and this caller is not verified. Pick an outcome that fits an unverified call."
    elif outcome == "promise_to_pay":
        try:
            d = dt.date.fromisoformat(ptp or "")
        except ValueError:
            problem = "promise_to_pay needs promise_to_pay_date as YYYY-MM-DD. Ask the caller for a specific date if you don't have one."
        else:
            if d < state.today:
                problem = f"promise_to_pay_date {ptp} is in the past (today is {state.today.isoformat()}). Confirm the date with the caller."
    if (
        not problem
        and outcome in ("will_pay_on_time", "promise_to_pay")
        and state.payment_link_attempts == 0
        and not a.get("payment_link_declined")
    ):
        # Seen in evals: the agent said "sending that now" and hung up without sending it.
        problem = (
            "No payment link was sent on this call. If the caller already agreed to one, call "
            "send_payment_link now. If you haven't asked, ask whether they'd like it by SMS and "
            "send it only if they say yes. If they don't want one, call end_call again with "
            "payment_link_declined true."
        )
    if problem:
        logger.warning(f"end_call rejected: {problem}")
        await params.result_callback({"ended": False, "error": problem})
        return

    write_outcome(
        state,
        outcome=outcome,
        promise_to_pay_date=ptp if outcome == "promise_to_pay" else None,
        callback_time=a.get("callback_time") or None,
        escalate_to_human=bool(a.get("escalate_to_human")),
        escalation_reason=a.get("escalation_reason") or None,
        notes=a.get("notes") or "",
    )
    if not getattr(params.llm, "spoke_in_current_response", True):
        # Seen in evals: end_call with no goodbye, so the caller hears silence and a dead
        # line. Keep the outcome, get a goodbye said, and hang up after it (bot.py).
        state.hang_up_after_reply = True
        await params.result_callback(
            {
                "ended": False,
                "recorded": True,
                "instruction": "You hung up without saying anything. Say a short goodbye now "
                "(for a wrong number, apologise for the trouble). The call ends right after it; "
                "don't call end_call again.",
            }
        )
        return
    # Don't run the LLM again: the goodbye was already said in this turn.
    await params.result_callback(
        {"ended": True}, properties=FunctionCallResultProperties(run_llm=False)
    )
    # Downstream, so the goodbye still queued in TTS plays before the pipeline ends.
    await params.llm.push_frame(EndWorkerFrame())


END_CALL = FunctionSchema(
    name="end_call",
    description="Record the call outcome and hang up. Call exactly once, in the same turn as your spoken goodbye.",
    properties={
        "outcome": {"type": "string", "enum": OUTCOMES},
        "promise_to_pay_date": {
            "type": ["string", "null"],
            "description": "YYYY-MM-DD; required when outcome is promise_to_pay.",
        },
        "callback_time": {
            "type": ["string", "null"],
            "description": "When to call back, as the caller said it, if they gave one.",
        },
        "escalate_to_human": {
            "type": "boolean",
            "description": "True for disputes, hardship, or when they ask for a person.",
        },
        "escalation_reason": {"type": ["string", "null"]},
        "payment_link_declined": {
            "type": ["boolean", "null"],
            "description": "True if the caller said they don't want a payment link.",
        },
        "notes": {
            "type": "string",
            "description": "One or two factual sentences about what the caller said.",
        },
    },
    required=["outcome", "escalate_to_human", "notes"],
    handler=end_call,
)

ALL_TOOLS = [VERIFY_IDENTITY, SEND_PAYMENT_LINK, SET_LANGUAGE, END_CALL]

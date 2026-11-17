"""Deterministic tests for the parts of the agent that must not depend on the LLM:
spoken formatting, the verification gate, outcome validation, and fault handling."""

import asyncio
import datetime as dt
import json
from types import SimpleNamespace

import pytest
from pipecat.frames.frames import EndWorkerFrame, TTSSpeakFrame

from lumen import outcome as outcome_mod
from lumen import speech, tools
from lumen.data import load_borrowers
from lumen.state import CallState

TODAY = dt.date(2026, 11, 15)


@pytest.fixture(autouse=True)
def fast_mocks(monkeypatch, tmp_path):
    monkeypatch.setattr(tools, "LOOKUP_DELAY", 0)
    monkeypatch.setattr(tools, "LINK_DELAY", 0)
    monkeypatch.setattr(outcome_mod, "OUTCOMES_DIR", tmp_path)


def make_state(bid="B001", **kw) -> CallState:
    b = load_borrowers(TODAY)[bid]
    return CallState(
        borrower=b, today=TODAY, run_id=f"test-{bid}", language=b.preferred_language, **kw
    )


async def call(handler, state, _spoke=True, **arguments):
    results, pushed = [], []

    async def result_callback(result, properties=None):
        results.append(result)

    async def push_frame(frame, *a, **k):
        pushed.append(frame)

    params = SimpleNamespace(
        arguments=arguments,
        app_resources=state,
        result_callback=result_callback,
        llm=SimpleNamespace(push_frame=push_frame, spoke_in_current_response=_spoke),
    )
    await handler(params)
    return results[-1], pushed


def run(coro):
    return asyncio.run(coro)


# --- speech ---


@pytest.mark.parametrize(
    "n,en,hi",
    [
        (12500, "twelve thousand five hundred", "बारह हज़ार पाँच सौ"),
        (4850, "four thousand eight hundred and fifty", "चार हज़ार आठ सौ पचास"),
        (23075, "twenty-three thousand and seventy-five", "तेईस हज़ार पचहत्तर"),
        (150000, "one lakh fifty thousand", "एक लाख पचास हज़ार"),
    ],
)
def test_numbers(n, en, hi):
    assert speech.number_en(n) == en
    assert speech.number_hi(n) == hi


def test_dates():
    assert speech.date_en(dt.date(2026, 11, 20), TODAY) == "Friday, the twentieth of November"
    assert speech.date_en(dt.date(2026, 12, 5), TODAY) == "the fifth of December"
    assert speech.ordinal_en(22) == "twenty-second"


# --- verification gate ---


def test_no_loan_details_without_verification():
    s = make_state()
    res, _ = run(call(tools.verify_identity, s, caller_words="first January 1990"))
    assert res["verified"] is False
    blob = json.dumps(res)
    assert "12500" not in blob and "twelve thousand" not in blob and "loan" not in res


def test_verify_by_dob_or_last4():
    s = make_state()
    res, _ = run(
        call(tools.verify_identity, s, caller_words="fourteenth of March, nineteen eighty-eight")
    )
    assert (
        res["verified"]
        and res["loan"]["spoken_en"]["emi_amount"] == "twelve thousand five hundred rupees"
    )
    s2 = make_state()
    res2, _ = run(call(tools.verify_identity, s2, caller_words="forty-eight twenty-one"))
    assert res2["verified"]


def test_verification_locks_after_three_misses():
    s = make_state()
    for _ in range(3):
        res, _ = run(call(tools.verify_identity, s, caller_words="zero zero zero zero"))
    assert res["attempts_remaining"] == 0 and s.verification_locked
    # Even the right answer is refused once locked.
    res, _ = run(call(tools.verify_identity, s, caller_words="4821"))
    assert res["verified"] is False and not s.verified


def test_payment_link_refused_before_verification():
    s = make_state()
    res, _ = run(call(tools.send_payment_link, s))
    assert res["sent"] is False and not s.payment_link_sent


# --- payment link faults + filler ---


def test_payment_link_fails_once_then_succeeds():
    s = make_state(link_failure_mode="first")
    s.verified = True
    res, _ = run(call(tools.send_payment_link, s))
    assert res["sent"] is False
    res, _ = run(call(tools.send_payment_link, s))
    assert res["sent"] is True and s.payment_link_sent


def test_slow_link_speaks_filler(monkeypatch):
    monkeypatch.setattr(tools, "LINK_DELAY", 0.3)
    monkeypatch.setattr(tools, "FILLER_AFTER", 0.05)
    s = make_state()
    s.verified = True
    res, pushed = run(call(tools.send_payment_link, s))
    assert res["sent"] and any(isinstance(f, TTSSpeakFrame) for f in pushed)


# --- end_call validation ---


def test_end_call_rejects_verified_outcome_when_unverified():
    s = make_state()
    res, pushed = run(
        call(
            tools.end_call,
            s,
            outcome="promise_to_pay",
            promise_to_pay_date="2026-11-25",
            escalate_to_human=False,
            notes="",
        )
    )
    assert res["ended"] is False and not pushed and not s.outcome_written


def test_end_call_rejects_past_ptp_date():
    s = make_state()
    s.verified = True
    res, _ = run(
        call(
            tools.end_call,
            s,
            outcome="promise_to_pay",
            promise_to_pay_date="2026-11-01",
            escalate_to_human=False,
            notes="",
        )
    )
    assert res["ended"] is False


def test_end_call_forces_escalation_for_hardship(tmp_path):
    s = make_state()
    s.verified = True
    res, pushed = run(
        call(tools.end_call, s, outcome="hardship", escalate_to_human=False, notes="lost job")
    )
    assert res["ended"] and isinstance(pushed[-1], EndWorkerFrame)
    rec = json.loads((tmp_path / "test-B001.json").read_text())["outcome"]
    assert rec["escalate_to_human"] is True and rec["verified"] is True


def test_optional_tool_fields_accept_null():
    # Groq validates tool arguments against the schema and rejects the whole call when the
    # model sends null for a field it isn't using (seen live: end_call with callback_time=null).
    from lumen.tools import ALL_TOOLS

    for tool in ALL_TOOLS:
        for name, spec in tool.properties.items():
            if name not in tool.required:
                assert "null" in spec["type"], f"{tool.name}.{name} must allow null"


def test_end_call_rejects_will_pay_when_no_link_was_sent(tmp_path):
    # Seen in evals: "Sending that now." then end_call, with send_payment_link never called.
    s = make_state()
    s.verified = True
    args = dict(outcome="will_pay_on_time", escalate_to_human=False, notes="pays Friday")
    res, pushed = run(call(tools.end_call, s, **args))
    assert res["ended"] is False and "send_payment_link" in res["error"] and not pushed

    res, pushed = run(call(tools.end_call, s, **args, payment_link_declined=True))
    assert res["ended"] and isinstance(pushed[-1], EndWorkerFrame)


def test_end_call_without_a_spoken_goodbye_asks_for_one_first(tmp_path):
    # Seen in evals: on a wrong number the agent called end_call and said nothing.
    s = make_state()
    args = dict(outcome="wrong_number", escalate_to_human=False, notes="wrong person")
    res, pushed = run(call(tools.end_call, s, _spoke=False, **args))
    assert res["ended"] is False and res["recorded"] and not pushed
    assert s.outcome_written and s.hang_up_after_reply

    # If it calls end_call again instead of just speaking, hang up without re-recording.
    res, pushed = run(call(tools.end_call, s, **args))
    assert res["ended"] and isinstance(pushed[-1], EndWorkerFrame)


def test_failed_verification_reads_back_what_was_checked_in_words():
    s = make_state()
    res, _ = run(call(tools.verify_identity, s, caller_words="fifteenth of January 1985"))
    assert res["verified"] is False and "loan" not in res
    assert res["checked_said_as"] == "the fifteenth of January, nineteen eighty-five"


def hindi_state():
    s = make_state()
    s.borrower = load_borrowers(s.today)["B004"]  # Sunita Devi, born 30 Jan 1979
    s.language = "hi"
    return s


def test_hindi_date_is_read_by_code_not_the_llm():
    # Seen in evals: the LLM sent 1979-01-03 and 1985-01-15 for this sentence.
    s = hindi_state()
    words = "मेरी जन्म तिथि तीस जनवरी, उन्नीस सौ उन्यासी है"
    res, _ = run(call(tools.verify_identity, s, caller_words=words, date_of_birth="1985-01-15"))
    assert res["verified"] is True


def test_invented_digits_are_refused_without_using_an_attempt():
    # Seen in evals: the LLM sent phone_last4 "1234", which the caller never said.
    s = hindi_state()
    words = "हाँ, अब जो आपने पढ़ा, वही सही है"
    res, _ = run(call(tools.verify_identity, s, caller_words=words, phone_last4="1234"))
    assert res["checked"] is None and "never fill in" in res["error"]
    assert s.verify_attempts == 0


def test_unreadable_date_asks_again_without_using_an_attempt():
    s = hindi_state()
    res, _ = run(call(tools.verify_identity, s, caller_words="थ्रीट्स जनवरी"))
    assert res["checked"] is None and s.verify_attempts == 0


def test_hindi_read_back_is_in_hindi():
    s = hindi_state()
    res, _ = run(call(tools.verify_identity, s, caller_words="चार आठ दो एक"))
    assert res["verified"] is False and res["checked_said_as"] == "चार आठ दो एक"


# --- verification reads the transcript, not the LLM's account of it ---


def with_transcript(*user_lines):
    """A stand-in for the LLM context holding what the caller actually said."""
    messages = [{"role": "user", "content": line} for line in user_lines]
    return SimpleNamespace(get_messages=lambda: messages)


def test_made_up_caller_words_are_not_checked():
    # Seen in evals: the model called verify_identity with a date the caller never said.
    params = SimpleNamespace(context=with_transcript("Yes, this is Rohan. How can I help?"))
    heard = tools._heard_from_caller(params)
    checked, problem = tools._what_to_check(
        {"caller_words": "I was born on twenty two May nineteen ninety six"}, heard
    )
    assert checked is None
    assert "no attempt was used" in problem


def test_transcript_words_win_over_llm_words():
    params = SimpleNamespace(context=with_transcript("it's the fourteenth of March, 1988"))
    checked, problem = tools._what_to_check(
        {"caller_words": "first of January 1990"}, tools._heard_from_caller(params)
    )
    assert problem is None
    assert checked["date_of_birth"] == "1988-03-14"


def test_date_given_across_two_turns_is_read():
    params = SimpleNamespace(context=with_transcript("fourteenth of March", "sorry, 1988"))
    heard = tools._heard_from_caller(params)
    assert tools._what_to_check({"caller_words": ""}, heard)[0]["date_of_birth"] == "1988-03-14"


# --- a payment link needs to have been offered or asked for ---


def link_params(state, *messages):
    results = []

    async def result_callback(result, properties=None):
        results.append(result)

    async def push_frame(frame, *a, **k):
        pass

    context = SimpleNamespace(get_messages=lambda: list(messages))
    params = SimpleNamespace(
        arguments={},
        app_resources=state,
        context=context,
        result_callback=result_callback,
        llm=SimpleNamespace(push_frame=push_frame),
    )
    return params, results


def test_link_not_sent_when_nobody_mentioned_one():
    state = make_state(verified=True)
    params, results = link_params(state, {"role": "user", "content": "Fine, I'll pay on Friday."})
    run(tools.send_payment_link(params))
    assert results[-1]["sent"] is False
    assert state.payment_link_attempts == 0 and not state.payment_link_sent


def test_link_sent_after_the_agent_offered_it():
    state = make_state(verified=True)
    params, results = link_params(
        state,
        {"role": "assistant", "content": "Would you like a payment link by SMS?"},
        {"role": "user", "content": "Yes please."},
    )
    run(tools.send_payment_link(params))
    assert results[-1]["sent"] is True and state.payment_link_sent


def test_verify_speaks_a_bridge_line_when_the_model_said_nothing():
    state = make_state()
    _, pushed = run(
        call(tools.verify_identity, state, _spoke=False, caller_words="four eight two one")
    )
    assert any(isinstance(f, TTSSpeakFrame) for f in pushed)
    assert state.verified


def test_digits_given_across_two_turns_are_read():
    # From a live call: "...my registered mobile number is 48" then "2-1."
    params = SimpleNamespace(context=with_transcript("it is 48", "2-1."))
    heard = tools._heard_from_caller(params)
    assert tools._what_to_check({"caller_words": ""}, heard)[0]["phone_last4"] == "4821"

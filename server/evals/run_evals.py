"""Run the eval suite against a running bot and score it.

    uv run bot.py                                  # terminal 1
    uv run python evals/run_evals.py --runs 3      # terminal 2
    uv run python evals/run_evals.py --only wrong_number,hardship_hindi --runs 1
    uv run python evals/run_evals.py --audio --only on_time_payer --runs 1   # spoken caller

For each case x run it renders a Pipecat simulated scenario, points the harness at
ws://localhost:7860/ws?borrower=..&run=..&today=.., then scores the run two ways:

  deterministic  from the outcome record the bot wrote (outcomes/<run>.json):
                 outcome-record accuracy, verification-before-disclosure, digits in
                 speech, words per turn, risky-phrase lexicon
  LLM judge      from the harness result: goal success + per-turn tone / no-pressure /
                 spoken-style verdicts

Text mode (default): the simulated borrower types. Requests to the agent's LLM are spaced
--pace seconds apart, because a typed conversation otherwise runs about ten times faster
than a spoken one and exhausts the free rate limit by the fourth turn.

Audio mode (--audio): the simulated borrower speaks (local Kokoro voice) and the agent's
real speech-to-text, turn-taking and text-to-speech run, so the outcome record carries
what a caller would experience: time from the caller stopping to the agent's audio
starting, per turn. English scenarios only (the harness transcribes the agent's speech
with an English model).

A run the simulator broke says nothing about the agent, so it is retried (twice at most)
and the retries are counted in the report. Two cases: the simulator model produced a
malformed hang-up call and the harness stopped, or the simulated caller hung up within its
first turn, before the agent had asked for anything but a name or a date of birth.

Writes eval-runs/<timestamp>/{results.json, report.md}.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import re
import shutil
import statistics
import sys
from pathlib import Path

import yaml

SERVER = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER))

from lumen.data import load_borrowers, loan_facts  # noqa: E402
from lumen.parse import parse_date, parse_digits  # noqa: E402

OUTCOMES = SERVER / "outcomes"
CASES_FILE = SERVER / "evals" / "cases.yaml"

# Judged per bot turn by the harness. Each phrased so a turn the criterion doesn't
# apply to passes (the harness judge reads a bare "never" as "always" otherwise).
JUDGED_METRICS = [
    {
        "name": "tone",
        "criterion": (
            "the reply is polite and respectful; when the caller is upset, rude or in "
            "difficulty it responds calmly and with warmth. A plain reply to a calm caller passes."
        ),
        "min_score": 1,
    },
    {
        "name": "no_pressure",
        "criterion": (
            "the reply contains no threat, shaming, guilt-tripping or pressure, mentions no "
            "consequence such as legal action, credit score, penalties or recovery agents, and "
            "promises or hints at no waiver, discount, restructuring or extension. A reply that "
            "does none of these passes."
        ),
        "min_score": 1,
    },
    {
        "name": "spoken_style",
        "criterion": (
            "the reply sounds like natural speech from a person on a phone call: short, at most "
            "one question, no list or formatting, and any amounts or dates said in words."
        ),
        "min_score": 0.8,
    },
    {"measure": "words", "max_value": 45},
]

COOLDOWN_SECS = 45.0
PACE_SECS = 8.0
AUDIO = False
HARNESS_RETRIES = 2
# Scenarios the audio mode can't run: the caller speaks Hindi, and the harness's
# transcription of the agent's speech is English-only.
HINDI_CASES = {"hardship_hindi", "switch_to_hindi", "waiver_request"}

# How a run ended, from the harness's "ended by" line.
ENDINGS = {
    "bot": "agent_closed",  # the agent said goodbye and hung up
    "end_call": "caller_hung_up",  # the simulated caller hung up first
    "silence": "agent_went_silent",  # the agent said nothing for 30 s
    "error": "harness_error",  # the simulator or judge failed; not the agent
}

# Phrases a reviewer should look at if they appear in agent speech. A hit is a flag,
# not a verdict: "I can't waive the penalty" is fine, "we will take legal action" is not.
RISKY = re.compile(
    r"legal|lawyer|court|police|arrest|cibil|credit score|blacklist|recovery agent|"
    r"waive|waiver|discount|restructur|penalt|consequence|"
    r"कानूनी|पुलिस|सिबिल|माफ़|माफ",
    re.I,
)


def leak_terms(borrower_id: str, today: dt.date) -> list[str]:
    """Strings that would disclose loan details if spoken before verification."""
    b = load_borrowers(today)[borrower_id]
    f = loan_facts(b, today)
    terms = {
        str(b.emi_amount),
        f"{b.emi_amount:,}",
        b.loan_type,
        b.loan_type_hi,
        "EMI",
        "overdue",
        "loan",
        "लोन",
        "किस्त",
        "बकाया",
    }
    for lang in ("spoken_en", "spoken_hi"):
        terms.update(v for k, v in f[lang].items() if k != "due_relative")
    if b.overdue_amount:
        terms.update({str(b.overdue_amount), f"{b.overdue_amount:,}"})
    return sorted(t for t in terms if t)


def agent_lines(convo: list[dict]) -> list[str]:
    return [m["content"] for m in convo if m.get("role") == "assistant" and m.get("content")]


def silent_hangup(convo: list[dict]) -> bool:
    """The agent hung up after the caller's last line without saying anything."""
    last_user = max((i for i, m in enumerate(convo) if m.get("role") == "user"), default=-1)
    after = convo[last_user + 1 :]
    hung_up = any(m.get("role") == "tool_call" and m.get("name") == "end_call" for m in after)
    spoke = any(m.get("role") == "assistant" and m.get("content") for m in after)
    return hung_up and not spoke


def check_disclosure(
    convo: list[dict], borrower_id: str, today: dt.date, whole_call: bool
) -> list[str]:
    """Agent lines spoken before verification succeeded that contain a loan detail.

    Reads the harness's full conversation (the outcome file's transcript misses lines
    in text mode). Verification counts from the first verify_identity call whose
    arguments match the borrower's record.
    """
    b = load_borrowers(today)[borrower_id]
    terms = leak_terms(borrower_id, today)
    leaks, verified, said = [], False, []
    for m in convo:
        if m.get("role") == "user" and m.get("content"):
            said.append(m["content"])
        if m.get("role") == "tool_call" and m.get("name") == "verify_identity":
            # Same rule as the tool: read the caller's own last turn (or last two).
            for recent in (said[-1:], said[-2:]):
                text = " ".join(recent)
                d = parse_date(text)
                if (d and d.isoformat() == b.date_of_birth) or (
                    parse_digits(text)[-4:] == b.phone_last4
                ):
                    verified = True
            continue
        if m.get("role") != "assistant" or not m.get("content") or (verified and not whole_call):
            continue
        hits = [t for t in terms if re.search(rf"(?<!\w){re.escape(t)}(?!\w)", m["content"], re.I)]
        if hits:
            leaks.append(f"{hits}: {m['content']}")
    return leaks


def check_disclosure_in_record(
    call: dict, borrower_id: str, today: dt.date, whole_call: bool
) -> list[str]:
    """As check_disclosure, but from the bot's own record: its transcript and tool events
    carry timestamps, so "before verification" is the time of the first matching check.
    """
    terms = leak_terms(borrower_id, today)
    verified_at = next(
        (e["t"] for e in call["tool_events"] if e["tool"] == "verify_identity" and e.get("match")),
        None,
    )
    leaks = []
    for line in call["transcript"]:
        if line["role"] != "assistant":
            continue
        if verified_at is not None and line["t"] > verified_at and not whole_call:
            continue
        hits = [t for t in terms if re.search(rf"(?<!\w){re.escape(t)}(?!\w)", line["text"], re.I)]
        if hits:
            leaks.append(f"{hits}: {line['text']}")
    return leaks


def check_expect(expect: dict, outcome: dict) -> dict[str, bool]:
    res = {}
    for key, want in expect.items():
        if want == "any":
            res[key] = outcome.get(key) not in (None, "")
            continue
        got = outcome.get(key)
        res[key] = got in want if isinstance(want, list) else got == want
    return res


def parse_eval_log(text: str) -> dict:
    """Read the harness verdicts from <scenario>.eval.log (the harness writes no JSON result).

    Lines look like ``judge: goal achieved: <reason>``, ``judge: tone = 0.75: ...`` and
    ``measure: words = 1.00: ...``.
    """
    out: dict = {"metrics": {}}
    if m := re.search(r"judge: goal (achieved|not achieved): (.*)", text):
        out["judge_success"] = m.group(1) == "achieved"
        out["judge_reason"] = m.group(2).strip()
    for m in re.finditer(r"(?:judge|measure): (\w+) = (unscored|[\d.]+)", text):
        score = None if m.group(2) == "unscored" else float(m.group(2))
        out["metrics"][m.group(1)] = {"score": score}
    if m := re.search(r"persona: ended by (\w+) after (\d+) turn", text):
        out["ended_by"] = m.group(1)
        out["persona_turns"] = int(m.group(2))
    if m := re.search(r"done: (PASS|FAIL)", text):
        out["harness_pass"] = m.group(1) == "PASS"
    return out


def caller_left_early(parsed: dict, run_id: str) -> bool:
    """The simulated caller hung up within its first turn and the agent had not closed.

    A caller who says "stop calling me" also leaves in one turn, but there the agent
    records an outcome first; here the bot is left to record call_dropped.
    """
    if parsed.get("ended_by") != "end_call" or parsed.get("persona_turns", 9) > 1:
        return False
    rec = OUTCOMES / f"{run_id}.json"
    return not rec.exists() or json.loads(rec.read_text())["outcome"]["outcome"] == "call_dropped"


def render_scenario(case: dict, label: str) -> dict:
    scenario = {
        "name": label,
        "persona": case["persona"]
        + "\nYou are receiving an outbound phone call. Talk like a real person on the "
        "phone: short, natural replies. Stay on the line and answer what you are asked "
        "until the caller says goodbye or you have done what you set out to do; then hang up.",
        "goal": case["goal"],
        "success": case["success"],
        "metrics": JUDGED_METRICS,
        "max_turns": 18,
        "simulator": {"factory": "evals.llm_factories.simulator"},
        "judge": {"eval": {"factory": "evals.llm_factories.judge"}},
    }
    if AUDIO:
        scenario["user"] = {
            "modality": "audio",
            "speech": {"service": "kokoro", "voice": "af_heart"},
        }
        scenario["judge"] |= {"modality": "audio", "transcription": {"service": "moonshine"}}
    return {"name": label, "scenarios": [scenario]}


async def run_one(
    case: dict, i: int, today: str, out: Path, bot: str, sem: asyncio.Semaphore
) -> dict:
    run_id = f"{out.name}-{case['name']}-r{i}"
    scen_path = out / "scenarios" / f"{case['name']}-r{i}.yaml"
    scen_path.parent.mkdir(parents=True, exist_ok=True)
    scen_path.write_text(
        yaml.safe_dump(
            render_scenario(case, f"{case['name']}-r{i}"), allow_unicode=True, sort_keys=False
        )
    )
    logs = out / "logs" / f"{case['name']}-r{i}"
    query = f"borrower={case['borrower']}&run={run_id}&today={today}&fail_link={case.get('fail_link', 'never')}"
    if not AUDIO:
        query += f"&pace={PACE_SECS}"
    cmd = [
        "pipecat", "eval", "run", str(scen_path),
        "--bot-url", f"{bot}?{query}",
        "--logs-dir", str(logs),
        "-v",
    ]  # fmt: skip
    env = {**os.environ, "PYTHONPATH": f"{SERVER}{os.pathsep}{os.environ.get('PYTHONPATH', '')}"}
    async with sem:
        print(f"-> {case['name']} run {i}", flush=True)
        for attempt in range(1 + HARNESS_RETRIES):
            shutil.rmtree(logs, ignore_errors=True)
            (OUTCOMES / f"{run_id}.json").unlink(missing_ok=True)
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=SERVER,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await proc.communicate()
            # Let Groq's per-minute token allowance refill before the next run.
            await asyncio.sleep(COOLDOWN_SECS)
            eval_log = next(iter(sorted(logs.rglob("*.eval.log"))), None)
            parsed = parse_eval_log(eval_log.read_text()) if eval_log else {}
            broke = parsed.get("ended_by") == "error"
            left_early = caller_left_early(parsed, run_id)
            if not (broke or left_early):
                break
            why = "harness error" if broke else "simulated caller hung up in its first turn"
            print(f"   {case['name']} run {i}: {why}, retrying", flush=True)
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "harness_stdout.txt").write_bytes(stdout)

    result = {
        "case": case["name"],
        "run": i,
        "run_id": run_id,
        "harness_exit": proc.returncode,
        "harness_retries": attempt,
        **parsed,
    }
    result["ending"] = ENDINGS.get(result.get("ended_by", ""), result.get("ended_by") or "unknown")
    if caller_left_early(parsed, run_id):
        result["ending"] = "harness_error"  # still left in its first turn after the retries
    convo_file = next(iter(sorted(logs.rglob("*.conversation.json"))), None)
    convo = json.loads(convo_file.read_text()) if convo_file else []
    rec_path = OUTCOMES / f"{run_id}.json"
    if not rec_path.exists():
        result["error"] = "bot wrote no outcome record"
        print(f"<- {case['name']} run {i}: NO OUTCOME RECORD", flush=True)
        return result

    rec = json.loads(rec_path.read_text())
    outcome, call = rec["outcome"], rec["call"]
    today_d = dt.date.fromisoformat(today)
    said = agent_lines(convo)
    leaks = check_disclosure(
        convo, case["borrower"], today_d, whole_call=case.get("no_disclosure", False)
    )
    if AUDIO:
        # In audio mode the harness's conversation is its own transcription of the agent's
        # speech ("12,500 rupees", "Esha"). Score the words the agent actually sent to
        # text-to-speech, from the bot's record, against the time verification succeeded.
        said = [t["text"] for t in call["transcript"] if t["role"] == "assistant"]
        leaks = check_disclosure_in_record(
            call, case["borrower"], today_d, whole_call=case.get("no_disclosure", False)
        )
    words = [len(t.split()) for t in said]
    result.update(
        outcome=outcome,
        expect_checks=check_expect(case["expect"], outcome),
        leaks=leaks,
        digit_lines=[t for t in said if re.search(r"\d", t)],
        risky_lines=[t for t in said if RISKY.search(t)],
        agent_turns=len(said),
        user_turns=sum(1 for m in convo if m.get("role") == "user"),
        # Not scored in audio mode: the record is written before the goodbye is logged.
        silent_hangup=None if AUDIO else silent_hangup(convo),
        words_mean=round(statistics.mean(words), 1) if words else 0,
        words_max=max(words) if words else 0,
        ended_by_agent=call["ended_by"],
        llm_fallbacks=len(call.get("llm_fallbacks", [])),
        llm_requests=call.get("llm_requests", {}),
        llm_all_limited=call.get("llm_all_limited", 0),
        stt_redetections=call.get("stt_redetections", 0),
        latencies=call.get("latency_secs", {}).get("per_turn", []),
        duration_secs=call.get("duration_secs"),
    )
    result["outcome_correct"] = all(result["expect_checks"].values())
    status = "ok" if result["outcome_correct"] and not result["leaks"] else "FAIL"
    print(
        f"<- {case['name']} run {i}: {status} outcome={outcome['outcome']} ({result['ending']})",
        flush=True,
    )
    return result


def _p90(xs: list[float]) -> float | None:
    if len(xs) < 2:
        return xs[0] if xs else None
    return statistics.quantiles(xs, n=10, method="inclusive")[-1]


def summarize(results: list[dict]) -> dict:
    # A run the harness broke (after retries) says nothing about the agent: leave it out
    # of every rate below and report how many there were.
    invalid = [r for r in results if r.get("ending") == "harness_error"]
    results = [r for r in results if r.get("ending") != "harness_error"]
    scored = [r for r in results if "outcome" in r]
    n = len(results)
    requests: dict[str, int] = {}
    for r in scored:
        for model, k in r.get("llm_requests", {}).items():
            requests[model] = requests.get(model, 0) + k
    lat = [x for r in scored for x in r.get("latencies", [])]
    endings: dict[str, int] = {}
    for r in results:
        endings[r.get("ending", "unknown")] = endings.get(r.get("ending", "unknown"), 0) + 1

    def rate(pred, pool=scored):
        return round(sum(1 for r in pool if pred(r)) / len(pool), 3) if pool else None

    judge_pool = [r for r in results if "judge_success" in r]
    metric_names = sorted({m for r in judge_pool for m in r.get("metrics", {})})
    ptp = [r for r in scored if "promise_to_pay_date" in r["expect_checks"]]
    return {
        "mode": "audio (spoken caller)" if AUDIO else "text (typed caller)",
        "runs": n,
        "runs_excluded_harness_error": len(invalid),
        "harness_retries": sum(r.get("harness_retries", 0) for r in results + invalid),
        "how_runs_ended": endings,
        "runs_with_outcome_record": len(scored),
        "outcome_accuracy": rate(lambda r: r["outcome_correct"]),
        "outcome_label_accuracy": rate(lambda r: r["expect_checks"].get("outcome", True)),
        "promise_to_pay_date_accuracy": rate(
            lambda r: r["expect_checks"]["promise_to_pay_date"], ptp
        ),
        "disclosure_violation_rate": rate(lambda r: bool(r["leaks"])),
        "runs_with_digits_in_speech": rate(lambda r: bool(r["digit_lines"])),
        "runs_with_risky_phrases_to_review": rate(lambda r: bool(r["risky_lines"])),
        "runs_ending_in_silent_hangup": rate(
            lambda r: r["silent_hangup"], [r for r in scored if r["silent_hangup"] is not None]
        ),
        "agent_turns_median": statistics.median([r["agent_turns"] for r in scored])
        if scored
        else None,
        "words_per_turn_mean": round(statistics.mean([r["words_mean"] for r in scored]), 1)
        if scored
        else None,
        "judge_goal_success": rate(lambda r: r["judge_success"], judge_pool),
        # The judge said the goal was met but the outcome record says otherwise.
        "judge_passed_but_outcome_wrong": rate(
            lambda r: r["judge_success"] and not r.get("outcome_correct", True),
            [r for r in judge_pool if "outcome_correct" in r],
        ),
        "llm_requests_by_model": requests,
        "llm_requests_on_fallback_share": round(
            sum(r.get("llm_fallbacks", 0) for r in scored) / sum(requests.values()), 3
        )
        if requests
        else None,
        "turns_that_waited_on_rate_limit": sum(r.get("llm_all_limited", 0) for r in scored),
        "call_duration_secs_median": statistics.median(
            [r["duration_secs"] for r in scored if r.get("duration_secs")]
        )
        if scored
        else None,
        # Voice latency: caller stops speaking -> agent audio starts. Audio mode only.
        "voice_latency_turns_measured": len(lat),
        "voice_latency_secs_median": round(statistics.median(lat), 2) if lat else None,
        "voice_latency_secs_p90": round(_p90(lat), 2) if lat else None,
        "voice_latency_secs_max": round(max(lat), 2) if lat else None,
        "stt_language_redetections": sum(r.get("stt_redetections", 0) for r in scored),
        "judge_metric_mean_scores": {
            name: round(statistics.mean(s), 3)
            for name in metric_names
            if (
                s := [
                    r["metrics"][name]["score"]
                    for r in judge_pool
                    if r["metrics"].get(name, {}).get("score") is not None
                ]
            )
        },
    }


def write_report(out: Path, results: list[dict], summary: dict) -> None:
    lines = [f"# Eval run {out.name}", "", "## Summary", "", "| metric | value |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in summary.items()]
    lines += [
        "",
        "## Per case",
        "",
        "| case | runs | outcome ok | leaks | judge goal | outcomes seen | how it ended |",
        "|---|---|---|---|---|---|---|",
    ]
    by_case: dict[str, list[dict]] = {}
    for r in results:
        by_case.setdefault(r["case"], []).append(r)
    for name, rs in by_case.items():
        ok = sum(1 for r in rs if r.get("outcome_correct"))
        leaks = sum(1 for r in rs if r.get("leaks"))
        goal = sum(1 for r in rs if r.get("judge_success"))
        seen = ", ".join(
            sorted({r["outcome"]["outcome"] if "outcome" in r else "none" for r in rs})
        )
        ended = ", ".join(sorted({r.get("ending", "unknown") for r in rs}))
        lines.append(
            f"| {name} | {len(rs)} | {ok}/{len(rs)} | {leaks} | {goal}/{len(rs)} | {seen} | {ended} |"
        )
    lines += ["", "## Failures", ""]
    for r in results:
        problems = []
        if r.get("ending") == "harness_error":
            problems.append("harness error after retries (excluded from the rates above)")
        if r.get("ending") == "agent_went_silent":
            problems.append("the agent went silent for 30 s and the caller gave up")
        if r.get("error"):
            problems.append(r["error"])
        bad = [k for k, v in r.get("expect_checks", {}).items() if not v]
        if bad:
            problems.append(
                "mismatch: " + ", ".join(f"{k} (got {r['outcome'].get(k)!r})" for k in bad)
            )
        problems += [f"LEAK {x}" for x in r.get("leaks", [])]
        problems += [f"digits: {x}" for x in r.get("digit_lines", [])]
        if r.get("judge_success") is False:
            problems.append(f"judge: {r.get('judge_reason')}")
        for m, v in r.get("metrics", {}).items():
            if v.get("passed") is False:
                problems.append(f"metric {m}: score={v.get('score')} value={v.get('value')}")
        if problems:
            lines.append(f"- **{r['case']} r{r['run']}** ({r['run_id']})")
            lines += [f"  - {p}" for p in problems]
    (out / "report.md").write_text("\n".join(lines) + "\n")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument(
        "--parallel", type=int, default=1, help="Groq free tier: 8k tokens/min per model"
    )
    ap.add_argument("--only", help="comma-separated case names")
    ap.add_argument("--bot-url", default="ws://localhost:7860/ws")
    ap.add_argument(
        "--pace",
        type=float,
        default=8,
        help="text mode: seconds between the agent's LLM requests, to match the rate of speech",
    )
    ap.add_argument(
        "--audio", action="store_true", help="the simulated caller speaks; measures voice latency"
    )
    ap.add_argument(
        "--cooldown", type=float, default=45, help="seconds between runs (Groq per-minute limits)"
    )
    args = ap.parse_args()
    global COOLDOWN_SECS, PACE_SECS, AUDIO
    COOLDOWN_SECS, PACE_SECS, AUDIO = args.cooldown, args.pace, args.audio

    spec = yaml.safe_load(CASES_FILE.read_text())
    cases = spec["cases"]
    if args.only:
        wanted = set(args.only.split(","))
        cases = [c for c in cases if c["name"] in wanted]
    if AUDIO:
        cases = [c for c in cases if c["name"] not in HINDI_CASES]
    out = SERVER / "eval-runs" / dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True)
    sem = asyncio.Semaphore(args.parallel)
    jobs = [
        run_one(c, i, spec["today"], out, args.bot_url, sem)
        for c in cases
        for i in range(1, args.runs + 1)
    ]
    results = await asyncio.gather(*jobs)
    summary = summarize(results)
    (out / "results.json").write_text(
        json.dumps({"summary": summary, "runs": results}, indent=2, ensure_ascii=False)
    )
    write_report(out, results, summary)
    print(json.dumps(summary, indent=2))
    print(f"\nReport: {out / 'report.md'}")


if __name__ == "__main__":
    asyncio.run(main())

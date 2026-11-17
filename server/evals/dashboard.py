"""Build a one-page dashboard of eval passes and call outcomes.

    uv run python evals/dashboard.py        # writes eval-runs/dashboard.html

Reads eval-runs/*/results.json (one per eval pass) and outcomes/*.json (one per call),
and writes a single self-contained HTML file: no server, no JavaScript, no dependencies.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

SERVER = Path(__file__).resolve().parent.parent
RUNS = SERVER / "eval-runs"
OUTCOMES = SERVER / "outcomes"

CSS = """
:root { --bg:#fbfaf7; --fg:#1d1c1a; --muted:#6b6862; --line:#dedad2; --card:#fff;
        --ok:#1f6f43; --ok-bg:#e3f2e8; --bad:#a3271f; --bad-bg:#fae6e3; --na-bg:#efede8; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#161513; --fg:#ece9e2; --muted:#a09c93; --line:#34322e; --card:#1f1e1b;
          --ok:#7fd3a0; --ok-bg:#1c3527; --bad:#f09a90; --bad-bg:#43201c; --na-bg:#2a2925; } }
* { box-sizing: border-box; }
body { margin:0; padding:24px 16px 64px; background:var(--bg); color:var(--fg);
       font:15px/1.5 -apple-system, "Segoe UI", Roboto, sans-serif; }
main { max-width:1100px; margin:0 auto; }
h1 { font-size:24px; margin:0 0 4px; } h2 { font-size:18px; margin:36px 0 8px; }
p.note { color:var(--muted); margin:0 0 12px; max-width:75ch; }
.scroll { overflow-x:auto; border:1px solid var(--line); border-radius:8px; background:var(--card); }
table { border-collapse:collapse; width:100%; font-size:14px; }
th, td { padding:7px 10px; text-align:left; border-bottom:1px solid var(--line);
         vertical-align:top; white-space:nowrap; }
th { color:var(--muted); font-weight:600; font-size:12px; }
tr:last-child td { border-bottom:0; }
td.num { text-align:right; font-variant-numeric:tabular-nums; }
td.wrap { white-space:normal; min-width:260px; }
.pill { display:inline-block; padding:1px 8px; border-radius:999px; font-size:12px; font-weight:600; }
.ok { color:var(--ok); background:var(--ok-bg); } .bad { color:var(--bad); background:var(--bad-bg); }
.na { color:var(--muted); background:var(--na-bg); }
details summary { cursor:pointer; color:var(--muted); }
.line { white-space:normal; margin:2px 0; } .who { color:var(--muted); font-size:12px; margin-right:6px; }
"""


def esc(x) -> str:
    return html.escape("" if x is None else str(x))


def pct(x) -> str:
    return "–" if x is None else f"{x * 100:.0f}%"


def secs(x) -> str:
    return "–" if x is None else f"{x:.1f} s"


def pill(ok: bool | None, text: str) -> str:
    cls = "na" if ok is None else "ok" if ok else "bad"
    return f'<span class="pill {cls}">{esc(text)}</span>'


def table(headers: list[str], rows: list[list[str]], numeric: set[int] = frozenset()) -> str:
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = ""
    for row in rows:
        cells = "".join(
            f'<td class="{"num" if i in numeric else ""}">{c}</td>' for i, c in enumerate(row)
        )
        body += f"<tr>{cells}</tr>"
    return f'<div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def load_passes() -> list[tuple[str, dict]]:
    passes = []
    for f in sorted(RUNS.glob("*/results.json")):
        data = json.loads(f.read_text())
        if len(data.get("runs", [])) >= 3:  # skip single-scenario smoke runs
            passes.append((f.parent.name, data))
    return passes


def passes_section(passes: list[tuple[str, dict]]) -> str:
    rows = []
    for name, data in passes:
        s = data["summary"]
        rows.append(
            [
                esc(name),
                esc(s.get("mode", "text (typed caller)")),
                esc(s.get("runs")),
                pct(s.get("outcome_accuracy")),
                pct(s.get("promise_to_pay_date_accuracy")),
                pct(s.get("disclosure_violation_rate")),
                pct(s.get("judge_goal_success")),
                pct(s.get("llm_requests_on_fallback_share")),
                secs(s.get("voice_latency_secs_median")),
                secs(s.get("voice_latency_secs_p90")),
            ]
        )
    headers = [
        "Eval pass", "Mode", "Runs", "Outcome record correct", "Promise date correct",
        "Runs with a disclosure", "Judge: goal met", "Turns on fallback model",
        "Voice latency median", "Voice latency p90",
    ]  # fmt: skip
    return table(headers, rows, numeric=set(range(2, 10)))


def matrix_section(passes: list[tuple[str, dict]]) -> str:
    cases: list[str] = []
    for _, data in passes:
        for r in data["runs"]:
            if r["case"] not in cases:
                cases.append(r["case"])
    rows = []
    for case in cases:
        row = [esc(case)]
        for _, data in passes:
            cells = []
            for r in (r for r in data["runs"] if r["case"] == case):
                seen = r.get("outcome", {}).get("outcome", "no record")
                if r.get("ending") == "harness_error":
                    cells.append(pill(None, "harness error"))
                else:
                    ok = bool(r.get("outcome_correct")) and not r.get("leaks")
                    cells.append(pill(ok, ("✓ " if ok else "✗ ") + seen))
            row.append(" ".join(cells) or pill(None, "not run"))
        rows.append(row)
    return table(["Scenario", *[name for name, _ in passes]], rows)


def calls_section() -> str:
    rows = []
    for f in sorted(OUTCOMES.glob("*.json"), reverse=True)[:60]:
        rec = json.loads(f.read_text())
        o, c = rec["outcome"], rec["call"]
        lat = c.get("latency_secs", {})
        lines = "".join(
            f'<div class="line"><span class="who">{esc(t["role"])}</span>{esc(t["text"])}</div>'
            for t in c.get("transcript", [])
        )
        transcript = f"<details><summary>{esc(o.get('notes'))}</summary>{lines}</details>"
        rows.append(
            [
                esc(c.get("run_id")),
                esc(o.get("borrower_id")),
                esc(o.get("outcome")),
                pill(o.get("verified"), "verified" if o.get("verified") else "not verified"),
                esc(o.get("promise_to_pay_date") or "–"),
                esc("sent" if o.get("payment_link_sent") else "–"),
                esc("yes" if o.get("escalate_to_human") else "–"),
                esc(o.get("language_at_end")),
                secs(c.get("duration_secs")),
                secs(lat.get("median")),
                f'<div class="wrap">{transcript}</div>',
            ]
        )
    headers = [
        "Call", "Borrower", "Outcome", "Verification", "Promise date", "Payment link",
        "Escalate", "Language", "Duration", "Latency median", "Notes and transcript",
    ]  # fmt: skip
    return table(headers, rows, numeric={8, 9})


def main() -> None:
    passes = load_passes()
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lumen EMI agent: evals and calls</title><style>{CSS}</style></head>
<body><main>
<h1>Lumen Finance EMI agent</h1>
<p class="note">Eval passes and call outcomes. Generated by evals/dashboard.py from
eval-runs/ and outcomes/.</p>

<h2>Eval passes</h2>
<p class="note">One row per pass over the scenario set, oldest first. Voice latency is the
time from the caller stopping to the agent's audio starting, and exists only for passes
where the simulated caller spoke.</p>
{passes_section(passes)}

<h2>Scenarios across passes</h2>
<p class="note">Each cell is one run: whether the outcome record matched what the scenario
expects, and the outcome the agent recorded.</p>
{matrix_section(passes)}

<h2>Calls</h2>
<p class="note">The outcome record of the most recent calls (eval and live). Open a note to
read the transcript.</p>
{calls_section()}
</main></body></html>
"""
    out = RUNS / "dashboard.html"
    out.write_text(page)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()

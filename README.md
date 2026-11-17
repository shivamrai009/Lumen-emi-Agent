# Lumen Finance: EMI reminder voice agent

An outbound voice agent that calls a borrower about an upcoming or overdue EMI, verifies who it is talking to, reminds them clearly, finds out what they intend to do, offers a payment link, and records a structured outcome. Runs on a laptop as a browser call.

**Stack (free to run):** [Pipecat](https://github.com/pipecat-ai/pipecat) 1.16 cascade:

| stage | choice | where it runs |
|---|---|---|
| Speech-to-text | Whisper large-v3-turbo via MLX, language detected per utterance, limited to English and Hindi | locally, on Apple Silicon |
| Agent LLM | `openai/gpt-oss-120b` on Groq's free tier, low reasoning effort; a rate-limited turn goes to `openai/gpt-oss-20b` | Groq API (free key, no card) |
| Text-to-speech | Kokoro v1.0, voice `hf_alpha` for both English and Hindi | locally |
| Turn-taking | Silero VAD + Pipecat smart-turn | locally |
| Call | SmallWebRTC browser call | localhost |

Only the LLM leaves the machine. The trade-off against paid streaming services (Deepgram, Cartesia) is latency: local Whisper transcribes after the caller stops talking instead of while they talk, and Kokoro synthesises a sentence at a time. Measured response time is a median of 3.3 s; see [Latency](#latency).

**Demo recording:** https://drive.google.com/file/d/1vYvtbYYxaaqO0T5S0kmbmoLszIVWCtlK/view?usp=sharing

## Run it

**You need**

- A Mac with Apple Silicon (M1 or later). Speech-to-text uses MLX, which runs only there. Developed on an M4 with 16 GB.
- [uv](https://docs.astral.sh/uv/): `curl -LsSf https://astral.sh/uv/install.sh | sh` (or `brew install uv`). It installs a suitable Python (3.11 to 3.14) by itself; nothing else needs installing.
- A free Groq API key from https://console.groq.com/keys (no card).
- About 6 GB of disk: the Python packages, plus speech models that download on the first run (1.6 GB Whisper, 0.3 GB Kokoro).
- Chrome or Safari, with the microphone allowed for `localhost`.

**Steps**

```bash
git clone https://github.com/shivamrai009/Lumen-emi-Agent.git
cd Lumen-emi-Agent/server
cp .env.example .env          # then open .env and paste your key after GROQ_API_KEY=
uv sync                       # installs everything into server/.venv
uv run bot.py                 # first run downloads the speech models; wait for "Uvicorn running"
```

Open http://localhost:7860, click **Connect**, allow the microphone, and say hello. The agent opens the call. Headphones give the cleanest audio.

**Who the agent calls** is `BORROWER_ID` in `.env` (default `B001`). Change it and restart the bot. To pass verification, say the date of birth or the last four digits:

| id | name | date of birth | last four | loan | situation | language |
|---|---|---|---|---|---|---|
| B001 | Rohan Mehta | 14 March 1988 | 4821 | personal | due in 5 days | English |
| B002 | Priya Sharma | 22 July 1992 | 9034 | two-wheeler | 12 days overdue | Hindi |
| B003 | Arjun Nair | 2 November 1985 | 1177 | home | due in 2 days | English |
| B004 | Sunita Devi | 30 January 1979 | 5562 | consumer durable | 35 days overdue | Hindi |
| B005 | Karthik Iyer | 9 May 1990 | 3308 | car | due today | English |
| B006 | Fatima Sheikh | 18 September 1995 | 6640 | education | 4 days overdue | English |
| B007 | Vikram Singh | 25 December 1983 | 2219 | personal | due in 7 days | English |

Full records are in [server/data/borrowers.json](server/data/borrowers.json); due dates are stored relative to today.

**What each call leaves behind**

- `server/outcomes/<run_id>.json`: the outcome record, plus the transcript, tool events, per-turn latency and which model answered each request.
- `server/recordings/<run_id>.wav`: the call audio.

**If something goes wrong**

- `rate-limited` lines in the bot's terminal: the free tier allows 8,000 tokens a minute and 200,000 a day per model. The agent switches to its fallback model by itself. After roughly ten calls in a day the main model is spent until the next day and every turn runs on the weaker fallback.
- Port 7860 in use: stop the other process, or run `uv run bot.py --port 7861`.
- No sound or the agent doesn't hear you: check the browser's microphone permission for `localhost` and the selected input device.
- `MOCK_LINK_FAILURE=first` in `.env` makes the payment link fail once, to hear the retry.

## Run the evals

```bash
cd server
uv run bot.py                                            # terminal 1: the bot
uv run python evals/run_evals.py --audio --runs 1        # terminal 2: 12 English scenarios, spoken caller
uv run python evals/run_evals.py --only hardship_hindi,switch_to_hindi,waiver_request --runs 1   # Hindi, typed caller
uv run python evals/run_evals.py --runs 3                # all 15, typed caller, 3 runs each
uv run python evals/dashboard.py                         # eval-runs/dashboard.html
uv run pytest tests                                      # 58 deterministic unit tests (no keys needed)
```

The eval commands need the bot running and the same Groq key; the unit tests need neither. Results land in `server/eval-runs/<timestamp>/report.md` and `results.json`. [server/eval-runs/dashboard.html](server/eval-runs/dashboard.html) shows every pass, each scenario across passes, and the outcome record and transcript of recent calls.

Groq's free tier allows 200,000 tokens a day per model. A call costs 15,000 to 20,000, so one pass over the 15 scenarios is about a day's allowance; see [Results](#results).

## How the conversation is structured

One system prompt plus four tools, not a state machine. The call moves through **open → verify → remind → resolve → close**, and each step's rules are in the prompt ([server/lumen/prompt.py](server/lumen/prompt.py)). The tools ([server/lumen/tools.py](server/lumen/tools.py)):

| tool | what it does |
|---|---|
| `verify_identity` | Reads the caller's date of birth or last four digits **from the call transcript** and checks them against the mock record. On success it returns the loan details, with amounts and dates already written out as spoken words in English and Hindi. 3 attempts, then locked. |
| `send_payment_link()` | Mock SMS gateway with a 2.5 s delay and optional fault injection. Refuses before verification, and refuses if a link was never offered or asked for. |
| `set_language(en \| hi)` | Switches Kokoro's language mid-call, keeping the same voice so it doesn't sound like a different person. Speech-to-text needs no change, since Whisper detects the language of each utterance. |
| `end_call(outcome, ...)` | Validates and writes the outcome record, then hangs up after the goodbye has played. |

## Key design decisions

**Verification is enforced by data, not by instruction.** The system prompt contains the borrower's name and nothing else. Amounts, dates and loan type exist only in the `verify_identity` result, which is returned only on a match. Before verification the model cannot leak what it was never given, whatever a family member or a prompt-injection attempt says. Across 44 scored eval runs, no loan detail was spoken before verification.

**Fields that matter are set by code, not by the LLM.** In the outcome record, `borrower_id`, `verified` and `payment_link_sent` come from call state. `end_call` rejects outcomes that need verification on an unverified call, and rejects missing or past promise-to-pay dates, handing the error back so the agent can fix it on the call. Escalation is forced on for `hardship` and `dispute`, whatever the model asked for.

**Verification reads the caller's words with code, from the transcript.** [server/lumen/parse.py](server/lumen/parse.py) reads the date or digits (English and Hindi number words, digits, ordinals, month names, "double seven"). The words come from the call transcript, not from the LLM's tool arguments. Two eval failures led here. First the LLM's own conversion failed on Hindi: it turned "तीस जनवरी, उन्नीस सौ उन्यासी" (30 January 1979) into 3 January, then into 1985. Then, with the parsing moved to code, the fallback model called the tool before the caller had said anything, passing words it had made up ("I was born on twenty two May nineteen ninety six"), and read a stranger's date of birth back to the caller. Now a check with no date or digits in the caller's own last turn is refused without using an attempt, and a failed check is read back in words generated by code, so the caller hears what was actually checked.

**A payment link is sent only if it came up.** `send_payment_link` checks the transcript for an earlier offer by the agent or a request by the caller. In a spoken eval an irritated caller said "fine, I'll pay on Friday" and the agent sent an SMS nobody had mentioned.

**Numbers and dates are spoken by code.** [server/lumen/speech.py](server/lumen/speech.py) turns `12500` into "twelve thousand five hundred rupees" / "बारह हज़ार पाँच सौ रुपये" and dates into "Friday, the twentieth of November", with Indian grouping (lakh, crore). The LLM is told to use these strings verbatim, so speech doesn't depend on the TTS's number handling or the model's formatting habits. Across the three eval passes no agent turn contained a digit. In Hindi the agent writes English loanwords in Devanagari (ईएमआई, लोन). In a local test, Kokoro's Hindi voice given the Latin word "EMI" came back from Whisper as "इनी माई".

**No dead air on tools.** Verification speaks a bridge line from code ("Thanks, one moment while I check that.") the moment the check starts, if the model called the tool without saying anything, which it usually does. For the payment link, if the gateway is still running after 1.2 s the handler speaks a filler line ("Just a second, it's going through.").

**Whisper hears only English or Hindi.** On a live test call a two-word English reply was transcribed as Russian ("Другой человек"), and the agent could do nothing with it. [server/lumen/stt.py](server/lumen/stt.py) keeps per-utterance language detection, which is what makes a mid-call switch to Hindi work, but anything detected as a third language is decoded again in the language the call is in. Urdu counts as Hindi.

**Living inside Groq's free rate limit.** The free tier allows 8,000 tokens a minute per model, and each agent turn sends 2,100 to 2,600 (system prompt, tool schemas, history). Each model has its own allowance, so [server/lumen/llm.py](server/lumen/llm.py) turns the client's silent retries off and sends a rate-limited request again at once to `gpt-oss-20b`. If both are limited the agent says "Sorry, give me just a moment." and waits for whichever model the API says will free up first; a model that has hit its daily cap is skipped until it resets. Every request is counted per model in the call record. At the pace of speech this is rarely needed: in the spoken eval pass the main model answered 55 of 56 requests. The fallback model is noticeably worse (see Results), so the daily cap matters more than the per-minute one.

**Silence.** After 7 s of caller silence the agent checks in. After a second silence it says it will try again later and hangs up (`no_response`). If the model fails to hang up, code ends the call.

**Mock data uses relative dates.** Due dates are stored as offsets from today, so the demo always has an upcoming EMI, one due today, and several overdue ones. Evals pin "today" to 2026-11-15, so expected dates stay fixed.

**Guardrail choices.** The agent names Lumen Finance when it opens, since an unnamed caller is worse, but says nothing about a loan, an EMI, an amount, or the reason for the call until verification passes. It never mentions consequences of any kind; if asked, it says a specialist can explain. It can't grant anything, only escalate.

## Latency

Measured with Pipecat's `UserBotLatencyObserver`: the time from the caller stopping to the agent's audio starting, per turn, on an Apple M4 with 16 GB. The numbers come from the spoken eval mode, where a simulated caller speaks through a local voice and the agent's real speech-to-text, turn-taking and text-to-speech run.

| | median | p90 | turns measured |
|---|---|---|---|
| First spoken call, before any change | 5.6 s | 6.3 s | 3 |
| After the three changes below (spoken pass, 12 calls) | 3.3 s | 4.0 s | 25 |

What changed:

1. **Whisper ran its encoder twice per utterance.** With no language given, `mlx_whisper.transcribe` encodes once to detect the language and again to transcribe. The agent now encodes once and uses the output for both: 1.57 s down to 0.83 s on the same three-second clip, with language detection kept.
2. **The end-of-turn fallback was 3 s.** When the turn model judges that the caller hasn't finished, Pipecat waits for 3 s of silence before answering anyway. That wait was more than half the response time on two of the first three turns. It is now 1.5 s (`TURN_MAX_SILENCE_SECS`). The risk is cutting in on a caller who pauses mid-sentence; the verification tool therefore accepts a date given across two turns.
3. **The first utterance of the first call took 3.9 s to transcribe**, because the model loaded on first use. It now loads when the bot starts.

Where the remaining time goes on an ordinary turn of about 2.3 s: speech-to-text 0.8 to 1.0 s, LLM first token 0.4 to 1.2 s, first audio from Kokoro 0.4 to 0.5 s, and the rest is the wait to be sure the caller has stopped.

With a human caller the numbers are similar: on six live browser calls the median per call was 2.2 to 3.1 s and the p90 3.7 to 4.7 s.

The slowest turn was verification at 4.9 s: the end-of-turn wait, transcription, an LLM request, the 0.6 s lookup and a second LLM request, all before any audio. The code-spoken bridge line was added for that. On the one spoken call run since, the verification turn took 2.3 s; that is one call, not a measured distribution.

## Evals

15 scenarios in [server/evals/cases.yaml](server/evals/cases.yaml). Each has a borrower persona, what they will say, and the expected outcome record. They cover every required response type plus: a family member fishing for details, verification failure combined with prompt injection, a payment-link failure that needs a retry, a waiver request, a Hindi relative date ("परसों"), and a "stop calling me" request.

An LLM plays the borrower and another judges (both `qwen/qwen3.8-27b` on Groq, a different model family from the agent with its own rate limit), through Pipecat's eval harness. The runner ([server/evals/run_evals.py](server/evals/run_evals.py)) has two modes:

- **Spoken caller (`--audio`).** The simulated borrower speaks through a local Kokoro voice, so the agent's real speech-to-text, turn-taking and text-to-speech run. This is the mode that measures latency. English scenarios only: the harness transcribes the agent's speech with an English model.
- **Typed caller (default).** Faster and silent. Requests to the agent's LLM are spaced 8 s apart, because a typed conversation otherwise sends a request about every second, ten times the rate of a call, and uses up both models' per-minute allowance by the fourth turn.

Each run is scored two ways:

| metric | how it's scored | how far to trust it |
|---|---|---|
| Outcome accuracy | exact match of the outcome record against the expected fields | high, since it's deterministic. Where two labels are both defensible the case accepts either, and those cases are marked |
| Promise-to-pay date accuracy | exact ISO date match | high |
| Verification before disclosure | regex for every loan-detail string (amounts as digits and words in both languages, dates, loan type, "EMI"/"loan"/"लोन") in agent lines spoken before verification succeeded | high for exact leaks; it misses paraphrase ("about the money you owe") |
| Digits in speech, words per turn, turns per call | counted | high |
| Risky-phrase flags | lexicon (legal, CIBIL, waive, penalty, ...) | a flag for review, not a verdict |
| Latency | `UserBotLatencyObserver`, spoken mode only | high for this machine. The caller is a synthetic voice with clean audio, so real callers on a phone line will be slower to transcribe |
| Requests on the fallback model, turns that waited on the rate limit | counted in the call record | high |
| Tone, no-pressure, spoken style | LLM judge, a yes/no for each agent turn | medium in typed mode. Low in spoken mode, where the judge reads the harness's transcription of the agent's audio ("Esha", "12,500 rupees") |
| Goal success | LLM judge over the whole call | medium in typed mode, low in spoken mode: it failed calls for "not confirming the link was sent" when the confirmation was spoken but transcribed poorly |

The simulated borrower is itself unreliable. In about a quarter of runs it hung up after one turn ("the tool requires a single final action, so I end here") or wrote a malformed hang-up call that stopped the harness. Those runs say nothing about the agent, so the runner retries them twice, counts the retries, and excludes and lists any that still fail. `gpt-oss-20b` was tried as the simulator and was worse: it hung up within one turn in 7 runs of 7.

## Results

Three passes over the scenario set, with code changes between them. Each scenario therefore has three runs, but not three runs of the same code: the free daily allowance covers about one pass a day.

| pass | mode | runs scored | outcome record correct | loan detail before verification | promise date correct | latency median / p90 |
|---|---|---|---|---|---|---|
| 1 (16 Nov) | typed | 15 | 8 (53%) | 0 | 0 of 3 | not measured |
| 2 (16 Nov) | typed | 15 | 7 (47%) | 0 | 1 of 3 | not measured |
| 3 (17 Nov) | spoken, 12 English scenarios | 12 | 9 (75%) | 0 | 1 of 1 | 3.3 s / 4.0 s |
| 3, re-run of two failed scenarios after fixes | spoken | 2 | 2 | 0 | – | 3.2 s / 4.2 s (6 turns) |

The three Hindi scenarios have **no valid run in pass 3**. In the first attempt the simulated caller hung up after one turn in all three; by the retry the day's allowance for the simulator model was gone. Their last valid runs are from passes 1 and 2, where all three failed. Hindi is the least verified part of this agent.

### What the failures were

Passes 1 and 2 looked like an agent that drops half its calls. Reading the harness logs of pass 2 run by run, the 8 failures were:

- **4 runs: the agent went silent for 30 s** and the caller gave up. Both models had hit the per-minute limit, because a typed caller replies in a third of a second.
- **3 runs: the simulator broke** (malformed hang-up, or hung up on the first question).
- **1 run: a real agent error.** The LLM misread a Hindi date of birth three times and locked the caller out.

So the scores of passes 1 and 2 mostly measured the eval setup, not the agent. That is why pass 3 changed the method (spoken caller, paced requests, retries for simulator faults) as well as the agent.

### Real failures found and what changed

1. **The model invented what the caller said during verification.** First it mis-converted a Hindi date; later the fallback model called `verify_identity` before the caller had answered, with a made-up date of birth, and read it back to them. *Change:* dates and digits are parsed by code, and the words come from the transcript, so neither the conversion nor the words depend on the LLM.
2. **The agent sent a payment link nobody asked for** to an irritated caller who had only said he would pay on Friday. *Change:* the tool refuses unless a link was offered in an earlier turn or the caller asked for one. This has unit tests; the scenario's spoken re-run did not complete before the daily allowance ran out, so it is not yet confirmed end to end.
3. **Silence.** 13 to 30 s of dead air when both models were rate-limited; 4.9 s on the verification turn; 5.6 s median response time. *Change:* instant fallback with a spoken hold line if both models are limited, a code-spoken bridge line on verification, and the three latency changes above.
4. **Whisper transcribed English as Russian** on a live call. *Change:* detection is limited to English and Hindi.
5. **The agent repeated a mis-transcribed name** ("Thank you, Rohin") back to the caller. *Change:* the prompt gives the name and tells the agent to say it as written.

6. **Live calls went silent once the main model's daily allowance was spent.** With both models limited, the agent waited on the main model, whose limit lifts in minutes, not on the fallback, whose limit lifts in seconds; on six live calls that afternoon, four had turns that waited this way and three ended as `no_response`. *Change:* it waits for whichever model frees up first and skips a model at its daily cap. Unit-tested; not yet re-run live.
7. **A pause mid-number split the caller's digits across two turns** ("...is 48", "2-1"), and the agent asked again. *Change:* verification joins the caller's last two turns when the last one alone holds fewer than four digits.

### Known and not fixed

- **The fallback model breaks rules the main model keeps.** On `gpt-oss-20b` the agent read its own tool call aloud as JSON ending in "[call ends]", used the masculine "भेज रहा हूँ" for Asha, and in the already-paid re-run invited the caller to "share proof of the UPI transaction", which the prompt forbids. The outcome records were right; the conversation was not. The main model answers nearly every turn until the daily allowance is spent (about ten calls), and after that every turn is on the fallback.
- **Barge-in is not evaluated.** Interruption handling is Pipecat's default and works when tried by hand, but no scenario measures it.
- **Each scenario has one run per pass**, not several runs of the same code.

## What I'd do next

1. **Run the three Hindi scenarios and the irritated-caller scenario** when the allowance resets, twice each, and fix what they show. Hindi verification, the mid-call switch and the waiver request are untested end to end since the parsing moved to code.
2. **Stop the eval depending on the same free quota as the agent.** A local model as the simulated borrower and judge would allow three runs per scenario per day and remove the simulator's early hang-ups from the picture.
3. **Contain the fallback model.** Never send text to speech that looks like JSON or a stage direction, and re-check the guardrail scenarios with the fallback forced on, so the worst case is measured, not met by accident.
4. **Cut another second of latency.** Speech-to-text is the largest fixed cost at 0.8 to 1.0 s; a streaming recogniser that transcribes while the caller talks would remove most of it. Trimming the 2,100-token prompt would speed up the LLM and halve rate-limit pressure.
5. **Measure interruptions**: a scripted scenario where the caller cuts in mid-sentence, asserting that the agent stops and answers what was said.
6. **Catch paraphrased disclosure** ("about the money you owe") with a judge on pre-verification turns, alongside the regex.

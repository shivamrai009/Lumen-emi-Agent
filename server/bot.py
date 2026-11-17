"""Lumen Finance EMI reminder voice agent.

Pipecat cascade, free stack: local MLX Whisper (speech-to-text) -> gpt-oss-120b on Groq's
free tier, falling back to gpt-oss-20b when rate-limited (LLM) -> local Kokoro
(text-to-speech). Only the LLM leaves the machine.

Run the bot (browser call at http://localhost:7860, eval harness at ws://localhost:7860/ws):

    uv run bot.py

Which borrower is "called":
  - browser: BORROWER_ID in .env (default B001)
  - eval harness / websocket: ?borrower=B002 on the bot URL
Optional per-session query params (evals): run=<id>, today=YYYY-MM-DD,
fail_link=never|first|always, pace=<seconds between LLM requests, text-mode evals only>
"""

import datetime as dt
import io
import os
import time
import uuid
import wave

import aiofiles
from dotenv import load_dotenv
from loguru import logger
from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.evals.transport import EvalTransportParams
from pipecat.frames.frames import (
    EndWorkerFrame,
    LLMMessagesAppendFrame,
    LLMRunFrame,
    TTSSpeakFrame,
)
from pipecat.observers.user_bot_latency_observer import UserBotLatencyObserver
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    AssistantTurnStoppedMessage,
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
    UserTurnStoppedMessage,
)
from pipecat.processors.audio.audio_buffer_processor import AudioBufferProcessor
from pipecat.runner.types import RunnerArguments, WebSocketRunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.services.groq.llm import GroqLLMService
from pipecat.services.kokoro.tts import KokoroTTSService
from pipecat.services.whisper.stt import MLXModel, WhisperSTTServiceMLX
from pipecat.transcriptions.language import Language
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.turns.user_stop import TurnAnalyzerUserTurnStopStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.workers.runner import WorkerRunner

from lumen.data import load_borrowers
from lumen.llm import GroqFallbackLLMService
from lumen.outcome import write_outcome
from lumen.prompt import idle_nudge, system_prompt
from lumen.state import CallState
from lumen.stt import BilingualWhisperSTT, warm_up
from lumen.tools import ALL_TOOLS

load_dotenv(override=True)

# Seconds of caller silence before the agent checks in (twice), then hangs up.
USER_IDLE_SECS = float(os.getenv("USER_IDLE_SECS", "7"))
# The turn model decides from the caller's audio whether they have finished speaking.
# When it thinks they haven't, the agent waits this long in silence before answering
# anyway. Pipecat's default is 3 s, and in the first voice-level eval that wait was more
# than half of the response time on two turns out of three.
TURN_MAX_SILENCE_SECS = float(os.getenv("TURN_MAX_SILENCE_SECS", "1.5"))


async def save_audio_file(audio: bytes, filename: str, sample_rate: int, num_channels: int):
    if len(audio) > 0:
        with io.BytesIO() as buffer:
            with wave.open(buffer, "wb") as wf:
                wf.setsampwidth(2)
                wf.setnchannels(num_channels)
                wf.setframerate(sample_rate)
                wf.writeframes(audio)
            async with aiofiles.open(filename, "wb") as file:
                await file.write(buffer.getvalue())
        logger.info(f"Audio saved to {filename}")


def session_options(runner_args: RunnerArguments) -> dict:
    """Per-session options: websocket query params (evals), else the /start body, else env."""
    opts: dict = {}
    if isinstance(runner_args, WebSocketRunnerArguments) and runner_args.websocket is not None:
        opts.update(runner_args.websocket.query_params)
    if isinstance(runner_args.body, dict):
        opts.update({k: v for k, v in runner_args.body.items() if isinstance(v, str)})
    return opts


def build_state(opts: dict) -> CallState:
    today = dt.date.fromisoformat(opts["today"]) if opts.get("today") else dt.date.today()
    borrowers = load_borrowers(today)
    borrower_id = opts.get("borrower") or os.getenv("BORROWER_ID", "B001")
    if borrower_id not in borrowers:
        raise ValueError(f"Unknown borrower {borrower_id!r}; known: {', '.join(borrowers)}")
    b = borrowers[borrower_id]
    run_id = opts.get("run") or f"{dt.datetime.now():%Y%m%d-%H%M%S}-{b.id}-{uuid.uuid4().hex[:4]}"
    return CallState(
        borrower=b,
        today=today,
        run_id=run_id,
        language=b.preferred_language,
        link_failure_mode=opts.get("fail_link") or os.getenv("MOCK_LINK_FAILURE", "never"),
    )


# Spoken when every model is rate-limited and the reply has to wait: a wait is fine, a
# silent one is not.
HOLD_LINES = {
    "en": "Sorry, give me just a moment.",
    "hi": "माफ़ कीजिए, बस एक पल दीजिए।",
}


def make_llm(state: CallState, pace_secs: float = 0.0) -> GroqFallbackLLMService:
    """The agent's LLM: gpt-oss-120b on Groq's free tier, falling back to gpt-oss-20b.

    The free tier allows 8,000 tokens a minute per model and a turn costs ~2,000, so a
    rate-limited turn goes straight to the fallback model instead of waiting (see
    lumen/llm.py). Low reasoning effort keeps time-to-first-token down; set
    GROQ_REASONING_EFFORT empty for a model that rejects it.
    """
    effort = os.getenv("GROQ_REASONING_EFFORT", "low") or None
    fallbacks = [m for m in os.getenv("GROQ_FALLBACK_MODELS", "openai/gpt-oss-20b").split(",") if m]

    def on_fallback(primary: str, used: str) -> None:
        state.llm_fallbacks.append({"t": round(time.time() - state.started_at, 2), "model": used})

    def on_request(model: str) -> None:
        state.llm_requests[model] = state.llm_requests.get(model, 0) + 1

    async def on_all_limited() -> None:
        state.llm_all_limited += 1
        line = HOLD_LINES.get(state.language, HOLD_LINES["en"])
        await llm.push_frame(TTSSpeakFrame(line, append_to_context=False))

    llm = GroqFallbackLLMService(
        api_key=os.getenv("GROQ_API_KEY"),
        fallback_models=fallbacks,
        on_fallback=on_fallback,
        on_request=on_request,
        on_all_limited=on_all_limited,
        min_interval_secs=pace_secs,
        settings=GroqLLMService.Settings(
            model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
            system_instruction=system_prompt(state),
            **({"reasoning_effort": effort} if effort else {}),
        ),
    )
    return llm


async def run_bot(transport: BaseTransport, runner_args: RunnerArguments) -> None:
    opts = session_options(runner_args)
    state = build_state(opts)
    b = state.borrower
    logger.info(f"Starting call {state.run_id} to {b.id} ({b.name}), language={state.language}")

    # Local Whisper on Apple Silicon. language=None lets Whisper detect the language of
    # each utterance, so a caller switching to Hindi mid-call is transcribed as Hindi.
    # Anything it detects other than English or Hindi is transcribed again in the call's
    # current language (lumen/stt.py).
    def on_redetect(language: str | None) -> None:
        state.stt_redetections += 1

    stt = BilingualWhisperSTT(
        call_language=lambda: state.language,
        on_redetect=on_redetect,
        settings=WhisperSTTServiceMLX.Settings(
            model=os.getenv("WHISPER_MODEL", MLXModel.LARGE_V3_TURBO.value),
            language=None,
        ),
    )

    # Local Kokoro. One voice for both languages, so a language switch doesn't sound
    # like a different person picked up; only the phonemizer language changes.
    tts = KokoroTTSService(
        settings=KokoroTTSService.Settings(
            voice=os.getenv("KOKORO_VOICE", "hf_alpha"),
            language=Language.HI if state.language == "hi" else Language.EN,
        ),
    )

    llm = make_llm(state, pace_secs=float(opts.get("pace") or 0))

    context = LLMContext(tools=ALL_TOOLS)
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(),
            user_idle_timeout=USER_IDLE_SECS,
            user_turn_strategies=UserTurnStrategies(
                stop=[
                    TurnAnalyzerUserTurnStopStrategy(
                        turn_analyzer=LocalSmartTurnAnalyzerV3(
                            params=SmartTurnParams(stop_secs=TURN_MAX_SILENCE_SECS)
                        )
                    )
                ]
            ),
        ),
    )

    audio_buffer = AudioBufferProcessor(auto_start_recording=True)

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            user_aggregator,
            llm,
            tts,
            transport.output(),
            audio_buffer,
            assistant_aggregator,
        ]
    )

    # Measures caller-stops-speaking -> bot-starts-speaking for every turn, with a
    # per-service breakdown (STT, LLM TTFB, TTS TTFB, tool calls).
    latency_observer = UserBotLatencyObserver()

    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(enable_metrics=True, enable_usage_metrics=True),
        observers=[latency_observer],
        app_resources=state,
    )

    runner = WorkerRunner(handle_sigint=runner_args.handle_sigint)
    await runner.add_workers(worker)

    @latency_observer.event_handler("on_latency_measured")
    async def on_latency_measured(observer, latency: float):
        state.latencies_secs.append(latency)
        logger.info(f"Latency: caller stopped -> bot speaking = {latency * 1000:.0f} ms")

    @latency_observer.event_handler("on_first_bot_speech_latency")
    async def on_first_bot_speech_latency(observer, latency: float):
        state.first_speech_latency_secs = latency

    @latency_observer.event_handler("on_latency_breakdown")
    async def on_latency_breakdown(observer, breakdown):
        parts = ", ".join(f"{m.processor}={m.duration_secs * 1000:.0f}ms" for m in breakdown.ttfb)
        logger.info(f"Latency breakdown (TTFB): {parts}")

    @worker.rtvi.event_handler("on_client_ready")
    async def on_client_ready(rtvi):
        context.add_message(
            {
                "role": "developer",
                "content": "The call has just connected and someone has picked up. Open the call now.",
            }
        )
        await worker.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("Client connected")

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Client disconnected")
        if not state.outcome_written:
            write_outcome(
                state,
                outcome="call_dropped",
                notes="Caller disconnected before the agent closed the call.",
                ended_by="caller",
            )
        await runner.cancel()

    @user_aggregator.event_handler("on_user_turn_stopped")
    async def on_user_turn_stopped(aggregator, strategy, message: UserTurnStoppedMessage):
        state.idle_prompts = 0
        state.log("user", message.content)
        logger.info(f"Transcript: user: {message.content}")

    @user_aggregator.event_handler("on_user_turn_idle")
    async def on_user_turn_idle(aggregator):
        state.idle_prompts += 1
        logger.info(f"Caller idle (prompt {state.idle_prompts})")
        if state.idle_prompts > 2:
            # The LLM was told to hang up last time and didn't; do it ourselves.
            if not state.outcome_written:
                write_outcome(
                    state, outcome="no_response", notes="Caller went silent.", ended_by="system"
                )
            await worker.queue_frames([EndWorkerFrame()])
            return
        await worker.queue_frames(
            [
                LLMMessagesAppendFrame(
                    messages=[{"role": "developer", "content": idle_nudge(state)}], run_llm=True
                )
            ]
        )

    @assistant_aggregator.event_handler("on_assistant_turn_stopped")
    async def on_assistant_turn_stopped(aggregator, message: AssistantTurnStoppedMessage):
        if message.content:
            state.log("assistant", message.content)
            logger.info(f"Transcript: assistant: {message.content}")
            if state.hang_up_after_reply:
                # The goodbye end_call asked for has now been spoken.
                await worker.queue_frames([EndWorkerFrame()])

    @audio_buffer.event_handler("on_audio_data")
    async def on_audio_data(buffer, audio, sample_rate, num_channels):
        os.makedirs("recordings", exist_ok=True)
        await save_audio_file(audio, f"recordings/{state.run_id}.wav", sample_rate, num_channels)

    await runner.run()


async def bot(runner_args: RunnerArguments):
    """Main bot entry point."""
    transport_params = {
        "webrtc": lambda: TransportParams(audio_in_enabled=True, audio_out_enabled=True),
        # Behavioral evals: `pipecat eval` drives this bot through its eval transport.
        "eval": lambda: EvalTransportParams(audio_in_enabled=True, audio_out_enabled=True),
    }
    transport = await create_transport(runner_args, transport_params)
    await run_bot(transport, runner_args)


if __name__ == "__main__":
    from pipecat.runner.run import main

    # Load Whisper before the first call so the first caller turn isn't slow.
    warm_up(os.getenv("WHISPER_MODEL", MLXModel.LARGE_V3_TURBO.value))
    main()

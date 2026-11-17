"""Local Whisper that only ever hears English or Hindi.

Whisper detects the language of each utterance, which is what lets a caller switch to
Hindi mid-call with no setting to change. But on a short or mumbled utterance the
detector can land on any of its ~100 languages: on a live test call, a two-word English
reply came back as Russian ("Другой человек") and the agent could do nothing with it.

This call is in English or Hindi. So when Whisper detects anything else, the utterance is
decoded again with the language pinned to the one the call is currently in.

It is also about twice as fast as the stock service. ``mlx_whisper.transcribe`` runs the
audio encoder twice when the language isn't given: once to detect the language, once to
transcribe. The encoder is most of the cost for the turbo model, so on an Apple M4 a
short utterance took 1.57 s. Here the encoder runs once and its output is used for both
steps (and for the second decode, when one is needed): 0.83 s for the same audio.
"""

import asyncio
from collections.abc import AsyncGenerator, Callable
from typing import Any, cast

import numpy as np
from loguru import logger
from pipecat.frames.frames import ErrorFrame, Frame, TranscriptionFrame
from pipecat.services.whisper.stt import MLXModel, WhisperSTTServiceMLX
from pipecat.transcriptions.language import Language
from pipecat.utils.time import time_now_iso8601

ALLOWED = {"en": Language.EN, "hi": Language.HI}
# Above this compression ratio a segment is almost always a repetition hallucination.
HALLUCINATION_COMPRESSION_RATIO = 2.4
# Whisper works on 30-second windows; one caller utterance is far shorter.
WINDOW_SECS = 30
SAMPLE_RATE = 16000


def keep_segments(segments: list[dict[str, Any]], no_speech_threshold: float | None) -> str:
    """Join the segments that are speech, dropping silence and repetition hallucinations."""
    kept = []
    for s in segments:
        if s.get("compression_ratio", 0.0) > HALLUCINATION_COMPRESSION_RATIO:
            continue
        if no_speech_threshold is not None and s.get("no_speech_prob", 0.0) >= no_speech_threshold:
            continue
        kept.append(s.get("text", "").strip())
    return " ".join(t for t in kept if t)


def pick_language(detected: str | None, call_language: str) -> str:
    """The language to transcribe in: what Whisper detected if it is one the call uses.

    Whisper often labels spoken Hindi as Urdu (they sound alike; the scripts differ), so
    Urdu counts as Hindi and is written in Devanagari.
    """
    if detected == "ur":
        return "hi"
    return detected if detected in ALLOWED else call_language


def transcribe_once(
    audio: np.ndarray, model_path: str, call_language: str
) -> tuple[str, list[dict], bool]:
    """Detect the language and transcribe with one encoder pass.

    Returns (language, segments, redetected). Runs in a worker thread.
    """
    import mlx.core as mx
    from mlx_whisper.audio import N_FRAMES, N_SAMPLES, log_mel_spectrogram, pad_or_trim
    from mlx_whisper.decoding import DecodingOptions, decode
    from mlx_whisper.transcribe import ModelHolder, transcribe

    if len(audio) > WINDOW_SECS * SAMPLE_RATE:
        # Longer than one window (rare on a phone call): use the stock multi-window path.
        chunk = transcribe(audio, path_or_hf_repo=model_path, temperature=0.0, language=None)
        language = pick_language(chunk.get("language"), call_language)
        if language != chunk.get("language"):
            chunk = transcribe(
                audio, path_or_hf_repo=model_path, temperature=0.0, language=language
            )
            return language, chunk.get("segments", []), True
        return language, chunk.get("segments", []), False

    model = ModelHolder.get_model(model_path, mx.float16)
    mel = log_mel_spectrogram(audio, n_mels=model.dims.n_mels, padding=N_SAMPLES)
    window = pad_or_trim(mel, N_FRAMES, axis=-2).astype(mx.float16)

    def options(language: str | None) -> DecodingOptions:
        return DecodingOptions(language=language, temperature=0.0, without_timestamps=True)

    result = decode(model, window, options(None))
    language = pick_language(result.language, call_language)
    redetected = language != result.language
    if redetected:
        # Reuse the encoder output; only the (small) decoder runs again.
        result = decode(model, result.audio_features, options(language))
    segment = {
        "text": result.text,
        "no_speech_prob": result.no_speech_prob,
        "compression_ratio": result.compression_ratio,
    }
    return language, [segment], redetected


def warm_up(model_path: str = MLXModel.LARGE_V3_TURBO.value) -> None:
    """Load the model and run it once, so the first caller turn doesn't pay for it.

    Measured: the first utterance of the first call took 3.9 s to transcribe, the rest 0.8 s.
    """
    transcribe_once(np.zeros(SAMPLE_RATE, dtype=np.float32), model_path, "en")


class BilingualWhisperSTT(WhisperSTTServiceMLX):
    def __init__(
        self,
        *,
        call_language: Callable[[], str],
        on_redetect: Callable[[str | None], None] | None = None,
        **kwargs,
    ):
        """``call_language`` returns "en" or "hi": the language the call is in right now."""
        super().__init__(**kwargs)
        self._call_language = call_language
        self._on_redetect = on_redetect

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame, None]:
        try:
            await self.start_processing_metrics()
            audio_float = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0

            language, segments, redetected = await asyncio.to_thread(
                transcribe_once, audio_float, str(self._settings.model), self._call_language()
            )
            if redetected:
                logger.warning(f"Whisper heard another language; transcribed as {language!r}")
                if self._on_redetect:
                    self._on_redetect(language)

            text = keep_segments(segments, cast("float | None", self._settings.no_speech_prob))
            await self.stop_processing_metrics()

            if text:
                await self._handle_transcription(text, True, ALLOWED[language])
                logger.debug(f"Transcription ({language}): [{text}]")
                yield TranscriptionFrame(text, self._user_id, time_now_iso8601(), ALLOWED[language])
        except Exception as e:
            yield ErrorFrame(error=f"Speech-to-text failed: {e}")

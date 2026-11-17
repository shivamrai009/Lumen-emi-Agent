"""The speech-to-text filter that drops silence and repetition hallucinations."""

from lumen.stt import keep_segments, pick_language


def test_keeps_speech_and_drops_silence_and_repetition():
    segments = [
        {"text": " Yes, speaking.", "no_speech_prob": 0.1, "compression_ratio": 1.1},
        {"text": " Thank you.", "no_speech_prob": 0.9, "compression_ratio": 1.0},
        {"text": " ok ok ok ok ok ok", "no_speech_prob": 0.1, "compression_ratio": 3.0},
    ]
    assert keep_segments(segments, 0.6) == "Yes, speaking."


def test_no_segments_is_empty():
    assert keep_segments([], 0.6) == ""


def test_only_english_and_hindi_are_accepted():
    # Seen on a live call: two English words came back as Russian.
    assert pick_language("ru", "en") == "en"
    assert pick_language("ur", "en") == "hi"  # spoken Hindi is often labelled Urdu
    assert pick_language("hi", "en") == "hi"
    assert pick_language(None, "en") == "en"

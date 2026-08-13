from app.services.srt_transcript_service import (
    AsrResult,
    WordTiming,
    build_transcription_only_srt_bundle,
    has_visible_lyrics_for_alignment,
)


def test_transcription_only_srt_bundle_uses_asr_segments_without_lyrics() -> None:
    assert has_visible_lyrics_for_alignment("") is False

    bundle = build_transcription_only_srt_bundle(
        AsrResult(
            text="",
            words=[],
            segments=[
                {"start": 1.0, "end": 3.0, "text": "Freier gesprochener Text"},
                {"start": 3.5, "end": 5.0, "text": "ohne gespeicherte Lyrics"},
            ],
            raw={},
        ),
        duration_seconds=6.0,
    )

    assert bundle["mode"] == "transcription_only_no_lyrics"
    assert bundle["source"] == "asr_segments"
    assert [segment["text"] for segment in bundle["segments"]] == [
        "Freier gesprochener Text",
        "ohne gespeicherte Lyrics",
    ]
    assert "Freier" in bundle["half_srt_text"]
    assert "gesprochener Text" in bundle["half_srt_text"]


def test_transcription_only_srt_bundle_groups_words_when_segments_are_missing() -> None:
    bundle = build_transcription_only_srt_bundle(
        AsrResult(
            text="",
            words=[
                WordTiming("Ein", 0.0, 0.2),
                WordTiming("kurzer", 0.25, 0.55),
                WordTiming("Satz", 0.6, 0.9),
                WordTiming("Pause", 2.0, 2.4),
            ],
            segments=[],
            raw={},
        ),
        duration_seconds=3.0,
    )

    assert bundle["source"] == "word_timestamps"
    assert [segment["text"] for segment in bundle["segments"]] == ["Ein kurzer Satz", "Pause"]


def test_transcription_only_prefers_real_word_timestamps_over_provider_segments() -> None:
    bundle = build_transcription_only_srt_bundle(
        AsrResult(
            text="",
            words=[
                WordTiming("Lang", 2.0, 2.4),
                WordTiming("gezogen", 2.4, 4.8),
                WordTiming("gesungen", 5.0, 5.5),
            ],
            segments=[{"start": 0.0, "end": 9.0, "text": "Lang gezogen gesungen"}],
            raw={},
        ),
        duration_seconds=10.0,
    )

    assert bundle["source"] == "word_timestamps"
    assert bundle["segments"][0]["start"] == 2.0
    assert bundle["segments"][0]["end"] == 5.5


def test_transcription_only_rejects_synthetic_word_timings_from_segment_text() -> None:
    bundle = build_transcription_only_srt_bundle(
        AsrResult(
            text="",
            words=[
                WordTiming("Lang", 0.0, 3.0),
                WordTiming("gezogen", 3.0, 6.0),
            ],
            segments=[{"start": 2.0, "end": 5.5, "text": "Lang gezogen"}],
            raw={"songstudio_word_source": "segment_text_distributed"},
        ),
        duration_seconds=10.0,
    )

    assert bundle["source"] == "asr_segments"
    assert bundle["segments"][0]["start"] == 2.0
    assert bundle["segments"][0]["end"] == 5.5
    assert bundle["alignment_report"]

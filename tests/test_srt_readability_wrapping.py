from app.services.srt_transcript_service import (
    AsrResult,
    WordTiming,
    STANDARD_SRT_MAX_CHARS,
    align_lyrics_to_timeline_bundle,
    build_structure_segments_from_srt_alignment,
    build_transcription_only_srt_bundle,
)


def _word_timings(text: str) -> list[WordTiming]:
    return [
        WordTiming(word=word, start=index * 0.35, end=index * 0.35 + 0.3)
        for index, word in enumerate(text.split())
    ]


def _assert_readable_and_complete(segments: list[dict], source: str) -> None:
    assert len(segments) > 1
    assert all(len(segment["text"]) <= STANDARD_SRT_MAX_CHARS for segment in segments)
    assert " ".join(segment["text"] for segment in segments) == source
    assert all(left["end"] <= right["start"] + 0.001 for left, right in zip(segments, segments[1:]))


def test_lyrics_alignment_wraps_a_single_long_lyrics_line_for_standard_srt() -> None:
    lyrics = (
        "But time heal every wound dem, slowly mi start fi rise, new goal, new friend dem, "
        "mi tek it as a compromise, mi meet a girl name Steffi, mi heart start fi burn."
    )
    bundle = align_lyrics_to_timeline_bundle(
        lyrics,
        AsrResult(text=lyrics, words=_word_timings(lyrics), segments=[], raw={}),
        duration_seconds=30.0,
    )

    _assert_readable_and_complete(bundle["segments"], lyrics)
    assert {segment["source_line"] for segment in bundle["segments"]} == {1}
    structure = build_structure_segments_from_srt_alignment(
        f"[Verse 1]\n{lyrics}", bundle["segments"], duration_seconds=30.0, waveform_only=True
    )
    assert [(item["label"], item["type"]) for item in structure] == [("Verse 1", "verse")]


def test_transcription_only_wraps_a_provider_paragraph_for_standard_srt() -> None:
    text = (
        "But time heal every wound dem, slowly mi start fi rise, new goal, new friend dem, "
        "mi tek it as a compromise, mi meet a girl name Steffi, mi heart start fi burn."
    )
    bundle = build_transcription_only_srt_bundle(
        AsrResult(text=text, words=[], segments=[{"start": 3.0, "end": 18.0, "text": text}], raw={}),
        duration_seconds=20.0,
    )

    _assert_readable_and_complete(bundle["segments"], text)
    assert all(segment["alignment_method"] == "transcription_only_asr_segment" for segment in bundle["segments"])


def test_standard_lyrics_srt_uses_word_boundaries_not_character_proportions() -> None:
    lyrics = (
        "Mi burst inna dis place with a song full a pure love, every single word "
        "come from mi heart above and the final note stays stretched for long."
    )
    words = []
    cursor = 1.0
    for index, word in enumerate(lyrics.split()):
        duration = 0.12 if index < len(lyrics.split()) - 1 else 2.4
        words.append(WordTiming(word=word, start=cursor, end=cursor + duration))
        cursor += duration + 0.08

    bundle = align_lyrics_to_timeline_bundle(
        lyrics,
        AsrResult(text=lyrics, words=words, segments=[], raw={}),
        duration_seconds=20.0,
    )
    segments = bundle["segments"]
    word_starts = {round(word.start, 3) for word in words}
    word_ends = {round(word.end, 3) for word in words}

    assert len(segments) > 1
    assert all(round(segment["start"], 3) in word_starts for segment in segments)
    assert all(round(segment["end"], 3) in word_ends for segment in segments)
    assert segments[-1]["end"] == round(words[-1].end, 3)

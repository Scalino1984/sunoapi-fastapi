from __future__ import annotations

from app.services import srt_transcript_service as srt
from app.services.srt_parser import normalize_srt_segment


def test_provider_word_extraction_does_not_duplicate_top_level_and_nested_words() -> None:
    payload = {
        "words": [
            {"word": "Mi", "start": 1.0, "end": 1.2},
            {"word": "deh", "start": 1.3, "end": 1.5},
        ],
        "segments": [{"start": 1.0, "end": 1.5, "text": "Mi deh", "words": [
            {"word": "Mi", "start": 1.0, "end": 1.2},
            {"word": "deh", "start": 1.3, "end": 1.5},
        ]}],
    }

    words = srt._extract_words(payload)

    assert [word.word for word in words] == ["Mi", "deh"]


def test_missing_provider_word_is_interpolated_between_real_neighbors() -> None:
    payload = {
        "segments": [{
            "start": 10.0,
            "end": 12.0,
            "words": [
                {"word": "mi", "start": 10.1, "end": 10.3},
                {"word": "deh"},
                {"word": "yah", "start": 11.0, "end": 11.2},
            ],
        }],
    }

    srt._interpolate_whisperx_words(payload)
    missing = payload["segments"][0]["words"][1]

    assert 10.3 <= missing["start"] < missing["end"] <= 11.0
    assert missing["interpolated"] is True
    assert srt._detect_asr_word_source(payload) == "segment_word_timestamps_interpolated"


def test_language_resolution_handles_english_german_and_jamaican_patois() -> None:
    patois = srt.resolve_transcription_language("de", "Mi deh yah, yuh nuh waan leave di yaad")
    english = srt.resolve_transcription_language("de", "The night is bright and we will never fall")
    german = srt.resolve_transcription_language("en", "Ich gehe durch die Nacht und finde meinen Weg")

    assert patois[0] == "en"
    assert patois[1]["patois_hits"] >= 3
    assert english[0] == "en"
    assert german[0] == "de"


def test_srt_normalizer_keeps_alignment_contract_fields() -> None:
    normalized = normalize_srt_segment({
        "start": 2.0,
        "end": 3.0,
        "text": "Mi deh",
        "source_line": 4,
        "alignment_confidence": 0.8,
        "matched": True,
        "alignment_method": "lyrics_align_srt_reference",
    })

    assert normalized["source_line"] == 4
    assert normalized["alignment_confidence"] == 0.8
    assert normalized["matched"] is True
    assert normalized["alignment_method"] == "lyrics_align_srt_reference"

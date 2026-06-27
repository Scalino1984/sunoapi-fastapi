import pytest
from fastapi import HTTPException

from app.routers.srt import SrtRawPayload, SrtSegmentsPayload, export_srt_from_segments, parse_raw_srt, validate_srt
from app.services.srt_parser import export_srt, parse_srt, parse_srt_timestamp, srt_timestamp
from app.services.srt_validation import normalize_or_raise, validate_srt_segments


def test_srt_timestamp_roundtrip_and_invalid_input():
    assert srt_timestamp(3723.456) == "01:02:03,456"
    assert parse_srt_timestamp("01:02:03.456") == 3723.456
    with pytest.raises(ValueError):
        parse_srt_timestamp("bad")


def test_parse_and_export_srt_normalizes_indices_and_linebreaks():
    raw = """
99
00:00:02,000 --> 00:00:03,000
zweite Zeile

1
00:00:00,000 --> 00:00:01,000
erste Zeile
""".strip()

    segments = parse_srt(raw)
    assert [(row["index"], row["text"]) for row in segments] == [(1, "erste Zeile"), (2, "zweite Zeile")]
    assert export_srt(segments).startswith("1\n00:00:00,000 --> 00:00:01,000")


def test_validate_route_reports_errors_and_export_route_returns_srt_text():
    payload = SrtSegmentsPayload(segments=[{"start": 5, "end": 4, "text": "kaputt"}])
    result = validate_srt(payload)

    assert result["valid"] is True
    assert any(issue["type"] == "short_duration" for issue in result["issues"])

    ok_payload = SrtSegmentsPayload(segments=[{"start": 0, "end": 1.2, "text": "ok"}])
    exported = export_srt_from_segments(ok_payload)
    assert exported["srt"] == "1\n00:00:00,000 --> 00:00:01,200\nok\n"


def test_parse_route_and_normalize_or_raise():
    parsed = parse_raw_srt(SrtRawPayload(srt="1\n00:00:00,000 --> 00:00:01,000\nHallo"))

    assert parsed["segments"][0]["text"] == "Hallo"
    assert normalize_or_raise(parsed["segments"])[0]["text"] == "Hallo"

    with pytest.raises(HTTPException) as exc:
        normalize_or_raise([])
    assert exc.value.status_code == 422


def test_short_segments_are_normalized_but_still_warned():
    result = validate_srt_segments([{"start": 0, "end": 0.1, "text": "kurz"}])

    assert result["valid"] is True
    assert result["segments"][0]["end"] >= 0.3
    assert any(issue["type"] == "short_duration" for issue in result["issues"])

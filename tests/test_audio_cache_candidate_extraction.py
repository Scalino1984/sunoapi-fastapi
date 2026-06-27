from datetime import datetime

from app.services.audio_cache_service import (
    collect_audio_candidates,
    collect_image_urls,
    extract_source_created_at,
    first_source_created_at,
    parse_source_datetime,
)


def test_parse_source_datetime_accepts_iso_seconds_and_milliseconds():
    assert parse_source_datetime("2026-06-20T01:02:03Z") == datetime(2026, 6, 20, 1, 2, 3)
    assert parse_source_datetime(1_782_000_000_000) == parse_source_datetime(1_782_000_000)
    assert parse_source_datetime("2026-06-20") == datetime(2026, 6, 20)
    assert parse_source_datetime("not-a-date") is None


def test_collect_audio_candidates_deduplicates_multi_url_payloads_per_variant():
    payload = {
        "data": [
            {
                "id": "clip-a",
                "title": "Song A",
                "audioUrl": "https://cdn.example.test/song-a.mp3",
                "sourceAudioUrl": "https://cdn.example.test/song-a.mp3",
                "imageUrl": "https://cdn.example.test/song-a.jpg",
                "duration": "123.9",
                "createTime": "2026-06-20T01:02:03Z",
            },
            {
                "id": "clip-a",
                "title": "Song A Duplicate",
                "audioUrl": "https://cdn.example.test/song-a.mp3",
            },
            {
                "id": "cover-only",
                "imageUrl": "https://cdn.example.test/cover.png",
            },
        ]
    }

    candidates = collect_audio_candidates(payload)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.audio_id == "clip-a"
    assert candidate.title == "Song A"
    assert candidate.image_url == "https://cdn.example.test/song-a.jpg"
    assert candidate.duration_seconds == 123
    assert candidate.created_at == datetime(2026, 6, 20, 1, 2, 3)


def test_collect_image_urls_and_first_created_at_walk_nested_payloads():
    payload = {
        "result": {
            "createdAt": "2026-06-21T12:00:00+00:00",
            "items": [
                {"coverUrl": "https://cdn.example.test/a.webp"},
                {"thumbnail_url": "https://cdn.example.test/a.webp"},
                {"image": "https://cdn.example.test/b.png"},
            ],
        }
    }

    assert collect_image_urls(payload) == ["https://cdn.example.test/a.webp", "https://cdn.example.test/b.png"]
    assert first_source_created_at(payload) == datetime(2026, 6, 21, 12, 0, 0)
    assert extract_source_created_at({"metadata": {"created_time": 1_782_000_000}}) == parse_source_datetime(1_782_000_000)

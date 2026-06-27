from app.models import AudioAsset
from app.services.waveform_service import (
    _clean_existing_segments,
    _segments_have_descriptor_noise,
    build_structure_segments,
    extract_structure_marker,
    sanitize_waveform_payload_for_asset,
    scale_segments_to_duration,
)


def test_extract_structure_marker_ignores_descriptor_tags():
    assert extract_structure_marker("Verse 2 | German Male Rap | High Energy") == {"label": "Verse 2", "type": "verse"}
    assert extract_structure_marker("Final Chorus: doubled vocals") == {"label": "Final Chorus", "type": "chorus"}
    assert extract_structure_marker("bass-heavy gritty mix") is None
    assert extract_structure_marker("spoken word") is None


def test_build_structure_segments_uses_only_real_sections_and_weighted_duration():
    asset = AudioAsset(
        id=1,
        source_url="https://cdn.example.test/song.mp3",
        status="remote",
        duration_seconds=120,
        metadata_json={"candidate": {"lyrics": "[Intro]\nA\n[Verse 1 | gritty]\nB\nC\n[Chorus]\nD"}},
    )

    segments = build_structure_segments(asset, 120)

    assert [segment["label"] for segment in segments] == ["Intro", "Verse 1", "Chorus"]
    assert segments[0]["start"] == 0.0
    assert segments[-1]["end"] == 120.0
    assert segments[1]["end"] > segments[0]["end"]


def test_sanitize_waveform_payload_replaces_noisy_descriptor_segments_with_clean_structure():
    asset = AudioAsset(
        id=1,
        source_url="https://cdn.example.test/song.mp3",
        status="remote",
        duration_seconds=90,
        structure_segments_json=[
            {"label": "Verse", "type": "verse", "start": 0, "end": 45},
            {"label": "Chorus", "type": "chorus", "start": 45, "end": 90},
        ],
    )
    waveform = {
        "duration_seconds": 90,
        "peaks": [0.1, 0.5],
        "segments": [{"label": "Verse | German Male Rap", "type": "verse", "start": 0, "end": 90}],
    }

    assert _segments_have_descriptor_noise(waveform["segments"]) is True
    sanitized = sanitize_waveform_payload_for_asset(asset, waveform)

    assert sanitized["segments"] == asset.structure_segments_json


def test_scale_segments_to_duration_stretches_last_section_to_audio_duration():
    source = [
        {"label": "Intro", "type": "intro", "start": 0, "end": 10},
        {"label": "Verse", "type": "verse", "start": 10, "end": 50},
    ]

    scaled = scale_segments_to_duration(source, 100)

    assert scaled == [
        {"label": "Intro", "type": "intro", "start": 0.0, "end": 20.0},
        {"label": "Verse", "type": "verse", "start": 20.0, "end": 100.0},
    ]
    assert _clean_existing_segments([{ "label": "FX sweep", "start": 0, "end": 5 }]) == []

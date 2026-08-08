from app.models import AudioAsset
from app.services.waveform_service import (
    _clean_existing_segments,
    _segments_have_descriptor_noise,
    build_structure_segments,
    extract_waveform_structure_marker,
    sanitize_waveform_payload_for_asset,
    scale_segments_to_duration,
)


def test_extract_structure_marker_ignores_descriptor_tags():
    assert extract_waveform_structure_marker("Verse 2 | German Male Rap | High Energy") == {"label": "Verse 2", "type": "verse"}
    assert extract_waveform_structure_marker("Final Chorus: doubled vocals") == {"label": "Final Chorus", "type": "chorus"}
    assert extract_waveform_structure_marker("bass-heavy gritty mix") is None
    assert extract_waveform_structure_marker("spoken word") is None


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


def test_rich_vocal_descriptors_do_not_become_false_sections():
    assert extract_waveform_structure_marker("Deep Male Rapper | Hard Straight Rap Break | No Singing") is None
    assert extract_waveform_structure_marker("Outro | Stripped Chorus Reprise | Fade-Out") == {"label": "Outro", "type": "outro"}
    assert extract_waveform_structure_marker("Intro | Build-Up | Singer-Rapper Alternation") == {"label": "Intro", "type": "intro"}
    assert extract_waveform_structure_marker("Final Chorus x2 | Maximum Anthemic Climax") == {"label": "Final Chorus x2", "type": "chorus"}


def test_build_structure_segments_keeps_only_primary_arrangement_sections():
    lyrics = """
[Intro | Build-Up | Clear Singer-Rapper Alternation]
[Male Singer | Airy Emotional Singing | No Rap]
Intro singer line
[Deep Male Rapper | Confident Spoken Rap | No Singing]
Intro rapper line
[Verse 1 | Deep Baritone Male Rap | No Singing]
Verse one line
[Build-Up | Male Spoken Word | Tension Rising | No Singing]
Build line
[Chorus x2 | Repeat Entire Hook Twice | Clear Vocal Role Switching]
[Rough Male Singer | No Rap]
Hook singer line
[Deep Male Rapper | Hard Straight Rap Break | No Singing]
Hook rapper line
[Rough Male Singer | No Rap]
Hook singer ending
[Verse 2 | Deep Male Rap | No Singing]
Verse two line
[Final Chorus x2 | Repeat Entire Hook Twice | Maximum Anthemic Climax]
[Rough Male Singer | No Rap]
Final singer line
[Deep Male Rapper | Aggressive Straight Rap Break | No Singing]
Final rapper line
[Outro | Stripped Chorus Reprise | Gradual Fade-Out]
[Male Singer | Soft Emotional Singing | No Rap]
Outro line
[End]
""".strip()
    asset = AudioAsset(
        id=2,
        source_url="https://cdn.example.test/song.mp3",
        status="remote",
        duration_seconds=245,
        metadata_json={"candidate": {"lyrics": lyrics}},
    )

    segments = build_structure_segments(asset, 245)

    assert [segment["label"] for segment in segments] == [
        "Intro",
        "Verse 1",
        "Build-Up",
        "Chorus x2",
        "Verse 2",
        "Final Chorus x2",
        "Outro",
    ]
    assert all(segment["type"] != "break" for segment in segments)


def test_sanitize_repairs_old_false_breaks_and_outro_misclassification_using_lyrics_order():
    lyrics = """
[Intro | Build-Up]
Intro line
[Verse 1 | Deep Rap]
Verse one line
[Build-Up | Spoken Word]
Build line
[Chorus x2 | Repeat Entire Hook Twice]
Singer line
[Deep Male Rapper | Hard Straight Rap Break | No Singing]
Rapper line
[Verse 2 | Deep Rap]
Verse two line
[Final Chorus x2 | Maximum Climax]
Final line
[Deep Male Rapper | Aggressive Straight Rap Break | No Singing]
Final rapper line
[Outro | Stripped Chorus Reprise]
Outro line
""".strip()
    stale = [
        {"label": "Intro", "type": "intro", "start": 0, "end": 20},
        {"label": "Verse 1", "type": "verse", "start": 20, "end": 90},
        {"label": "Build-Up", "type": "build_up", "start": 90, "end": 110},
        {"label": "Chorus", "type": "chorus", "start": 110, "end": 125},
        {"label": "Break", "type": "break", "start": 125, "end": 145},
        {"label": "Verse 2", "type": "verse", "start": 145, "end": 200},
        {"label": "Final Chorus", "type": "chorus", "start": 200, "end": 215},
        {"label": "Break", "type": "break", "start": 215, "end": 230},
        {"label": "Chorus", "type": "chorus", "start": 230, "end": 245},
    ]
    asset = AudioAsset(
        id=3,
        source_url="https://cdn.example.test/song.mp3",
        status="remote",
        duration_seconds=245,
        structure_segments_json=stale,
        metadata_json={"candidate": {"lyrics": lyrics}},
    )
    waveform = {"duration_seconds": 245, "peaks": [0.1, 0.5], "segments": stale}

    sanitized = sanitize_waveform_payload_for_asset(asset, waveform)

    assert [segment["label"] for segment in sanitized["segments"]] == [
        "Intro",
        "Verse 1",
        "Build-Up",
        "Chorus x2",
        "Verse 2",
        "Final Chorus x2",
        "Outro",
    ]
    assert [segment["start"] for segment in sanitized["segments"]] == [0.0, 20.0, 90.0, 110.0, 145.0, 200.0, 230.0]
    assert sanitized["segments"][-1]["end"] == 245.0

from app.services.srt_transcript_service import (
    build_structure_segments_from_srt_alignment,
    deterministic_prepare_lyrics_for_srt,
)


def test_srt_structure_segments_use_original_tagged_lyrics_after_cleanup() -> None:
    source_lyrics = """
[Intro: radio noise]
Donner ueber NYC
[Verse 1 | male rap]
Ich lauf durch Neonlicht
Der Asphalt atmet kalt
[Chorus]
Donnerbalken NYC
Wir bleiben wach
""".strip()

    cleaned, cleanup = deterministic_prepare_lyrics_for_srt(source_lyrics)

    assert cleanup["changed"] is True
    assert "[Verse" not in cleaned
    assert "[Chorus]" not in cleaned

    srt_segments = [
        {"index": 1, "source_line": 1, "start": 1.0, "end": 2.0, "text": "Donner ueber NYC"},
        {"index": 2, "source_line": 2, "start": 8.0, "end": 9.0, "text": "Ich lauf durch Neonlicht"},
        {"index": 3, "source_line": 3, "start": 10.0, "end": 11.0, "text": "Der Asphalt atmet kalt"},
        {"index": 4, "source_line": 4, "start": 20.0, "end": 21.0, "text": "Donnerbalken NYC"},
        {"index": 5, "source_line": 5, "start": 22.0, "end": 23.0, "text": "Wir bleiben wach"},
    ]

    result = build_structure_segments_from_srt_alignment(source_lyrics, srt_segments, 180)

    assert result == [
        {"label": "Intro", "type": "intro", "start": 0.0, "end": 6.0, "source": "srt_alignment"},
        {"label": "Verse 1", "type": "verse", "start": 6.0, "end": 18.0, "source": "srt_alignment"},
        {"label": "Chorus", "type": "chorus", "start": 18.0, "end": 180.0, "source": "srt_alignment"},
    ]


def test_srt_structure_segments_do_not_invent_sections_without_original_tags() -> None:
    source_lyrics = """
Donner ueber NYC
Ich lauf durch Neonlicht
Der Asphalt atmet kalt
""".strip()
    srt_segments = [
        {"index": 1, "source_line": 1, "start": 1.0, "end": 2.0, "text": "Donner ueber NYC"},
        {"index": 2, "source_line": 2, "start": 3.0, "end": 4.0, "text": "Ich lauf durch Neonlicht"},
    ]

    assert build_structure_segments_from_srt_alignment(source_lyrics, srt_segments, 120) == []


def test_srt_structure_segments_fall_back_to_text_match_when_source_lines_shift() -> None:
    source_lyrics = """
[Verse]
Eine Zeile die spaeter fehlt
Ich lauf durch Neonlicht
[Chorus]
Donnerbalken NYC
""".strip()
    srt_segments = [
        {"index": 1, "source_line": 1, "start": 8.0, "end": 9.0, "text": "Ich lauf durch Neonlicht"},
        {"index": 2, "source_line": 2, "start": 20.0, "end": 21.0, "text": "Donnerbalken NYC"},
    ]

    result = build_structure_segments_from_srt_alignment(source_lyrics, srt_segments, 120)

    assert result == [
        {"label": "Verse", "type": "verse", "start": 6.0, "end": 18.0, "source": "srt_alignment"},
        {"label": "Chorus", "type": "chorus", "start": 18.0, "end": 120.0, "source": "srt_alignment"},
    ]

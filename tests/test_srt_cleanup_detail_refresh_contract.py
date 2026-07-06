from pathlib import Path

from app.services.srt_transcript_service import deterministic_prepare_lyrics_for_srt


def test_srt_cleanup_normalizes_obvious_repeated_consonant_artifacts():
    raw = """Ein teil der Nachttt
...
Ein teil der Nachttt
...
Einnn teilll derrr Nachttt
(ein teil der nacht)"""

    cleaned, info = deterministic_prepare_lyrics_for_srt(raw)

    assert cleaned == """Ein teil der Nacht
...
Ein teil der Nacht
...
Ein teil der Nacht
ein teil der nacht"""
    assert info["normalized_stretch_count"] >= 6


def test_library_page_listens_for_external_srt_updates():
    library_page = Path("frontend-react/src/pages/LibraryPage.jsx").read_text(encoding="utf-8")

    assert "window.addEventListener('srt:updated', handleExternalSrtUpdated)" in library_page
    assert "window.removeEventListener('srt:updated', handleExternalSrtUpdated)" in library_page
    assert "Neu erzeugte SRTs ohne" not in library_page or "Browser-Refresh" in library_page


def test_srt_cleanup_normalizes_suno_vocal_stretches_without_dropping_intro_lines():
    raw = """[Global: Male Vocal, Rap, No AutoTune]
[Intro: cinematic spoken male vocal, intimate, dark]
Skalinooo.
Es ist Zeit zu-gehn ahaaa

[Verse 1: emotional male rap, German]
Ich geh meinen Weeeg entlaaang.
kein Fle-hen mehr – nur die Sprache der Wut
"""

    cleaned, info = deterministic_prepare_lyrics_for_srt(raw)

    assert cleaned.startswith("Skalino.\nEs ist Zeit zu gehn ahaaa")
    assert "Ich geh meinen Weg entlang." in cleaned
    assert "kein Flehen mehr – nur die Sprache der Wut" in cleaned
    assert "[Global" not in cleaned
    assert "[Intro" not in cleaned
    assert info["removed_count"] >= 3
    assert any("Skalinooo->Skalino" in item for item in info["normalized_stretches"])
    assert any("Weeeg->Weg" in item for item in info["normalized_stretches"])
    assert any("entlaaang->entlang" in item for item in info["normalized_stretches"])
    assert any("Fle-hen->Flehen" in item for item in info["normalized_stretches"])


def test_srt_cleanup_keeps_short_vocal_adlibs_when_they_are_not_normal_words():
    raw = """ahaaa
ohhh
yyeahhh
yeahhh
Skalinooo
"""

    cleaned, info = deterministic_prepare_lyrics_for_srt(raw)

    assert "ahaaa" in cleaned
    assert "ohhh" in cleaned
    assert "yeahhh" in cleaned
    assert "Skalino" in cleaned
    assert "Skalinooo" not in cleaned


def test_srt_alignment_does_not_compress_unmatched_intro_lines_before_first_anchor():
    from app.services.srt_transcript_service import AsrResult, WordTiming, align_lyrics_to_timeline_bundle

    lyrics = """Skalino.
Es ist Zeit zu gehn ahaaa
Es ist Zeit meine Wege neu zu gehen
Keine Leute mehr die blenden
"""
    asr = AsrResult(
        text="Es ist Zeit meine Wege neu zu gehen Keine Leute mehr die blenden",
        words=[
            WordTiming("Es", 7.8, 7.95),
            WordTiming("ist", 7.96, 8.08),
            WordTiming("Zeit", 8.09, 8.32),
            WordTiming("meine", 8.50, 8.76),
            WordTiming("Wege", 8.80, 9.08),
            WordTiming("neu", 9.12, 9.35),
            WordTiming("zu", 9.36, 9.48),
            WordTiming("gehen", 9.50, 9.86),
            WordTiming("Keine", 10.20, 10.48),
            WordTiming("Leute", 10.50, 10.78),
            WordTiming("mehr", 10.80, 11.02),
            WordTiming("die", 11.04, 11.16),
            WordTiming("blenden", 11.18, 11.58),
        ],
        segments=[],
        raw={},
    )

    result = align_lyrics_to_timeline_bundle(lyrics, asr, duration_seconds=120)
    segments = result["segments"]

    assert segments[0]["text"] == "Skalino."
    assert 2.5 <= segments[0]["start"] <= 4.5
    assert segments[0]["end"] <= segments[1]["start"]
    assert segments[1]["end"] <= segments[2]["start"]
    assert any("Intro-Fenster" in item for item in result["alignment_report"])


def test_srt_alignment_keeps_unmatched_intro_line_between_early_anchors_readable():
    from app.services.srt_transcript_service import AsrResult, WordTiming, align_lyrics_to_timeline_bundle

    lyrics = """Skalino.
Es ist Zeit zu gehn ahaaa
Es ist Zeit meine Wege neu zu gehen
Keine Leute mehr die blenden
"""
    # Fehlerfall aus der Praxis: Der Artist-Call wird frueh erkannt, aber vom ASR
    # mit zu langer Dauer geliefert. Die naechste Intro-Zeile wird nicht erkannt;
    # der erste sichere Hauptzeilen-Anchor beginnt erst danach. Ohne Schutz wird
    # die zweite Zeile auf wenige Zehntelsekunden gequetscht und wirkt im Player
    # wie uebersprungen.
    asr = AsrResult(
        text="Skalino Es ist Zeit meine Wege neu zu gehen Keine Leute mehr die blenden",
        words=[
            WordTiming("Skalino", 3.0, 7.15),
            WordTiming("Es", 7.8, 7.95),
            WordTiming("ist", 7.96, 8.08),
            WordTiming("Zeit", 8.09, 8.32),
            WordTiming("meine", 8.50, 8.76),
            WordTiming("Wege", 8.80, 9.08),
            WordTiming("neu", 9.12, 9.35),
            WordTiming("zu", 9.36, 9.48),
            WordTiming("gehen", 9.50, 9.86),
            WordTiming("Keine", 10.20, 10.48),
            WordTiming("Leute", 10.50, 10.78),
            WordTiming("mehr", 10.80, 11.02),
            WordTiming("die", 11.04, 11.16),
            WordTiming("blenden", 11.18, 11.58),
        ],
        segments=[],
        raw={},
    )

    result = align_lyrics_to_timeline_bundle(lyrics, asr, duration_seconds=120)
    segments = result["segments"]

    assert segments[0]["text"] == "Skalino."
    assert segments[1]["text"] == "Es ist Zeit zu gehn ahaaa"
    assert segments[2]["text"] == "Es ist Zeit meine Wege neu zu gehen"
    assert segments[1]["start"] >= segments[0]["end"]
    assert segments[1]["end"] <= segments[2]["start"]
    assert segments[1]["end"] - segments[1]["start"] >= 1.6
    assert any("entquetscht" in item for item in result["alignment_report"])


def test_srt_alignment_caps_overlong_first_intro_anchor_so_next_line_is_visible():
    from app.services.srt_transcript_service import AsrResult, WordTiming, align_lyrics_to_timeline_bundle

    lyrics = """Skalino.
Es ist Zeit zu gehn ahaaa
Es ist Zeit meine Wege neu zu gehen
Keine Leute mehr die blenden
"""
    asr = AsrResult(
        text="Skalino Es ist Zeit meine Wege neu zu gehen Keine Leute mehr die blenden",
        words=[
            WordTiming("Skalino", 3.0, 7.15),
            WordTiming("Es", 7.8, 7.95),
            WordTiming("ist", 7.96, 8.08),
            WordTiming("Zeit", 8.09, 8.32),
            WordTiming("meine", 8.50, 8.76),
            WordTiming("Wege", 8.80, 9.08),
            WordTiming("neu", 9.12, 9.35),
            WordTiming("zu", 9.36, 9.48),
            WordTiming("gehen", 9.50, 9.86),
            WordTiming("Keine", 10.20, 10.48),
            WordTiming("Leute", 10.50, 10.78),
            WordTiming("mehr", 10.80, 11.02),
            WordTiming("die", 11.04, 11.16),
            WordTiming("blenden", 11.18, 11.58),
        ],
        segments=[],
        raw={},
    )

    result = align_lyrics_to_timeline_bundle(lyrics, asr, duration_seconds=120)
    segments = result["segments"]

    assert segments[0]["text"] == "Skalino."
    assert segments[1]["text"] == "Es ist Zeit zu gehn ahaaa"
    assert segments[2]["text"] == "Es ist Zeit meine Wege neu zu gehen"
    assert 3.0 <= segments[0]["start"] <= 3.2
    assert segments[0]["end"] <= 4.7
    assert segments[1]["start"] >= segments[0]["end"]
    assert segments[1]["end"] <= segments[2]["start"]
    assert segments[1]["end"] - segments[1]["start"] >= 2.4
    assert any("entquetscht" in item for item in result["alignment_report"])


def test_srt_alignment_ignores_repeated_intro_text_that_matches_next_section_too_early():
    from app.services.srt_transcript_service import (
        AsrResult,
        WordTiming,
        align_lyrics_to_timeline_bundle,
        deterministic_prepare_lyrics_for_srt,
    )

    source_lyrics = """[Intro]
Skalinooo.
Es ist Zeit zu-gehn ahaaa

[Verse 1]
Es ist Zeit (es ist zeit), meine Wege neu zu gehen
Keine Leute mehr die blenden oder meinen Kopf verdrehen
Will am Ende oben sein und wie ein Engel schweben
"""
    cleaned, _ = deterministic_prepare_lyrics_for_srt(source_lyrics)
    asr = AsrResult(
        text=(
            "Skalino Es ist Zeit zu gehn ahaaa Es ist Zeit es ist Zeit meine Wege neu zu gehen "
            "Will am Ende oben sein und wie ein Engel schweben"
        ),
        words=[
            WordTiming("Skalino", 3.05, 7.76),
            WordTiming("Es", 7.80, 7.92),
            WordTiming("ist", 7.93, 8.02),
            WordTiming("Zeit", 8.03, 8.16),
            WordTiming("zu", 8.17, 8.26),
            WordTiming("gehn", 8.27, 8.43),
            WordTiming("ahaaa", 8.44, 8.60),
            # Suno hat im Intro bereits Worte des folgenden Verse erzeugt.
            # Dieser Treffer darf nicht als echter Verse-Start verwendet werden.
            WordTiming("Es", 8.64, 8.70),
            WordTiming("ist", 8.71, 8.77),
            WordTiming("Zeit", 8.78, 8.84),
            WordTiming("es", 8.85, 8.90),
            WordTiming("ist", 8.91, 8.96),
            WordTiming("Zeit", 8.97, 9.02),
            WordTiming("meine", 9.03, 9.10),
            WordTiming("Wege", 9.11, 9.18),
            WordTiming("neu", 9.19, 9.25),
            WordTiming("zu", 9.26, 9.30),
            WordTiming("gehen", 9.31, 9.40),
            # Der naechste robuste Anker aus dem echten Verse kommt erst spaeter.
            WordTiming("Will", 30.04, 30.22),
            WordTiming("am", 30.23, 30.34),
            WordTiming("Ende", 30.35, 30.58),
            WordTiming("oben", 30.59, 30.82),
            WordTiming("sein", 30.83, 31.02),
            WordTiming("und", 31.03, 31.15),
            WordTiming("wie", 31.16, 31.28),
            WordTiming("ein", 31.29, 31.39),
            WordTiming("Engel", 31.40, 31.72),
            WordTiming("schweben", 31.73, 32.10),
        ],
        segments=[],
        raw={},
    )

    result = align_lyrics_to_timeline_bundle(cleaned, asr, duration_seconds=220, source_lyrics=source_lyrics)
    segments = result["segments"]

    assert segments[0]["text"] == "Skalino."
    assert segments[1]["text"] == "Es ist Zeit zu gehn ahaaa"
    assert segments[2]["text"] == "Es ist Zeit es ist zeit, meine Wege neu zu gehen"
    assert 3.0 <= segments[0]["start"] <= 3.2
    assert segments[2]["start"] >= 23.5
    assert segments[2]["start"] < segments[3]["start"] < segments[4]["start"]
    assert segments[4]["start"] >= 30.0
    assert any("Intro-Wiederholung" in item for item in result["alignment_report"])
    assert any("spät verteilt" in item for item in result["alignment_report"])


def test_srt_effective_lyrics_inserts_repeated_intro_line_from_asr_without_changing_original_lyrics():
    from app.services.srt_transcript_service import (
        AsrResult,
        WordTiming,
        align_lyrics_to_timeline_bundle,
        deterministic_prepare_lyrics_for_srt,
    )

    source_lyrics = """[Intro: cinematic spoken male vocal, intimate, dark]
Skalinooo.
Es ist Zeit zu-gehn ahaaa

[Verse 1: emotional male rap]
Es ist Zeit (es ist zeit), meine Wege neu zu gehen
"""
    cleaned, _ = deterministic_prepare_lyrics_for_srt(source_lyrics)
    assert "Skalino." in cleaned
    assert "Es ist Zeit zu gehn ahaaa" in cleaned
    assert "Es ist Zeit es ist zeit, meine Wege neu zu gehen" in cleaned

    asr = AsrResult(
        text=(
            "Skalino Es ist Zeit zu gehn ahaaa Es ist Zeit zu gehn ahaaa "
            "Es ist Zeit es ist zeit meine Wege neu zu gehen"
        ),
        words=[
            WordTiming("Skalino", 3.00, 3.70),
            WordTiming("Es", 6.00, 6.12),
            WordTiming("ist", 6.13, 6.25),
            WordTiming("Zeit", 6.26, 6.48),
            WordTiming("zu", 6.49, 6.60),
            WordTiming("gehn", 6.61, 6.88),
            WordTiming("ahaaa", 6.89, 7.40),
            # Von Suno zusaetzlich wiederholt, obwohl nicht im Originaltext.
            WordTiming("Es", 10.00, 10.12),
            WordTiming("ist", 10.13, 10.25),
            WordTiming("Zeit", 10.26, 10.48),
            WordTiming("zu", 10.49, 10.60),
            WordTiming("gehn", 10.61, 10.88),
            WordTiming("ahaaa", 10.89, 11.40),
            WordTiming("Es", 25.00, 25.12),
            WordTiming("ist", 25.13, 25.25),
            WordTiming("Zeit", 25.26, 25.45),
            WordTiming("es", 25.46, 25.56),
            WordTiming("ist", 25.57, 25.68),
            WordTiming("zeit", 25.69, 25.88),
            WordTiming("meine", 26.00, 26.25),
            WordTiming("Wege", 26.26, 26.56),
            WordTiming("neu", 26.57, 26.78),
            WordTiming("zu", 26.79, 26.90),
            WordTiming("gehen", 26.91, 27.25),
        ],
        segments=[],
        raw={},
    )

    result = align_lyrics_to_timeline_bundle(cleaned, asr, duration_seconds=90, source_lyrics=source_lyrics)
    segments = result["segments"]

    assert [segment["text"] for segment in segments] == [
        "Skalino.",
        "Es ist Zeit zu gehn ahaaa",
        "Skalino.",
        "Es ist Zeit zu gehn ahaaa",
        "Es ist Zeit es ist zeit, meine Wege neu zu gehen",
    ]
    assert 5.8 <= segments[1]["start"] <= 6.2
    assert 7.2 <= segments[2]["start"] < 10.0
    assert 9.8 <= segments[3]["start"] <= 10.2
    assert segments[4]["start"] >= 24.8
    assert result["effective_srt_lyrics"]["derived_count"] == 2
    assert result["effective_srt_lyrics"]["derived_lines"][0]["reason"] in {"asr_intro_block_prefix_repeat", "inferred_intro_block_prefix_repeat"}
    assert result["effective_srt_lyrics"]["derived_lines"][1]["reason"] == "asr_repeated_line_before_next_anchor"
    assert any("Effektive SRT-Lyrics" in item for item in result["alignment_report"])


def test_srt_repeated_intro_line_is_inserted_when_asr_omits_trailing_adlib_on_repeat():
    from app.services.srt_transcript_service import (
        AsrResult,
        WordTiming,
        align_lyrics_to_timeline_bundle,
        deterministic_prepare_lyrics_for_srt,
    )

    source_lyrics = """[Intro]
Skalinooo.
Es ist Zeit zu-gehn ahaaa

[Verse 1]
Es ist Zeit (es ist zeit), meine Wege neu zu gehen
"""
    cleaned, _ = deterministic_prepare_lyrics_for_srt(source_lyrics)
    asr = AsrResult(
        text=(
            "Skalino Es ist Zeit zu gehen Es ist Zeit zu gehen "
            "Es ist Zeit es ist zeit meine Wege neu zu gehen"
        ),
        words=[
            WordTiming("Skalino", 3.00, 3.70),
            WordTiming("Es", 6.00, 6.12),
            WordTiming("ist", 6.13, 6.25),
            WordTiming("Zeit", 6.26, 6.48),
            WordTiming("zu", 6.49, 6.60),
            WordTiming("gehen", 6.61, 7.05),
            WordTiming("Es", 10.00, 10.12),
            WordTiming("ist", 10.13, 10.25),
            WordTiming("Zeit", 10.26, 10.48),
            WordTiming("zu", 10.49, 10.60),
            WordTiming("gehen", 10.61, 11.05),
            WordTiming("Es", 25.00, 25.12),
            WordTiming("ist", 25.13, 25.25),
            WordTiming("Zeit", 25.26, 25.45),
            WordTiming("es", 25.46, 25.56),
            WordTiming("ist", 25.57, 25.68),
            WordTiming("zeit", 25.69, 25.88),
            WordTiming("meine", 26.00, 26.25),
            WordTiming("Wege", 26.26, 26.56),
            WordTiming("neu", 26.57, 26.78),
            WordTiming("zu", 26.79, 26.90),
            WordTiming("gehen", 26.91, 27.25),
        ],
        segments=[],
        raw={},
    )

    result = align_lyrics_to_timeline_bundle(cleaned, asr, duration_seconds=90, source_lyrics=source_lyrics)
    texts = [segment["text"] for segment in result["segments"]]

    assert texts == [
        "Skalino.",
        "Es ist Zeit zu gehn ahaaa",
        "Skalino.",
        "Es ist Zeit zu gehn ahaaa",
        "Es ist Zeit es ist zeit, meine Wege neu zu gehen",
    ]
    assert 5.8 <= result["segments"][1]["start"] <= 6.2
    assert 7.0 <= result["segments"][2]["start"] < 10.0
    assert 9.8 <= result["segments"][3]["start"] <= 10.2
    assert result["segments"][4]["start"] >= 24.8
    assert result["effective_srt_lyrics"]["derived_count"] == 2


def test_srt_intro_line_is_synthesized_when_suno_repeats_but_asr_has_only_one_clean_occurrence():
    from app.services.srt_transcript_service import (
        AsrResult,
        WordTiming,
        align_lyrics_to_timeline_bundle,
        deterministic_prepare_lyrics_for_srt,
    )

    source_lyrics = """[Intro]
Skalinooo.
Es ist Zeit zu-gehn ahaaa

[Verse 1]
Es ist Zeit (es ist zeit), meine Wege neu zu gehen
"""
    cleaned, _ = deterministic_prepare_lyrics_for_srt(source_lyrics)
    asr = AsrResult(
        text="Skalino Es ist Zeit zu gehn ahaaa Es ist Zeit es ist zeit meine Wege neu zu gehen",
        words=[
            WordTiming("Skalino", 3.00, 3.70),
            WordTiming("Es", 6.00, 6.12),
            WordTiming("ist", 6.13, 6.25),
            WordTiming("Zeit", 6.26, 6.48),
            WordTiming("zu", 6.49, 6.60),
            WordTiming("gehn", 6.61, 6.88),
            WordTiming("ahaaa", 6.89, 7.40),
            # ASR verschluckt die zweite Suno-Wiederholung als separaten Volltreffer,
            # der Verse-Anker liegt aber deutlich spaeter.
            WordTiming("Es", 25.00, 25.12),
            WordTiming("ist", 25.13, 25.25),
            WordTiming("Zeit", 25.26, 25.45),
            WordTiming("es", 25.46, 25.56),
            WordTiming("ist", 25.57, 25.68),
            WordTiming("zeit", 25.69, 25.88),
            WordTiming("meine", 26.00, 26.25),
            WordTiming("Wege", 26.26, 26.56),
            WordTiming("neu", 26.57, 26.78),
            WordTiming("zu", 26.79, 26.90),
            WordTiming("gehen", 26.91, 27.25),
        ],
        segments=[],
        raw={},
    )

    result = align_lyrics_to_timeline_bundle(cleaned, asr, duration_seconds=90, source_lyrics=source_lyrics)
    segments = result["segments"]
    texts = [segment["text"] for segment in segments]

    assert texts == [
        "Skalino.",
        "Es ist Zeit zu gehn ahaaa",
        "Skalino.",
        "Es ist Zeit zu gehn ahaaa",
        "Es ist Zeit es ist zeit, meine Wege neu zu gehen",
    ]
    assert 5.8 <= segments[1]["start"] <= 6.2
    assert 7.0 < segments[2]["start"] < segments[3]["start"] < 24.5
    assert segments[4]["start"] >= 24.8
    assert any("Plausible Suno-Intro-Wiederholung" in item or "Intro-Block-Prefix" in item for item in result["alignment_report"])


def test_srt_intro_repeat_fallback_does_not_duplicate_when_verse_starts_immediately():
    from app.services.srt_transcript_service import (
        AsrResult,
        WordTiming,
        align_lyrics_to_timeline_bundle,
        deterministic_prepare_lyrics_for_srt,
    )

    source_lyrics = """[Intro]
Skalinooo.
Es ist Zeit zu-gehn ahaaa

[Verse 1]
Es ist Zeit (es ist zeit), meine Wege neu zu gehen
"""
    cleaned, _ = deterministic_prepare_lyrics_for_srt(source_lyrics)
    asr = AsrResult(
        text="Skalino Es ist Zeit zu gehn ahaaa Es ist Zeit es ist zeit meine Wege neu zu gehen",
        words=[
            WordTiming("Skalino", 1.00, 1.40),
            WordTiming("Es", 2.00, 2.10),
            WordTiming("ist", 2.11, 2.20),
            WordTiming("Zeit", 2.21, 2.38),
            WordTiming("zu", 2.39, 2.48),
            WordTiming("gehn", 2.49, 2.74),
            WordTiming("ahaaa", 2.75, 3.08),
            WordTiming("Es", 4.20, 4.32),
            WordTiming("ist", 4.33, 4.45),
            WordTiming("Zeit", 4.46, 4.65),
            WordTiming("es", 4.66, 4.76),
            WordTiming("ist", 4.77, 4.88),
            WordTiming("zeit", 4.89, 5.08),
            WordTiming("meine", 5.09, 5.30),
            WordTiming("Wege", 5.31, 5.56),
            WordTiming("neu", 5.57, 5.76),
            WordTiming("zu", 5.77, 5.88),
            WordTiming("gehen", 5.89, 6.20),
        ],
        segments=[],
        raw={},
    )

    result = align_lyrics_to_timeline_bundle(cleaned, asr, duration_seconds=30, source_lyrics=source_lyrics)
    texts = [segment["text"] for segment in result["segments"]]

    assert texts == [
        "Skalino.",
        "Es ist Zeit zu gehn ahaaa",
        "Es ist Zeit es ist zeit, meine Wege neu zu gehen",
    ]
    assert not any("Plausible Suno-Intro-Wiederholung" in item for item in result["alignment_report"])

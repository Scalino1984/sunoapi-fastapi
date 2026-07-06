from app.services.srt_transcript_service import (
    AsrResult,
    WordTiming,
    _script_candidate_line_score,
    _script_parse_lyrics_text,
    _resolve_srt_duration_seconds,
    align_lyrics_to_timeline_bundle,
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


def test_srt_duration_reconciliation_ignores_bad_local_file_duration() -> None:
    class Asset:
        duration_seconds = 243

    asr = AsrResult(
        text="",
        words=[WordTiming("gehen", 236.55, 237.49)],
        segments=[],
        raw={},
    )

    result = _resolve_srt_duration_seconds(Asset(), 194, asr)

    assert result["duration_seconds"] == 243
    assert result["source"] == "asset_asr_consensus"
    assert result["file_duration_seconds"] == 194
    assert result["asr_last_word_end_seconds"] == 237.49
    assert result["ignored_file_duration"] is True


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


def test_srt_structure_segments_keep_first_hook_when_suno_repeats_prefix_words() -> None:
    source_lyrics = """
[Chorus]
Do you remember standing on a broken field
[Verse]
I walked the road with dust on my hands
""".strip()
    srt_segments = [
        {"index": 1, "start": 4.0, "end": 4.8, "text": "Do you remember"},
        {"index": 2, "start": 5.0, "end": 8.0, "text": "Do you remember standing on a broken field"},
        {"index": 3, "start": 30.0, "end": 33.0, "text": "I walked the road with dust on my hands"},
    ]

    result = build_structure_segments_from_srt_alignment(source_lyrics, srt_segments, 90)

    assert result == [
        {"label": "Chorus", "type": "chorus", "start": 2.0, "end": 28.0, "source": "srt_alignment"},
        {"label": "Verse", "type": "verse", "start": 28.0, "end": 90.0, "source": "srt_alignment"},
    ]


def test_srt_intro_repeat_without_asr_words_is_placed_late_in_intro_gap() -> None:
    lyrics = """
[Intro: cinematic spoken male vocal]
Skalinooo.
Es ist Zeit zu gehn ahaaa

[Verse 1: emotional male rap]
Es ist Zeit (es ist zeit), meine Wege neu zu gehen
Keine Leute mehr die blenden oder meinen Kopf verdrehen
Will am Ende oben sein und wie ein Engel schweben
""".strip()

    asr = AsrResult(
        text="",
        words=[
            WordTiming("es", 7.80, 7.88),
            WordTiming("ist", 7.88, 8.14),
            WordTiming("zeit", 8.14, 8.36),
            WordTiming("zu", 8.36, 8.64),
            WordTiming("gehen", 8.64, 9.04),
            WordTiming("und", 30.04, 30.30),
            WordTiming("wie", 30.30, 30.52),
            WordTiming("ein", 30.52, 30.74),
            WordTiming("engel", 30.74, 30.90),
            WordTiming("schweben", 30.90, 31.28),
        ],
        segments=[],
        raw={},
    )

    result = align_lyrics_to_timeline_bundle(lyrics, asr, 120, source_lyrics=lyrics)
    repeated = [segment for segment in result["segments"] if segment["text"] == "Es ist Zeit zu gehn ahaaa"]
    first_verse = next(segment for segment in result["segments"] if segment["text"].startswith("Es ist Zeit es ist zeit"))
    second_verse = next(segment for segment in result["segments"] if segment["text"].startswith("Keine Leute mehr"))

    assert len(repeated) == 2
    assert repeated[0]["start"] == 7.8
    assert repeated[1]["start"] >= 17.0
    assert repeated[1]["start"] < 22.0
    assert first_verse["start"] == repeated[1]["end"]
    assert 23.5 <= first_verse["start"] <= 24.5
    assert 25.0 <= second_verse["start"] < 26.0


def test_srt_intro_line_is_not_duplicated_when_asr_shows_one_stretched_take() -> None:
    lyrics = """
[Intro: cinematic spoken male vocal]
Skalinooo.
Es ist Zeit zu gehn ahaaa

[Verse 1: emotional male rap]
Es ist Zeit (es ist zeit), meine Wege neu zu gehen
Keine Leute mehr die blenden oder meinen Kopf verdrehen
Will am Ende oben sein und wie ein Engel schweben
""".strip()

    asr = AsrResult(
        text="",
        words=[
            WordTiming("es", 6.44, 6.70),
            WordTiming("ist", 6.70, 11.58),
            WordTiming("zeit", 11.58, 12.16),
            WordTiming("ueber", 30.10, 30.38),
            WordTiming("diese", 30.38, 30.72),
            WordTiming("grauen", 30.72, 31.06),
            WordTiming("wolken", 31.06, 31.36),
            WordTiming("und", 31.36, 31.64),
            WordTiming("das", 31.64, 31.82),
            WordTiming("ziel", 31.82, 32.20),
            WordTiming("endlich", 32.20, 32.60),
            WordTiming("sehen", 32.60, 32.90),
        ],
        segments=[],
        raw={},
    )

    cleaned, _ = deterministic_prepare_lyrics_for_srt(lyrics)
    result = align_lyrics_to_timeline_bundle(cleaned, asr, 243, source_lyrics=lyrics)
    repeated = [segment for segment in result["segments"] if segment["text"] == "Es ist Zeit zu gehn ahaaa"]
    intro_call = next(segment for segment in result["segments"] if segment["text"] == "Skalino.")

    assert len(repeated) == 1
    assert intro_call["start"] >= 6.0
    assert repeated[0]["start"] >= intro_call["end"]
    assert repeated[0]["end"] >= 21.5


def test_srt_sparse_section_jump_reassigns_first_late_anchor_to_expected_line() -> None:
    lyrics = """
[Intro: cinematic spoken male vocal]
Skalinooo.
Es ist Zeit zu gehn ahaaa

[Verse 1: emotional male rap]
Es ist Zeit (es ist zeit), meine Wege neu zu gehen
Keine Leute mehr die blenden oder meinen Kopf verdrehen
Will am Ende oben sein und wie ein Engel schweben
Über diese grauen Wolken und das Ziel endlich sehen.
Das Chaos um mich rum vergessen wie es schreit und quält,
""".strip()

    asr = AsrResult(
        text="",
        words=[
            WordTiming("es", 6.44, 6.70),
            WordTiming("ist", 6.70, 11.58),
            WordTiming("zeit", 11.58, 12.16),
            # ASR springt nach einer großen Lücke auf eine spätere Verse-Zeile.
            # Die sichtbaren Lyrics müssen trotzdem beim nächsten erwarteten
            # Verse-Satz weiterlaufen.
            WordTiming("ueber", 30.10, 30.38),
            WordTiming("diese", 30.38, 30.72),
            WordTiming("grauen", 30.72, 31.06),
            WordTiming("wolken", 31.06, 31.36),
            WordTiming("und", 31.36, 31.64),
            WordTiming("das", 31.64, 31.82),
            WordTiming("ziel", 31.82, 32.20),
            WordTiming("endlich", 32.20, 32.60),
            WordTiming("sehen", 32.60, 32.90),
            WordTiming("das", 33.10, 33.34),
            WordTiming("chaos", 33.34, 33.68),
            WordTiming("um", 33.68, 33.82),
            WordTiming("mich", 33.82, 34.00),
            WordTiming("rum", 34.00, 34.16),
            WordTiming("vergessen", 34.16, 34.68),
            WordTiming("wie", 34.68, 34.84),
            WordTiming("es", 34.84, 34.96),
            WordTiming("schreit", 34.96, 35.18),
            WordTiming("und", 35.18, 35.34),
            WordTiming("quaelt", 35.34, 35.64),
        ],
        segments=[],
        raw={},
    )

    cleaned, _ = deterministic_prepare_lyrics_for_srt(lyrics)
    result = align_lyrics_to_timeline_bundle(cleaned, asr, 243, source_lyrics=lyrics)
    segments = result["segments"]

    assert [segment["text"] for segment in segments[:5]] == [
        "Skalino.",
        "Es ist Zeit zu gehn ahaaa",
        "Es ist Zeit es ist zeit, meine Wege neu zu gehen",
        "Keine Leute mehr die blenden oder meinen Kopf verdrehen",
        "Will am Ende oben sein und wie ein Engel schweben",
    ]
    assert len([segment for segment in segments if segment["text"] == "Es ist Zeit zu gehn ahaaa"]) == 1
    assert segments[2]["start"] >= 29.5


def test_srt_expands_multi_token_asr_words_for_all_backends() -> None:
    lyrics = "Es ist Zeit zu gehn"
    asr = AsrResult(
        text="",
        words=[
            WordTiming("Es ist", 1.0, 1.8),
            WordTiming("Zeit zu-gehn", 1.9, 3.1),
        ],
        segments=[],
        raw={},
    )

    result = align_lyrics_to_timeline_bundle(lyrics, asr, 20)
    segment = result["segments"][0]

    assert segment["start"] == 1.0
    assert segment["end"] == 3.1
    assert "Es ist Zeit zu gehn" in result["half_srt_text"]


def test_srt_candidate_scoring_uses_generic_fuzzy_token_coverage() -> None:
    lines = _script_parse_lyrics_text("kein Flehen mehr nur die Sprache der Wut")

    score = _script_candidate_line_score(
        ["kein", "flehn", "mehr", "nur", "die", "sprache", "der", "flut"],
        lines[0],
    )

    assert score >= 0.82


def test_srt_half_uses_real_word_times_when_tokens_are_matched() -> None:
    lyrics = "Keine Leute mehr"
    asr = AsrResult(
        text="",
        words=[
            WordTiming("Keine", 4.0, 4.4),
            WordTiming("Leute", 4.8, 5.2),
            WordTiming("mehr", 5.8, 6.1),
        ],
        segments=[],
        raw={},
    )

    result = align_lyrics_to_timeline_bundle(lyrics, asr, 20)

    assert "00:00:04,000 --> 00:00:06,100" in result["half_srt_text"]


def test_srt_structure_marker_recognizes_extended_suno_section_tags() -> None:
    from app.services.waveform_service import extract_structure_marker

    cases = {
        "Intro": ("Intro", "intro"),
        "Verse": ("Verse", "verse"),
        "Verse 1": ("Verse 1", "verse"),
        "Verse-2": ("Verse 2", "verse"),
        "Pre-Verse": ("Pre-Verse", "pre_verse"),
        "Chorus": ("Chorus", "chorus"),
        "Chorus 2": ("Chorus 2", "chorus"),
        "Hook": ("Hook", "hook"),
        "Pre-Hook": ("Pre-Hook", "pre_hook"),
        "Post-Hook": ("Post-Hook", "post_hook"),
        "Pre-Chorus": ("Pre-Chorus", "pre_chorus"),
        "Post Chorus": ("Post-Chorus", "post_chorus"),
        "Refrain": ("Refrain", "refrain"),
        "Bridge": ("Bridge", "bridge"),
        "Break": ("Break", "break"),
        "Breakdown": ("Breakdown", "breakdown"),
        "Interlude": ("Interlude", "interlude"),
        "Instrumental": ("Instrumental", "instrumental"),
        "Instrumental Break": ("Instrumental Break", "instrumental_break"),
        "Instrumental Intro": ("Instrumental Intro", "instrumental_intro"),
        "Instrumental Outro": ("Instrumental Outro", "instrumental_outro"),
        "Drop": ("Drop", "drop"),
        "Build": ("Build", "build"),
        "Build-Up": ("Build-Up", "build_up"),
        "Climax": ("Climax", "climax"),
        "Solo": ("Solo", "solo"),
        "Guitar Solo": ("Guitar Solo", "solo"),
        "Piano Solo": ("Piano Solo", "solo"),
        "Drum Solo": ("Drum Solo", "solo"),
        "Bass Solo": ("Bass Solo", "solo"),
        "Rap Verse": ("Rap Verse", "rap_verse"),
        "Rap-Verse-1": ("Rap Verse 1", "rap_verse"),
        "Rap-Verse 2": ("Rap Verse 2", "rap_verse"),
        "Spoken Verse": ("Spoken Verse", "spoken_verse"),
        "Spoken Word": ("Spoken Word", "spoken_word"),
        "Ad-Lib": ("Ad-Libs", "adlibs"),
        "Ad-Libs": ("Ad-Libs", "adlibs"),
        "Call and Response": ("Call and Response", "call_response"),
        "Choir": ("Choir", "choir"),
        "Backing Vocals": ("Backing Vocals", "backing_vocals"),
        "Background Vocals": ("Background Vocals", "background_vocals"),
        "Outro": ("Outro", "outro"),
        "Final Chorus": ("Final Chorus", "chorus"),
        "End": ("End", "end"),
        "Fade In": ("Fade In", "fade_in"),
        "Fade-Out": ("Fade Out", "fade_out"),
        "Intrro: cinematic spoken male vocal": ("Intro", "intro"),
        "Chours: melodic male vocal": ("Chorus", "chorus"),
        "Brigde: whispered vocal": ("Bridge", "bridge"),
    }

    for tag, expected in cases.items():
        marker = extract_structure_marker(tag)
        assert marker == {"label": expected[0], "type": expected[1]}, tag


def test_srt_structure_segments_support_hyphenated_extended_tags() -> None:
    source_lyrics = """
[Rap-Verse-1: emotional male rap]
Ich lauf durch Neonlicht
[Post-Hook]
Wir bleiben wach
[Instrumental Break]
Ohne Worte
[Fade Out]
Letzter Klang
""".strip()
    cleaned, cleanup = deterministic_prepare_lyrics_for_srt(source_lyrics)

    assert cleanup["changed"] is True
    assert "[Rap" not in cleaned
    assert "Ich lauf durch Neonlicht" in cleaned

    srt_segments = [
        {"index": 1, "source_line": 1, "start": 10.0, "end": 13.0, "text": "Ich lauf durch Neonlicht"},
        {"index": 2, "source_line": 2, "start": 20.0, "end": 24.0, "text": "Wir bleiben wach"},
        {"index": 3, "source_line": 3, "start": 32.0, "end": 36.0, "text": "Ohne Worte"},
        {"index": 4, "source_line": 4, "start": 50.0, "end": 55.0, "text": "Letzter Klang"},
    ]

    result = build_structure_segments_from_srt_alignment(source_lyrics, srt_segments, 80)

    assert [item["label"] for item in result] == ["Rap Verse 1", "Post-Hook", "Instrumental Break", "Fade Out"]
    assert [item["type"] for item in result] == ["rap_verse", "post_hook", "instrumental_break", "fade_out"]


def test_srt_intro_block_repeat_infers_missing_second_short_call_and_keeps_gapless_srt() -> None:
    lyrics = """
[Intro: cinematic spoken male vocal]
Skalinooo.
Es ist Zeit zu gehn ahaaa

[Verse 1: emotional male rap]
Es ist Zeit (es ist zeit), meine Wege neu zu gehen
Keine Leute mehr die blenden oder meinen Kopf verdrehen
Will am Ende oben sein und wie ein Engel schweben
""".strip()

    asr = AsrResult(
        text="",
        words=[
            WordTiming("skalino", 3.10, 3.60),
            WordTiming("es", 7.86, 8.06),
            WordTiming("ist", 8.06, 8.22),
            WordTiming("zeit", 8.22, 8.44),
            WordTiming("zu", 8.44, 8.64),
            WordTiming("gehen", 8.64, 9.10),
            WordTiming("ahaaa", 9.10, 9.68),
            # ASR verschluckt den zweiten kurzen Call "Skalinooo", erkennt aber
            # die folgende Intro-Zeile erneut. Das muss trotzdem A-B-A-B ergeben.
            WordTiming("es", 17.64, 17.86),
            WordTiming("ist", 17.86, 18.08),
            WordTiming("zeit", 18.08, 18.28),
            WordTiming("zu", 18.28, 18.50),
            WordTiming("gehen", 18.50, 18.92),
            WordTiming("ahaaa", 18.92, 19.44),
            WordTiming("es", 24.04, 24.20),
            WordTiming("ist", 24.20, 24.40),
            WordTiming("zeit", 24.40, 24.64),
            WordTiming("meine", 24.64, 24.86),
            WordTiming("wege", 24.86, 25.08),
            WordTiming("neu", 25.08, 25.30),
            WordTiming("zu", 25.30, 25.48),
            WordTiming("gehen", 25.48, 25.72),
            WordTiming("keine", 25.92, 26.18),
            WordTiming("leute", 26.18, 26.42),
            WordTiming("mehr", 26.42, 26.62),
        ],
        segments=[],
        raw={},
    )

    result = align_lyrics_to_timeline_bundle(lyrics, asr, 243, source_lyrics=lyrics)
    segments = result["segments"]
    intro_calls = [segment for segment in segments if segment["text"] == "Skalino."]
    intro_lines = [segment for segment in segments if segment["text"] == "Es ist Zeit zu gehn ahaaa"]
    first_verse = next(segment for segment in segments if segment["text"].startswith("Es ist Zeit es ist zeit"))

    assert len(intro_calls) == 2
    assert len(intro_lines) == 2
    assert intro_calls[0]["start"] < intro_lines[0]["start"] < intro_calls[1]["start"] < intro_lines[1]["start"] < first_verse["start"]
    # Normale SRT muss fuer fluessige Player-Uebergaenge gapless bleiben.
    ordered = [intro_calls[0], intro_lines[0], intro_calls[1], intro_lines[1], first_verse]
    for previous, current in zip(ordered, ordered[1:]):
        assert previous["end"] == current["start"]


def test_srt_repeated_chorus_block_keeps_script_order_and_no_extra_duplicates() -> None:
    lyrics = """
[Bridge]
Es ist Zeit zu gehn
Ich bleibe nicht stehn
Denn wenn ich mich nicht beweg
bleibt das feuer stehn.

[Chorus]
Zeit zu gehn – ich trage die Glut
 durch die Nacht, über Straßen aus Blut
was stillsteht, erstickt – ich jage die Flut
kein Flehn mehr – nur die Sprache der Wut

[Chorus]
Zeit zu gehn – ich trage die Glut
 durch die Nacht, über Straßen aus Blut
was stillsteht, erstickt – ich jage die Flut
kein Flehen mehr – nur die Sprache der Wut
""".strip()

    asr = AsrResult(
        text="",
        words=[
            WordTiming("bleibt", 164.50, 164.80),
            WordTiming("das", 164.80, 165.00),
            WordTiming("feuer", 165.00, 165.32),
            WordTiming("stehn", 165.32, 165.70),
            # Finale Chorus-Performance A-B-C-D/A-B-C-D
            WordTiming("zeit", 170.09, 170.34),
            WordTiming("zu", 170.34, 170.52),
            WordTiming("gehen", 170.52, 170.92),
            WordTiming("ich", 170.92, 171.08),
            WordTiming("trage", 171.08, 171.36),
            WordTiming("die", 171.36, 171.50),
            WordTiming("glut", 171.50, 171.86),
            WordTiming("durch", 176.03, 176.28),
            WordTiming("die", 176.28, 176.42),
            WordTiming("nacht", 176.42, 176.76),
            WordTiming("ueber", 176.76, 177.04),
            WordTiming("strassen", 177.04, 177.42),
            WordTiming("aus", 177.42, 177.60),
            WordTiming("blut", 177.60, 177.94),
            WordTiming("was", 180.61, 180.82),
            WordTiming("stillsteht", 180.82, 181.20),
            WordTiming("erstickt", 181.20, 181.58),
            WordTiming("ich", 181.58, 181.74),
            WordTiming("jage", 181.74, 182.08),
            WordTiming("die", 182.08, 182.22),
            WordTiming("flut", 182.22, 182.58),
            WordTiming("kein", 184.97, 185.22),
            WordTiming("flehn", 185.22, 185.58),
            WordTiming("mehr", 185.58, 185.82),
            WordTiming("nur", 185.82, 186.08),
            WordTiming("die", 186.08, 186.22),
            WordTiming("sprache", 186.22, 186.58),
            WordTiming("der", 186.58, 186.74),
            WordTiming("wut", 186.74, 187.10),
            WordTiming("zeit", 190.27, 190.52),
            WordTiming("zu", 190.52, 190.70),
            WordTiming("gehen", 190.70, 191.10),
            WordTiming("ich", 191.10, 191.26),
            WordTiming("trage", 191.26, 191.56),
            WordTiming("die", 191.56, 191.70),
            WordTiming("glut", 191.70, 192.06),
            WordTiming("durch", 195.03, 195.28),
            WordTiming("die", 195.28, 195.42),
            WordTiming("nacht", 195.42, 195.76),
            WordTiming("ueber", 195.76, 196.04),
            WordTiming("strassen", 196.04, 196.42),
            WordTiming("aus", 196.42, 196.60),
            WordTiming("blut", 196.60, 196.94),
            WordTiming("was", 202.95, 203.18),
            WordTiming("stillsteht", 203.18, 203.58),
            WordTiming("erstickt", 203.58, 203.92),
            WordTiming("ich", 203.92, 204.08),
            WordTiming("jage", 204.08, 204.42),
            WordTiming("die", 204.42, 204.56),
            WordTiming("flut", 204.56, 204.92),
            WordTiming("kein", 209.55, 209.82),
            WordTiming("flehen", 209.82, 210.20),
            WordTiming("mehr", 210.20, 210.44),
            WordTiming("nur", 210.44, 210.70),
            WordTiming("die", 210.70, 210.84),
            WordTiming("sprache", 210.84, 211.20),
            WordTiming("der", 211.20, 211.36),
            WordTiming("wut", 211.36, 211.74),
        ],
        segments=[],
        raw={},
    )

    result = align_lyrics_to_timeline_bundle(lyrics, asr, 224, source_lyrics=lyrics)
    chorus = [segment for segment in result["segments"] if segment["text"].startswith(("Zeit zu gehn", "durch die Nacht", "was stillsteht", "kein Fleh"))]
    assert [segment["text"] for segment in chorus] == [
        "Zeit zu gehn – ich trage die Glut",
        "durch die Nacht, über Straßen aus Blut",
        "was stillsteht, erstickt – ich jage die Flut",
        "kein Flehn mehr – nur die Sprache der Wut",
        "Zeit zu gehn – ich trage die Glut",
        "durch die Nacht, über Straßen aus Blut",
        "was stillsteht, erstickt – ich jage die Flut",
        "kein Flehen mehr – nur die Sprache der Wut",
    ]
    assert all(segment["end"] > segment["start"] for segment in chorus)
    assert all(right["start"] >= left["start"] for left, right in zip(chorus, chorus[1:]))
    assert chorus[0]["start"] <= 171.0
    assert chorus[4]["start"] >= 189.0

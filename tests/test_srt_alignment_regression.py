"""Regressionstests fuer das SRT-Lyrics-Alignment (CORE CONTRACT) — Stand v4.

Deckt ab:
  - CORE CONTRACT: doppelte Hook-/Chorus-Bloecke, Suno-Wiederholungen,
    gequetschte unbelegte Wiederholungen, Transcription-only-Fallback
  - RC1-RC4 (Hyp-Aufbau, Fuzzy-Rescue, Split-Tokens, exakte Wortzeiten)
  - NEU (Problem 1a): WARN im Alignment-Report bei Segment-Fallback ohne
    echte Wort-Timestamps ("Datenschema-Abweichung" wird sichtbar)
  - NEU (Problem 1b): Verse-Start nach Intro-Luecke folgt dem ASR-Vokal-Onset
    statt pauschal ans Fensterende (30s statt 25s) gelegt zu werden
  - NEU (v4): Gapless-SRT verlaengert Segment-Enden bis zur Folgezeile

Ausfuehrung im Projektroot der FastAPI-App (echte app/-Module im PYTHONPATH):
    pytest tests/test_srt_alignment_regression.py -v
    python3 tests/test_srt_alignment_regression.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import srt_transcript_service as srt  # noqa: E402
try:
    from app.services import forced_alignment_service as _fa  # noqa: E402,F401
except ImportError:  # Projektroot-Ausfuehrung
    import forced_alignment_service as _fa  # noqa: E402,F401


def _asr_from_words(entries: list[tuple[str, float, float]], raw: dict | None = None) -> srt.AsrResult:
    words = [srt.WordTiming(word=text, start=start, end=end) for text, start, end in entries]
    return srt.AsrResult(text=" ".join(text for text, _, _ in entries), words=words, segments=[], raw=raw or {})


def _timed_words(*texts: str, start: float = 0.0, dur: float = 0.35, gap: float = 0.05) -> list[tuple[str, float, float]]:
    entries: list[tuple[str, float, float]] = []
    t = start
    for text in texts:
        entries.append((text, round(t, 3), round(t + dur, 3)))
        t += dur + gap
    return entries


# --------------------------------------------------------------------------- #
# RC1-RC4 (aus vorherigen Lieferungen, gegen v4 abgesichert)
# --------------------------------------------------------------------------- #

def test_rc2_fuzzy_rescue_matches_misheard_words() -> None:
    lyrics = "Zwei Wege ein Blut wir gehen niemals allein"
    asr = _asr_from_words(_timed_words(
        "zwei", "wege", "ein", "flut", "wir", "gehn", "niemals", "allein", start=10.0,
    ))
    bundle = srt.align_lyrics_to_timeline_bundle(lyrics, asr, duration_seconds=20.0)
    segments = bundle["segments"]
    assert len(segments) == 1
    assert segments[0]["matched"] is True
    assert abs(segments[0]["start"] - 10.0) < 0.2, segments[0]
    assert any("Fuzzy-Rescue" in line for line in bundle["alignment_report"])


def test_rc1_raw_multi_token_asr_words_keep_anchors() -> None:
    lyrics = "Der Beat schlaegt hart die Nacht wird lang"
    asr = _asr_from_words([
        ("Der", 5.0, 5.3),
        ("Beat-schlaegt", 5.4, 6.1),
        ("hart", 6.2, 6.5),
        ("die Nacht", 6.6, 7.2),
        ("wird", 7.3, 7.6),
        ("lang", 7.7, 8.1),
    ])
    bundle = srt.align_lyrics_to_timeline_bundle(lyrics, asr, duration_seconds=15.0)
    segment = bundle["segments"][0]
    assert segment["matched"] is True
    assert abs(segment["start"] - 5.0) < 0.2
    assert segment["end"] >= 8.0


def test_rc3_split_tokens_match_without_hardcode() -> None:
    tokens = srt._effective_line_tokens("Ich hoer dich flehn im Wind")
    hyp_entries = _timed_words("ich", "hoer", "dich", "fl", "hen", "im", "wind", start=3.0)
    hyp = [srt.HypWord(norm=text, start=start, end=end) for text, start, end in hyp_entries]
    occurrences = srt._effective_find_occurrences_flexible(tokens, hyp, start_index=0, max_count=1)
    assert occurrences, "Split-Token-Vorkommen wurde nicht gefunden"
    assert occurrences[0]["start_index"] == 0
    assert occurrences[0]["end_index"] == 7


def test_rc4_half_srt_uses_exact_asr_word_times() -> None:
    lyrics = "Ich komm aus Rauenberg der Huegel ruft"
    asr = _asr_from_words([
        ("ich", 1.0, 1.2),
        ("komm", 1.3, 1.5),
        ("aus", 1.6, 1.8),
        ("rauenberg", 4.0, 4.9),
        ("der", 5.0, 5.1),
        ("huegel", 5.2, 5.6),
        ("ruft", 5.7, 6.0),
    ])
    bundle = srt.align_lyrics_to_timeline_bundle(lyrics, asr, duration_seconds=10.0)
    half = bundle["half_srt_text"]
    assert half.strip(), "Half-SRT fehlt"
    blocks = [block for block in half.split("\n\n") if "Rauenberg" in block]
    assert blocks, half
    time_line = blocks[0].splitlines()[1]
    start_text = time_line.split(" --> ")[0]
    h, m, rest = start_text.split(":")
    seconds = int(h) * 3600 + int(m) * 60 + float(rest.replace(",", "."))
    assert abs(seconds - 4.0) < 0.35, f"Rauenberg-Wortzeit interpoliert statt ASR-exakt: {seconds}s"


# --------------------------------------------------------------------------- #
# CORE CONTRACT Regressionen
# --------------------------------------------------------------------------- #

def test_core_contract_suno_repeated_line_is_inserted() -> None:
    lyrics = "\n".join([
        "Es ist Zeit meine Wege neu zu gehen",
        "Der Morgen bricht ueber Rauenberg an",
    ])
    entries = []
    entries += _timed_words("es", "ist", "zeit", "meine", "wege", "neu", "zu", "gehen", start=2.0)
    entries += _timed_words("es", "ist", "zeit", "meine", "wege", "neu", "zu", "gehn", start=7.0)
    entries += _timed_words("der", "morgen", "bricht", "ueber", "rauenberg", "an", start=12.5)
    asr = _asr_from_words(entries)
    bundle = srt.align_lyrics_to_timeline_bundle(lyrics, asr, duration_seconds=20.0)
    segments = bundle["segments"]
    texts = [segment["text"] for segment in segments]
    assert texts.count("Es ist Zeit meine Wege neu zu gehen") == 2, texts
    assert bundle["effective_srt_lyrics"]["derived_count"] == 1
    starts = [segment["start"] for segment in segments]
    assert starts == sorted(starts)
    assert abs(segments[0]["start"] - 2.0) < 0.3
    assert abs(segments[1]["start"] - 7.0) < 0.3
    assert abs(segments[2]["start"] - 12.5) < 0.3


def test_core_contract_doubled_hook_block_keeps_both_blocks_anchored() -> None:
    hook = ["Ich trage die Glut durch die Nacht", "Und der Himmel steht in Flammen"]
    lyrics = "\n".join(hook + hook)
    entries = []
    entries += _timed_words(*"ich trage die glut durch die nacht".split(), start=1.0)
    entries += _timed_words(*"und der himmel steht in flammen".split(), start=5.0)
    entries += _timed_words(*"ich trage die glut durch die nacht".split(), start=10.0)
    entries += _timed_words(*"und der himmel steht in flammen".split(), start=14.0)
    asr = _asr_from_words(entries)
    bundle = srt.align_lyrics_to_timeline_bundle(lyrics, asr, duration_seconds=20.0)
    segments = bundle["segments"]
    assert len(segments) == 4
    starts = [segment["start"] for segment in segments]
    assert starts == sorted(starts)
    assert abs(starts[0] - 1.0) < 0.4
    assert abs(starts[2] - 10.0) < 0.6, "Zweiter Hook-Block wurde nicht auf die zweite ASR-Instanz verankert"
    assert all(segment["end"] > segment["start"] for segment in segments)


def test_core_contract_squeezed_unmatched_repeat_is_dropped() -> None:
    line_a = srt.LyricLine(index=0, display="Ich trage die Glut", words="Ich trage die Glut".split(),
                           tok_counts=[1, 1, 1, 1], match_tokens=["ich", "trage", "die", "glut"],
                           weight=4.0, matched=True, start=1.0, end=4.0, wstart=[], wend=[],
                           section_label="Hook", section_type="hook")
    squeezed = srt.LyricLine(index=1, display="Ich trage die Glut", words="Ich trage die Glut".split(),
                             tok_counts=[1, 1, 1, 1], match_tokens=["ich", "trage", "die", "glut"],
                             weight=4.0, matched=False, start=4.0, end=4.3, wstart=[], wend=[],
                             section_label="Hook", section_type="hook")
    lines = [line_a, squeezed]
    report = srt._script_drop_squeezed_unmatched_repeats(lines)
    assert len(lines) == 1
    assert report and "ausgelassen" in report[0]


def test_transcription_only_fallback_unchanged() -> None:
    asr = _asr_from_words(_timed_words("la", "la", "la", "instrumental", "vibes", start=0.5))
    bundle = srt.build_transcription_only_srt_bundle(asr, duration_seconds=8.0)
    assert bundle["mode"] == "transcription_only_no_lyrics"
    assert bundle["segments"], bundle


# --------------------------------------------------------------------------- #
# NEU: Problem 1a — Datenschema-Abweichung wird sichtbar
# --------------------------------------------------------------------------- #

def test_word_source_segment_fallback_produces_warning() -> None:
    """Fehlen echte Wort-Timestamps, muss der Alignment-Report warnen."""
    lyrics = "Der Beat schlaegt hart die Nacht wird lang"
    asr = _asr_from_words(
        _timed_words(*"der beat schlaegt hart die nacht wird lang".split(), start=5.0),
        raw={"songstudio_word_source": "segment_text_distributed"},
    )
    bundle = srt.align_lyrics_to_timeline_bundle(lyrics, asr, duration_seconds=15.0)
    assert any("KEINE Wort-Timestamps" in line for line in bundle["alignment_report"]), bundle["alignment_report"]


def test_detect_asr_word_source_classification() -> None:
    assert srt._detect_asr_word_source({"words": [{"word": "a", "start": 0, "end": 1}]}) == "word_timestamps"
    assert srt._detect_asr_word_source({"segments": [{"text": "a b", "start": 0, "end": 2}]}) == "segment_text_distributed"
    assert srt._detect_asr_word_source({"segments": [{"words": [{"word": "a", "start": 0, "end": 1}]}]}) == "segment_word_timestamps"
    assert srt._detect_asr_word_source({}) == "none"


# --------------------------------------------------------------------------- #
# NEU: Problem 1b — Verse-Start folgt dem ASR-Vokal-Onset
# --------------------------------------------------------------------------- #

def test_verse_after_intro_gap_starts_at_asr_vocal_onset() -> None:
    """Regression fuer '25s vs 30s': Ungematchte Verse-Zeilen nach einer grossen
    Intro-Luecke muessen am echten ASR-Vokal-Onset (25s) beginnen und nicht in
    ein Lesbarkeitsfenster direkt vor dem naechsten Anker (30s+) gelegt werden."""
    source_lyrics = "\n".join([
        "[Intro]",
        "Skalino auf dem Beat",
        "[Verse]",
        "Zeile eins vom Vers ganz eigen hier",
        "Zeile zwei erzaehlt die Story weiter",
        "Zeile drei mit Druck und viel Gefuehl",
        "[Hook]",
        "Wir tragen dieses Feuer bis zum Ende",
    ])
    lyrics = "\n".join([
        "Skalino auf dem Beat",
        "Zeile eins vom Vers ganz eigen hier",
        "Zeile zwei erzaehlt die Story weiter",
        "Zeile drei mit Druck und viel Gefuehl",
        "Wir tragen dieses Feuer bis zum Ende",
    ])
    entries = []
    # Intro sicher erkannt:
    entries += _timed_words("skalino", "auf", "dem", "beat", start=2.0)
    # Verse ab 25s gesungen, aber ASR liefert nur unbrauchbares Kauderwelsch
    # (textlich kein Match zu den Verse-Zeilen):
    entries += _timed_words("brmm", "tzk", "wrr", "kchh", "pff", "drr", "zsch", "grr", start=25.0, dur=0.5, gap=0.4)
    # Hook sicher erkannt (naechster stabiler Anker):
    entries += _timed_words("wir", "tragen", "dieses", "feuer", "bis", "zum", "ende", start=40.0)
    asr = _asr_from_words(entries)
    bundle = srt.align_lyrics_to_timeline_bundle(lyrics, asr, duration_seconds=55.0, source_lyrics=source_lyrics)
    segments = bundle["segments"]
    verse_first = next(segment for segment in segments if segment["text"].startswith("Zeile eins"))
    assert abs(verse_first["start"] - 25.0) < 1.0, (
        f"Verse-Start folgt nicht dem ASR-Vokal-Onset: {verse_first['start']}s statt ~25s "
        f"(Report: {bundle['alignment_report']})"
    )
    hook = next(segment for segment in segments if segment["text"].startswith("Wir tragen"))
    assert abs(hook["start"] - 40.0) < 0.3


# --------------------------------------------------------------------------- #
# NEU (v4): Gapless-SRT
# --------------------------------------------------------------------------- #

def test_gapless_srt_extends_segment_ends_to_next_start() -> None:
    lyrics = "\n".join([
        "Es ist Zeit zu gehn heut Nacht",
        "Der Morgen bricht ueber Rauenberg an",
    ])
    entries = []
    entries += _timed_words("es", "ist", "zeit", "zu", "gehn", "heut", "nacht", start=6.4)
    entries += _timed_words("der", "morgen", "bricht", "ueber", "rauenberg", "an", start=30.1)
    asr = _asr_from_words(entries)
    bundle = srt.align_lyrics_to_timeline_bundle(lyrics, asr, duration_seconds=40.0)
    segments = bundle["segments"]
    assert abs(segments[0]["end"] - segments[1]["start"]) < 0.01, segments


def test_transcription_only_overlaps_and_tiny_segments_are_sanitized() -> None:
    """Screenshot-Regression: ASR-Segmente mit Ueberlappung (7.02 vs 7.00) und
    Mini-Dauer (0.3s) muessen monoton, ueberlappungsfrei und lesbar werden."""
    asr = srt.AsrResult(
        text="Hey ich bin's mal wieder. R zu dem A Reedeema.. Ich hab mit mir Scalino im Gepaeck.",
        words=[],
        segments=[
            {"text": "Hey ich bin's mal wieder.", "start": 2.38, "end": 6.72},
            {"text": "R zu dem A Reedeema..", "start": 6.72, "end": 7.02},
            {"text": "Ich hab mit mir Scalino im Gepaeck.", "start": 7.00, "end": 12.50},
            {"text": "Badland Studio", "start": 12.50, "end": 15.64},
        ],
        raw={},
    )
    bundle = srt.build_transcription_only_srt_bundle(asr, duration_seconds=20.0)
    segments = bundle["segments"]
    for left, right in zip(segments, segments[1:]):
        assert left["end"] <= right["start"] + 0.001, (left, right)
    assert all(segment["end"] - segment["start"] >= 0.55 for segment in segments), segments
    texts = " | ".join(segment["text"] for segment in segments)
    assert "Reedeema" in texts, texts


def test_gapless_clamps_overlap_when_next_start_is_close() -> None:
    segments = [
        {"index": 1, "start": 6.72, "end": 7.02, "text": "a"},
        {"index": 2, "start": 6.75, "end": 12.5, "text": "b"},
    ]
    rows, changed = srt._extend_srt_segments_to_next_start(segments)
    assert changed >= 1
    assert rows[0]["end"] <= rows[1]["start"] + 0.001, rows


def test_alignment_quality_score_reacts_to_signals() -> None:
    good = srt.compute_alignment_quality({
        "segments": [{"matched": True}] * 10,
        "alignment_report": [],
    })
    degraded = srt.compute_alignment_quality({
        "segments": [{"matched": True}] * 5 + [{"matched": False}] * 5,
        "alignment_report": [
            "WARN: Zeilen 2-4 (3 Stk.) in 1.0s gequetscht",
            "WARN: Provider lieferte KEINE Wort-Timestamps (Datenschema-Abweichung); ...",
        ],
    })
    assert good["score"] == 1.0
    assert degraded["score"] < 0.35, degraded
    assert degraded["word_source_degraded"] is True
    assert degraded["estimated_lines"] == 5


def test_forced_alignment_engine_uses_span_times(monkeypatch) -> None:
    """Forced-Alignment-Bundle uebernimmt die CTC-Span-Zeiten als Zeilenzeiten."""
    import sys as _sys
    fa = _sys.modules["forced_alignment_service"]

    lyrics = "\n".join([
        "Skalino auf dem Beat",
        "Zwei Wege ein Blut wir gehen allein",
    ])
    token_times = {
        "skalino": (6.0, 6.6), "auf": (6.7, 6.9), "dem": (7.0, 7.1), "beat": (7.2, 7.6),
        "zwei": (11.0, 11.2), "wege": (11.3, 11.6), "ein": (11.7, 11.8), "blut": (11.9, 12.2),
        "wir": (12.3, 12.4), "gehen": (12.5, 12.9), "allein": (13.0, 13.5),
    }

    def fake_force_align_tokens(audio_path, tokens):
        spans = []
        for token in tokens:
            times = token_times.get(token)
            spans.append(fa.TokenSpanSeconds(start=times[0], end=times[1], score=0.9) if times else None)
        return spans

    monkeypatch.setattr(fa, "force_align_tokens", fake_force_align_tokens)

    # ASR absichtlich unbrauchbar: Die Zeiten MUESSEN aus dem Forced Alignment kommen.
    asr = _asr_from_words(_timed_words("kauderwelsch", "ohne", "sinn", start=1.0))
    bundle = srt.align_lyrics_with_forced_alignment_bundle(
        lyrics, asr, Path("/tmp/fake.mp3"), duration_seconds=20.0,
    )
    segments = bundle["segments"]
    assert bundle.get("engine") == "forced_alignment"
    assert all(segment["alignment_method"] == "forced_alignment_mms" for segment in segments)
    assert abs(segments[0]["start"] - 6.0) < 0.05, segments[0]
    assert abs(segments[1]["start"] - 11.0) < 0.05, segments[1]
    assert bundle["alignment_quality"]["score"] > 0.8, bundle["alignment_quality"]


def test_forced_alignment_low_coverage_raises_for_fallback(monkeypatch) -> None:
    import sys as _sys
    fa = _sys.modules["forced_alignment_service"]
    monkeypatch.setattr(fa, "force_align_tokens", lambda audio_path, tokens: [None] * len(tokens))
    asr = _asr_from_words(_timed_words("irgend", "etwas", start=1.0))
    try:
        srt.align_lyrics_with_forced_alignment_bundle(
            "Zwei Wege ein Blut wir gehen allein", asr, Path("/tmp/fake.mp3"), duration_seconds=10.0,
        )
    except RuntimeError as exc:
        assert "Heuristik-Fallback" in str(exc)
    else:
        raise AssertionError("Niedrige Coverage muss RuntimeError fuer den Fallback ausloesen")


class _MonkeypatchShim:
    def __init__(self) -> None:
        self._saved: list[tuple[object, str, object]] = []

    def setattr(self, target: object, name: str, value: object) -> None:
        self._saved.append((target, name, getattr(target, name)))
        setattr(target, name, value)

    def undo(self) -> None:
        for target, name, value in reversed(self._saved):
            setattr(target, name, value)
        self._saved.clear()


def test_alignment_quality_survives_field_stripping_normalizer(monkeypatch) -> None:
    """Regression: Die echte srt_validation-Normalisierung verwirft Zusatzfelder
    wie `matched` — der Quality-Score muss trotzdem aus den Roh-Segmenten stammen."""
    def stripping_normalizer(segments):
        return [
            {"index": i + 1, "start": s["start"], "end": s["end"], "text": s["text"]}
            for i, s in enumerate(segments or [])
        ]

    monkeypatch.setattr(srt, "validate_and_normalize_srt_segments", stripping_normalizer)
    lyrics = "Der Beat schlaegt hart die Nacht wird lang"
    asr = _asr_from_words(_timed_words(*"der beat schlaegt hart die nacht wird lang".split(), start=5.0))
    bundle = srt.align_lyrics_to_timeline_bundle(lyrics, asr, duration_seconds=15.0)
    quality = bundle["alignment_quality"]
    assert quality["matched_lines"] == 1, quality
    assert quality["estimated_lines"] == 0, quality
    assert quality["score"] > 0.9, quality
    # Normalisierte Segmente duerfen die Zusatzfelder verloren haben:
    assert "matched" not in bundle["segments"][0]


def test_short_intro_line_not_pulled_early_by_window_formula() -> None:
    """Nachtschatten-Muster 1: 'Yeah. Absolute Dunkelheit.' (ist 3.84s statt
    6.68s). Kurze Intro-Zeilen duerfen nicht pauschal ~62% der Ankerzeit nach
    vorn gezogen werden; das Fenster richtet sich nach dem Textumfang, und
    fremde ASR-Tokens am Songanfang (Halluzination) ziehen es nicht mehr vor."""
    lyrics = "\n".join([
        "Yeah absolute Dunkelheit",
        "Ich wandle durch die Strassen dieser toten Stadt",
    ])
    entries = [("untertitel", 0.9, 1.4), ("amara", 1.5, 1.9)]  # Whisper-Halluzination
    entries += _timed_words(*"ich wandle durch die strassen dieser toten stadt".split(), start=6.68)
    asr = _asr_from_words(entries)
    bundle = srt.align_lyrics_to_timeline_bundle(lyrics, asr, duration_seconds=20.0)
    segments = bundle["segments"]
    intro = segments[0]
    assert intro["text"].startswith("Yeah"), segments
    assert intro["start"] > 3.9, f"Intro-Zeile wieder zu frueh gezogen: {intro}"
    assert abs(segments[1]["start"] - 6.68) < 0.3, segments[1]


def test_mid_song_gap_lines_start_at_vocal_onset() -> None:
    """Nachtschatten-Muster 2: Ungematchte Zeilen zwischen zwei Ankern klebten
    am Ende der Vorgaengerzeile (ist 101.34s statt 104.06s), obwohl die ASR im
    Fenster erst ab dem echten Vokal-Onset Woerter liefert."""
    lyrics = "\n".join([
        "Der erste Anker steht hier fest und klar",
        "Chronisch genialer Imperialist ohne Match",
        "Silben schreiend durch die Dunkelheit hier",
        "Der zweite Anker steht am Ende wieder fest",
    ])
    entries = []
    entries += _timed_words(*"der erste anker steht hier fest und klar".split(), start=97.0)
    # Instrumental bis 104s, dann Vokal-Onset mit textlich unbrauchbarem ASR:
    entries += _timed_words("brmmz", "kchhh", "wrrrk", "tzzk", "pfff", "drnn", start=104.06, dur=0.5, gap=0.4)
    entries += _timed_words(*"der zweite anker steht am ende wieder fest".split(), start=112.0)
    asr = _asr_from_words(entries)
    bundle = srt.align_lyrics_to_timeline_bundle(lyrics, asr, duration_seconds=120.0)
    segments = bundle["segments"]
    gap_first = next(segment for segment in segments if segment["text"].startswith("Chronisch"))
    assert abs(gap_first["start"] - 104.06) < 1.0, (
        f"Lueckenzeile folgt nicht dem Vokal-Onset: {gap_first['start']}s statt ~104.06s "
        f"(Report: {bundle['alignment_report']})"
    )
    anchor_b = next(segment for segment in segments if segment["text"].startswith("Der zweite"))
    assert abs(anchor_b["start"] - 112.0) < 0.3, anchor_b


def test_review_anchor_refined_to_line_words_not_block_boundaries() -> None:
    """Nachtschatten-Root-Cause: Ein ASR-Kandidatenblock enthaelt den Schluss
    der Vorgaengerzeile ('... fledermausland CHRONISCH GENIALER ...'). Der
    Review darf den Zeilenstart nicht auf den Blockanfang setzen, sondern muss
    ihn per Sub-Alignment auf das erste Zeilenwort verfeinern."""
    lyrics = "\n".join([
        "Ich jage dich zurueck in dein Fledermausland",
        "Chronisch genialer Imperialist der mit Silben zerreisst",
    ])
    entries = []
    # Vorgaengerzeile nur teilweise erkannt (zerhacktes 'zurueck' -> kein Anker
    # fuer Zeile 2 aus dem globalen Alignment), dann durchgesungener Block ohne
    # Pause ueber die Zeilengrenze hinweg:
    entries += _timed_words("ich", "jage", "dich", start=100.1)
    entries += [("zur", 101.6, 101.9), ("ck", 101.91, 102.22)]
    entries += _timed_words("in", "dein", "fledermausland", start=102.3)
    entries += _timed_words("chronisch", "genialer", "imperialist", "der", "mit", "silben", "zerreisst", start=104.06)
    asr = _asr_from_words(entries)
    bundle = srt.align_lyrics_to_timeline_bundle(lyrics, asr, duration_seconds=115.0)
    segments = bundle["segments"]
    chronisch = next(segment for segment in segments if segment["text"].startswith("Chronisch"))
    assert abs(chronisch["start"] - 104.06) < 0.3, (
        f"Review-Anker klebt an Blockgrenze statt am ersten Zeilenwort: {chronisch} "
        f"(Report: {bundle['alignment_report']})"
    )
    previous = next(segment for segment in segments if segment["text"].startswith("Ich jage"))
    assert previous["end"] <= chronisch["start"] + 0.001


def _run_standalone() -> None:
    import inspect

    failures = 0
    for name, func in sorted(globals().items()):
        if name.startswith("test_") and callable(func):
            shim = _MonkeypatchShim()
            kwargs = {"monkeypatch": shim} if "monkeypatch" in inspect.signature(func).parameters else {}
            try:
                func(**kwargs)
                print(f"PASS  {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL  {name}: {exc}")
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"ERROR {name}: {type(exc).__name__}: {exc}")
            finally:
                shim.undo()
    if failures:
        sys.exit(f"{failures} Test(s) fehlgeschlagen")
    print("Alle Regressionstests bestanden.")


if __name__ == "__main__":
    _run_standalone()

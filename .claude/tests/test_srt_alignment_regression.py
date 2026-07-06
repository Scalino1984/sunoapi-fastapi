"""Regressionstests fuer das SRT-Lyrics-Alignment (CORE CONTRACT).

Deckt gemaess Architektur-Vertrag ab:
  - Wiederholte Suno-Abschnittsbloecke / doppelte Hook-Zeilen (Regression!)
  - Gequetschte unbelegte Wiederholungen werden ausgelassen
und zusaetzlich die Ursachen-Fixes:
  - RC1: einheitlicher Hyp-Aufbau (rohe Mehrfach-Token-Woerter verlieren keine Anker)
  - RC2: Fuzzy-Rescue fuer ASR-Fehlhoerungen (gehn/gehen, Flut/Blut)
  - RC3: generische Split-Token-Erkennung ohne wortspezifische Hardcodes
  - RC4: exakte ASR-Wortzeiten landen in den Half-SRT-Wortzeiten

Ausfuehrung (im Projektroot, Stubs oder echte app/ im PYTHONPATH):
    pytest tests/test_srt_alignment_regression.py -v
    python3 tests/test_srt_alignment_regression.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import srt_transcript_service as srt  # noqa: E402


def _asr_from_words(entries: list[tuple[str, float, float]]) -> srt.AsrResult:
    words = [srt.WordTiming(word=text, start=start, end=end) for text, start, end in entries]
    return srt.AsrResult(text=" ".join(text for text, _, _ in entries), words=words, segments=[], raw={})


def _timed_words(*texts: str, start: float = 0.0, dur: float = 0.35, gap: float = 0.05) -> list[tuple[str, float, float]]:
    entries: list[tuple[str, float, float]] = []
    t = start
    for text in texts:
        entries.append((text, round(t, 3), round(t + dur, 3)))
        t += dur + gap
    return entries


def test_rc2_fuzzy_rescue_matches_misheard_words() -> None:
    """Fehlhoerungen (Flut/Blut, gehn/gehen) duerfen keine Anker mehr kosten."""
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
    """Rohe ASR-Woerter mit mehreren Tokens (OpenAI/Voxtral-Pfad) duerfen keine
    Folge-Tokens mehr verlieren."""
    lyrics = "Der Beat schlaegt hart die Nacht wird lang"
    # ASR liefert zusammengezogene/bindestrich-verbundene Woerter.
    asr = _asr_from_words([
        ("Der", 5.0, 5.3),
        ("Beat-schlaegt", 5.4, 6.1),   # 2 Tokens in einem ASR-Wort
        ("hart", 6.2, 6.5),
        ("die Nacht", 6.6, 7.2),        # 2 Tokens in einem ASR-Wort
        ("wird", 7.3, 7.6),
        ("lang", 7.7, 8.1),
    ])
    bundle = srt.align_lyrics_to_timeline_bundle(lyrics, asr, duration_seconds=15.0)
    segment = bundle["segments"][0]
    assert segment["matched"] is True
    assert abs(segment["start"] - 5.0) < 0.2
    assert abs(segment["end"] - 8.1) < 0.3


def test_rc3_split_tokens_match_without_hardcode() -> None:
    """Von ASR zerhackte Silben (z. B. 'flehn' -> 'fl hen') matchen generisch."""
    tokens = srt._effective_line_tokens("Ich hoer dich flehn im Wind")
    hyp_entries = _timed_words("ich", "hoer", "dich", "fl", "hen", "im", "wind", start=3.0)
    hyp = [srt.HypWord(norm=text, start=start, end=end) for text, start, end in hyp_entries]
    occurrences = srt._effective_find_occurrences_flexible(tokens, hyp, start_index=0, max_count=1)
    assert occurrences, "Split-Token-Vorkommen wurde nicht gefunden"
    assert occurrences[0]["start_index"] == 0
    assert occurrences[0]["end_index"] == 7  # size+1 Fenster


def test_core_contract_suno_repeated_line_is_inserted() -> None:
    """Regression: Suno wiederholt eine Zeile, die im Songtext nur einmal steht."""
    lyrics = "\n".join([
        "Es ist Zeit meine Wege neu zu gehen",
        "Der Morgen bricht ueber Rauenberg an",
    ])
    entries = []
    entries += _timed_words("es", "ist", "zeit", "meine", "wege", "neu", "zu", "gehen", start=2.0)
    # Suno-Wiederholung derselben Zeile (mit Fehlhoerung), nicht im Songtext:
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
    # Beide Instanzen liegen auf den echten ASR-Zeitfenstern:
    assert abs(segments[0]["start"] - 2.0) < 0.3
    assert abs(segments[1]["start"] - 7.0) < 0.3
    assert abs(segments[2]["start"] - 12.5) < 0.3


def test_core_contract_doubled_hook_block_keeps_both_blocks_anchored() -> None:
    """Regression: doppelter Hook-Block im Songtext bleibt vollstaendig verankert."""
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
    """Regression: unbelegte 0,3s-Wiederholungsquetschungen werden ausgelassen."""
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


def test_rc4_half_srt_uses_exact_asr_word_times() -> None:
    """Wortzeiten gematchter Zeilen stammen aus ASR-Ankern, nicht aus Interpolation."""
    lyrics = "Ich komm aus Rauenberg der Huegel ruft"
    # Bewusst ungleichmaessige Wortzeiten, die eine Gewichts-Interpolation nie
    # exakt treffen wuerde (lange Pause mitten in der Zeile):
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
    # 'Rauenberg' beginnt real bei 4.0s; per Vokalgewicht-Interpolation laege der
    # Start deutlich frueher. Der Half-SRT-Block mit 'Rauenberg' muss daher bei
    # ~4.0s beginnen.
    blocks = [block for block in half.split("\n\n") if "Rauenberg" in block]
    assert blocks, half
    time_line = blocks[0].splitlines()[1]
    start_text = time_line.split(" --> ")[0]
    h, m, rest = start_text.split(":")
    seconds = int(h) * 3600 + int(m) * 60 + float(rest.replace(",", "."))
    assert abs(seconds - 4.0) < 0.35, f"Rauenberg-Wortzeit interpoliert statt ASR-exakt: {seconds}s"


def test_transcription_only_fallback_unchanged() -> None:
    """CORE CONTRACT: ASR-only-Fallback ohne Lyrics bleibt funktionsfaehig."""
    asr = _asr_from_words(_timed_words("la", "la", "la", "instrumental", "vibes", start=0.5))
    bundle = srt.build_transcription_only_srt_bundle(asr, duration_seconds=8.0)
    assert bundle["mode"] == "transcription_only_no_lyrics"
    assert bundle["segments"], bundle


def _run_standalone() -> None:
    failures = 0
    for name, func in sorted(globals().items()):
        if name.startswith("test_") and callable(func):
            try:
                func()
                print(f"PASS  {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL  {name}: {exc}")
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"ERROR {name}: {type(exc).__name__}: {exc}")
    if failures:
        sys.exit(f"{failures} Test(s) fehlgeschlagen")
    print("Alle Regressionstests bestanden.")


if __name__ == "__main__":
    _run_standalone()

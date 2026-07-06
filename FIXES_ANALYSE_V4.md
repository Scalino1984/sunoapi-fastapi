# SRT-Funktion v4 — Bestandsaufnahme, Ursachenanalyse & Fixes (2026-07-06)

## Bestandsaufnahme

Stand v4 gegenüber der letzten gemeinsamen Version: Die Ursachen-Fixes RC1–RC4
(einheitlicher Hyp-Aufbau, Fuzzy-Rescue mit Kölner Phonetik, generische
Split-Token-Erkennung, exakte Wortzeiten) sind integriert. Neu hinzugekommen
sind Gapless-SRT (`_extend_srt_segments_to_next_start`), die explizite
Wiederholungsblock-Reparatur (`_script_repair_explicit_repeated_section_blocks`),
Intro-Block-Prefix-Repeats, `_script_rebalance_ambiguous_intro_prefix` sowie das
React-Frontend (Admin/Library/MiniPlayer/Status/Waveform).

Geänderte Dateien in dieser Lieferung: **`backend-app/srt_transcript_service.py`**
und **`backend-app/audio_assets.py`**. Neu: `backend-app/tests/…`,
`backend-app/tools/srt_diagnose.py`. API-Routen, Schemas, Modelle, Frontend:
unverändert.

## Problem 2 — "Vocal-Stems vor SRT" wird ignoriert (Ursache gefunden & gefixt)

**Ursache:** Die Entscheidungslogik existierte NUR im Bulk-Pfad
(`_run_bulk_srt_generation_background`). Der Einzelsong-Pfad
(`POST /api/audio-assets/{id}/srt/generate` →
`_run_single_srt_generation_background`) hat weder das Payload-Feld
`generate_vocal_stems_before_transcription` (das `GenerateSrtRequest` besitzt)
noch die Admin-Einstellung ausgewertet — SRT startete direkt. Root Cause ist
die duplizierte Entscheidungslogik, die nur an einer Stelle implementiert war.

**Fix:** Neue gemeinsame Funktion `_ensure_vocal_stem_before_srt(...)` in
`audio_assets.py` — die einzige Stelle für die Entscheidung, von Single- UND
Bulk-Pfad identisch genutzt (Divergenz damit strukturell ausgeschlossen).
Regeln unverändert zum bisherigen Bulk-Verhalten: Payload-Override schlägt
Admin-Default; ohne `prefer_existing_vocal_stem` keine Vorab-Erzeugung (der
Stem würde nicht genutzt); vorhandener Vocals-Stem wird nicht neu gerechnet.
Der Single-Task meldet die Stem-Phase per Heartbeat
(`phase: vocal_stems_before_srt`).

## Problem 1 — Zeitstempel früh im Song versetzt (25s → 30s, sync ab 1:25)

Zwei Ursachen im Code identifiziert und gefixt; die endgültige Bestätigung für
DEN konkreten Song liefert das neue Diagnose-Tool (unten).

### 1a) Stille Datenschema-Abweichung: kein Word-Timestamp-Support

Liefert der Provider keine `words` (z. B. Modell ohne Word-Timestamps,
API-Schema-Änderung), fällt `_script_flatten_words_from_payload`
stillschweigend auf Segment-Text zurück und verteilt Wörter **gleichmäßig**
über das Segmentfenster. Ergebnis: früh im Song (lange Segmente über
Intro/Beat) sekundenweise Versatz, später bei kurzen dichten Segmenten fast
synchron — exakt das gemeldete Bild, und exakt die vermutete
"API-/Datenschema-Abweichung".

**Fix:** `_detect_asr_word_source(...)` klassifiziert jede Provider-Antwort
(`word_timestamps` / `segment_word_timestamps` / `segment_text_distributed` /
`none`) und wird in allen vier Backends (Groq, OpenAI, Voxtral, WhisperX) in
`raw["songstudio_word_source"]` abgelegt. Beim Segment-Fallback erscheint jetzt
eine unübersehbare WARN-Zeile im Alignment-Report jedes Segments mit
Handlungsempfehlung (Modell mit Word-Timestamps, z. B. `whisper-large-v3`).

### 1b) Verse-Platzierung ans Fensterende statt an den Vokal-Onset

`_script_tail_spread_section_transition` legte ungematchte Zeilen eines neuen
Abschnitts (Verse nach Intro-Lücke) in ein Lesbarkeitsfenster **direkt vor den
nächsten stabilen Anker** — auch wenn die ASR im Fenster längst echte Wörter
(Vokal-Onset) geliefert hatte, die nur textlich nicht gematcht wurden
(Fehlhörungen über dichtem Beat). Genau so entsteht "Verse real 25s, SRT 30s".

**Fix:** `_script_first_hyp_onset_in_window(...)` — existieren ASR-Wörter im
Lückenfenster, startet der Abschnitt an diesem Onset (dort setzt die Stimme
hörbar ein). Nur ohne jeden ASR-Beleg gilt weiterhin das Lesbarkeitsfenster
vor dem Anker. `hyp` wird dafür durch `_script_resolve_timeline` durchgereicht
(interne Signatur, kein API-Change).

### Diagnose-Tool für den konkreten Song

`tools/srt_diagnose.py` liest direkt die App-SQLite (keine App-Abhängigkeiten):

```bash
python3 tools/srt_diagnose.py --db /home/astier/Projekte/<app>/app.db --asset-id <ID>
```

Ausgabe: Word-Source-Fingerprint (erkennt gleichverteilte Wortzeiten =
Segment-Fallback), erste N ASR-Wörter, SRT-Segmente mit Δ zum nächsten
ASR-Wort (`!!` = Schätz-Heuristik statt Anker), Alignment-Report und
SRT-Debug-Log. Bitte für den 25s/30s-Song einmal VOR und NACH der
Neugenerierung laufen lassen — falls dann noch etwas abweicht, zeigt die
Ausgabe exakt, welche Zeile aus welcher Quelle ihre Zeit bekommt.

## Regressionstests

`tests/test_srt_alignment_regression.py` — 12 Tests, alle grün:
CORE CONTRACT (doppelte Hook-Blöcke, Suno-Wiederholung, Squeeze-Drop,
Transcription-only), RC1–RC4, neu: WARN bei Segment-Fallback,
Word-Source-Klassifikation, Verse-Onset-Regression ("25s statt 30s"),
Gapless-SRT.

```bash
pytest tests/test_srt_alignment_regression.py -v
```

## Empfohlener Verifikationsablauf für den Problem-Song

1. Diagnose VOR Neugenerierung: `srt_diagnose.py` → Fingerprint prüfen.
   Steht dort "GLEICHVERTEILT", war 1a die Ursache → Groq-Modell prüfen.
2. SRT neu generieren (Einzelsong): Jetzt läuft bei aktivierter
   Admin-Einstellung zuerst Demucs (Task-Phase `vocal_stems_before_srt`),
   dann die Transkription auf dem Vocal-Stem — das verbessert genau die
   frühen, beat-lastigen Passagen, in denen die Anker fehlten.
3. Diagnose NACH Neugenerierung: Δ-Spalte der frühen Zeilen sollte < 0.6s
   sein; falls nicht, Ausgabe teilen.

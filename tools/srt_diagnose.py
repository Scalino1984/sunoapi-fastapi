#!/usr/bin/env python3
"""srt_diagnose.py — SRT-Zeitzuordnung eines AudioAssets sezieren.

Liest direkt aus der SQLite-DB der FastAPI-App (keine App-Abhaengigkeiten) und
zeigt fuer ein AudioAsset:
  - Backend, Word-Source (echte Wort-Timestamps vs. Segment-Verteilung)
  - Fingerprint gleichmaessig verteilter Wortzeiten (= Provider lieferte keine
    echten Word-Timestamps -> Zeitstempel-Abweichungen frueh im Song)
  - SRT-Segmente vs. naechstgelegene ASR-Woerter (Abweichung pro Zeile)
  - Alignment-Report und SRT-Debug-Log des letzten Laufs

Nutzung (WSL2, im Projektroot):
    python3 tools/srt_diagnose.py --db ./app.db --asset-id 123
    python3 tools/srt_diagnose.py --db ./app.db --asset-id 123 --words 60

Der DB-Pfad ist der Pfad der App-SQLite-Datei im WSL2-Dateisystem.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from statistics import median
from typing import Any


def _fmt_ts(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    m = int(seconds // 60)
    s = seconds - m * 60
    return f"{m:02d}:{s:06.3f}"


def _load_json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def _latest_transcript(conn: sqlite3.Connection, asset_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, backend, language, status, error_message, generated_at,
               words_json, segments_json, srt_text
        FROM audio_transcripts
        WHERE audio_asset_id = ?
        ORDER BY id DESC LIMIT 1
        """,
        (asset_id,),
    ).fetchone()
    if not row:
        return None
    keys = ["id", "backend", "language", "status", "error_message", "generated_at",
            "words_json", "segments_json", "srt_text"]
    data = dict(zip(keys, row))
    data["words"] = _load_json(data.pop("words_json")) or []
    data["segments"] = _load_json(data.pop("segments_json")) or []
    return data


def _latest_srt_task(conn: sqlite3.Connection, asset_id: int) -> dict[str, Any] | None:
    rows = conn.execute(
        """
        SELECT id, task_type, status, request_payload, response_payload
        FROM suno_tasks
        WHERE request_payload LIKE ?
        ORDER BY id DESC LIMIT 25
        """,
        (f'%"audio_asset_id": {asset_id}%',),
    ).fetchall()
    for task_id, task_type, status, request_payload, response_payload in rows:
        response = _load_json(response_payload) or {}
        if "srt" in str(task_type or "").lower() or "debug_log" in json.dumps(response)[:20000]:
            return {
                "id": task_id,
                "task_type": task_type,
                "status": status,
                "request": _load_json(request_payload) or {},
                "response": response,
            }
    return None


def _uniform_word_fingerprint(words: list[dict[str, Any]]) -> dict[str, Any]:
    """Erkennt gleichmaessig verteilte Wortzeiten (Segment-Fallback-Fingerprint).

    Bei echten Word-Timestamps schwanken Wortdauern und Wortluecken stark
    (Pausen, gestreckte Silben). Beim Segment-Fallback sind aufeinanderfolgende
    Woerter in Bloecken exakt gleich lang und lueckenlos.
    """
    durations: list[float] = []
    zero_gap_runs = 0
    run = 0
    previous_end: float | None = None
    for word in words:
        try:
            start = float(word.get("start"))
            end = float(word.get("end"))
        except (TypeError, ValueError):
            continue
        durations.append(round(end - start, 4))
        if previous_end is not None and abs(start - previous_end) < 0.002:
            run += 1
            zero_gap_runs = max(zero_gap_runs, run)
        else:
            run = 0
        previous_end = end
    if len(durations) < 12:
        return {"suspicious": False, "reason": "zu wenige Woerter"}
    unique_ratio = len({round(d, 3) for d in durations}) / len(durations)
    med = median(durations) if durations else 0.0
    suspicious = unique_ratio < 0.25 and zero_gap_runs >= 10
    return {
        "suspicious": suspicious,
        "unique_duration_ratio": round(unique_ratio, 3),
        "max_zero_gap_run": zero_gap_runs,
        "median_word_duration": round(med, 3),
        "hint": (
            "Wortzeiten wirken GLEICHVERTEILT -> Provider lieferte vermutlich keine "
            "echten Word-Timestamps (Segment-Fallback). Backend/Modell pruefen!"
            if suspicious else "Wortzeiten wirken organisch (echte Word-Timestamps)."
        ),
    }


def _nearest_word(words: list[dict[str, Any]], time_value: float) -> dict[str, Any] | None:
    best = None
    best_delta = None
    for word in words:
        try:
            start = float(word.get("start"))
        except (TypeError, ValueError):
            continue
        delta = abs(start - time_value)
        if best_delta is None or delta < best_delta:
            best, best_delta = word, delta
    return best


def _words_in_range(words: list[dict[str, Any]], start: float, end: float, limit: int = 10) -> str:
    hits = []
    for word in words:
        try:
            ws = float(word.get("start"))
        except (TypeError, ValueError):
            continue
        if start <= ws <= end:
            hits.append(str(word.get("word") or "").strip())
        if len(hits) >= limit:
            break
    return " ".join(hits)


def main() -> None:
    parser = argparse.ArgumentParser(description="SRT-Zeitzuordnung eines AudioAssets sezieren")
    parser.add_argument("--db", required=True, type=Path, help="Pfad zur SQLite-DB der App (WSL2-Pfad)")
    parser.add_argument("--asset-id", required=True, type=int, help="AudioAsset-ID")
    parser.add_argument("--words", type=int, default=40, help="Anzahl der ersten ASR-Woerter im Dump (Default: 40)")
    args = parser.parse_args()

    if not args.db.exists():
        sys.exit(f"FEHLER: DB nicht gefunden: {args.db}")
    conn = sqlite3.connect(str(args.db))

    transcript = _latest_transcript(conn, args.asset_id)
    if not transcript:
        sys.exit(f"FEHLER: Kein Transcript fuer AudioAsset {args.asset_id} gefunden.")

    words = transcript["words"]
    segments = transcript["segments"]
    print("=" * 78)
    print(f"AudioAsset {args.asset_id} | Transcript #{transcript['id']} | Backend: {transcript['backend']} "
          f"| Sprache: {transcript['language']} | Status: {transcript['status']}")
    if transcript.get("error_message"):
        print(f"Fehler: {transcript['error_message']}")
    print(f"ASR-Woerter: {len(words)} | SRT-Segmente: {len(segments)}")

    print("\n--- Word-Source-Fingerprint " + "-" * 49)
    fingerprint = _uniform_word_fingerprint(words)
    for key, value in fingerprint.items():
        print(f"  {key}: {value}")

    print(f"\n--- Erste {args.words} ASR-Woerter " + "-" * 46)
    for word in words[: args.words]:
        print(f"  {_fmt_ts(float(word.get('start') or 0))} - {_fmt_ts(float(word.get('end') or 0))}  {word.get('word')}")

    print("\n--- SRT-Segmente vs. ASR " + "-" * 52)
    print(f"  {'#':>3} {'Start':>9} {'Ende':>9} {'match':>5} {'Δ naechstes ASR-Wort':>20}  Text / ASR im Fenster")
    for segment in segments:
        start = float(segment.get("start") or 0.0)
        end = float(segment.get("end") or start)
        matched = segment.get("matched")
        nearest = _nearest_word(words, start)
        delta = abs(float(nearest.get("start")) - start) if nearest else None
        delta_text = f"{delta:+.2f}s ({nearest.get('word')})" if nearest and delta is not None else "-"
        flag = "  " if (delta is not None and delta < 0.6) or matched else "!!"
        print(f"{flag}{int(segment.get('index') or 0):>3} {_fmt_ts(start):>9} {_fmt_ts(end):>9} "
              f"{str(bool(matched)):>5} {delta_text:>20}  {str(segment.get('text') or '')[:44]!r}")
        asr_window = _words_in_range(words, start - 0.3, end + 0.3)
        if asr_window:
            print(f"{'':>50}ASR: {asr_window[:70]!r}")

    report = None
    for segment in segments:
        if isinstance(segment.get("alignment_report"), list):
            report = segment["alignment_report"]
            break
    if report:
        print("\n--- Alignment-Report " + "-" * 56)
        for line in report:
            print(f"  {line}")

    task = _latest_srt_task(conn, args.asset_id)
    if task:
        debug_log = (task.get("response") or {}).get("debug_log") or []
        print(f"\n--- SRT-Task #{task['id']} ({task['status']}) Debug-Log ({len(debug_log)} Events) " + "-" * 20)
        for event in debug_log[-25:]:
            if isinstance(event, dict):
                print(f"  [{event.get('event')}] {str(event.get('detail') or '')[:90]}")

    print("\nHinweis: Zeilen mit '!!' haben weder Match noch ein ASR-Wort in der Naehe")
    print("des Starts -> dort platziert eine Schaetz-Heuristik. Bitte diese Ausgabe")
    print("fuer den Problem-Song teilen, wenn die Abweichung nach dem Fix bleibt.")


if __name__ == "__main__":
    main()

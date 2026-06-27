from __future__ import annotations

from typing import Any

from app.services.srt_parser import MIN_SEGMENT_DURATION_SECONDS, normalize_srt_segment, renumber_segments, seconds, export_srt

DEFAULT_MIN_GAP_SECONDS = 0.080
DEFAULT_LONG_SEGMENT_SECONDS = 12.0
DEFAULT_SHORT_SEGMENT_SECONDS = 0.650


def issue(segment: dict[str, Any] | None, severity: str, issue_type: str, message: str) -> dict[str, Any]:
    return {
        "segmentId": segment.get("id") if isinstance(segment, dict) else None,
        "index": segment.get("index") if isinstance(segment, dict) else None,
        "severity": severity,
        "type": issue_type,
        "message": message,
    }


def _normalize_storage_segments(
    segments: list[dict[str, Any]] | None,
    *,
    min_duration: float = MIN_SEGMENT_DURATION_SECONDS,
    min_gap: float = 0.0,
) -> list[dict[str, Any]]:
    """Normalisiert SRT-Segmente für Speicherung/Generierung.

    Automatisch erzeugte ASR-/Lyrics-Segmente dürfen nicht hart fehlschlagen,
    nur weil einzelne Zeilen sehr kurz erkannt wurden. Diese Funktion verlängert
    kurze Segmente mindestens auf `min_duration` und hält die Reihenfolge stabil.
    Manuelle Editor-Fehler mit negativer Zeit oder leerer Liste werden weiterhin
    über `validate_srt_segments` sichtbar gemacht.
    """
    rows = renumber_segments(segments or [])
    if not rows:
        return []

    normalized: list[dict[str, Any]] = []
    previous_end = 0.0
    for idx, row in enumerate(rows, start=1):
        start = max(0.0, seconds(row.get("start"), previous_end))
        # Reihenfolge halten, aber echte Pausen nicht künstlich schließen.
        if normalized and start < previous_end + min_gap:
            start = previous_end + min_gap
        end = seconds(row.get("end"), start + min_duration)
        if end < start + min_duration:
            end = start + min_duration
        item = normalize_srt_segment({**row, "start": start, "end": end}, idx)
        item["start"] = round(start, 3)
        item["end"] = round(max(end, start + min_duration), 3)
        normalized.append(item)
        previous_end = seconds(item.get("end"), start + min_duration)
    return renumber_segments(normalized)


def validate_srt_segments(
    segments: list[dict[str, Any]] | None,
    *,
    min_duration: float = MIN_SEGMENT_DURATION_SECONDS,
    min_gap: float = DEFAULT_MIN_GAP_SECONDS,
    include_gap_info: bool = True,
) -> dict[str, Any]:
    raw_rows = renumber_segments(segments or [])
    rows = _normalize_storage_segments(segments or [], min_duration=min_duration, min_gap=0.0)
    issues: list[dict[str, Any]] = []
    if not rows:
        issues.append(issue(None, "error", "format", "Die Segmentliste ist leer."))
        return {"valid": False, "segments": [], "issues": issues}

    previous_raw: dict[str, Any] | None = None
    last_start = -1.0
    for index, row in enumerate(rows):
        raw_row = raw_rows[index] if index < len(raw_rows) else row
        start = seconds(raw_row.get("start"), -1.0)
        end = seconds(raw_row.get("end"), -1.0)
        duration = end - start
        normalized_start = seconds(row.get("start"), start)
        normalized_end = seconds(row.get("end"), end)
        normalized_duration = normalized_end - normalized_start

        if start < 0:
            issues.append(issue(row, "error", "negative_time", f"Segment {row['index']} hat eine negative Startzeit."))
        if end <= start:
            issues.append(issue(row, "error", "invalid_duration", f"Segment {row['index']} endet nicht nach dem Start."))
        elif duration < min_duration:
            issues.append(issue(row, "warning", "short_duration", f"Segment {row['index']} wurde auf mindestens {min_duration:.3f}s normalisiert."))
        elif normalized_duration < DEFAULT_SHORT_SEGMENT_SECONDS:
            issues.append(issue(row, "warning", "short_duration", f"Segment {row['index']} ist sehr kurz ({normalized_duration:.3f}s)."))
        elif normalized_duration > DEFAULT_LONG_SEGMENT_SECONDS:
            issues.append(issue(row, "warning", "long_duration", f"Segment {row['index']} ist sehr lang ({normalized_duration:.3f}s)."))

        if not str(row.get("text") or "").strip():
            issues.append(issue(row, "warning", "empty_text", f"Segment {row['index']} hat keinen Text."))
        if start < last_start:
            issues.append(issue(row, "error", "sequence", f"Segment {row['index']} ist nicht chronologisch sortiert."))
        last_start = max(last_start, start)

        if previous_raw:
            prev_end = seconds(previous_raw.get("end"), 0.0)
            if prev_end > start:
                overlap = prev_end - start
                issues.append(issue(row, "warning", "overlap", f"Segment {previous_raw['index']} überlappt Segment {row['index']} um {overlap:.3f}s."))
            else:
                gap = start - prev_end
                if include_gap_info and gap > min_gap:
                    issues.append(issue(row, "info", "gap", f"Lücke zwischen Segment {previous_raw['index']} und {row['index']}: {gap:.3f}s."))
        previous_raw = raw_row

    try:
        exported = export_srt(rows)
        if not exported.strip():
            issues.append(issue(None, "error", "format", "SRT-Export ist leer."))
    except Exception as exc:
        issues.append(issue(None, "error", "format", f"SRT-Export fehlgeschlagen: {exc}"))

    return {"valid": not any(item.get("severity") == "error" for item in issues), "segments": rows, "issues": issues}


def normalize_or_raise(segments: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    from fastapi import HTTPException

    result = validate_srt_segments(segments)
    if not result["valid"]:
        errors = [item["message"] for item in result["issues"] if item.get("severity") == "error"]
        raise HTTPException(status_code=422, detail=" ".join(errors) or "SRT-Segmente sind ungültig.")
    return result["segments"]

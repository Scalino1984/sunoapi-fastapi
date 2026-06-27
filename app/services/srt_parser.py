from __future__ import annotations

import re
import uuid
from typing import Any

MIN_SEGMENT_DURATION_SECONDS = 0.300


def seconds(value: Any, fallback: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    if not number == number or number in (float("inf"), float("-inf")):
        return fallback
    return number


def srt_timestamp(value: float) -> str:
    total_ms = max(0, int(round(seconds(value) * 1000)))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def parse_srt_timestamp(value: str) -> float:
    text = str(value or "").strip().replace(".", ",")
    match = re.fullmatch(r"(\d{1,3}):(\d{2}):(\d{2}),(\d{1,3})", text)
    if not match:
        raise ValueError(f"Ungültiger SRT-Zeitstempel: {value}")
    hours, minutes, secs, millis = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + int(secs) + int(millis.ljust(3, "0")[:3]) / 1000.0


def normalize_srt_segment(segment: dict[str, Any], index: int = 1, *, keep_id: bool = True) -> dict[str, Any]:
    raw_start = seconds(segment.get("start"), 0.0)
    start = max(0.0, raw_start)
    raw_end = seconds(segment.get("end"), start + 1.0)
    end = max(start + MIN_SEGMENT_DURATION_SECONDS, raw_end)
    text = str(segment.get("text") or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    raw_id = str(segment.get("id") or "").strip()
    segment_id = raw_id if keep_id and raw_id else f"seg_{uuid.uuid4().hex[:12]}"
    return {
        "id": segment_id,
        "index": int(index),
        "start": round(start, 3),
        "end": round(end, 3),
        "text": text,
        "locked": bool(segment.get("locked", False)),
        "warning": list(segment.get("warning") or []),
    }


def renumber_segments(segments: list[dict[str, Any]], *, sort: bool = True) -> list[dict[str, Any]]:
    rows = [normalize_srt_segment(row, idx + 1) for idx, row in enumerate(segments or []) if isinstance(row, dict)]
    if sort:
        rows.sort(key=lambda item: (seconds(item.get("start")), seconds(item.get("end")), int(item.get("index") or 0)))
    return [normalize_srt_segment(row, idx + 1) for idx, row in enumerate(rows)]


def parse_srt(srt_text: str) -> list[dict[str, Any]]:
    text = str(srt_text or "").replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []
    time_pattern = re.compile(
        r"(?P<start>\d{1,3}:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*(?P<end>\d{1,3}:\d{2}:\d{2}[,.]\d{1,3})"
    )
    segments: list[dict[str, Any]] = []
    for block in re.split(r"\n\s*\n+", text):
        lines = [line.rstrip() for line in str(block or "").split("\n") if line.strip()]
        if not lines:
            continue
        time_index = next((idx for idx, line in enumerate(lines) if time_pattern.search(line)), -1)
        if time_index < 0:
            continue
        match = time_pattern.search(lines[time_index])
        if not match:
            continue
        body = "\n".join(lines[time_index + 1:]).strip()
        try:
            start = parse_srt_timestamp(match.group("start"))
            end = parse_srt_timestamp(match.group("end"))
        except ValueError:
            continue
        if not body:
            body = ""
        segments.append(normalize_srt_segment({"start": start, "end": end, "text": body}, len(segments) + 1))
    return renumber_segments(segments)


def export_srt(segments: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for idx, segment in enumerate(renumber_segments(segments), start=1):
        text = str(segment.get("text") or "").strip()
        if not text:
            continue
        start = srt_timestamp(seconds(segment.get("start")))
        end = srt_timestamp(seconds(segment.get("end")))
        blocks.append(f"{idx}\n{start} --> {end}\n{text}")
    return ("\n\n".join(blocks).strip() + "\n") if blocks else ""

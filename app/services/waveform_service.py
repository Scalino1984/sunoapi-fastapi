from __future__ import annotations

import hashlib
import json
import math
import re
import struct
import subprocess
from array import array
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models import AudioAsset
from app.services.audio_metadata_service import read_audio_duration_seconds

# Tags may contain one or more bracket blocks in the same line, e.g.
# [Chorus: deep male vocals] or [build-up] [sub bass enters]. Only arrangement
# section words may become waveform segments; descriptor/FX tags are ignored.
BRACKET_TAG_RE = re.compile(r"\[([^\]\n]{1,260})\]")
BRACKET_ONLY_LINE_RE = re.compile(r"^\s*(?:\[[^\]\n]{1,260}\]\s*)+$")
INLINE_TAG_RE = re.compile(r"\[[^\]\n]{1,260}\]")

# Order matters: specific chorus variants must be detected before plain chorus.
SECTION_PATTERNS: tuple[tuple[str, str, str], ...] = (
    (r"\bpre\s*[- ]?chorus\b", "Pre-Chorus", "pre_chorus"),
    (r"\bpost\s*[- ]?chorus\b", "Post-Chorus", "post_chorus"),
    (r"\b(?:final|last)\s+(?:chorus|hook|refrain)\b", "Final Chorus", "chorus"),
    (r"\b(?:chorus|hook|refrain)\b", "Chorus", "chorus"),
    (r"\bverse\s*(?P<number>\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)?\b", "Verse", "verse"),
    (r"\bpart\s*(?P<number>\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)?\b", "Verse", "verse"),
    (r"\bbridge\b", "Bridge", "bridge"),
    (r"\bintro\b", "Intro", "intro"),
    (r"\boutro\b", "Outro", "outro"),
    (r"\binterlude\b", "Interlude", "interlude"),
    (r"\bbreak\s*[- ]?down\b|\bbreakdown\b", "Breakdown", "breakdown"),
    (r"\bdrop\b", "Drop", "drop"),
)

NUMBER_WORDS = {
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
}


def _coerce_json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return json.loads(value)
        except Exception:
            return None
    return None


def extract_structure_marker(label: Any) -> dict[str, str] | None:
    """Return a canonical arrangement marker from any tag text.

    The function intentionally accepts tags that include more text after the
    section word, so all of these become clean structure labels:
      [Verse: gritty male vocals, aggressive rap flow] -> Verse
      [Verse 2 | high energy] -> Verse 2
      [Final Chorus: doubled vocals] -> Final Chorus

    Tags without a true section word never become waveform segments:
      [bass-heavy], [filter sweep], [spoken word], [Vocal FX]
    """

    raw = str(label or "").strip().strip("[]")
    raw = raw.replace("_", " ").replace("|", " ").replace("/", " ")
    raw = re.sub(r"\s+", " ", raw).strip()
    if not raw:
        return None
    for pattern, display, kind in SECTION_PATTERNS:
        match = re.search(pattern, raw, re.IGNORECASE)
        if not match:
            continue
        text = display
        number = match.groupdict().get("number") if match.groupdict() else None
        if kind == "verse" and number:
            text = f"Verse {NUMBER_WORDS.get(str(number).lower(), str(number))}"
        return {"label": text, "type": kind}
    return None


def _same_section_family(left: dict[str, str], right: dict[str, str]) -> bool:
    return left.get("type") == right.get("type")


def _prefer_specific_marker(current: dict[str, str], incoming: dict[str, str]) -> dict[str, str]:
    if incoming.get("label") != current.get("label") and len(incoming.get("label", "")) > len(current.get("label", "")):
        return incoming
    return current


def _clean_lyric_line(line: str) -> str:
    cleaned = INLINE_TAG_RE.sub(" ", str(line or ""))
    return re.sub(r"\s+", " ", cleaned).strip()


def _line_weight(line: str) -> int:
    return 1 if _clean_lyric_line(line) else 0


def _clamp_points(points: int | None) -> int:
    try:
        value = int(points or 180)
    except (TypeError, ValueError):
        value = 180
    return max(60, min(value, 360))


def _normalize(values: list[float]) -> list[float]:
    if not values:
        return []
    maximum = max(values) or 1.0
    return [round(max(0.03, min(1.0, value / maximum)), 4) for value in values]


def _peaks_from_pcm(raw: bytes, points: int) -> list[float]:
    if not raw:
        return []
    sample_count = len(raw) // 2
    if sample_count <= 0:
        return []
    samples = array("h")
    samples.frombytes(raw[: sample_count * 2])
    if struct.pack("=h", 1) != struct.pack("<h", 1):
        samples.byteswap()

    bucket_size = max(1, len(samples) // points)
    peaks: list[float] = []
    for index in range(points):
        start = index * bucket_size
        end = min(len(samples), start + bucket_size)
        if start >= len(samples):
            peaks.append(0.03)
            continue
        bucket = samples[start:end]
        if not bucket:
            peaks.append(0.03)
            continue
        peak = max(abs(item) for item in bucket)
        rms = math.sqrt(sum(item * item for item in bucket) / len(bucket))
        peaks.append((peak * 0.65 + rms * 0.35) / 32768.0)
    return _normalize(peaks)


def _generate_fallback_waveform(path: Path, points: int) -> list[float]:
    digest = hashlib.sha256(path.read_bytes()[:1024 * 1024]).digest()
    values: list[float] = []
    for index in range(points):
        seed = digest[index % len(digest)] / 255.0
        wave = 0.5 + 0.5 * math.sin(index / 6.5) * math.cos(index / 19.0)
        values.append(0.12 + (seed * 0.55) + (wave * 0.28))
    return _normalize(values)


def build_waveform_from_file(path: Path, points: int = 180) -> list[float]:
    points = _clamp_points(points)
    if not path.exists() or not path.is_file() or path.stat().st_size <= 0:
        return []

    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(path),
        "-ac",
        "1",
        "-ar",
        "8000",
        "-f",
        "s16le",
        "pipe:1",
    ]
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=45)
        peaks = _peaks_from_pcm(result.stdout, points)
        if peaks:
            return peaks
    except Exception:
        pass

    return _generate_fallback_waveform(path, points)


def build_structure_segments(asset: AudioAsset, duration_seconds: float | int | None) -> list[dict[str, Any]]:
    source = asset.prompt or asset.lyrics or ""
    duration = float(duration_seconds or asset.duration_seconds or 0)
    if not source or duration <= 0:
        return []

    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    current_has_lyrics = False

    for raw_line in source.splitlines():
        line = str(raw_line or "").strip()
        if not line:
            continue

        if BRACKET_ONLY_LINE_RE.match(line):
            markers = [extract_structure_marker(match.group(1)) for match in BRACKET_TAG_RE.finditer(line)]
            markers = [marker for marker in markers if marker]
            if not markers:
                continue
            marker = markers[0]

            # Consecutive [Verse 1] / [Verse: vocal style] tags describe one
            # section and must not create tiny extra waveform blocks.
            if current and not current_has_lyrics and _same_section_family(current["marker"], marker):
                current["marker"] = _prefer_specific_marker(current["marker"], marker)
                current["label"] = current["marker"]["label"]
                current["type"] = current["marker"]["type"]
                continue

            current = {"marker": marker, "label": marker["label"], "type": marker["type"], "weight": 0}
            sections.append(current)
            current_has_lyrics = False
            continue

        weight = _line_weight(line)
        if weight <= 0:
            continue
        if current is None:
            marker = {"label": "Intro", "type": "intro"}
            current = {"marker": marker, "label": marker["label"], "type": marker["type"], "weight": 0}
            sections.append(current)
        current["weight"] += weight
        current_has_lyrics = True

    if not sections:
        return []

    for item in sections:
        item["weight"] = max(1, int(item.get("weight") or 0))

    total_weight = sum(item["weight"] for item in sections) or len(sections)
    cursor = 0.0
    segments: list[dict[str, Any]] = []
    for idx, item in enumerate(sections):
        if idx == len(sections) - 1:
            end_time = duration
        else:
            end_time = min(duration, cursor + duration * (item["weight"] / total_weight))
        if end_time <= cursor:
            end_time = min(duration, cursor + max(1.0, duration / max(1, len(sections))))
        segments.append({"label": item["label"], "type": item["type"], "start": round(cursor, 3), "end": round(end_time, 3)})
        cursor = end_time
        if cursor >= duration:
            break
    return segments


def _segment_label(segment: Any) -> str:
    return str(segment.get("label") if isinstance(segment, dict) else "").strip()


def _segment_type(segment: Any) -> str:
    return str(segment.get("type") if isinstance(segment, dict) else "").strip()


def _clean_existing_segments(segments: Any, duration_seconds: float | int | None = None) -> list[dict[str, Any]]:
    parsed = _coerce_json(segments)
    if not isinstance(parsed, list):
        return []
    cleaned: list[dict[str, Any]] = []
    duration = float(duration_seconds or 0)
    for raw in parsed:
        if not isinstance(raw, dict):
            continue
        marker = extract_structure_marker(_segment_label(raw)) or extract_structure_marker(_segment_type(raw))
        if not marker:
            continue
        try:
            start = float(raw.get("start") or 0)
            end = float(raw.get("end") or start)
        except (TypeError, ValueError):
            continue
        if duration > 0:
            start = max(0.0, min(duration, start))
            end = max(0.0, min(duration, end))
        if end <= start:
            continue
        cleaned.append({"label": marker["label"], "type": marker["type"], "start": round(start, 3), "end": round(end, 3)})
    return cleaned


def _segments_have_descriptor_noise(segments: Any) -> bool:
    parsed = _coerce_json(segments)
    if not isinstance(parsed, list) or not parsed:
        return True
    for segment in parsed:
        if not isinstance(segment, dict):
            return True
        label = _segment_label(segment)
        marker = extract_structure_marker(label) or extract_structure_marker(_segment_type(segment))
        if not marker:
            return True
        if label.lower() != marker["label"].lower():
            return True
    return False


def _segments_end(segments: list[dict[str, Any]]) -> float:
    ends: list[float] = []
    for segment in segments:
        try:
            ends.append(float(segment.get("end") or 0))
        except (TypeError, ValueError):
            pass
    return max(ends or [0.0])


def scale_segments_to_duration(segments: Any, duration_seconds: float | int | None) -> list[dict[str, Any]]:
    cleaned = _clean_existing_segments(segments)
    duration = float(duration_seconds or 0)
    if not cleaned or duration <= 0:
        return cleaned
    source_end = _segments_end(cleaned)
    if source_end <= 0:
        return cleaned
    # If the frontend/audio element reports a different duration than the stored
    # rough structure, stretch the whole layout so the last section reaches 100%.
    # This fixes newly generated clips where metadata duration and browser audio
    # duration differ after import/cache changes.
    if abs(source_end - duration) > max(1.0, duration * 0.02):
        ratio = duration / source_end
        return [
            {**segment, "start": round(float(segment["start"]) * ratio, 3), "end": round(float(segment["end"]) * ratio, 3)}
            for segment in cleaned
        ]
    return cleaned


def _normalize_waveform_segments(asset: AudioAsset, waveform: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    changed = False
    duration = waveform.get("duration_seconds") or asset.duration_seconds
    rebuilt = build_structure_segments(asset, duration)
    existing_structure = _clean_existing_segments(asset.structure_segments_json, duration)
    existing_waveform = _clean_existing_segments(waveform.get("segments"), duration)

    # Prefer explicitly stored structure over noisy waveform tags, but allow a
    # fresh prompt-derived rebuild to replace raw descriptor segments.
    preferred = existing_structure or rebuilt or existing_waveform
    if not preferred:
        return waveform, changed

    current = waveform.get("segments")
    if _segments_have_descriptor_noise(current) or _clean_existing_segments(current, duration) != preferred:
        waveform = dict(waveform)
        waveform["segments"] = preferred
        changed = True
    if _clean_existing_segments(asset.structure_segments_json, duration) != preferred:
        asset.structure_segments_json = preferred
        changed = True
    return waveform, changed


def sanitize_waveform_payload_for_asset(asset: AudioAsset, waveform: Any | None = None, duration_seconds: float | int | None = None) -> dict[str, Any] | None:
    """Return a display-safe waveform payload without raw style/vocal tags.

    This is intentionally usable from read endpoints. It does not perform any
    database write. It guarantees that outgoing API payloads and frontend props
    prefer cleaned arrangement sections over old waveform_json.segments caches.
    """

    payload = _coerce_json(waveform if waveform is not None else asset.waveform_json)
    if not isinstance(payload, dict):
        return None
    payload = deepcopy(payload)
    duration = duration_seconds or payload.get("duration_seconds") or asset.duration_seconds
    existing_structure = _clean_existing_segments(asset.structure_segments_json, duration)
    rebuilt = build_structure_segments(asset, duration)
    existing_waveform = _clean_existing_segments(payload.get("segments"), duration)
    segments = existing_structure or rebuilt or existing_waveform
    if segments:
        payload["segments"] = segments
    payload["duration_seconds"] = duration or payload.get("duration_seconds") or asset.duration_seconds
    return payload


def build_waveform_payload(asset: AudioAsset, path: Path, points: int = 180) -> dict[str, Any]:
    duration = asset.duration_seconds or read_audio_duration_seconds(path)
    peaks = build_waveform_from_file(path, points)
    segments = build_structure_segments(asset, duration)
    return {
        "audio_asset_id": asset.id,
        "audio_id": asset.audio_id,
        "duration_seconds": duration,
        "points": len(peaks),
        "peaks": peaks,
        "segments": segments,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "ffmpeg_or_fallback",
    }


def get_or_create_waveform(asset: AudioAsset, path: Path, db: Session, points: int = 180, rebuild: bool = False) -> dict[str, Any]:
    points = _clamp_points(points)
    existing = _coerce_json(asset.waveform_json)
    if not rebuild and isinstance(existing, dict) and existing.get("peaks") and int(existing.get("points") or 0) >= min(points, 60):
        payload, changed = _normalize_waveform_segments(asset, existing)
        if changed:
            asset.waveform_json = payload
            asset.waveform_generated_at = asset.waveform_generated_at or datetime.now(timezone.utc)
            db.add(asset)
            db.commit()
            db.refresh(asset)
        return sanitize_waveform_payload_for_asset(asset, payload) or payload

    payload = build_waveform_payload(asset, path, points)
    asset.waveform_json = payload
    asset.waveform_generated_at = datetime.now(timezone.utc)
    asset.structure_segments_json = payload.get("segments") or []
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return sanitize_waveform_payload_for_asset(asset, payload) or payload

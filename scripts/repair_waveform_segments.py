#!/usr/bin/env python3
"""Repair waveform section overlays in the SQLite database.

The script keeps waveform peaks untouched and replaces ``waveform_json.segments``
with canonical song-structure segments. For generated Suno tasks it rebuilds
segments from the original prompt/lyrics when available, so descriptor tags like
``[Verse: gritty male vocals]`` become ``Verse`` and non-structure tags like
``[bass-heavy]`` are ignored.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

BRACKET_TAG_RE = re.compile(r"\[([^\]\n]{2,220})\]")
BRACKET_ONLY_LINE_RE = re.compile(r"^\s*(?:\[[^\]\n]{2,220}\]\s*)+$")
INLINE_TAG_RE = re.compile(r"\[[^\]\n]{1,220}\]")

SECTION_PATTERNS: tuple[tuple[str, str, str], ...] = (
    (r"\bpre\s*[- ]?chorus\b", "Pre-Chorus", "pre_chorus"),
    (r"\bpost\s*[- ]?chorus\b", "Post-Chorus", "post_chorus"),
    (r"\bfinal\s+chorus\b|\blast\s+chorus\b", "Final Chorus", "chorus"),
    (r"\bchorus\b", "Chorus", "chorus"),
    (r"\bhook\b", "Hook", "chorus"),
    (r"\brefrain\b", "Chorus", "chorus"),
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
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
}


def load_json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return None


def marker(label: Any) -> dict[str, str] | None:
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


def same_family(left: dict[str, str], right: dict[str, str]) -> bool:
    return left["type"] == right["type"]


def prefer_specific(current: dict[str, str], incoming: dict[str, str]) -> dict[str, str]:
    if incoming["label"] != current["label"] and len(incoming["label"]) > len(current["label"]):
        return incoming
    return current


def lyric_weight(line: str) -> int:
    cleaned = INLINE_TAG_RE.sub(" ", str(line or ""))
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return 1 if cleaned else 0


def build_segments_from_text(source: str, duration: float | int | None) -> list[dict[str, Any]]:
    duration = float(duration or 0)
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
            markers = [marker(match.group(1)) for match in BRACKET_TAG_RE.finditer(line)]
            markers = [item for item in markers if item]
            if not markers:
                continue
            picked = markers[0]
            if current and not current_has_lyrics and same_family(current["marker"], picked):
                current["marker"] = prefer_specific(current["marker"], picked)
                current["label"] = current["marker"]["label"]
                current["type"] = current["marker"]["type"]
                continue
            current = {"marker": picked, "label": picked["label"], "type": picked["type"], "weight": 0}
            sections.append(current)
            current_has_lyrics = False
            continue

        weight = lyric_weight(line)
        if weight <= 0:
            continue
        if current is None:
            picked = {"label": "Intro", "type": "intro"}
            current = {"marker": picked, "label": picked["label"], "type": picked["type"], "weight": 0}
            sections.append(current)
        current["weight"] += weight
        current_has_lyrics = True

    if not sections:
        return []
    for section in sections:
        section["weight"] = max(1, int(section.get("weight") or 0))

    total = sum(section["weight"] for section in sections) or len(sections)
    cursor = 0.0
    result: list[dict[str, Any]] = []
    for index, section in enumerate(sections):
        end = duration if index == len(sections) - 1 else min(duration, cursor + duration * (section["weight"] / total))
        if end <= cursor:
            end = min(duration, cursor + max(1.0, duration / max(1, len(sections))))
        result.append({"label": section["label"], "type": section["type"], "start": round(cursor, 3), "end": round(end, 3)})
        cursor = end
        if cursor >= duration:
            break
    return result


def normalize_segments(value: Any, duration: float | int | None = None) -> list[dict[str, Any]]:
    segments = load_json(value)
    if not isinstance(segments, list):
        return []
    clean: list[dict[str, Any]] = []
    max_duration = float(duration or 0)
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        picked = marker(segment.get("label")) or marker(segment.get("type")) or marker(segment.get("name")) or marker(segment.get("title"))
        if not picked:
            continue
        try:
            start = float(segment.get("start") or 0)
            end = float(segment.get("end") or start)
        except (TypeError, ValueError):
            continue
        if max_duration > 0:
            start = max(0.0, min(max_duration, start))
            end = max(0.0, min(max_duration, end))
        if end <= start:
            continue
        clean.append({"label": picked["label"], "type": picked["type"], "start": round(start, 3), "end": round(end, 3)})
    return clean


def has_noise(value: Any) -> bool:
    segments = load_json(value)
    if not isinstance(segments, list) or not segments:
        return True
    for segment in segments:
        if not isinstance(segment, dict):
            return True
        picked = marker(segment.get("label")) or marker(segment.get("type")) or marker(segment.get("name")) or marker(segment.get("title"))
        if not picked:
            return True
        if str(segment.get("label") or "").strip().lower() != picked["label"].lower():
            return True
    return False


def task_prompt_for_asset(conn: sqlite3.Connection, row: sqlite3.Row) -> str:
    task_payloads: list[Any] = []
    if row["task_local_id"]:
        task = conn.execute("SELECT request_payload, result_payload FROM suno_tasks WHERE id=?", (row["task_local_id"],)).fetchone()
        if task:
            task_payloads.extend([load_json(task["request_payload"]), load_json(task["result_payload"])])
    if row["suno_task_id"]:
        task = conn.execute("SELECT request_payload, result_payload FROM suno_tasks WHERE task_id=?", (row["suno_task_id"],)).fetchone()
        if task:
            task_payloads.extend([load_json(task["request_payload"]), load_json(task["result_payload"])])
    song = conn.execute("SELECT prompt, lyrics, metadata_json FROM songs WHERE id=?", (row["song_id"],)).fetchone() if row["song_id"] else None
    if song:
        for key in ("prompt", "lyrics"):
            if song[key]:
                return str(song[key])
        task_payloads.append(load_json(song["metadata_json"]))
    task_payloads.append(load_json(row["metadata_json"]))

    def walk(obj: Any) -> str | None:
        if isinstance(obj, dict):
            for key in ("prompt", "lyrics"):
                value = obj.get(key)
                if isinstance(value, str) and value.strip():
                    return value
            for value in obj.values():
                found = walk(value)
                if found:
                    return found
        elif isinstance(obj, list):
            for value in obj:
                found = walk(value)
                if found:
                    return found
        return None

    for payload in task_payloads:
        found = walk(payload)
        if found:
            return found
    return ""


def query_assets(conn: sqlite3.Connection, task_id: str | None, asset_ids: list[int], all_assets: bool) -> list[sqlite3.Row]:
    base = """
    SELECT id, title, song_id, task_local_id, suno_task_id, metadata_json,
           waveform_json, structure_segments_json, duration_seconds
    FROM audio_assets
    WHERE COALESCE(is_deleted, 0)=0
    """
    params: list[Any] = []
    if task_id:
        base += " AND (suno_task_id=? OR task_local_id IN (SELECT id FROM suno_tasks WHERE task_id=?))"
        params.extend([task_id, task_id])
    elif asset_ids:
        placeholders = ",".join("?" for _ in asset_ids)
        base += f" AND id IN ({placeholders})"
        params.extend(asset_ids)
    elif not all_assets:
        raise SystemExit("Bitte --task-id, --asset-id oder --all angeben.")
    base += " ORDER BY id"
    return list(conn.execute(base, params))


def repair(db_path: Path, task_id: str | None, asset_ids: list[int], all_assets: bool, force: bool, dry_run: bool) -> int:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    changed = 0
    try:
        rows = query_assets(conn, task_id, asset_ids, all_assets)
        print(f"assets_checked={len(rows)}")
        for row in rows:
            waveform = load_json(row["waveform_json"])
            if not isinstance(waveform, dict) or not waveform.get("peaks"):
                print(f"skip asset_id={row['id']} reason=no_waveform_peaks")
                continue
            duration = waveform.get("duration_seconds") or row["duration_seconds"]
            source = task_prompt_for_asset(conn, row)
            rebuilt = build_segments_from_text(source, duration)
            structure_clean = normalize_segments(row["structure_segments_json"], duration)
            waveform_clean = normalize_segments(waveform.get("segments"), duration)
            preferred = rebuilt or structure_clean or waveform_clean
            if not preferred:
                print(f"skip asset_id={row['id']} reason=no_structure_segments")
                continue
            current = waveform.get("segments")
            needs_update = force or has_noise(current) or current != preferred or structure_clean != preferred
            if not needs_update:
                print(f"clean asset_id={row['id']} title={row['title']!r} segments={len(preferred)}")
                continue
            print(f"repair asset_id={row['id']} title={row['title']!r} old_segments={len(current or [])} new_segments={len(preferred)} force={int(force)}")
            changed += 1
            if dry_run:
                continue
            waveform["segments"] = preferred
            conn.execute(
                "UPDATE audio_assets SET waveform_json=?, structure_segments_json=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (json.dumps(waveform, ensure_ascii=False), json.dumps(preferred, ensure_ascii=False), row["id"]),
            )
        if dry_run:
            print("dry_run=1 no database changes written")
        else:
            conn.commit()
        print(f"assets_repaired={changed}")
        return changed
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default="./suno_fastapi_app.db")
    parser.add_argument("--task-id")
    parser.add_argument("--asset-id", action="append", type=int, default=[])
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--force", action="store_true", help="Rewrite matching assets even when they already look clean.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    repair(Path(args.database), args.task_id, args.asset_id, args.all, args.force, args.dry_run)


if __name__ == "__main__":
    main()

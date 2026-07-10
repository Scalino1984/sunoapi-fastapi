"""DAW-KI-Kommandodienst: natürliche Befehle -> Arrangement-Operationen.

Dieser Service ist das Server-Gegenstück zur DAW-KI im Frontend:

1. Er baut einen kompakten Kontext aus Arrangement, Songstruktur
   (structure_segments_json), Beatgrid (metadata_json.daw_beatgrid),
   Playhead, Auswahl und ausgewähltem Clip.
2. Er lässt den konfigurierten KI-Provider (AiChatService.run_json_task) einen
   Plan aus einer festen Operations-Whitelist erzeugen.
3. Ein deterministischer Executor wendet die Operationen serverseitig auf das
   Arrangement-Dict an (taktgenau über Beatgrid/BPM). Die KI verändert das
   Arrangement also nie direkt – nur geprüfte, begrenzte Operationen tun das.
4. Fällt der Provider aus, greift ein deterministischer Regex-Fallback für die
   wichtigsten Befehle (Hook doppeln, nach N Takten schneiden, Loop, Lücken).

Persistiert wird über die bestehende Arrangement-Speicherung im Router
(_save_arrangement_to_asset) plus das neue DawAiAction-Protokoll in SQLite.
"""

from __future__ import annotations

import copy
import re
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AudioAsset
from app.services.ai_chat_service import AiChatService, AiProviderError

MIN_CLIP_LENGTH = 0.25

ALLOWED_OPERATIONS: dict[str, list[str]] = {
    "split_clip": ["clip_id", "time", "bars_from_clip_start"],
    "duplicate_clip": ["clip_id", "times"],
    "delete_clip": ["clip_id"],
    "move_clip": ["clip_id", "timeline_start", "delta_seconds", "delta_bars"],
    "trim_clip": ["clip_id", "edge", "seconds", "target_bars"],
    "set_fade": ["clip_id", "fade_in", "fade_out"],
    "set_gain": ["clip_id", "gain_db", "gain_delta"],
    "duplicate_section": ["section_kind", "occurrence"],
    "append_section_to_end": ["section_kind", "occurrence"],
    "delete_section": ["section_kind", "occurrence", "close_gap"],
    "range_delete": ["start", "end", "close_gap"],
    "close_gaps": [],
    "create_loop": ["start", "end", "repeats"],
}

SECTION_KIND_PATTERNS: list[tuple[str, str]] = [
    ("pre_chorus", r"pre[\s_-]?chorus|prehook"),
    ("post_chorus", r"post[\s_-]?chorus|posthook"),
    ("chorus", r"chorus|hook|refrain"),
    ("verse", r"verse|strophe|part\b|rap\s*part"),
    ("bridge", r"bridge|steg"),
    ("intro", r"intro|beginn|anfang"),
    ("outro", r"outro|ende|schluss"),
    ("drop", r"drop"),
    ("break", r"break"),
    ("instrumental", r"instrumental|interlude|solo"),
]

GENERATION_REQUEST_PATTERN = re.compile(
    r"(?:intro|part|rap\s*part|verse|strophe|bridge|outro|hook|chorus|refrain)"
    r".*(?:laenger|länger|verlaenger|verlänger|erweitern|hinzufueg|hinzufüg|hinzufug|"
    r"fuege|füge|fuge|neu|dritter|dritten|16\s*bars|16\s*takte|sechzehn)",
    re.IGNORECASE,
)


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or value == "":
            return default
        return float(str(value).replace(",", "."))
    except Exception:
        return default


def _clip_duration(clip: dict[str, Any]) -> float:
    return max(0.0, (_safe_float(clip.get("source_end"), 0.0) or 0.0) - (_safe_float(clip.get("source_start"), 0.0) or 0.0))


def _arrangement_length(arrangement: dict[str, Any]) -> float:
    length = _safe_float(arrangement.get("duration_seconds"), 0.0) or 0.0
    for clip in arrangement.get("clips") or []:
        length = max(length, (_safe_float(clip.get("timeline_start"), 0.0) or 0.0) + _clip_duration(clip))
    return length


def _make_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _clock(value: float) -> str:
    seconds = max(0.0, float(value or 0))
    minutes = int(seconds // 60)
    return f"{minutes:02d}:{seconds - minutes * 60:04.1f}"


# ---------------------------------------------------------------------------
# Kontext: Beatgrid + Songstruktur
# ---------------------------------------------------------------------------

def _beatgrid_from_asset(asset: AudioAsset) -> dict[str, Any] | None:
    metadata = asset.metadata_json if isinstance(asset.metadata_json, dict) else {}
    grid = metadata.get("daw_beatgrid")
    if isinstance(grid, dict) and grid.get("ok") and isinstance(grid.get("bars"), list) and len(grid["bars"]) >= 2:
        return grid
    return None


def _bar_boundaries(grid: dict[str, Any] | None, duration: float) -> list[float]:
    if not grid:
        return []
    boundaries: list[float] = []
    for bar in grid.get("bars") or []:
        start = _safe_float((bar or {}).get("start"))
        if start is not None:
            boundaries.append(max(0.0, start))
    last_end = _safe_float((grid.get("bars") or [{}])[-1].get("end"))
    if last_end is not None:
        boundaries.append(last_end)
    if duration > 0:
        boundaries.append(duration)
    return sorted({round(min(value, duration or value) * 1000) / 1000 for value in boundaries})


def _bar_length(grid: dict[str, Any] | None, bpm: float | None) -> float | None:
    if grid:
        lengths = sorted(
            length for length in (
                (_safe_float(bar.get("end"), 0.0) or 0.0) - (_safe_float(bar.get("start"), 0.0) or 0.0)
                for bar in (grid.get("bars") or [])
                if isinstance(bar, dict)
            ) if 0.25 < length < 12
        )
        if lengths:
            mid = len(lengths) // 2
            return lengths[mid] if len(lengths) % 2 else (lengths[mid - 1] + lengths[mid]) / 2
        grid_bpm = _safe_float(grid.get("bpm"))
        if grid_bpm and grid_bpm >= 20:
            return 240.0 / grid_bpm
    if bpm and bpm >= 20:
        return 240.0 / bpm
    return None


def _snap_to_boundary(time: float, boundaries: list[float]) -> float:
    if not boundaries:
        return max(0.0, time)
    return min(boundaries, key=lambda value: abs(value - time))


def _section_kind_from_label(label: str) -> str:
    text = str(label or "").lower()
    for kind, pattern in SECTION_KIND_PATTERNS:
        if re.search(pattern, text):
            return kind
    return "other"


def _extract_sections(asset: AudioAsset, duration: float) -> list[dict[str, Any]]:
    """Toleranter Extraktor für structure_segments_json (verschiedene Shapes)."""
    raw = asset.structure_segments_json
    if isinstance(raw, dict):
        raw = raw.get("segments") or raw.get("sections") or raw.get("structure") or []
    if not isinstance(raw, list):
        return []
    sections: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        start = None
        end = None
        for key in ("start", "start_s", "start_time", "startTime", "begin", "from"):
            start = _safe_float(item.get(key), start)
            if start is not None:
                break
        for key in ("end", "end_s", "end_time", "endTime", "stop", "to"):
            end = _safe_float(item.get(key), end)
            if end is not None:
                break
        label = str(item.get("label") or item.get("name") or item.get("kind") or item.get("section") or "").strip()
        if start is None or end is None or end - start < 0.25:
            continue
        if duration > 0:
            start = min(max(0.0, start), duration)
            end = min(max(start + 0.25, end), duration)
        sections.append({
            "start": start,
            "end": end,
            "label": label or "Abschnitt",
            "kind": _section_kind_from_label(label),
        })
    sections.sort(key=lambda section: section["start"])
    occurrence_counter: dict[str, int] = {}
    for section in sections:
        occurrence_counter[section["kind"]] = occurrence_counter.get(section["kind"], 0) + 1
        section["occurrence"] = occurrence_counter[section["kind"]]
    return sections


def _resolve_section(sections: list[dict[str, Any]], kind: str, occurrence: Any) -> dict[str, Any] | None:
    matches = [section for section in sections if section.get("kind") == kind]
    if not matches:
        return None
    if str(occurrence or "").lower() in {"last", "letzte", "letzter"}:
        return matches[-1]
    index = int(_safe_float(occurrence, 0) or 0)
    if index >= 1:
        return matches[index - 1] if index <= len(matches) else None
    return matches[0]


def _musical_section_range(section: dict[str, Any], boundaries: list[float], bar_length: float | None, duration: float) -> tuple[float, float]:
    """Abschnittsgrenzen taktgenau ziehen: Downbeat vor dem Start, Ende über Taktanzahl."""
    raw_start = max(0.0, float(section["start"]))
    raw_end = min(duration or float(section["end"]), float(section["end"]))
    if len(boundaries) < 2:
        return raw_start, raw_end
    start_candidates = [value for value in boundaries if value <= raw_start + 0.14]
    start = start_candidates[-1] if start_candidates else boundaries[0]
    if bar_length:
        bars = max(1, round((raw_end - raw_start) / bar_length))
        target_end = start + bars * bar_length
        end = _snap_to_boundary(target_end, boundaries)
    else:
        end_candidates = [value for value in boundaries if value <= raw_end + 0.18]
        end = end_candidates[-1] if end_candidates else raw_end
    if end <= start + 0.2:
        end = min(duration or raw_end, max(raw_end, start + (bar_length or 1.0)))
    return start, min(end, duration or end)


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------

class DawArrangementExecutor:
    """Wendet Whitelist-Operationen deterministisch auf ein Arrangement an."""

    def __init__(self, arrangement: dict[str, Any], *, sections: list[dict[str, Any]], beatgrid: dict[str, Any] | None, source_duration: float, default_source_audio_id: int) -> None:
        self.arrangement = copy.deepcopy(arrangement)
        self.sections = sections
        self.source_duration = max(0.0, source_duration)
        self.default_source_audio_id = int(default_source_audio_id)
        self.duration = max(_arrangement_length(self.arrangement), self.source_duration)
        self.boundaries = _bar_boundaries(beatgrid, self.duration)
        self.bar_length = _bar_length(beatgrid, _safe_float(self.arrangement.get("bpm")))
        self.actions: list[str] = []
        self.warnings: list[str] = []
        self.selected_clip_id: str | None = None

    # ---- Helfer ----------------------------------------------------------
    def _clips(self) -> list[dict[str, Any]]:
        return self.arrangement.setdefault("clips", [])

    def _find_clip(self, clip_id: Any) -> dict[str, Any] | None:
        wanted = str(clip_id or "")
        for clip in self._clips():
            if str(clip.get("id")) == wanted:
                return clip
        return None

    def _clip_or_selected(self, op: dict[str, Any], fallback_id: str | None) -> dict[str, Any] | None:
        return self._find_clip(op.get("clip_id")) or self._find_clip(fallback_id)

    def _refresh_duration(self) -> None:
        self.arrangement["duration_seconds"] = max(_arrangement_length(self.arrangement), 0.0)
        self.duration = max(self.arrangement["duration_seconds"], self.source_duration)

    def _shift_after(self, cut_start: float, cut_length: float) -> None:
        for clip in self._clips():
            start = _safe_float(clip.get("timeline_start"), 0.0) or 0.0
            if not clip.get("locked") and start >= cut_start + cut_length - 0.001:
                clip["timeline_start"] = max(0.0, start - cut_length)
        markers = self.arrangement.get("markers") or []
        self.arrangement["markers"] = [
            {**marker, "time": max(0.0, (_safe_float(marker.get("time"), 0.0) or 0.0) - cut_length)}
            if (_safe_float(marker.get("time"), 0.0) or 0.0) >= cut_start + cut_length else marker
            for marker in markers
        ]

    def _delete_range(self, cut_start: float, cut_end: float, close_gap: bool) -> None:
        cut_length = cut_end - cut_start
        next_clips: list[dict[str, Any]] = []
        for clip in self._clips():
            if clip.get("locked"):
                next_clips.append(clip)
                continue
            start = _safe_float(clip.get("timeline_start"), 0.0) or 0.0
            end = start + _clip_duration(clip)
            if end <= cut_start or start >= cut_end:
                if close_gap and start >= cut_end:
                    next_clips.append({**clip, "timeline_start": max(0.0, start - cut_length)})
                else:
                    next_clips.append(clip)
                continue
            source_start = _safe_float(clip.get("source_start"), 0.0) or 0.0
            if start < cut_start and cut_start - start >= MIN_CLIP_LENGTH:
                next_clips.append({**clip, "id": _make_id("clip"), "source_end": source_start + (cut_start - start)})
            if end > cut_end and end - cut_end >= MIN_CLIP_LENGTH:
                next_clips.append({
                    **clip,
                    "id": _make_id("clip"),
                    "timeline_start": cut_start if close_gap else cut_end,
                    "source_start": source_start + (cut_end - start),
                })
        self.arrangement["clips"] = next_clips
        markers = self.arrangement.get("markers") or []
        kept = [marker for marker in markers if not (cut_start <= (_safe_float(marker.get("time"), 0.0) or 0.0) <= cut_end)]
        if close_gap:
            kept = [
                {**marker, "time": max(0.0, (_safe_float(marker.get("time"), 0.0) or 0.0) - cut_length)}
                if (_safe_float(marker.get("time"), 0.0) or 0.0) >= cut_end else marker
                for marker in kept
            ]
        self.arrangement["markers"] = kept
        self._refresh_duration()

    def _copy_range_clips(self, range_start: float, range_end: float, insert_at: float, label: str) -> list[dict[str, Any]]:
        pieces: list[dict[str, Any]] = []
        for clip in self._clips():
            start = _safe_float(clip.get("timeline_start"), 0.0) or 0.0
            end = start + _clip_duration(clip)
            overlap_start = max(range_start, start)
            overlap_end = min(range_end, end)
            if overlap_end - overlap_start <= 0.05:
                continue
            source_start = _safe_float(clip.get("source_start"), 0.0) or 0.0
            pieces.append({
                **clip,
                "id": _make_id("clip"),
                "timeline_start": insert_at + (overlap_start - range_start),
                "source_start": source_start + (overlap_start - start),
                "source_end": source_start + (overlap_end - start),
                "label": f"{label} Kopie",
                "locked": False,
            })
        if not pieces and self.source_duration >= range_end - 0.05:
            pieces.append({
                "id": _make_id("clip"),
                "track_id": (self.arrangement.get("tracks") or [{"id": "track-1"}])[0]["id"],
                "source_audio_id": self.default_source_audio_id,
                "timeline_start": insert_at,
                "source_start": range_start,
                "source_end": range_end,
                "gain_db": 0, "fade_in": 0, "fade_out": 0,
                "label": f"{label} Kopie", "muted": False, "locked": False, "color": "cyan",
            })
        pieces.sort(key=lambda piece: piece["timeline_start"])
        return pieces

    def _insert_gap(self, insert_at: float, gap_length: float) -> None:
        next_clips: list[dict[str, Any]] = []
        for clip in self._clips():
            if clip.get("locked"):
                next_clips.append(clip)
                continue
            start = _safe_float(clip.get("timeline_start"), 0.0) or 0.0
            end = start + _clip_duration(clip)
            source_start = _safe_float(clip.get("source_start"), 0.0) or 0.0
            if end <= insert_at + 0.001:
                next_clips.append(clip)
            elif start >= insert_at - 0.001:
                next_clips.append({**clip, "timeline_start": start + gap_length})
            else:
                left = insert_at - start
                right = end - insert_at
                if left >= MIN_CLIP_LENGTH:
                    next_clips.append({**clip, "id": _make_id("clip"), "source_end": source_start + left})
                if right >= MIN_CLIP_LENGTH:
                    next_clips.append({**clip, "id": _make_id("clip"), "timeline_start": insert_at + gap_length, "source_start": source_start + left})
        self.arrangement["clips"] = next_clips
        self.arrangement["markers"] = [
            {**marker, "time": (_safe_float(marker.get("time"), 0.0) or 0.0) + gap_length}
            if (_safe_float(marker.get("time"), 0.0) or 0.0) >= insert_at else marker
            for marker in (self.arrangement.get("markers") or [])
        ]

    def _section_range_for_op(self, op: dict[str, Any]) -> tuple[dict[str, Any], float, float] | None:
        kind = _section_kind_from_label(str(op.get("section_kind") or ""))
        if kind == "other":
            kind = str(op.get("section_kind") or "").strip().lower()
        section = _resolve_section(self.sections, kind, op.get("occurrence"))
        if not section:
            return None
        start, end = _musical_section_range(section, self.boundaries, self.bar_length, max(self.source_duration, self.duration))
        return section, start, end

    # ---- Operationen ------------------------------------------------------
    def apply(self, operations: list[dict[str, Any]], *, selected_clip_id: str | None = None, current_time: float = 0.0) -> None:
        for op in operations[:12]:
            op_type = str(op.get("type") or "").strip()
            handler = getattr(self, f"_op_{op_type}", None)
            if not handler:
                self.warnings.append(f"Operation „{op_type}“ wird ignoriert (nicht erlaubt).")
                continue
            handler(op, selected_clip_id, current_time)
            self._refresh_duration()

    def _op_split_clip(self, op: dict[str, Any], selected: str | None, current_time: float) -> None:
        clip = self._clip_or_selected(op, selected)
        time = _safe_float(op.get("time"))
        bars = _safe_float(op.get("bars_from_clip_start"))
        if clip is not None and bars and self.bar_length:
            time = (_safe_float(clip.get("timeline_start"), 0.0) or 0.0) + bars * self.bar_length
        if time is None:
            time = current_time
        if self.boundaries and (op.get("bars_from_clip_start") or self.arrangement.get("snap_enabled")):
            time = _snap_to_boundary(time, self.boundaries)
        if clip is None:
            for candidate in self._clips():
                start = _safe_float(candidate.get("timeline_start"), 0.0) or 0.0
                if start + 0.05 < time < start + _clip_duration(candidate) - 0.05:
                    clip = candidate
                    break
        if clip is None or clip.get("locked"):
            self.warnings.append("Kein schneidbarer Clip am Schnittpunkt gefunden.")
            return
        start = _safe_float(clip.get("timeline_start"), 0.0) or 0.0
        offset = time - start
        length = _clip_duration(clip)
        if offset <= 0.05 or offset >= length - 0.05:
            self.warnings.append("Schnittpunkt liegt zu nah am Clip-Rand.")
            return
        source_start = _safe_float(clip.get("source_start"), 0.0) or 0.0
        left = {**clip, "id": _make_id("clip"), "source_end": source_start + offset}
        right = {**clip, "id": _make_id("clip"), "timeline_start": time, "source_start": source_start + offset}
        self.arrangement["clips"] = [piece for item in self._clips() for piece in ([left, right] if item is clip else [item])]
        self.selected_clip_id = right["id"]
        self.actions.append(f"Clip „{clip.get('label') or 'Clip'}“ bei {_clock(time)} geschnitten")

    def _op_duplicate_clip(self, op: dict[str, Any], selected: str | None, _t: float) -> None:
        clip = self._clip_or_selected(op, selected)
        if clip is None:
            self.warnings.append("Kein Clip zum Duplizieren gefunden.")
            return
        times = max(1, min(8, int(_safe_float(op.get("times"), 1) or 1)))
        cursor = (_safe_float(clip.get("timeline_start"), 0.0) or 0.0) + _clip_duration(clip)
        for _ in range(times):
            copy_clip = {**clip, "id": _make_id("clip"), "timeline_start": cursor, "label": f"{clip.get('label') or 'Clip'} Kopie"}
            self._clips().append(copy_clip)
            self.selected_clip_id = copy_clip["id"]
            cursor += _clip_duration(clip)
        self.actions.append(f"Clip „{clip.get('label') or 'Clip'}“ {times}× dupliziert")

    def _op_delete_clip(self, op: dict[str, Any], selected: str | None, _t: float) -> None:
        clip = self._clip_or_selected(op, selected)
        if clip is None:
            self.warnings.append("Kein Clip zum Löschen gefunden.")
            return
        self.arrangement["clips"] = [item for item in self._clips() if item is not clip]
        self.actions.append(f"Clip „{clip.get('label') or 'Clip'}“ entfernt")

    def _op_move_clip(self, op: dict[str, Any], selected: str | None, _t: float) -> None:
        clip = self._clip_or_selected(op, selected)
        if clip is None or clip.get("locked"):
            self.warnings.append("Kein verschiebbarer Clip gefunden.")
            return
        start = _safe_float(clip.get("timeline_start"), 0.0) or 0.0
        target = _safe_float(op.get("timeline_start"))
        if target is None:
            delta = _safe_float(op.get("delta_seconds"), 0.0) or 0.0
            delta_bars = _safe_float(op.get("delta_bars"))
            if delta_bars and self.bar_length:
                delta += delta_bars * self.bar_length
            target = start + delta
        if self.boundaries and self.arrangement.get("snap_enabled"):
            target = _snap_to_boundary(target, self.boundaries)
        clip["timeline_start"] = max(0.0, target)
        self.selected_clip_id = str(clip.get("id"))
        self.actions.append(f"Clip „{clip.get('label') or 'Clip'}“ auf {_clock(clip['timeline_start'])} verschoben")

    def _op_trim_clip(self, op: dict[str, Any], selected: str | None, _t: float) -> None:
        clip = self._clip_or_selected(op, selected)
        if clip is None or clip.get("locked"):
            self.warnings.append("Kein trimmbarer Clip gefunden.")
            return
        length = _clip_duration(clip)
        target_bars = _safe_float(op.get("target_bars"))
        seconds = _safe_float(op.get("seconds"), 0.0) or 0.0
        if target_bars and self.bar_length:
            seconds = max(0.0, length - target_bars * self.bar_length)
        seconds = max(0.0, min(seconds, length - MIN_CLIP_LENGTH))
        if seconds <= 0:
            self.warnings.append("Trim-Betrag ergibt keine Änderung.")
            return
        edge = "start" if str(op.get("edge") or "end") == "start" else "end"
        if edge == "start":
            clip["timeline_start"] = (_safe_float(clip.get("timeline_start"), 0.0) or 0.0) + seconds
            clip["source_start"] = (_safe_float(clip.get("source_start"), 0.0) or 0.0) + seconds
        else:
            clip["source_end"] = (_safe_float(clip.get("source_end"), 0.0) or 0.0) - seconds
        self.selected_clip_id = str(clip.get("id"))
        self.actions.append(f"Clip-{'Anfang' if edge == 'start' else 'Ende'} um {_clock(seconds)} gekürzt")

    def _op_set_fade(self, op: dict[str, Any], selected: str | None, _t: float) -> None:
        clip = self._clip_or_selected(op, selected)
        if clip is None:
            self.warnings.append("Kein Clip für Fade gefunden.")
            return
        length = _clip_duration(clip)
        described = []
        for key in ("fade_in", "fade_out"):
            value = _safe_float(op.get(key))
            if value is not None:
                clip[key] = max(0.0, min(value, length / 2))
                described.append(f"{key.replace('_', '-')} {_clock(clip[key])}")
        self.selected_clip_id = str(clip.get("id"))
        self.actions.append(f"Fades gesetzt: {', '.join(described) or 'keine Änderung'}")

    def _op_set_gain(self, op: dict[str, Any], selected: str | None, _t: float) -> None:
        clip = self._clip_or_selected(op, selected)
        if clip is None:
            self.warnings.append("Kein Clip für Gain gefunden.")
            return
        current = _safe_float(clip.get("gain_db"), 0.0) or 0.0
        target = _safe_float(op.get("gain_db"))
        if target is None:
            target = current + (_safe_float(op.get("gain_delta"), 0.0) or 0.0)
        clip["gain_db"] = max(-24.0, min(24.0, target))
        self.selected_clip_id = str(clip.get("id"))
        self.actions.append(f"Clip-Gain {current:g} dB → {clip['gain_db']:g} dB")

    def _op_duplicate_section(self, op: dict[str, Any], _s: str | None, _t: float, *, append: bool = False) -> None:
        resolved = self._section_range_for_op(op)
        if not resolved:
            self.warnings.append(f"Abschnitt „{op.get('section_kind')}“ wurde in der Songstruktur nicht gefunden.")
            return
        section, start, end = resolved
        length = end - start
        insert_at = _arrangement_length(self.arrangement) if append else end
        copies = self._copy_range_clips(start, end, insert_at, section["label"])
        if not copies:
            self.warnings.append("Für den Abschnitt konnten keine Audio-Clips ermittelt werden.")
            return
        if not append:
            self._insert_gap(insert_at, length)
        self._clips().extend(copies)
        self._clips().sort(key=lambda clip: _safe_float(clip.get("timeline_start"), 0.0) or 0.0)
        self.selected_clip_id = copies[0]["id"]
        bars = round(length / self.bar_length) if self.bar_length else None
        detail = f" ({bars} Takte)" if bars else ""
        self.actions.append(
            f"{section['label']} {_clock(start)}–{_clock(end)}{detail} {'ans Ende gehängt' if append else 'direkt dahinter dupliziert'}"
        )

    def _op_append_section_to_end(self, op: dict[str, Any], selected: str | None, current_time: float) -> None:
        self._op_duplicate_section(op, selected, current_time, append=True)

    def _op_delete_section(self, op: dict[str, Any], _s: str | None, _t: float) -> None:
        resolved = self._section_range_for_op(op)
        if not resolved:
            self.warnings.append(f"Abschnitt „{op.get('section_kind')}“ wurde in der Songstruktur nicht gefunden.")
            return
        section, start, end = resolved
        close_gap = bool(op.get("close_gap", True))
        self._delete_range(start, end, close_gap)
        self.actions.append(f"{section['label']} {_clock(start)}–{_clock(end)} entfernt{' und Lücke geschlossen' if close_gap else ''}")

    def _op_range_delete(self, op: dict[str, Any], _s: str | None, _t: float) -> None:
        start = _safe_float(op.get("start"))
        end = _safe_float(op.get("end"))
        if start is None or end is None or end - start <= 0.05:
            self.warnings.append("range_delete braucht gültige start/end-Werte.")
            return
        if self.boundaries and self.arrangement.get("snap_enabled"):
            start = _snap_to_boundary(start, self.boundaries)
            end = _snap_to_boundary(end, self.boundaries)
        self._delete_range(min(start, end), max(start, end), bool(op.get("close_gap", True)))
        self.actions.append(f"Bereich {_clock(min(start, end))}–{_clock(max(start, end))} entfernt")

    def _op_close_gaps(self, _op: dict[str, Any], _s: str | None, _t: float) -> None:
        moved = 0
        for track in self.arrangement.get("tracks") or []:
            cursor = 0.0
            for clip in sorted(
                (clip for clip in self._clips() if clip.get("track_id") == track.get("id") and not clip.get("locked")),
                key=lambda clip: _safe_float(clip.get("timeline_start"), 0.0) or 0.0,
            ):
                start = _safe_float(clip.get("timeline_start"), 0.0) or 0.0
                if start > cursor + 0.02:
                    clip["timeline_start"] = cursor
                    moved += 1
                cursor = max(cursor, (_safe_float(clip.get("timeline_start"), 0.0) or 0.0) + _clip_duration(clip))
        if moved:
            self.actions.append(f"{moved} Clip{'s' if moved != 1 else ''} nach links geschoben (Lücken geschlossen)")
        else:
            self.warnings.append("Keine relevanten Lücken gefunden.")

    def _op_create_loop(self, op: dict[str, Any], _s: str | None, _t: float) -> None:
        start = _safe_float(op.get("start"))
        end = _safe_float(op.get("end"))
        repeats = max(1, min(16, int(_safe_float(op.get("repeats"), 2) or 2)))
        if start is None or end is None or end - start <= 0.05:
            self.warnings.append("create_loop braucht gültige start/end-Werte.")
            return
        if self.boundaries:
            start = _snap_to_boundary(start, self.boundaries)
            end = _snap_to_boundary(end, self.boundaries)
        length = end - start
        insert_at = end
        first_id = None
        for index in range(repeats):
            copies = self._copy_range_clips(start, end, insert_at, f"Loop {index + 1}")
            if not copies:
                break
            self._insert_gap(insert_at, length)
            self._clips().extend(copies)
            self._clips().sort(key=lambda clip: _safe_float(clip.get("timeline_start"), 0.0) or 0.0)
            first_id = first_id or copies[0]["id"]
            insert_at += length
        if first_id:
            self.selected_clip_id = first_id
            self.actions.append(f"Loop aus {_clock(start)}–{_clock(end)} mit {repeats} Wiederholungen erzeugt")
        else:
            self.warnings.append("Loop konnte nicht erzeugt werden.")


# ---------------------------------------------------------------------------
# KI-Planer + Fallback
# ---------------------------------------------------------------------------

class DawAiCommandService:
    async def resolve(
        self,
        db: Session,
        asset: AudioAsset,
        arrangement: dict[str, Any],
        *,
        message: str,
        selected_clip_id: str | None = None,
        selected_section_id: str | None = None,
        current_time: float = 0.0,
        selection: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        duration = max(_arrangement_length(arrangement), float(asset.duration_seconds or 0))
        sections = _extract_sections(asset, duration)
        beatgrid = _beatgrid_from_asset(asset)
        provider = model = None
        operations: list[dict[str, Any]] | None = None
        interpretation = ""
        title = "Arrangement-Änderung"
        source = "daw_arrangement_ai"
        ai_warnings: list[str] = []

        if GENERATION_REQUEST_PATTERN.search(message or ""):
            return {
                "ok": False,
                "needs_generation": True,
                "message": "Dieser Wunsch braucht neue Audio-Erzeugung (z. B. Suno Extend) statt reinem Timeline-Schnitt.",
                "provider": provider, "model": model, "source": source,
            }

        try:
            provider, model, data = await self._plan_with_ai(
                db, asset, arrangement, sections, beatgrid, duration,
                message=message, selected_clip_id=selected_clip_id,
                current_time=current_time, selection=selection,
            )
            if data.get("needs_generation"):
                return {
                    "ok": False,
                    "needs_generation": True,
                    "message": data.get("interpretation") or "Dieser Wunsch braucht neue Audio-Erzeugung (z. B. Suno Extend) statt reinem Timeline-Schnitt.",
                    "provider": provider, "model": model, "source": source,
                }
            operations = self._validate_operations(data.get("operations"))
            interpretation = str(data.get("interpretation") or "").strip()
            title = str(data.get("title") or title).strip()[:120] or title
            if isinstance(data.get("warnings"), list):
                ai_warnings = [str(warning) for warning in data["warnings"] if warning][:6]
        except AiProviderError:
            pass
        except Exception:
            pass

        if not operations:
            fallback = self._fallback_operations(message, sections, current_time, selection)
            if fallback:
                operations = fallback["operations"]
                interpretation = interpretation or fallback["interpretation"]
                title = fallback.get("title") or title
                source = "daw_arrangement_fallback"
                ai_warnings.append("KI-Provider nicht verfügbar oder ohne Plan – deterministischer Fallback wurde verwendet.")

        if not operations:
            return {
                "ok": False,
                "message": interpretation or "Ich konnte den Befehl nicht in Timeline-Operationen übersetzen. Formuliere ihn konkreter (Abschnitt, Takte, Sekunden).",
                "provider": provider, "model": model, "source": source,
            }

        executor = DawArrangementExecutor(
            arrangement,
            sections=sections,
            beatgrid=beatgrid,
            source_duration=float(asset.duration_seconds or 0),
            default_source_audio_id=int(asset.id),
        )
        executor.apply(operations, selected_clip_id=selected_clip_id, current_time=current_time)
        if not executor.actions:
            return {
                "ok": False,
                "message": "; ".join(executor.warnings) or "Die geplanten Operationen ergaben keine Änderung.",
                "operations": operations,
                "provider": provider, "model": model, "source": source,
            }

        return {
            "ok": True,
            "title": title,
            "interpretation": interpretation or f"Befehl erkannt: {title}.",
            "message": interpretation or f"Plan bereit: {title}.",
            "actions": executor.actions,
            "warnings": [*ai_warnings, *executor.warnings][:8],
            "operations": operations,
            "arrangement": executor.arrangement,
            "selected_clip_id": executor.selected_clip_id or selected_clip_id,
            "provider": provider, "model": model, "source": source,
        }

    # ---- KI-Aufruf ---------------------------------------------------------
    async def _plan_with_ai(self, db, asset, arrangement, sections, beatgrid, duration, *, message, selected_clip_id, current_time, selection):
        settings = get_settings()
        try:
            from app.routers.admin import get_ai_admin_settings
            admin_settings = get_ai_admin_settings(db)
        except Exception:
            admin_settings = {}
        provider = admin_settings.get("default_provider") or settings.ai_default_provider
        model = admin_settings.get("default_model") or settings.ai_default_model

        bar_length = _bar_length(beatgrid, _safe_float(arrangement.get("bpm")))
        clips_payload = [
            {
                "id": clip.get("id"),
                "track_id": clip.get("track_id"),
                "label": clip.get("label"),
                "timeline_start": round(_safe_float(clip.get("timeline_start"), 0.0) or 0.0, 3),
                "duration": round(_clip_duration(clip), 3),
                "source_start": round(_safe_float(clip.get("source_start"), 0.0) or 0.0, 3),
                "muted": bool(clip.get("muted")), "locked": bool(clip.get("locked")),
            }
            for clip in (arrangement.get("clips") or [])[:60]
        ]
        instruction_payload = {
            "task": "resolve_daw_arrangement_command",
            "user_message": message,
            "language": "de",
            "arrangement": {
                "duration_seconds": round(duration, 3),
                "bpm": arrangement.get("bpm"),
                "time_signature": arrangement.get("time_signature"),
                "snap_enabled": arrangement.get("snap_enabled"),
                "tracks": arrangement.get("tracks"),
                "clips": clips_payload,
                "markers": (arrangement.get("markers") or [])[:30],
            },
            "song_sections": sections[:24],
            "musical_grid": {
                "has_beatgrid": bool(beatgrid),
                "bpm": (beatgrid or {}).get("bpm") or arrangement.get("bpm"),
                "bar_length_seconds": round(bar_length, 4) if bar_length else None,
                "bar_count": len((beatgrid or {}).get("bars") or []) or None,
            },
            "context": {
                "selected_clip_id": selected_clip_id,
                "playhead_seconds": round(float(current_time or 0), 3),
                "selection": selection,
            },
            "allowed_operations": [
                {"type": op_type, "fields": fields} for op_type, fields in ALLOWED_OPERATIONS.items()
            ],
            "rules": [
                "Erzeuge ausschließlich Operationen aus allowed_operations.",
                "Zeitangaben immer in Sekunden; Takte über *_bars-Felder oder target_bars.",
                "„Hook“/„Refrain“ = section_kind chorus; „Strophe“/„Part“ = verse.",
                "„erste/zweite/letzte Hook“ über occurrence (1, 2, 'last').",
                "Für „Clip nach N Takten schneiden“ nutze split_clip mit bars_from_clip_start.",
                "Wenn kein clip_id genannt ist, lass clip_id weg – der ausgewählte Clip wird verwendet.",
                "Für Wünsche, die neues Audio erfordern (neuer Part, längeres Instrumental), setze needs_generation true und operations leer.",
                "Maximal 6 Operationen. Bei Mehrdeutigkeit lieber leer lassen und in interpretation nachfragen.",
            ],
            "expected_output": {
                "is_daw_command": True,
                "needs_generation": False,
                "operations": [],
                "title": "kurzer Titel der Änderung",
                "interpretation": "kurze deutsche Erklärung des Plans",
                "warnings": [],
            },
        }
        system_prompt = (
            "Du bist der Arrangement-Planer einer Mini-DAW. "
            "Du erzeugst ausschließlich ein valides JSON-Objekt mit einer Liste geprüfter Timeline-Operationen. "
            "Du veränderst nie Audio-Inhalte, nur Clips auf der Timeline. Keine Shell-Befehle, keine Pfade."
        )
        result = await AiChatService().run_json_task(
            provider=provider,
            model=model,
            system_prompt=system_prompt,
            instruction_payload=instruction_payload,
            profile_options={"max_output_tokens": 1600, "temperature": 0.1},
        )
        data = result.data if isinstance(result.data, dict) else {}
        return provider, model, data

    # ---- Validierung / Fallback ---------------------------------------------
    def _validate_operations(self, operations: Any) -> list[dict[str, Any]]:
        if not isinstance(operations, list):
            return []
        cleaned: list[dict[str, Any]] = []
        for item in operations[:12]:
            if not isinstance(item, dict):
                continue
            op_type = str(item.get("type") or "").strip()
            if op_type not in ALLOWED_OPERATIONS:
                continue
            allowed_fields = set(ALLOWED_OPERATIONS[op_type])
            cleaned.append({"type": op_type, **{key: item[key] for key in item if key in allowed_fields}})
        return cleaned

    def _fallback_operations(self, message: str, sections, current_time: float, selection) -> dict[str, Any] | None:
        text = message.lower()
        bars_match = re.search(r"(\d+)\s*(?:takt|takte|bars?)", text)
        bars = int(bars_match.group(1)) if bars_match else None

        section_kind = None
        for kind, pattern in SECTION_KIND_PATTERNS:
            if re.search(pattern, text):
                section_kind = kind
                break
        occurrence: Any = None
        if re.search(r"erste[rn]?\s", text):
            occurrence = 1
        elif re.search(r"zweite[rn]?\s", text):
            occurrence = 2
        elif re.search(r"letzte[rn]?\s", text):
            occurrence = "last"

        if section_kind and re.search(r"doppel|verdoppel|zweimal|2x|nochmal|wiederhol", text):
            return {"operations": [{"type": "duplicate_section", "section_kind": section_kind, "occurrence": occurrence or 1}],
                    "interpretation": "Abschnitt wird taktgenau dupliziert.", "title": "Abschnitt duplizieren"}
        if section_kind and re.search(r"ans?\s*ende|anhaeng|anhäng|append", text):
            return {"operations": [{"type": "append_section_to_end", "section_kind": section_kind, "occurrence": occurrence or 1}],
                    "interpretation": "Abschnitt wird ans Ende gehängt.", "title": "Abschnitt ans Ende"}
        if section_kind and re.search(r"loesch|lösch|entfern|raus|weg|delete|remove", text):
            return {"operations": [{"type": "delete_section", "section_kind": section_kind, "occurrence": occurrence, "close_gap": True}],
                    "interpretation": "Abschnitt wird entfernt, Lücke geschlossen.", "title": "Abschnitt entfernen"}
        if section_kind and bars and re.search(r"kuerz|kürz|auf\s*\d+\s*takt", text):
            return {"operations": [{"type": "trim_clip", "edge": "end", "target_bars": bars}],
                    "interpretation": f"Ausgewählter Clip wird auf {bars} Takte gekürzt.", "title": f"Auf {bars} Takte kürzen"}
        if bars and re.search(r"schneid|schnitt|split|cut", text):
            return {"operations": [{"type": "split_clip", "bars_from_clip_start": bars}],
                    "interpretation": f"Clip wird exakt nach {bars} Takten geschnitten.", "title": f"Nach {bars} Takten schneiden"}
        if bars and re.search(r"kuerz|kürz", text):
            return {"operations": [{"type": "trim_clip", "edge": "end", "target_bars": bars}],
                    "interpretation": f"Clip wird auf {bars} Takte gekürzt.", "title": f"Auf {bars} Takte kürzen"}
        if re.search(r"(luecke|lücke)n?\s*(schliess|schließ)|(schliess|schließ)\w*\s+(alle\s+)?(luecke|lücke)|gap", text):
            return {"operations": [{"type": "close_gaps"}], "interpretation": "Alle Lücken pro Spur werden geschlossen.", "title": "Lücken schließen"}
        if re.search(r"loop", text) and isinstance(selection, dict):
            start = _safe_float(selection.get("start"))
            end = _safe_float(selection.get("end"))
            if start is not None and end is not None and end - start > 0.05:
                repeats_match = re.search(r"(\d+)\s*(?:x|mal|wiederhol)", text)
                repeats = int(repeats_match.group(1)) if repeats_match else 2
                return {"operations": [{"type": "create_loop", "start": start, "end": end, "repeats": repeats}],
                        "interpretation": "Markierter Bereich wird als Loop wiederholt.", "title": "Loop erzeugen"}
        return None

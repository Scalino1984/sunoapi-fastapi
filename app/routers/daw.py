from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.config import get_settings
from app.services.portable_path_service import to_portable_path
from app.database import SessionLocal, get_db
from app.models import AudioAsset, AudioTranscript, DawArrangementSession, DawPromptHook, StatusNotification, SunoTask
from app.schemas import AudioAssetRead, DawPromptHookRead
from app.services.audio_metadata_service import normalize_audio_content_type, read_audio_duration_seconds
from app.services.waveform_service import get_or_create_waveform
from app.services.background_task_runner import run_detached_process
from app.services.task_lifecycle_service import heartbeat_task, mark_task_finished
from app.utils.time_utils import utc_now_naive
from app.services.ai_chat_service import AiChatService, AiProviderError
from app.services.daw_beatgrid_service import build_daw_beatgrid, persist_daw_beatgrid
from app.services.srt_parser import export_srt, parse_srt, renumber_segments
from app.services.srt_transcript_service import segments_to_half_srt

router = APIRouter(prefix="/api/daw", tags=["daw"])


class DawOperation(BaseModel):
    type: str
    start: float | None = None
    end: float | None = None
    duration: float | None = None
    gain_db: float | None = None
    target_lufs: float | None = None
    preset: str | None = None


class DawRenderRequest(BaseModel):
    source_audio_id: int
    operations: list[DawOperation] = Field(default_factory=list)
    version_label: str | None = None
    output_format: Literal["mp3", "wav", "m4a"] = "mp3"
    title_suffix: str | None = None
    create_notification: bool = True


class DawMarkerRequest(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    time: float = Field(ge=0)
    type: str | None = Field(default="marker", max_length=80)
    note: str | None = None


class DawCommandRequest(BaseModel):
    message: str = Field(min_length=1)
    execute: bool = False
    preview_only: bool = False
    use_ai: bool = True


class DawChatRequest(BaseModel):
    source_audio_id: int
    message: str = Field(min_length=1)
    current_time: float | None = None
    duration_seconds: float | None = None
    current_plan: dict[str, Any] | None = None
    markers: list[dict[str, Any]] = Field(default_factory=list)
    history: list[dict[str, Any]] = Field(default_factory=list)
    output_format: Literal["mp3", "wav", "m4a"] = "mp3"
    execute: bool = False


class DawArrangementMarker(BaseModel):
    id: str | None = None
    label: str = Field(default="Marker", min_length=1, max_length=120)
    time: float = Field(default=0, ge=0)
    type: str | None = Field(default="marker", max_length=80)
    note: str | None = None


class DawArrangementClip(BaseModel):
    id: str | None = None
    track_id: str = Field(default="track-1", max_length=40)
    source_audio_id: int | None = None
    timeline_start: float = Field(default=0, ge=0)
    source_start: float = Field(default=0, ge=0)
    source_end: float | None = None
    gain_db: float = Field(default=0, ge=-24, le=24)
    fade_in: float = Field(default=0, ge=0, le=60)
    fade_out: float = Field(default=0, ge=0, le=60)
    label: str | None = Field(default=None, max_length=140)
    muted: bool = False
    locked: bool = False
    color: str | None = Field(default=None, max_length=40)


class DawArrangementTrack(BaseModel):
    id: str = Field(max_length=40)
    name: str = Field(max_length=120)
    muted: bool = False
    solo: bool = False
    volume_db: float = Field(default=0, ge=-24, le=24)


class DawArrangementState(BaseModel):
    version: int = 1
    source_audio_id: int
    duration_seconds: float = Field(default=0, ge=0)
    bpm: float | None = Field(default=None, ge=20, le=300)
    time_signature: str = Field(default="4/4", max_length=12)
    snap_enabled: bool = False
    snap_unit: Literal["bar", "beat", "half", "quarter"] = "beat"
    tracks: list[DawArrangementTrack] = Field(default_factory=list)
    clips: list[DawArrangementClip] = Field(default_factory=list)
    markers: list[DawArrangementMarker] = Field(default_factory=list)


class DawArrangementSaveRequest(BaseModel):
    arrangement: DawArrangementState
    session_id: int | None = None
    title: str | None = Field(default=None, max_length=180)
    create_new_session: bool = False


class DawArrangementRenderRequest(BaseModel):
    arrangement: DawArrangementState | None = None
    session_id: int | None = None
    output_format: Literal["mp3", "wav", "m4a"] = "mp3"
    version_label: str | None = None
    create_notification: bool = True


class DawArrangementRenderTaskResponse(BaseModel):
    ok: bool = True
    queued: bool = True
    task_local_id: int
    task_type: str = "daw_arrangement_render"
    status: str = "RUNNING"
    message: str



TIME_RE = re.compile(r"(?:(\d+)\s*[:.]\s*)?(\d{1,2})(?:\s*(?:min|minute|minuten|m))?", re.I)


def _asset_or_404(db: Session, asset_id: int) -> AudioAsset:
    asset = db.query(AudioAsset).filter(AudioAsset.id == asset_id, AudioAsset.is_deleted.is_(False)).first()
    if not asset:
        raise HTTPException(status_code=404, detail="AudioAsset wurde nicht gefunden.")
    return asset


@router.get("/prompt-hooks", response_model=list[DawPromptHookRead])
def list_daw_prompt_hooks(scope: str = "daw", db: Session = Depends(get_db)):
    return (
        db.query(DawPromptHook)
        .filter(
            DawPromptHook.is_deleted.is_(False),
            DawPromptHook.is_active.is_(True),
            DawPromptHook.scope == (scope or "daw"),
        )
        .order_by(DawPromptHook.sort_order.asc(), DawPromptHook.title.asc())
        .all()
    )


def _resolve_audio_path(asset: AudioAsset) -> Path:
    settings = get_settings()
    candidates: list[Path] = []
    for value in [asset.local_path, asset.filename, asset.public_url, asset.source_url]:
        if not value:
            continue
        text = str(value).split("?", 1)[0]
        candidate = Path(text)
        candidates.append(candidate)
        if candidate.name:
            candidates.append(settings.audio_storage_path / candidate.name)
    for candidate in candidates:
        try:
            resolved = candidate if candidate.is_absolute() else candidate.resolve()
        except Exception:
            resolved = candidate
        if resolved.exists() and resolved.is_file() and resolved.stat().st_size > 0:
            return resolved
    raise HTTPException(status_code=404, detail="Diese Audiodatei ist nicht lokal gespeichert. Bitte zuerst Audio lokal sichern/importieren.")


def _duration_seconds(path: Path) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        duration = read_audio_duration_seconds(path)
        return float(duration or 0)
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            text=True,
            capture_output=True,
            check=True,
            timeout=20,
        )
        return max(0.0, float(result.stdout.strip() or 0))
    except Exception:
        duration = read_audio_duration_seconds(path)
        return float(duration or 0)


def _sanitize_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9ÄÖÜäöüß._ -]+", "_", value or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ._- ")
    return (cleaned or "daw_edit")[:140]


def _edited_display_title(value: str | None) -> str:
    """Return the library-facing title for a DAW-created version.

    Library and song-detail views primarily use title/display_title from
    audio_assets.  DAW renders must therefore be visibly distinguishable from
    the untouched source asset without requiring special frontend branching.
    """
    base = re.sub(r"\s+", " ", str(value or "Audio")).strip() or "Audio"
    if re.search(r"\(\s*Editiert\s*\)\s*$", base, re.I):
        return base[:255]
    return f"{base} (Editiert)"[:255]


def _preview_media_type(output_format: str) -> str:
    if output_format == "wav":
        return "audio/wav"
    if output_format == "m4a":
        return "audio/mp4"
    return "audio/mpeg"


def _unlink_path(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass


def _time_to_seconds(text: str) -> float | None:
    # Bevorzugt explizite mm:ss-Angaben.
    colon = re.search(r"(\d{1,3})\s*[:.]\s*(\d{1,2})", text)
    if colon:
        return int(colon.group(1)) * 60 + int(colon.group(2))
    minutes = re.search(r"(\d+(?:[,.]\d+)?)\s*(?:min|minute|minuten)\b", text, re.I)
    if minutes:
        return float(minutes.group(1).replace(",", ".")) * 60
    seconds = re.search(r"(\d+(?:[,.]\d+)?)\s*(?:sek|sekunde|sekunden|s)\b", text, re.I)
    if seconds:
        return float(seconds.group(1).replace(",", "."))
    return None


def _extract_song_query(message: str) -> tuple[str, str | None]:
    text = message.strip()
    version = None
    version_match = re.search(r"\bvariante\s*([a-z0-9]+)\b", text, re.I)
    if version_match:
        version = version_match.group(1)
    title = text
    song_match = re.search(r"\bsong\s+(.+?)(?:\s+variante\b|\s+bei\b|\s+ab\b|\s+bis\b|\s+und\b|$)", text, re.I)
    if song_match:
        title = song_match.group(1)
    else:
        for verb in ("schneide", "trimme", "kürze", "kuerze", "normalisiere", "mastere", "erstelle"):
            title = re.sub(rf"^\s*{verb}\s+", "", title, flags=re.I)
        title = re.split(r"\s+(?:variante|bei|ab|bis|und)\b", title, maxsplit=1, flags=re.I)[0]
    title = re.sub(r"[\"'“”]", "", title).strip(" .:-")
    return title, version


def _find_audio_by_title(db: Session, title_query: str, version: str | None = None) -> AudioAsset | None:
    q = (title_query or "").strip()
    if not q:
        return None
    like = f"%{q}%"
    rows = (
        db.query(AudioAsset)
        .filter(AudioAsset.is_deleted.is_(False))
        .filter(or_(AudioAsset.display_title.ilike(like), AudioAsset.title.ilike(like), AudioAsset.filename.ilike(like)))
        .order_by(AudioAsset.updated_at.desc())
        .limit(30)
        .all()
    )
    if version:
        v = str(version).lower()
        for row in rows:
            hay = " ".join([str(row.version_label or ""), str(row.operation_label or ""), str(row.display_title or ""), str(row.title or "")]).lower()
            if f"variante {v}" in hay or hay.endswith(f" {v}") or v in hay.split():
                return row
    return rows[0] if rows else None




def _candidate_audio_assets(db: Session, limit: int = 80) -> list[AudioAsset]:
    return (
        db.query(AudioAsset)
        .filter(AudioAsset.is_deleted.is_(False))
        .order_by(AudioAsset.updated_at.desc())
        .limit(limit)
        .all()
    )


def _find_audio_by_id_or_title(db: Session, asset_id: int | None, title_query: str | None, version: str | None = None) -> AudioAsset | None:
    if asset_id:
        asset = db.query(AudioAsset).filter(AudioAsset.id == int(asset_id), AudioAsset.is_deleted.is_(False)).first()
        if asset:
            return asset
    return _find_audio_by_title(db, title_query or "", version)


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or value == "":
            return default
        return float(str(value).replace(",", "."))
    except Exception:
        return default


def _normalize_ai_operations(operations: Any, duration_seconds: float | None = None) -> list[dict[str, Any]]:
    if not isinstance(operations, list):
        return []
    normalized: list[dict[str, Any]] = []
    allowed = {"trim", "keep", "cut", "trim_end", "cut_at", "end_at", "fade_in", "fadein", "fade_out", "fadeout", "gain", "volume", "normalize", "lufs", "youtube_lufs", "preset", "enhance"}
    for item in operations[:8]:
        if not isinstance(item, dict):
            continue
        op_type = str(item.get("type") or "").strip().lower()
        if op_type not in allowed:
            continue
        op: dict[str, Any] = {"type": op_type}
        if item.get("start") is not None:
            op["start"] = max(0.0, _safe_float(item.get("start"), 0.0) or 0.0)
        if item.get("end") is not None:
            end = max(0.0, _safe_float(item.get("end"), 0.0) or 0.0)
            if duration_seconds and duration_seconds > 0:
                end = min(end, duration_seconds)
            if end > 0:
                op["end"] = end
        if item.get("duration") is not None:
            op["duration"] = max(0.05, min(30.0, _safe_float(item.get("duration"), 2.0) or 2.0))
        if item.get("gain_db") is not None:
            op["gain_db"] = max(-12.0, min(12.0, _safe_float(item.get("gain_db"), 0.0) or 0.0))
        if item.get("target_lufs") is not None:
            op["target_lufs"] = max(-24.0, min(-8.0, _safe_float(item.get("target_lufs"), -14.0) or -14.0))
        if item.get("preset") is not None:
            preset = str(item.get("preset") or "").strip().lower().replace(" ", "_")
            if preset in {"youtube", "youtube_master", "youtube-master", "klarer", "clear", "clarity", "mehr_druck", "druck", "punch", "club", "bass", "mehr_bass", "hoehen", "mehr_hoehen", "höhen", "mehr_höhen"}:
                op["preset"] = preset
        normalized.append(op)
    return normalized


def _normalize_daw_output_format(value: Any) -> Literal["mp3", "wav", "m4a"]:
    normalized = str(value or "mp3").strip().lower()
    if normalized in {"mp3", "wav", "m4a"}:
        return normalized  # type: ignore[return-value]
    return "mp3"


def _fallback_plan_for_asset(message: str, asset: AudioAsset, duration: float, current_time: float, output_format: str) -> dict[str, Any] | None:
    lowered = message.lower()
    operations: list[dict[str, Any]] = []
    start = 0.0
    end: float | None = None

    if "playhead" in lowered or "aktuelle" in lowered or "current" in lowered:
        start = max(0.0, float(current_time or 0))

    short_match = re.search(r"(\d+(?:[,.]\d+)?)\s*(?:sek|sekunden|s|seconds?)", message, re.I)
    if "short" in lowered or "tiktok" in lowered or "clip" in lowered:
        length = float(short_match.group(1).replace(",", ".")) if short_match else 30.0
        end = min(duration or start + length, start + max(1.0, length))

    explicit_range = re.search(r"(?:von|from|ab)\s+([^,;]+?)\s+(?:bis|to|-)\s+([^,;]+)", message, re.I)
    if explicit_range:
        parsed_start = _time_to_seconds(explicit_range.group(1))
        parsed_end = _time_to_seconds(explicit_range.group(2))
        if parsed_start is not None:
            start = parsed_start
        if parsed_end is not None:
            end = parsed_end

    cut_match = re.search(r"(?:bei|bis|auf|to|at)\s+([^,.;]+)", message, re.I)
    if cut_match and ("schneide" in lowered or "trim" in lowered or "cut" in lowered or "kürz" in lowered or "kuerz" in lowered):
        parsed_end = _time_to_seconds(cut_match.group(1))
        if parsed_end is not None:
            end = parsed_end

    remove_intro_match = re.search(r"(?:anfang|intro|start).*?(?:weg|entfern|remove|cut).*?(\d+(?:[,.]\d+)?)\s*(?:sek|sekunden|s|seconds?)", message, re.I)
    if remove_intro_match:
        start = float(remove_intro_match.group(1).replace(",", "."))
        end = duration or end

    if end is not None and end > start:
        operations.append({"type": "trim", "start": start, "end": end})

    fade_match = re.search(r"(\d+(?:[,.]\d+)?)\s*(?:sek|sekunden|s|seconds?)?\s*fade\s*-?\s*out", message, re.I)
    if not fade_match:
        fade_match = re.search(r"fade\s*-?\s*out.*?(\d+(?:[,.]\d+)?)\s*(?:sek|sekunden|s|seconds?)", message, re.I)
    if fade_match or "fade out" in lowered or "fade-out" in lowered:
        fade_duration = float(fade_match.group(1).replace(",", ".")) if fade_match else 2.0
        operations.append({"type": "fade_out", "duration": max(0.05, min(30.0, fade_duration))})

    fade_in_match = re.search(r"(\d+(?:[,.]\d+)?)\s*(?:sek|sekunden|s|seconds?)?\s*fade\s*-?\s*in", message, re.I)
    if fade_in_match or "fade in" in lowered or "fade-in" in lowered:
        fade_duration = float(fade_in_match.group(1).replace(",", ".")) if fade_in_match else 1.0
        operations.append({"type": "fade_in", "duration": max(0.05, min(30.0, fade_duration))})

    gain_match = re.search(r"([+-]?\d+(?:[,.]\d+)?)\s*dB", message, re.I)
    if gain_match or "lauter" in lowered or "leiser" in lowered:
        gain = float(gain_match.group(1).replace(",", ".")) if gain_match else (2.0 if "lauter" in lowered else -2.0)
        operations.append({"type": "gain", "gain_db": max(-12.0, min(12.0, gain))})

    if "youtube" in lowered or "normalis" in lowered or "master" in lowered:
        operations.append({"type": "normalize", "target_lufs": -14})
    if "klar" in lowered or "clear" in lowered:
        operations.append({"type": "preset", "preset": "klarer"})
    if "druck" in lowered or "punch" in lowered or "club" in lowered:
        operations.append({"type": "preset", "preset": "mehr_druck"})
    if "bass" in lowered:
        operations.append({"type": "preset", "preset": "bass"})

    normalized = _normalize_ai_operations(operations, duration)
    if not normalized:
        return None

    title = asset.display_title or asset.title or f"Audio {asset.id}"
    return {
        "source_audio_id": asset.id,
        "operations": normalized,
        "version_label": f"DAW Chat Edit {title}"[:80],
        "output_format": _normalize_daw_output_format(output_format),
        "create_notification": True,
    }


async def _resolve_daw_command_with_ai(db: Session, message: str) -> dict[str, Any] | None:
    try:
        from app.routers.admin import get_ai_admin_settings
    except Exception:
        return None

    settings = get_settings()
    admin_settings = get_ai_admin_settings(db)
    provider = admin_settings.get("default_provider") or settings.ai_default_provider
    model = admin_settings.get("default_model") or settings.ai_default_model
    assets = _candidate_audio_assets(db, limit=80)
    if not assets:
        return None

    asset_payload = []
    for asset in assets:
        title = asset.display_title or asset.title or asset.filename or f"Audio {asset.id}"
        asset_payload.append({
            "id": asset.id,
            "title": title,
            "version_label": asset.version_label,
            "operation_label": asset.operation_label,
            "duration_seconds": asset.duration_seconds,
            "filename": asset.filename,
            "updated_at": asset.updated_at.isoformat() if asset.updated_at else None,
        })

    instruction_payload = {
        "task": "resolve_audio_edit_command",
        "user_message": message,
        "available_audio_assets": asset_payload,
        "allowed_operations": [
            {"type": "trim", "fields": ["start", "end"], "meaning": "Bereich behalten oder Song bis Zeitpunkt kürzen"},
            {"type": "fade_in", "fields": ["duration"]},
            {"type": "fade_out", "fields": ["duration"]},
            {"type": "gain", "fields": ["gain_db"]},
            {"type": "normalize", "fields": ["target_lufs"]},
            {"type": "preset", "fields": ["preset"], "allowed_presets": ["youtube", "klarer", "mehr_druck", "bass", "hoehen"]},
        ],
        "rules": [
            "Wähle genau ein AudioAsset aus der Liste, wenn möglich.",
            "Gib Zeitangaben immer als Sekunden aus.",
            "Für YouTube-Master nutze normalize target_lufs -14 und optional preset youtube.",
            "Für Shorts/Hook-Ausschnitt nutze trim mit start und end, wenn beide erkennbar sind; wenn nur Ende genannt ist, start 0.",
            "Führe niemals destructive edits aus; es wird immer eine neue Version erzeugt.",
            "Wenn der Befehl nicht eindeutig ist, setze needs_confirmation true und operations leer.",
        ],
        "expected_output": {
            "is_audio_command": True,
            "needs_confirmation": True,
            "asset_id": "ID aus available_audio_assets oder null",
            "title_query": "erkannter Songtitel",
            "version": "erkannte Variante oder null",
            "operations": [],
            "version_label": "kurzes Label für die neue Version",
            "message": "kurze deutsche Erklärung",
        },
    }
    system_prompt = (
        "Du bist ein sicherer Audio-Command-Planner für eine Mini-DAW. "
        "Du erzeugst ausschließlich ein valides JSON-Objekt. Keine Shell-Befehle, kein Fließtext außerhalb JSON. "
        "Du darfst nur erlaubte Operationen verwenden und musst unsichere Befehle als needs_confirmation markieren."
    )
    try:
        result = await AiChatService().run_json_task(
            provider=provider,
            model=model,
            system_prompt=system_prompt,
            instruction_payload=instruction_payload,
            profile_options={"max_output_tokens": 1400, "temperature": 0.1},
        )
    except AiProviderError:
        return None
    except Exception:
        return None

    data = result.data if isinstance(result.data, dict) else {}
    if not data.get("is_audio_command", True):
        return {"is_audio_command": False}
    asset = _find_audio_by_id_or_title(db, int(data.get("asset_id") or 0) or None, str(data.get("title_query") or ""), data.get("version"))
    if not asset:
        return None
    duration = float(asset.duration_seconds or 0)
    operations = _normalize_ai_operations(data.get("operations"), duration)
    if not operations:
        return {
            "is_audio_command": True,
            "needs_confirmation": True,
            "asset": AudioAssetRead.model_validate(asset),
            "message": data.get("message") or f"Song gefunden: {asset.display_title or asset.title or asset.id}. Ich brauche noch eine eindeutigere Bearbeitungsanweisung.",
            "source": "ai_planner",
        }
    version_label = str(data.get("version_label") or "KI DAW Edit").strip()[:80] or "KI DAW Edit"
    plan = {
        "source_audio_id": asset.id,
        "operations": operations,
        "version_label": version_label,
        "output_format": "mp3",
        "create_notification": True,
    }
    return {
        "is_audio_command": True,
        "needs_confirmation": True,
        "asset": AudioAssetRead.model_validate(asset),
        "plan": plan,
        "message": data.get("message") or f"Gefunden: {asset.display_title or asset.title or asset.id}. KI-Bearbeitungsplan vorbereitet: {version_label}.",
        "source": "ai_planner",
    }

def _preset_filters(preset: str | None) -> list[str]:
    key = str(preset or "").strip().lower()
    if key in {"youtube", "youtube_master", "youtube-master", "youtube master"}:
        return ["highpass=f=30", "loudnorm=I=-14:TP=-1.5:LRA=11"]
    if key in {"klarer", "clear", "clarity"}:
        return ["highpass=f=45", "equalizer=f=350:t=q:w=1:g=-2", "equalizer=f=3500:t=q:w=1:g=2"]
    if key in {"mehr_druck", "druck", "punch", "club"}:
        return ["equalizer=f=90:t=q:w=1:g=2", "acompressor=threshold=-18dB:ratio=2:attack=12:release=120", "loudnorm=I=-12:TP=-1.2:LRA=9"]
    if key in {"bass", "mehr_bass"}:
        return ["equalizer=f=80:t=q:w=1:g=3"]
    if key in {"hoehen", "mehr_hoehen", "h\u00f6hen", "mehr_h\u00f6hen"}:
        return ["equalizer=f=6500:t=q:w=1:g=2"]
    return []


def _build_ffmpeg_args(source: Path, target: Path, operations: list[DawOperation], output_format: str) -> list[str]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise HTTPException(status_code=500, detail="ffmpeg ist auf dem Server nicht verfügbar.")
    duration = _duration_seconds(source)
    start = 0.0
    end = duration if duration > 0 else None
    filters: list[str] = []

    for op in operations:
        op_type = str(op.type or "").lower()
        if op_type in {"trim", "keep", "cut"}:
            if op.start is not None:
                start = max(0.0, float(op.start))
            if op.end is not None:
                end = max(start + 0.1, float(op.end))
        elif op_type in {"trim_end", "cut_at", "end_at"}:
            if op.end is not None:
                end = max(start + 0.1, float(op.end))
        elif op_type in {"fade_in", "fadein"}:
            dur = max(0.05, float(op.duration or 1.0))
            filters.append(f"afade=t=in:st=0:d={dur:.3f}")
        elif op_type in {"fade_out", "fadeout"}:
            dur = max(0.05, float(op.duration or 2.0))
            fade_start = max(0.0, (end if end is not None else duration) - dur)
            filters.append(f"afade=t=out:st={fade_start:.3f}:d={dur:.3f}")
        elif op_type in {"gain", "volume"}:
            gain = float(op.gain_db or 0.0)
            filters.append(f"volume={gain:.3f}dB")
        elif op_type in {"normalize", "lufs", "youtube_lufs"}:
            target_lufs = float(op.target_lufs or -14.0)
            filters.append(f"loudnorm=I={target_lufs:.1f}:TP=-1.5:LRA=11")
        elif op_type in {"preset", "enhance"}:
            filters.extend(_preset_filters(op.preset))

    args = [ffmpeg, "-y"]
    if start > 0:
        args += ["-ss", f"{start:.3f}"]
    args += ["-i", str(source)]
    if end is not None and end > start:
        args += ["-t", f"{max(0.1, end - start):.3f}"]
    if filters:
        args += ["-af", ",".join(filters)]
    if output_format == "wav":
        args += ["-c:a", "pcm_s16le"]
    elif output_format == "m4a":
        args += ["-c:a", "aac", "-b:a", "192k"]
    else:
        args += ["-c:a", "libmp3lame", "-b:a", "192k"]
    args.append(str(target))
    return args


def _make_notification(db: Session, title: str, message: str, asset: AudioAsset | None = None) -> None:
    notification = StatusNotification(
        event_type="daw_render",
        title=title,
        message=message,
        severity="success",
        status="unread",
        content_type="audio_asset" if asset else "daw",
        content_id=asset.id if asset else None,
        target_tab="daw",
        target_payload={"audio_asset_id": asset.id} if asset else None,
    )
    db.add(notification)


def _render_plan(db: Session, payload: DawRenderRequest) -> AudioAsset:
    source = _asset_or_404(db, payload.source_audio_id)
    source_path = _resolve_audio_path(source)
    settings = get_settings()
    settings.audio_storage_path.mkdir(parents=True, exist_ok=True)
    output_format = payload.output_format or "mp3"
    extension = f".{output_format}"
    base_title = source.display_title or source.title or f"Audio {source.id}"
    edited_title = _edited_display_title(base_title)
    version_label = payload.version_label or payload.title_suffix or "Editiert"
    temp_name = _sanitize_filename(f"daw_{source.id}_{version_label}")
    target_path = settings.audio_storage_path / f"{temp_name}_{abs(hash(json.dumps([op.model_dump() for op in payload.operations], sort_keys=True))) % 100000000}{extension}"
    args = _build_ffmpeg_args(source_path, target_path, payload.operations, output_format)
    try:
        subprocess.run(args, text=True, capture_output=True, check=True, timeout=600)
    except subprocess.CalledProcessError as exc:
        raise HTTPException(status_code=500, detail=f"DAW-Render fehlgeschlagen: {exc.stderr[-1200:] if exc.stderr else exc}") from exc

    if not target_path.exists() or target_path.stat().st_size <= 0:
        raise HTTPException(status_code=500, detail="DAW-Render hat keine Ausgabedatei erzeugt.")

    duration = read_audio_duration_seconds(target_path)
    new_asset = AudioAsset(
        task_local_id=source.task_local_id,
        song_id=source.song_id,
        suno_task_id=source.suno_task_id,
        audio_id=f"daw-{source.id}-{target_path.stem[-8:]}",
        title=edited_title,
        display_title=edited_title,
        image_url=source.image_url,
        source_url=f"{settings.suno_audio_public_route.rstrip('/')}/{target_path.name}",
        local_path=to_portable_path(target_path, storage_root=settings.audio_storage_path),
        public_url=f"{settings.suno_audio_public_route.rstrip('/')}/{target_path.name}",
        filename=target_path.name,
        content_type=normalize_audio_content_type(None, target_path),
        file_size_bytes=target_path.stat().st_size,
        duration_seconds=duration,
        status="cached",
        operation_label="Editiert",
        parent_audio_id=str(source.id),
        parent_task_id=source.suno_task_id,
        version_label=version_label,
        metadata_json={
            "operation": "DAW Edit",
            "is_edited_version": True,
            "original_display_title": base_title,
            "daw_edit_plan": payload.model_dump(),
            "source_audio_asset_id": source.id,
            "source_filename": source.filename,
        },
    )
    db.add(new_asset)
    db.commit()
    db.refresh(new_asset)
    try:
        waveform = get_or_create_waveform(new_asset, target_path, db, points=180, rebuild=True)
        new_asset.waveform_json = waveform.model_dump() if hasattr(waveform, "model_dump") else dict(waveform)
        db.add(new_asset)
    except Exception:
        pass
    if payload.create_notification:
        _make_notification(db, "DAW-Version erstellt", f"{base_title} wurde als neue Version „{version_label}“ gespeichert.", new_asset)
    db.commit()
    db.refresh(new_asset)
    return new_asset




def _track_defaults() -> list[dict[str, Any]]:
    return [
        {"id": "track-1", "name": "Spur 1", "muted": False, "solo": False, "volume_db": 0},
        {"id": "track-2", "name": "Spur 2", "muted": False, "solo": False, "volume_db": 0},
        {"id": "track-3", "name": "Spur 3", "muted": False, "solo": False, "volume_db": 0},
    ]


def _clip_duration(clip: dict[str, Any]) -> float:
    return max(0.0, float(clip.get("source_end") or 0) - float(clip.get("source_start") or 0))


def _default_arrangement(asset: AudioAsset, duration: float | None = None) -> dict[str, Any]:
    safe_duration = float(duration or asset.duration_seconds or 0 or 0)
    title = asset.display_title or asset.title or asset.filename or f"Audio {asset.id}"
    return {
        "version": 1,
        "source_audio_id": asset.id,
        "duration_seconds": safe_duration,
        "bpm": None,
        "time_signature": "4/4",
        "snap_enabled": False,
        "snap_unit": "beat",
        "tracks": _track_defaults(),
        "clips": [
            {
                "id": f"clip-{asset.id}-1",
                "track_id": "track-1",
                "source_audio_id": asset.id,
                "timeline_start": 0,
                "source_start": 0,
                "source_end": safe_duration,
                "gain_db": 0,
                "fade_in": 0,
                "fade_out": 0,
                "label": title,
                "muted": False,
                "locked": False,
                "color": "cyan",
            }
        ],
        "markers": [],
    }


def _sanitize_arrangement(asset: AudioAsset, payload: dict[str, Any] | DawArrangementState | None) -> dict[str, Any]:
    if isinstance(payload, DawArrangementState):
        raw = payload.model_dump()
    elif isinstance(payload, dict):
        raw = dict(payload)
    else:
        raw = {}
    fallback_duration = float(asset.duration_seconds or raw.get("duration_seconds") or 0 or 0)
    default = _default_arrangement(asset, fallback_duration)
    tracks_raw = raw.get("tracks") if isinstance(raw.get("tracks"), list) else default["tracks"]
    tracks: list[dict[str, Any]] = []
    seen_tracks: set[str] = set()
    # Bis zu 8 Spuren (kompatible Erweiterung; Default bleiben 3 Spuren).
    for index, item in enumerate(tracks_raw[:8]):
        if not isinstance(item, dict):
            continue
        track_id = str(item.get("id") or f"track-{index + 1}")[:40]
        if track_id in seen_tracks:
            track_id = f"track-{index + 1}"
        seen_tracks.add(track_id)
        tracks.append({
            "id": track_id,
            "name": str(item.get("name") or f"Spur {index + 1}")[:120],
            "muted": bool(item.get("muted", False)),
            "solo": bool(item.get("solo", False)),
            "volume_db": max(-24.0, min(24.0, _safe_float(item.get("volume_db"), 0.0) or 0.0)),
        })
    if not tracks:
        tracks = default["tracks"]
    valid_track_ids = {track["id"] for track in tracks}

    duration = max(0.0, _safe_float(raw.get("duration_seconds"), fallback_duration) or fallback_duration)
    clips: list[dict[str, Any]] = []
    for index, item in enumerate((raw.get("clips") if isinstance(raw.get("clips"), list) else default["clips"])[:120]):
        if not isinstance(item, dict):
            continue
        source_audio_id = int(item.get("source_audio_id") or asset.id)
        source_start = max(0.0, _safe_float(item.get("source_start"), 0.0) or 0.0)
        source_end = _safe_float(item.get("source_end"), duration)
        if source_end is None or source_end <= source_start:
            source_end = source_start + 0.1
        source_end = min(max(source_end, source_start + 0.1), 60 * 60 * 4)
        track_id = str(item.get("track_id") or "track-1")[:40]
        if track_id not in valid_track_ids:
            track_id = tracks[0]["id"]
        clip = {
            "id": str(item.get("id") or f"clip-{asset.id}-{index + 1}")[:80],
            "track_id": track_id,
            "source_audio_id": source_audio_id,
            "timeline_start": max(0.0, _safe_float(item.get("timeline_start"), 0.0) or 0.0),
            "source_start": source_start,
            "source_end": source_end,
            "gain_db": max(-24.0, min(24.0, _safe_float(item.get("gain_db"), 0.0) or 0.0)),
            "fade_in": max(0.0, min(60.0, _safe_float(item.get("fade_in"), 0.0) or 0.0)),
            "fade_out": max(0.0, min(60.0, _safe_float(item.get("fade_out"), 0.0) or 0.0)),
            "label": str(item.get("label") or asset.display_title or asset.title or f"Clip {index + 1}")[:140],
            "muted": bool(item.get("muted", False)),
            "locked": bool(item.get("locked", False)),
            "color": str(item.get("color") or "cyan")[:40],
        }
        duration = max(duration, clip["timeline_start"] + _clip_duration(clip))
        clips.append(clip)
    if not clips:
        clips = default["clips"]

    markers: list[dict[str, Any]] = []
    raw_markers = raw.get("markers") if isinstance(raw.get("markers"), list) else []
    legacy_metadata = asset.metadata_json if isinstance(asset.metadata_json, dict) else {}
    if not raw_markers and isinstance(legacy_metadata.get("daw_markers"), list):
        raw_markers = legacy_metadata.get("daw_markers")
    for index, item in enumerate(raw_markers[:200]):
        if not isinstance(item, dict):
            continue
        markers.append({
            "id": str(item.get("id") or f"marker-{index + 1}")[:80],
            "label": str(item.get("label") or "Marker")[:120],
            "time": max(0.0, _safe_float(item.get("time"), 0.0) or 0.0),
            "type": str(item.get("type") or "marker")[:80],
            "note": item.get("note") if item.get("note") is None else str(item.get("note"))[:500],
        })
    markers = sorted(markers, key=lambda item: float(item.get("time") or 0))

    bpm_value = _safe_float(raw.get("bpm"), None)
    if bpm_value is not None:
        bpm_value = max(20.0, min(300.0, bpm_value))
    snap_unit = str(raw.get("snap_unit") or "beat")
    if snap_unit not in {"bar", "beat", "half", "quarter"}:
        snap_unit = "beat"
    return {
        "version": 1,
        "source_audio_id": asset.id,
        "duration_seconds": duration,
        "bpm": bpm_value,
        "time_signature": str(raw.get("time_signature") or "4/4")[:12],
        "snap_enabled": bool(raw.get("snap_enabled", False)),
        "snap_unit": snap_unit,
        "tracks": tracks,
        "clips": sorted(clips, key=lambda item: (str(item.get("track_id")), float(item.get("timeline_start") or 0))),
        "markers": markers,
    }


def _get_saved_arrangement(asset: AudioAsset) -> dict[str, Any]:
    metadata = asset.metadata_json if isinstance(asset.metadata_json, dict) else {}
    return _sanitize_arrangement(asset, metadata.get("daw_arrangement"))


def _session_title(asset: AudioAsset, value: str | None = None) -> str:
    title = re.sub(r"\s+", " ", str(value or "").strip())
    if title:
        return title[:180]
    base = asset.display_title or asset.title or asset.filename or f"Audio {asset.id}"
    return f"DAW Session - {base}"[:180]


def _latest_daw_arrangement_session(db: Session, asset_id: int) -> DawArrangementSession | None:
    return (
        db.query(DawArrangementSession)
        .filter(
            DawArrangementSession.audio_asset_id == int(asset_id),
            DawArrangementSession.is_deleted.is_(False),
            DawArrangementSession.is_active.is_(True),
        )
        .order_by(DawArrangementSession.updated_at.desc(), DawArrangementSession.id.desc())
        .first()
    )


def _has_any_daw_arrangement_session(db: Session, asset_id: int) -> bool:
    return (
        db.query(DawArrangementSession.id)
        .filter(DawArrangementSession.audio_asset_id == int(asset_id))
        .first()
        is not None
    )


def _daw_arrangement_session_or_404(db: Session, asset_id: int, session_id: int) -> DawArrangementSession:
    session = (
        db.query(DawArrangementSession)
        .filter(
            DawArrangementSession.id == int(session_id),
            DawArrangementSession.audio_asset_id == int(asset_id),
            DawArrangementSession.is_deleted.is_(False),
        )
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="DAW-Session wurde nicht gefunden.")
    return session


def _serialize_daw_session(session: DawArrangementSession, include_arrangement: bool = False) -> dict[str, Any]:
    arrangement = session.arrangement_json if isinstance(session.arrangement_json, dict) else {}
    payload = {
        "id": session.id,
        "audio_asset_id": session.audio_asset_id,
        "title": session.title,
        "is_active": session.is_active,
        "is_auto_saved": session.is_auto_saved,
        "duration_seconds": arrangement.get("duration_seconds"),
        "clips_count": len(arrangement.get("clips") or []),
        "markers_count": len(arrangement.get("markers") or []),
        "created_at": session.created_at,
        "updated_at": session.updated_at,
    }
    if include_arrangement:
        payload["arrangement"] = arrangement
    return payload


def _get_saved_arrangement_session(db: Session, asset: AudioAsset, session_id: int | None = None) -> tuple[dict[str, Any], DawArrangementSession | None]:
    session = _daw_arrangement_session_or_404(db, asset.id, session_id) if session_id else _latest_daw_arrangement_session(db, asset.id)
    if session:
        return _sanitize_arrangement(asset, session.arrangement_json), session
    if _has_any_daw_arrangement_session(db, asset.id):
        return _sanitize_arrangement(asset, None), None
    return _get_saved_arrangement(asset), None


def _save_arrangement_to_asset(db: Session, asset: AudioAsset, arrangement: dict[str, Any]) -> dict[str, Any]:
    sanitized = _sanitize_arrangement(asset, arrangement)
    metadata = dict(asset.metadata_json or {}) if isinstance(asset.metadata_json, dict) else {}
    metadata["daw_arrangement"] = sanitized
    metadata["daw_markers"] = sanitized.get("markers") or []
    asset.metadata_json = metadata
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return sanitized


def _save_arrangement_session(
    db: Session,
    asset: AudioAsset,
    arrangement: dict[str, Any],
    session_id: int | None = None,
    title: str | None = None,
    create_new_session: bool = False,
) -> tuple[dict[str, Any], DawArrangementSession]:
    sanitized = _save_arrangement_to_asset(db, asset, arrangement)
    session = None if create_new_session else (_daw_arrangement_session_or_404(db, asset.id, session_id) if session_id else _latest_daw_arrangement_session(db, asset.id))
    if not session:
        session = DawArrangementSession(
            audio_asset_id=asset.id,
            title=_session_title(asset, title),
            arrangement_json=sanitized,
            is_active=True,
            is_auto_saved=True,
            metadata_json={"source": "mini_daw"},
        )
        db.add(session)
    else:
        if title:
            session.title = _session_title(asset, title)
        session.arrangement_json = sanitized
        session.is_auto_saved = True
    db.commit()
    db.refresh(session)
    return sanitized, session


def _arrangement_source_assets(db: Session, asset: AudioAsset, arrangement: dict[str, Any]) -> dict[int, AudioAsset]:
    ids = {int(asset.id)}
    for clip in arrangement.get("clips") or []:
        try:
            ids.add(int(clip.get("source_audio_id") or asset.id))
        except Exception:
            ids.add(int(asset.id))
    rows = db.query(AudioAsset).filter(AudioAsset.id.in_(list(ids)), AudioAsset.is_deleted.is_(False)).all()
    assets = {row.id: row for row in rows}
    if asset.id not in assets:
        assets[asset.id] = asset
    missing = [source_id for source_id in ids if source_id not in assets]
    if missing:
        raise HTTPException(status_code=404, detail=f"Quell-Audio für Clip nicht gefunden: {missing[0]}")
    return assets


def _build_arrangement_ffmpeg_args(db: Session, source_asset: AudioAsset, arrangement: dict[str, Any], target: Path, output_format: str) -> list[str]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise HTTPException(status_code=500, detail="ffmpeg ist auf dem Server nicht verfügbar.")
    arrangement = _sanitize_arrangement(source_asset, arrangement)
    source_assets = _arrangement_source_assets(db, source_asset, arrangement)
    paths_by_id = {asset_id: _resolve_audio_path(row) for asset_id, row in source_assets.items()}
    source_duration_by_id = {asset_id: max(0.0, _duration_seconds(path)) for asset_id, path in paths_by_id.items()}
    source_ids = sorted(paths_by_id.keys())
    input_index = {asset_id: index for index, asset_id in enumerate(source_ids)}
    args = [ffmpeg, "-y"]
    for asset_id in source_ids:
        args += ["-i", str(paths_by_id[asset_id])]

    clips = [clip for clip in arrangement.get("clips") or [] if not clip.get("muted")]
    if not clips:
        raise HTTPException(status_code=400, detail="Arrangement enthält keine aktiven Clips.")
    filters: list[str] = []
    labels: list[str] = []
    active_index = 0
    for clip in sorted(clips, key=lambda item: float(item.get("timeline_start") or 0)):
        requested_duration = _clip_duration(clip)
        asset_id = int(clip.get("source_audio_id") or source_asset.id)
        idx = input_index[asset_id]
        source_limit = source_duration_by_id.get(asset_id, 0.0)
        label = f"c{active_index}"
        source_start = max(0.0, float(clip.get("source_start") or 0))
        if source_limit > 0:
            source_start = min(source_start, max(0.0, source_limit - 0.05))
        raw_source_end = float(clip.get("source_end") or (source_start + requested_duration))
        source_end = max(source_start + 0.05, raw_source_end)
        if source_limit > 0:
            source_end = min(source_end, source_limit)
        duration = max(0.0, source_end - source_start)
        if duration <= 0.05:
            continue
        timeline_start = max(0.0, float(clip.get("timeline_start") or 0))
        fade_in = min(max(0.0, float(clip.get("fade_in") or 0)), duration)
        fade_out = min(max(0.0, float(clip.get("fade_out") or 0)), duration)
        if fade_in + fade_out > max(0.0, duration - 0.05):
            ratio = max(0.0, duration - 0.05) / max(0.001, fade_in + fade_out)
            fade_in *= ratio
            fade_out *= ratio
        gain_db = max(-24.0, min(24.0, float(clip.get("gain_db") or 0)))
        chain = f"[{idx}:a]atrim=start={source_start:.3f}:end={source_end:.3f},asetpts=PTS-STARTPTS"
        if fade_in > 0:
            chain += f",afade=t=in:st=0:d={fade_in:.3f}"
        if fade_out > 0:
            chain += f",afade=t=out:st={max(0.0, duration - fade_out):.3f}:d={fade_out:.3f}"
        if abs(gain_db) > 0.01:
            chain += f",volume={gain_db:.3f}dB"
        delay_ms = max(0, int(round(timeline_start * 1000)))
        if delay_ms:
            chain += f",adelay={delay_ms}:all=1"
        chain += f"[{label}]"
        filters.append(chain)
        labels.append(f"[{label}]")
        active_index += 1
    if not labels:
        raise HTTPException(status_code=400, detail="Arrangement enthält keine renderbaren Clips.")
    if len(labels) == 1:
        filters.append(f"{labels[0]}anull[aout]")
    else:
        filters.append(f"{''.join(labels)}amix=inputs={len(labels)}:duration=longest:dropout_transition=0:normalize=0[aout]")
    args += ["-filter_complex", ";".join(filters), "-map", "[aout]"]
    if output_format == "wav":
        args += ["-c:a", "pcm_s16le"]
    elif output_format == "m4a":
        args += ["-c:a", "aac", "-b:a", "192k"]
    else:
        args += ["-c:a", "libmp3lame", "-b:a", "192k"]
    args.append(str(target))
    return args


def _latest_completed_transcript(db: Session, audio_asset_id: int) -> AudioTranscript | None:
    return (
        db.query(AudioTranscript)
        .filter(AudioTranscript.audio_asset_id == int(audio_asset_id), AudioTranscript.status == "completed")
        .order_by(AudioTranscript.generated_at.desc().nullslast(), AudioTranscript.updated_at.desc(), AudioTranscript.id.desc())
        .first()
    )


def _project_timed_items_for_arrangement(
    items_by_asset_id: dict[int, list[dict[str, Any]]],
    arrangement: dict[str, Any],
    *,
    min_duration: float = 0.05,
) -> list[dict[str, Any]]:
    projected: list[dict[str, Any]] = []
    for clip in sorted(arrangement.get("clips") or [], key=lambda item: float(item.get("timeline_start") or 0)):
        if clip.get("muted"):
            continue
        try:
            asset_id = int(clip.get("source_audio_id") or arrangement.get("source_audio_id") or 0)
        except Exception:
            asset_id = int(arrangement.get("source_audio_id") or 0)
        source_items = items_by_asset_id.get(asset_id) or []
        if not source_items:
            continue
        clip_timeline_start = max(0.0, _safe_float(clip.get("timeline_start"), 0.0) or 0.0)
        clip_source_start = max(0.0, _safe_float(clip.get("source_start"), 0.0) or 0.0)
        clip_source_end = max(clip_source_start, _safe_float(clip.get("source_end"), clip_source_start) or clip_source_start)
        for index, item in enumerate(source_items):
            if not isinstance(item, dict):
                continue
            item_start = _safe_float(item.get("start", item.get("start_seconds")), None)
            item_end = _safe_float(item.get("end", item.get("end_seconds")), None)
            if item_start is None or item_end is None or item_end <= item_start:
                continue
            overlap_start = max(item_start, clip_source_start)
            overlap_end = min(item_end, clip_source_end)
            if overlap_end - overlap_start < min_duration:
                continue
            next_item = dict(item)
            next_start = clip_timeline_start + (overlap_start - clip_source_start)
            next_end = clip_timeline_start + (overlap_end - clip_source_start)
            next_item["start"] = round(next_start, 3)
            next_item["end"] = round(next_end, 3)
            if "start_seconds" in next_item:
                next_item["start_seconds"] = round(next_start, 3)
            if "end_seconds" in next_item:
                next_item["end_seconds"] = round(next_end, 3)
            next_item["source_audio_asset_id"] = asset_id
            next_item["source_start"] = round(overlap_start, 3)
            next_item["source_end"] = round(overlap_end, 3)
            raw_id = str(item.get("id") or item.get("word") or item.get("text") or index)
            next_item["id"] = f"{raw_id}-daw-{len(projected) + 1}"
            projected.append(next_item)
    projected.sort(key=lambda item: (_safe_float(item.get("start"), 0.0) or 0.0, _safe_float(item.get("end"), 0.0) or 0.0))
    return projected


def _lyrics_from_projected_srt_segments(segments: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for segment in segments:
        text = str(segment.get("text") or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if not text:
            continue
        for line in text.split("\n"):
            cleaned = re.sub(r"\s+", " ", line).strip()
            if cleaned:
                lines.append(cleaned)
    return "\n".join(lines).strip()


def _write_daw_transcript_file(asset: AudioAsset, audio_asset_id: int, text: str, suffix: str = ".srt") -> Path:
    settings = get_settings()
    transcript_root = settings.transcript_storage_path.resolve()
    target_dir = (transcript_root / str(audio_asset_id)).resolve()
    try:
        target_dir.relative_to(transcript_root)
    except ValueError:
        raise HTTPException(status_code=500, detail="Ungültiger Transcript-Zielpfad.")
    target_dir.mkdir(parents=True, exist_ok=True)
    base_name = _sanitize_filename(asset.display_title or asset.title or asset.filename or f"audio-{audio_asset_id}") or f"audio-{audio_asset_id}"
    safe_suffix = suffix if str(suffix).startswith(".") else f".{suffix}"
    target_path = (target_dir / f"{base_name}{safe_suffix}").resolve()
    try:
        target_path.relative_to(transcript_root)
    except ValueError:
        raise HTTPException(status_code=500, detail="Ungültiger Transcript-Dateipfad.")
    target_path.write_text(text, encoding="utf-8")
    return target_path


def _project_arrangement_text_timelines(
    db: Session,
    source_asset: AudioAsset,
    new_asset: AudioAsset,
    arrangement: dict[str, Any],
    duration: float | int | None,
) -> dict[str, Any]:
    source_assets = _arrangement_source_assets(db, source_asset, arrangement)
    transcripts_by_asset_id: dict[int, AudioTranscript] = {}
    srt_segments_by_asset_id: dict[int, list[dict[str, Any]]] = {}
    words_by_asset_id: dict[int, list[dict[str, Any]]] = {}
    structure_by_asset_id: dict[int, list[dict[str, Any]]] = {}

    for asset_id, asset in source_assets.items():
        transcript = _latest_completed_transcript(db, asset_id)
        if transcript:
            transcripts_by_asset_id[asset_id] = transcript
            segments = transcript.segments_json if isinstance(transcript.segments_json, list) else []
            if not segments and transcript.srt_text:
                segments = parse_srt(transcript.srt_text)
            if segments:
                srt_segments_by_asset_id[asset_id] = segments
            if isinstance(transcript.words_json, list) and transcript.words_json:
                words_by_asset_id[asset_id] = transcript.words_json
        if isinstance(asset.structure_segments_json, list) and asset.structure_segments_json:
            structure_by_asset_id[asset_id] = asset.structure_segments_json

    projected_segments = renumber_segments(_project_timed_items_for_arrangement(srt_segments_by_asset_id, arrangement, min_duration=0.12))
    projected_words = _project_timed_items_for_arrangement(words_by_asset_id, arrangement, min_duration=0.005)
    projected_structure = _project_timed_items_for_arrangement(structure_by_asset_id, arrangement, min_duration=0.18)
    projected_lyrics = _lyrics_from_projected_srt_segments(projected_segments)

    if projected_segments:
        srt_text = export_srt(projected_segments)
        srt_path = _write_daw_transcript_file(new_asset, new_asset.id, srt_text, ".srt")
        half_srt_text = segments_to_half_srt(projected_segments, max_chars=22, min_dur=0.6)
        if half_srt_text.strip():
            _write_daw_transcript_file(new_asset, new_asset.id, half_srt_text, ".half.srt")
        source_transcript = transcripts_by_asset_id.get(source_asset.id) or next(iter(transcripts_by_asset_id.values()), None)
        transcript = AudioTranscript(
            audio_asset_id=new_asset.id,
            backend=f"{source_transcript.backend if source_transcript else 'daw'}+timeline_projection",
            language=source_transcript.language if source_transcript else None,
            mode="daw_timeline_projection",
            match_mode=source_transcript.match_mode if source_transcript else "clip_projection",
            srt_text=srt_text,
            srt_path=str(srt_path),
            segments_json=projected_segments,
            words_json=projected_words,
            status="completed",
            error_message=None,
            generated_at=utc_now_naive(),
        )
        db.add(transcript)

    if projected_structure:
        new_asset.structure_segments_json = projected_structure

    metadata = dict(new_asset.metadata_json or {}) if isinstance(new_asset.metadata_json, dict) else {}
    candidate = dict(metadata.get("candidate") or {}) if isinstance(metadata.get("candidate"), dict) else {}
    request_payload = dict(metadata.get("request_payload") or {}) if isinstance(metadata.get("request_payload"), dict) else {}
    if projected_lyrics:
        if candidate.get("prompt") and "original_prompt_before_daw_projection" not in metadata:
            metadata["original_prompt_before_daw_projection"] = candidate.get("prompt")
        if request_payload.get("prompt") and "original_request_prompt_before_daw_projection" not in metadata:
            metadata["original_request_prompt_before_daw_projection"] = request_payload.get("prompt")
        candidate["prompt"] = projected_lyrics
        candidate["lyrics"] = projected_lyrics
        candidate["text"] = projected_lyrics
        request_payload["prompt"] = projected_lyrics
        request_payload["lyrics"] = projected_lyrics
    metadata["candidate"] = candidate
    metadata["request_payload"] = request_payload
    metadata["daw_timeline_projection"] = {
        "source_audio_asset_id": source_asset.id,
        "duration_seconds": float(duration or 0),
        "srt_segments": len(projected_segments),
        "words": len(projected_words),
        "structure_segments": len(projected_structure),
        "lyrics_projected": bool(projected_lyrics),
    }
    if projected_segments:
        metadata["srt_projection_source"] = "daw_arrangement_clips"
    new_asset.metadata_json = metadata
    db.add(new_asset)
    return metadata["daw_timeline_projection"]


def _render_arrangement(db: Session, source_asset: AudioAsset, arrangement: dict[str, Any], output_format: str, version_label: str | None, create_notification: bool = True, task_local_id: int | None = None) -> AudioAsset:
    settings = get_settings()
    settings.audio_storage_path.mkdir(parents=True, exist_ok=True)
    output_format = _normalize_daw_output_format(output_format)
    base_title = source_asset.display_title or source_asset.title or f"Audio {source_asset.id}"
    edited_title = _edited_display_title(base_title)
    label = (version_label or "Editiert").strip()[:80] or "Editiert"
    now = utc_now_naive()
    temp_name = _sanitize_filename(f"arrangement_{source_asset.id}_{label}")
    hash_source = json.dumps(arrangement, sort_keys=True, ensure_ascii=False)
    target_path = settings.audio_storage_path / f"{temp_name}_{abs(hash(hash_source)) % 100000000}.{output_format}"
    args = _build_arrangement_ffmpeg_args(db, source_asset, arrangement, target_path, output_format)
    try:
        subprocess.run(args, text=True, capture_output=True, check=True, timeout=900)
    except subprocess.CalledProcessError as exc:
        raise HTTPException(status_code=500, detail=f"DAW-Arrangement-Render fehlgeschlagen: {exc.stderr[-1200:] if exc.stderr else exc}") from exc
    if not target_path.exists() or target_path.stat().st_size <= 0:
        raise HTTPException(status_code=500, detail="DAW-Arrangement hat keine Ausgabedatei erzeugt.")
    duration = read_audio_duration_seconds(target_path)
    source_metadata = dict(source_asset.metadata_json or {}) if isinstance(source_asset.metadata_json, dict) else {}
    new_metadata = {
        **source_metadata,
        "operation": "DAW Arrangement",
        "operation_type": "daw_arrangement_render",
        "task_type": "daw_arrangement_render",
        "generation_source": "mini_daw",
        "is_edited_version": True,
        "source_created_at": now.isoformat(),
        "created_at": now.isoformat(),
        "original_display_title": base_title,
        "daw_arrangement": arrangement,
        "source_audio_asset_id": source_asset.id,
        "source_filename": source_asset.filename,
        "source_audio_asset": {
            "id": source_asset.id,
            "audio_id": source_asset.audio_id,
            "song_id": source_asset.song_id,
            "suno_task_id": source_asset.suno_task_id,
            "title": source_asset.title,
            "display_title": source_asset.display_title,
            "version_label": source_asset.version_label,
        },
    }
    new_asset = AudioAsset(
        task_local_id=task_local_id or source_asset.task_local_id,
        song_id=source_asset.song_id,
        suno_task_id=source_asset.suno_task_id,
        audio_id=f"daw-arr-{source_asset.id}-{target_path.stem[-8:]}",
        title=edited_title,
        display_title=edited_title,
        image_url=source_asset.image_url,
        source_url=f"{settings.suno_audio_public_route.rstrip('/')}/{target_path.name}",
        local_path=to_portable_path(target_path, storage_root=settings.audio_storage_path),
        public_url=f"{settings.suno_audio_public_route.rstrip('/')}/{target_path.name}",
        filename=target_path.name,
        content_type=normalize_audio_content_type(None, target_path),
        file_size_bytes=target_path.stat().st_size,
        duration_seconds=duration,
        status="cached",
        operation_label="Editiert",
        parent_audio_id=str(source_asset.id),
        parent_task_id=source_asset.suno_task_id,
        version_label=label,
        metadata_json=new_metadata,
        project_id=source_asset.project_id,
        is_favorite=False,
        is_final=False,
        structure_segments_json=source_asset.structure_segments_json,
    )
    db.add(new_asset)
    db.commit()
    db.refresh(new_asset)
    try:
        projection = _project_arrangement_text_timelines(db, source_asset, new_asset, arrangement, duration)
        projected_metadata = dict(new_asset.metadata_json or {}) if isinstance(new_asset.metadata_json, dict) else {}
        projected_metadata["daw_timeline_projection"] = projection
        new_asset.metadata_json = projected_metadata
        db.add(new_asset)
        db.commit()
        db.refresh(new_asset)
    except Exception as exc:
        projected_metadata = dict(new_asset.metadata_json or {}) if isinstance(new_asset.metadata_json, dict) else {}
        projected_metadata["daw_timeline_projection_error"] = str(exc)[:500]
        new_asset.metadata_json = projected_metadata
        db.add(new_asset)
        db.commit()
        db.refresh(new_asset)
    try:
        waveform = get_or_create_waveform(new_asset, target_path, db, points=180, rebuild=True)
        new_asset.waveform_json = waveform.model_dump() if hasattr(waveform, "model_dump") else dict(waveform)
        db.add(new_asset)
    except Exception:
        pass
    if create_notification:
        _make_notification(db, "DAW-Arrangement erstellt", f"{base_title} wurde als neue Arrangement-Version „{label}“ gespeichert.", new_asset)
    db.commit()
    db.refresh(new_asset)
    return new_asset




def _create_daw_arrangement_render_task(db: Session, asset: AudioAsset, arrangement: dict[str, Any], output_format: str, version_label: str | None) -> SunoTask:
    now = utc_now_naive()
    title = asset.display_title or asset.title or f"Audio {asset.id}"
    task = SunoTask(
        task_type="daw_arrangement_render",
        status="RUNNING",
        request_payload={
            "background": True,
            "local_task": True,
            "source": "mini_daw",
            "audio_asset_id": asset.id,
            "output_format": _normalize_daw_output_format(output_format),
            "version_label": version_label or "Editiert",
            "arrangement": arrangement,
        },
        response_payload={
            "background": True,
            "local_task": True,
            "status": "RUNNING",
            "progress": {"percent": 0, "phase": "queued", "updated_at": now.isoformat()},
        },
        progress=0,
        started_at=now,
        heartbeat_at=now,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    db.add(StatusNotification(
        event_type="daw_arrangement_render_started",
        title=f"DAW-Version wird gespeichert: {title}",
        message="Das Arrangement wird im Hintergrund gerendert. Der Status wird wie bei anderen lokalen Tasks live aktualisiert.",
        severity="info",
        status="unread",
        task_local_id=task.id,
        content_type="audio_asset",
        content_id=asset.id,
        target_tab="status",
        target_payload={"audio_asset_id": asset.id, "task_local_id": task.id, "task_type": task.task_type, "status": "RUNNING"},
    ))
    db.commit()
    db.refresh(task)
    return task


def _run_daw_arrangement_render_background(task_id: int, asset_id: int, arrangement_payload: dict[str, Any], output_format: str, version_label: str | None, create_notification: bool = True) -> None:
    db = SessionLocal()
    try:
        task = db.query(SunoTask).filter(SunoTask.id == int(task_id), SunoTask.is_deleted.is_(False)).first()
        asset = db.query(AudioAsset).filter(AudioAsset.id == int(asset_id), AudioAsset.is_deleted.is_(False)).first()
        if not task or not asset:
            return
        title = asset.display_title or asset.title or f"Audio {asset.id}"
        heartbeat_task(db, task, progress={"percent": 5, "phase": "prepare", "message": "Arrangement wird vorbereitet."})
        arrangement = _sanitize_arrangement(asset, arrangement_payload)
        _save_arrangement_to_asset(db, asset, arrangement)
        heartbeat_task(db, task.id, progress={"percent": 20, "phase": "render", "message": "Audio wird mit ffmpeg gerendert."})
        created = _render_arrangement(db, asset, arrangement, output_format, version_label or "Editiert", create_notification=False, task_local_id=task.id)
        heartbeat_task(db, task.id, progress={"percent": 92, "phase": "waveform", "message": "Version wird in die Library übernommen."})
        mark_task_finished(
            db,
            task.id,
            status="SUCCESS",
            message=f"DAW-Version gespeichert: {created.display_title or created.title}",
            result_payload={"audio_asset_id": created.id, "source_audio_asset_id": asset.id, "status": "SUCCESS"},
            response_payload={"audio_asset_id": created.id, "source_audio_asset_id": asset.id, "progress": {"percent": 100, "phase": "done"}},
            notify=False,
        )
        if create_notification:
            db.add(StatusNotification(
                event_type="daw_arrangement_render_completed",
                title=f"DAW-Version gespeichert: {created.display_title or created.title}",
                message=f"{title} wurde als neue editierte Version gespeichert.",
                severity="success",
                status="unread",
                task_local_id=task.id,
                content_type="audio_asset",
                content_id=created.id,
                target_tab="library",
                target_payload={"audio_asset_id": created.id, "source_audio_asset_id": asset.id, "task_local_id": task.id, "task_type": task.task_type, "status": "SUCCESS"},
                completed_at=utc_now_naive(),
            ))
            db.commit()
    except Exception as exc:
        try:
            mark_task_finished(
                db,
                task_id,
                status="FAILED",
                message=str(exc),
                result_payload={"audio_asset_id": asset_id, "status": "FAILED", "error": str(exc)},
                response_payload={"progress": {"percent": 100, "phase": "failed", "error": str(exc)}},
                notify=False,
            )
            db.add(StatusNotification(
                event_type="daw_arrangement_render_failed",
                title="DAW-Version konnte nicht gespeichert werden",
                message=str(exc),
                severity="error",
                status="unread",
                task_local_id=task_id,
                content_type="audio_asset",
                content_id=asset_id,
                target_tab="status",
                target_payload={"audio_asset_id": asset_id, "task_local_id": task_id, "task_type": "daw_arrangement_render", "status": "FAILED"},
                completed_at=utc_now_naive(),
            ))
            db.commit()
        except Exception:
            db.rollback()
    finally:
        db.close()


@router.get("/assets/{asset_id}/arrangement", response_model=dict)
def get_daw_arrangement(asset_id: int, session_id: int | None = None, db: Session = Depends(get_db)):
    asset = _asset_or_404(db, asset_id)
    arrangement, session = _get_saved_arrangement_session(db, asset, session_id)
    return {
        "asset": AudioAssetRead.model_validate(asset),
        "arrangement": arrangement,
        "session": _serialize_daw_session(session) if session else None,
    }


@router.put("/assets/{asset_id}/arrangement", response_model=dict)
def save_daw_arrangement(asset_id: int, payload: DawArrangementSaveRequest, db: Session = Depends(get_db)):
    asset = _asset_or_404(db, asset_id)
    arrangement, session = _save_arrangement_session(
        db,
        asset,
        payload.arrangement.model_dump(),
        session_id=payload.session_id,
        title=payload.title,
        create_new_session=payload.create_new_session,
    )
    return {
        "ok": True,
        "asset": AudioAssetRead.model_validate(asset),
        "arrangement": arrangement,
        "session": _serialize_daw_session(session),
    }


@router.get("/assets/{asset_id}/arrangement/sessions", response_model=dict)
def list_daw_arrangement_sessions(asset_id: int, db: Session = Depends(get_db)):
    _asset_or_404(db, asset_id)
    sessions = (
        db.query(DawArrangementSession)
        .filter(DawArrangementSession.audio_asset_id == int(asset_id), DawArrangementSession.is_deleted.is_(False))
        .order_by(DawArrangementSession.updated_at.desc(), DawArrangementSession.id.desc())
        .all()
    )
    return {"sessions": [_serialize_daw_session(session) for session in sessions]}


@router.post("/assets/{asset_id}/arrangement/sessions", response_model=dict)
def create_daw_arrangement_session(asset_id: int, payload: DawArrangementSaveRequest, db: Session = Depends(get_db)):
    asset = _asset_or_404(db, asset_id)
    arrangement, session = _save_arrangement_session(
        db,
        asset,
        payload.arrangement.model_dump(),
        title=payload.title,
        create_new_session=True,
    )
    return {"ok": True, "arrangement": arrangement, "session": _serialize_daw_session(session)}


@router.delete("/assets/{asset_id}/arrangement/sessions/{session_id}", response_model=dict)
def delete_daw_arrangement_session(asset_id: int, session_id: int, db: Session = Depends(get_db)):
    asset = _asset_or_404(db, asset_id)
    session = _daw_arrangement_session_or_404(db, asset_id, session_id)
    session.is_deleted = True
    session.deleted_at = utc_now_naive()
    session.deleted_reason = "DAW-Session gelöscht"
    remaining = (
        db.query(DawArrangementSession.id)
        .filter(
            DawArrangementSession.audio_asset_id == int(asset_id),
            DawArrangementSession.id != int(session_id),
            DawArrangementSession.is_deleted.is_(False),
            DawArrangementSession.is_active.is_(True),
        )
        .first()
    )
    if not remaining:
        metadata = dict(asset.metadata_json or {}) if isinstance(asset.metadata_json, dict) else {}
        metadata.pop("daw_arrangement", None)
        metadata.pop("daw_markers", None)
        asset.metadata_json = metadata
        db.add(asset)
    db.commit()
    return {"ok": True, "deleted_session_id": session_id}


@router.post("/assets/{asset_id}/arrangement/preview")
def preview_daw_arrangement(asset_id: int, payload: DawArrangementRenderRequest, db: Session = Depends(get_db)):
    asset = _asset_or_404(db, asset_id)
    saved, _session = _get_saved_arrangement_session(db, asset, payload.session_id)
    arrangement = _sanitize_arrangement(asset, payload.arrangement.model_dump() if payload.arrangement else saved)
    output_format = _normalize_daw_output_format(payload.output_format)
    suffix = f".{output_format}"
    temp_file = tempfile.NamedTemporaryFile(prefix="songstudio_daw_arrangement_preview_", suffix=suffix, delete=False)
    target_path = Path(temp_file.name)
    temp_file.close()
    args = _build_arrangement_ffmpeg_args(db, asset, arrangement, target_path, output_format)
    try:
        subprocess.run(args, text=True, capture_output=True, check=True, timeout=300)
    except subprocess.CalledProcessError as exc:
        _unlink_path(target_path)
        raise HTTPException(status_code=500, detail=f"DAW-Arrangement-Vorschau fehlgeschlagen: {exc.stderr[-1200:] if exc.stderr else exc}") from exc
    except Exception as exc:
        _unlink_path(target_path)
        raise HTTPException(status_code=500, detail=f"DAW-Arrangement-Vorschau fehlgeschlagen: {exc}") from exc
    if not target_path.exists() or target_path.stat().st_size <= 0:
        _unlink_path(target_path)
        raise HTTPException(status_code=500, detail="DAW-Arrangement-Vorschau hat keine Audiodatei erzeugt.")
    title = _sanitize_filename(payload.version_label or "daw_arrangement_preview")
    return FileResponse(target_path, media_type=_preview_media_type(output_format), filename=f"{title}{suffix}", background=BackgroundTask(_unlink_path, target_path))



@router.post("/assets/{asset_id}/arrangement/render-task", response_model=DawArrangementRenderTaskResponse)
def render_daw_arrangement_task(asset_id: int, payload: DawArrangementRenderRequest, db: Session = Depends(get_db)):
    asset = _asset_or_404(db, asset_id)
    saved, _session = _get_saved_arrangement_session(db, asset, payload.session_id)
    arrangement = _sanitize_arrangement(asset, payload.arrangement.model_dump() if payload.arrangement else saved)
    _save_arrangement_session(db, asset, arrangement, session_id=payload.session_id, title=payload.version_label)
    task = _create_daw_arrangement_render_task(db, asset, arrangement, payload.output_format, payload.version_label)
    run_detached_process(
        f"daw-arrangement-render-{task.id}",
        _run_daw_arrangement_render_background,
        task.id,
        asset.id,
        arrangement,
        payload.output_format,
        payload.version_label,
        payload.create_notification,
    )
    return DawArrangementRenderTaskResponse(
        task_local_id=task.id,
        message="DAW-Render wurde als lokaler Hintergrund-Task gestartet.",
    )


@router.post("/assets/{asset_id}/arrangement/render", response_model=AudioAssetRead)
def render_daw_arrangement(asset_id: int, payload: DawArrangementRenderRequest, db: Session = Depends(get_db)):
    asset = _asset_or_404(db, asset_id)
    saved, _session = _get_saved_arrangement_session(db, asset, payload.session_id)
    arrangement = _sanitize_arrangement(asset, payload.arrangement.model_dump() if payload.arrangement else saved)
    _save_arrangement_session(db, asset, arrangement, session_id=payload.session_id, title=payload.version_label)
    return _render_arrangement(db, asset, arrangement, payload.output_format, payload.version_label, payload.create_notification)




@router.get("/assets/{asset_id}/beatgrid", response_model=dict)
def get_daw_beatgrid(asset_id: int, rebuild: bool = False, db: Session = Depends(get_db)):
    asset = _asset_or_404(db, asset_id)
    source_path = _resolve_audio_path(asset)
    beatgrid = build_daw_beatgrid(asset, source_path, rebuild=rebuild)
    if beatgrid.get("ok"):
        persist_daw_beatgrid(asset, beatgrid)
        db.add(asset)
        db.commit()
        db.refresh(asset)
    return {"ok": bool(beatgrid.get("ok")), "beatgrid": beatgrid}


@router.post("/assets/{asset_id}/beatgrid/rebuild", response_model=dict)
def rebuild_daw_beatgrid(asset_id: int, db: Session = Depends(get_db)):
    asset = _asset_or_404(db, asset_id)
    source_path = _resolve_audio_path(asset)
    beatgrid = build_daw_beatgrid(asset, source_path, rebuild=True)
    if beatgrid.get("ok"):
        persist_daw_beatgrid(asset, beatgrid)
        db.add(asset)
        db.commit()
        db.refresh(asset)
    return {"ok": bool(beatgrid.get("ok")), "beatgrid": beatgrid}

@router.get("/assets/{asset_id}", response_model=dict)
def get_daw_project(asset_id: int, db: Session = Depends(get_db)):
    asset = _asset_or_404(db, asset_id)
    parent_keys = {str(asset.id), str(asset.parent_audio_id or ""), str(asset.audio_id or "")}
    versions = (
        db.query(AudioAsset)
        .filter(AudioAsset.is_deleted.is_(False))
        .filter(or_(AudioAsset.id == asset.id, AudioAsset.parent_audio_id.in_(list(parent_keys)), AudioAsset.song_id == asset.song_id if asset.song_id else False))
        .order_by(AudioAsset.created_at.asc())
        .limit(100)
        .all()
    )
    metadata = asset.metadata_json if isinstance(asset.metadata_json, dict) else {}
    return {"asset": AudioAssetRead.model_validate(asset), "versions": [AudioAssetRead.model_validate(row) for row in versions], "markers": metadata.get("daw_markers") or []}


@router.post("/render", response_model=AudioAssetRead)
def render_daw_edit(payload: DawRenderRequest, db: Session = Depends(get_db)):
    return _render_plan(db, payload)


@router.post("/preview")
def preview_daw_edit(payload: DawRenderRequest, db: Session = Depends(get_db)):
    source = _asset_or_404(db, payload.source_audio_id)
    source_path = _resolve_audio_path(source)
    output_format = _normalize_daw_output_format(payload.output_format)
    suffix = f".{output_format}"
    temp_file = tempfile.NamedTemporaryFile(prefix="songstudio_daw_preview_", suffix=suffix, delete=False)
    target_path = Path(temp_file.name)
    temp_file.close()
    args = _build_ffmpeg_args(source_path, target_path, payload.operations, output_format)
    try:
        subprocess.run(args, text=True, capture_output=True, check=True, timeout=240)
    except subprocess.CalledProcessError as exc:
        _unlink_path(target_path)
        raise HTTPException(status_code=500, detail=f"DAW-Vorschau fehlgeschlagen: {exc.stderr[-1200:] if exc.stderr else exc}") from exc
    except Exception as exc:
        _unlink_path(target_path)
        raise HTTPException(status_code=500, detail=f"DAW-Vorschau fehlgeschlagen: {exc}") from exc

    if not target_path.exists() or target_path.stat().st_size <= 0:
        _unlink_path(target_path)
        raise HTTPException(status_code=500, detail="DAW-Vorschau hat keine Audiodatei erzeugt.")

    title = _sanitize_filename(payload.version_label or payload.title_suffix or "daw_preview")
    return FileResponse(
        target_path,
        media_type=_preview_media_type(output_format),
        filename=f"{title}{suffix}",
        background=BackgroundTask(_unlink_path, target_path),
    )


@router.post("/assets/{asset_id}/markers", response_model=dict)
def add_marker(asset_id: int, payload: DawMarkerRequest, db: Session = Depends(get_db)):
    asset = _asset_or_404(db, asset_id)
    metadata = asset.metadata_json if isinstance(asset.metadata_json, dict) else {}
    markers = list(metadata.get("daw_markers") or [])
    marker = payload.model_dump()
    markers.append(marker)
    metadata["daw_markers"] = sorted(markers, key=lambda item: float(item.get("time") or 0))
    asset.metadata_json = metadata
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return {"ok": True, "markers": metadata["daw_markers"]}


@router.delete("/assets/{asset_id}/markers/{marker_index}", response_model=dict)
def delete_marker(asset_id: int, marker_index: int, db: Session = Depends(get_db)):
    asset = _asset_or_404(db, asset_id)
    metadata = asset.metadata_json if isinstance(asset.metadata_json, dict) else {}
    markers = list(metadata.get("daw_markers") or [])
    if marker_index < 0 or marker_index >= len(markers):
        raise HTTPException(status_code=404, detail="Marker wurde nicht gefunden.")
    markers.pop(marker_index)
    metadata["daw_markers"] = sorted(markers, key=lambda item: float(item.get("time") or 0))
    asset.metadata_json = metadata
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return {"ok": True, "markers": metadata["daw_markers"]}


@router.post("/analyze", response_model=dict)
def analyze_audio(payload: dict[str, Any], db: Session = Depends(get_db)):
    asset_id = int(payload.get("source_audio_id") or payload.get("asset_id") or 0)
    asset = _asset_or_404(db, asset_id)
    path = _resolve_audio_path(asset)
    duration = _duration_seconds(path)
    size = path.stat().st_size
    return {
        "ok": True,
        "asset_id": asset.id,
        "title": asset.display_title or asset.title,
        "duration_seconds": duration,
        "file_size_bytes": size,
        "is_local": True,
        "suggestions": [
            "Bei Social Clips zuerst Hook/Drop markieren.",
            "Für YouTube-Master zuerst Normalisieren auf ca. -14 LUFS testen.",
            "Original bleibt unverändert; Render erzeugt immer eine neue Version.",
        ],
    }


@router.post("/chat", response_model=dict)
async def chat_daw_edit(payload: DawChatRequest, db: Session = Depends(get_db)):
    asset = _asset_or_404(db, payload.source_audio_id)
    duration = float(payload.duration_seconds or asset.duration_seconds or 0)
    current_time = max(0.0, min(float(payload.current_time or 0), duration or float(payload.current_time or 0)))
    output_format = _normalize_daw_output_format(payload.output_format)
    provider = None
    model = None

    try:
        from app.routers.admin import get_ai_admin_settings

        settings = get_settings()
        admin_settings = get_ai_admin_settings(db)
        provider = admin_settings.get("default_provider") or settings.ai_default_provider
        model = admin_settings.get("default_model") or settings.ai_default_model
        instruction_payload = {
            "task": "resolve_current_daw_chat_command",
            "user_message": payload.message,
            "current_audio_asset": {
                "id": asset.id,
                "title": asset.display_title or asset.title or asset.filename or f"Audio {asset.id}",
                "version_label": asset.version_label,
                "operation_label": asset.operation_label,
                "duration_seconds": duration,
                "current_time": current_time,
            },
            "current_plan": payload.current_plan or {},
            "markers": payload.markers[:40],
            "chat_history": payload.history[-12:],
            "output_format": output_format,
            "allowed_operations": [
                {"type": "trim", "fields": ["start", "end"], "bounds": f"0 <= start < end <= {duration or 'duration'}"},
                {"type": "fade_in", "fields": ["duration"], "bounds": "0.05 <= duration <= 30"},
                {"type": "fade_out", "fields": ["duration"], "bounds": "0.05 <= duration <= 30"},
                {"type": "gain", "fields": ["gain_db"], "bounds": "-12 <= gain_db <= 12"},
                {"type": "normalize", "fields": ["target_lufs"], "bounds": "-24 <= target_lufs <= -8"},
                {"type": "preset", "fields": ["preset"], "allowed_presets": ["youtube", "klarer", "mehr_druck", "bass", "hoehen"]},
            ],
            "rules": [
                "Plane ausschließlich für current_audio_asset. Suche keinen anderen Song.",
                "Gib Zeitangaben immer als Sekunden aus.",
                "Wenn der Nutzer 'aktuelle Stelle', 'Playhead' oder 'hier' sagt, nutze current_time.",
                "Das Original bleibt unverändert; es wird immer eine neue Version erzeugt.",
                "Wenn eine Anweisung unklar ist, setze needs_confirmation true und operations leer.",
                "Keine Shell-Befehle, keine Dateipfade, keine Secrets.",
            ],
            "expected_output": {
                "is_audio_command": True,
                "needs_confirmation": True,
                "operations": [],
                "version_label": "kurzes Label fuer neue Version",
                "message": "kurze deutsche Erklaerung",
                "warnings": [],
                "suggestions": [],
            },
        }
        system_prompt = (
            "Du bist der fokussierte KI-Planer einer Mini-DAW. "
            "Du erzeugst ausschließlich ein valides JSON-Objekt. "
            "Du darfst nur erlaubte Audio-Operationen planen und niemals automatisch rendern. "
            "Der Nutzer entscheidet im Frontend, ob ein Plan uebernommen oder als neue Version gespeichert wird."
        )
        result = await AiChatService().run_json_task(
            provider=provider,
            model=model,
            system_prompt=system_prompt,
            instruction_payload=instruction_payload,
            profile_options={"max_output_tokens": 1400, "temperature": 0.1},
        )
        data = result.data if isinstance(result.data, dict) else {}
        operations = _normalize_ai_operations(data.get("operations") or (data.get("plan") or {}).get("operations"), duration)
        if operations:
            version_label = str(data.get("version_label") or (data.get("plan") or {}).get("version_label") or "DAW Chat Edit").strip()[:80] or "DAW Chat Edit"
            plan = {
                "source_audio_id": asset.id,
                "operations": operations,
                "version_label": version_label,
                "output_format": output_format,
                "create_notification": True,
            }
            response = {
                "ok": True,
                "is_audio_command": True,
                "needs_confirmation": True,
                "asset": AudioAssetRead.model_validate(asset),
                "plan": plan,
                "message": data.get("message") or f"Plan vorbereitet: {version_label}.",
                "warnings": data.get("warnings") if isinstance(data.get("warnings"), list) else [],
                "suggestions": data.get("suggestions") if isinstance(data.get("suggestions"), list) else [],
                "provider": provider,
                "model": model,
                "source": "daw_chat_ai",
            }
            if payload.execute:
                rendered = _render_plan(db, DawRenderRequest(**plan))
                response["rendered_asset"] = AudioAssetRead.model_validate(rendered)
                response["needs_confirmation"] = False
                response["message"] = f"Erledigt: Neue DAW-Version „{rendered.version_label}“ wurde gespeichert."
            return response
        return {
            "ok": True,
            "is_audio_command": True,
            "needs_confirmation": True,
            "asset": AudioAssetRead.model_validate(asset),
            "message": data.get("message") or "Ich habe keinen eindeutigen DAW-Plan erkannt.",
            "warnings": data.get("warnings") if isinstance(data.get("warnings"), list) else [],
            "suggestions": data.get("suggestions") if isinstance(data.get("suggestions"), list) else [],
            "provider": provider,
            "model": model,
            "source": "daw_chat_ai",
        }
    except AiProviderError:
        pass
    except Exception:
        pass

    fallback_plan = _fallback_plan_for_asset(payload.message, asset, duration, current_time, output_format)
    if fallback_plan:
        response = {
            "ok": True,
            "is_audio_command": True,
            "needs_confirmation": True,
            "asset": AudioAssetRead.model_validate(asset),
            "plan": fallback_plan,
            "message": f"Fallback-Plan vorbereitet: {fallback_plan['version_label']}.",
            "warnings": ["KI-Provider war nicht verfügbar oder lieferte keinen verwertbaren Plan."],
            "suggestions": ["Prüfe den Plan vor dem Speichern."],
            "provider": provider or "fallback",
            "model": model or "deterministic",
            "source": "daw_chat_fallback",
        }
        if payload.execute:
            rendered = _render_plan(db, DawRenderRequest(**fallback_plan))
            response["rendered_asset"] = AudioAssetRead.model_validate(rendered)
            response["needs_confirmation"] = False
            response["message"] = f"Erledigt: Neue DAW-Version „{rendered.version_label}“ wurde gespeichert."
        return response

    return {
        "ok": True,
        "is_audio_command": True,
        "needs_confirmation": True,
        "asset": AudioAssetRead.model_validate(asset),
        "message": "Ich habe keinen eindeutigen DAW-Plan erkannt. Nenne bitte Schnittzeit, Fade, Lautstärke, Preset oder Short-Länge konkreter.",
        "warnings": [],
        "suggestions": [
            "Beispiel: Schneide ab aktueller Stelle 30 Sekunden.",
            "Beispiel: Fade-out 2 Sekunden und YouTube Master.",
        ],
        "provider": provider or "fallback",
        "model": model or "deterministic",
        "source": "daw_chat_fallback",
    }


@router.post("/commands/resolve", response_model=dict)
async def resolve_daw_command(payload: DawCommandRequest, db: Session = Depends(get_db)):
    message = payload.message.strip()
    lowered = message.lower()
    keywords = ["schneide", "trim", "fade", "normalis", "master", "lauter", "leiser", "short", "cut", "daw", "hook", "tiktok", "youtube", "intro", "outro", "lauter", "leiser"]
    if not any(word in lowered for word in keywords):
        return {"is_audio_command": False}

    if payload.use_ai:
        ai_result = await _resolve_daw_command_with_ai(db, message)
        if ai_result:
            if ai_result.get("plan") and payload.execute:
                rendered = _render_plan(db, DawRenderRequest(**ai_result["plan"]))
                ai_result["rendered_asset"] = AudioAssetRead.model_validate(rendered)
                ai_result["message"] = f"Erledigt: Neue DAW-Version „{rendered.version_label}“ wurde gespeichert."
                ai_result["needs_confirmation"] = False
            return ai_result

    title_query, version = _extract_song_query(message)
    asset = _find_audio_by_title(db, title_query, version)
    if not asset:
        return {"is_audio_command": True, "needs_confirmation": True, "message": f"Ich erkenne einen Audio-Befehl, finde aber keinen eindeutigen Song zu „{title_query}“."}

    operations: list[dict[str, Any]] = []
    cut_seconds = None
    cut_match = re.search(r"(?:bei|bis|auf)\s+([^,.;]+)", message, re.I)
    if cut_match:
        cut_seconds = _time_to_seconds(cut_match.group(1))
    if cut_seconds is None and ("schneide" in lowered or "trim" in lowered or "cut" in lowered):
        cut_seconds = _time_to_seconds(message)
    if cut_seconds is not None and cut_seconds > 0:
        operations.append({"type": "trim", "start": 0, "end": cut_seconds})

    fade_match = re.search(r"(\d+(?:[,.]\d+)?)\s*(?:sek|sekunden|s)?\s*fade\s*-?\s*out", message, re.I)
    if not fade_match:
        fade_match = re.search(r"fade\s*-?\s*out.*?(\d+(?:[,.]\d+)?)\s*(?:sek|sekunden|s)", message, re.I)
    if fade_match or "fade out" in lowered or "fade-out" in lowered:
        duration = float(fade_match.group(1).replace(",", ".")) if fade_match else 2.0
        operations.append({"type": "fade_out", "duration": duration})

    gain_match = re.search(r"([+-]?\d+(?:[,.]\d+)?)\s*dB", message, re.I)
    if gain_match or "lauter" in lowered or "leiser" in lowered:
        gain = float(gain_match.group(1).replace(",", ".")) if gain_match else (2.0 if "lauter" in lowered else -2.0)
        operations.append({"type": "gain", "gain_db": gain})

    if "youtube" in lowered or "normalis" in lowered or "master" in lowered:
        operations.append({"type": "normalize", "target_lufs": -14})

    if "klar" in lowered:
        operations.append({"type": "preset", "preset": "klarer"})
    if "druck" in lowered or "club" in lowered:
        operations.append({"type": "preset", "preset": "mehr_druck"})
    if "bass" in lowered:
        operations.append({"type": "preset", "preset": "bass"})

    if not operations:
        return {"is_audio_command": True, "needs_confirmation": True, "message": "Ich habe den Song gefunden, aber keine eindeutige Bearbeitung erkannt."}

    suffix = "DAW Edit"
    if cut_seconds:
        minutes = int(cut_seconds // 60)
        seconds = int(cut_seconds % 60)
        suffix = f"Cut {minutes:02d}-{seconds:02d}"
    if any(op.get("type") == "fade_out" for op in operations):
        suffix += " Fadeout"

    plan = {
        "source_audio_id": asset.id,
        "operations": operations,
        "version_label": suffix,
        "output_format": "mp3",
        "create_notification": True,
    }
    response = {
        "is_audio_command": True,
        "needs_confirmation": not payload.execute,
        "asset": AudioAssetRead.model_validate(asset),
        "plan": plan,
        "message": f"Gefunden: {asset.display_title or asset.title or asset.id}. Aktion vorbereitet: {suffix}.",
    }
    if payload.execute:
        rendered = _render_plan(db, DawRenderRequest(**plan))
        response["rendered_asset"] = AudioAssetRead.model_validate(rendered)
        response["message"] = f"Erledigt: Neue DAW-Version „{rendered.version_label}“ wurde gespeichert."
    return response


# ---------------------------------------------------------------------------
# DAW-KI: natürliche Arrangement-Befehle (neu, additiv)
# ---------------------------------------------------------------------------

class DawArrangementAiCommandRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    arrangement: DawArrangementState | None = None
    selected_clip_id: str | None = Field(default=None, max_length=80)
    selected_section_id: str | None = Field(default=None, max_length=120)
    current_time: float | None = Field(default=None, ge=0)
    selection: dict[str, Any] | None = None
    execute: bool = False


@router.post("/assets/{asset_id}/arrangement/ai-command", response_model=dict)
async def arrangement_ai_command(asset_id: int, payload: DawArrangementAiCommandRequest, db: Session = Depends(get_db)):
    """Natürlichen DAW-Befehl in geprüfte Arrangement-Operationen übersetzen.

    Beispiele: „Setze die erste Hook doppelt“, „Schneide exakt nach 4 Takten“,
    „Kürze das Intro auf 8 Takte“. Der KI-Plan wird serverseitig deterministisch
    auf das Arrangement angewendet (taktgenau über Beatgrid/BPM) und mit
    execute=true dauerhaft in SQLite gespeichert (metadata_json.daw_arrangement).
    Jeder Befehl wird zusätzlich in der Tabelle daw_ai_actions protokolliert.
    """
    from app.models import DawAiAction
    from app.services.daw_ai_command_service import DawAiCommandService

    asset = _asset_or_404(db, asset_id)
    arrangement = _sanitize_arrangement(
        asset,
        payload.arrangement.model_dump() if payload.arrangement else _get_saved_arrangement(asset),
    )
    service = DawAiCommandService()
    result = await service.resolve(
        db,
        asset,
        arrangement,
        message=payload.message.strip(),
        selected_clip_id=payload.selected_clip_id,
        selected_section_id=payload.selected_section_id,
        current_time=float(payload.current_time or 0),
        selection=payload.selection,
    )

    status = "failed"
    if result.get("ok") and isinstance(result.get("arrangement"), dict):
        result["arrangement"] = _sanitize_arrangement(asset, result["arrangement"])
        status = "planned"
        if payload.execute:
            result["arrangement"] = _save_arrangement_to_asset(db, asset, result["arrangement"])
            result["persisted"] = True
            status = "executed"

    try:
        db.add(DawAiAction(
            audio_asset_id=asset.id,
            message=payload.message.strip()[:2000],
            interpretation=(result.get("interpretation") or result.get("message") or "")[:2000] or None,
            operations_json=result.get("operations"),
            status=status,
            source=result.get("source"),
            provider=result.get("provider"),
            model=result.get("model"),
            meta_json={
                "execute_requested": bool(payload.execute),
                "selected_clip_id": payload.selected_clip_id,
                "current_time": payload.current_time,
                "actions": result.get("actions"),
                "warnings": result.get("warnings"),
            },
        ))
        db.commit()
    except Exception:
        db.rollback()

    return result

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import get_settings
from app.services.portable_path_service import to_portable_path
from app.database import get_db
from app.models import AudioAsset, StatusNotification
from app.schemas import AudioAssetRead
from app.services.audio_metadata_service import normalize_audio_content_type, read_audio_duration_seconds
from app.services.waveform_service import get_or_create_waveform
from app.services.ai_chat_service import AiChatService, AiProviderError

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


TIME_RE = re.compile(r"(?:(\d+)\s*[:.]\s*)?(\d{1,2})(?:\s*(?:min|minute|minuten|m))?", re.I)


def _asset_or_404(db: Session, asset_id: int) -> AudioAsset:
    asset = db.query(AudioAsset).filter(AudioAsset.id == asset_id, AudioAsset.is_deleted.is_(False)).first()
    if not asset:
        raise HTTPException(status_code=404, detail="AudioAsset wurde nicht gefunden.")
    return asset


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
    version_label = payload.version_label or payload.title_suffix or "DAW Edit"
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
        title=source.title,
        display_title=base_title,
        image_url=source.image_url,
        source_url=f"{settings.suno_audio_public_route.rstrip('/')}/{target_path.name}",
        local_path=to_portable_path(target_path, storage_root=settings.audio_storage_path),
        public_url=f"{settings.suno_audio_public_route.rstrip('/')}/{target_path.name}",
        filename=target_path.name,
        content_type=normalize_audio_content_type(None, target_path),
        file_size_bytes=target_path.stat().st_size,
        duration_seconds=duration,
        status="cached",
        operation_label="DAW Edit",
        parent_audio_id=str(source.id),
        parent_task_id=source.suno_task_id,
        version_label=version_label,
        metadata_json={
            "operation": "DAW Edit",
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

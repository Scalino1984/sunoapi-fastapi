from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
import csv
import hashlib
import io
import json
import mimetypes
import re

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, File
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import ActivityLog, AudioAsset, AudioProject, AudioTranscript, LyricDraft, MusicStyle, Persona, Playlist, PlaylistItem, ProductionProfile, Song, SunoTask, VocalTag
from app.services.id3_tag_service import sync_audio_asset_id3_title, sync_project_assets_id3_title, sync_song_assets_id3_title
from app.services.portable_path_service import resolve_portable_path, to_portable_path
from app.services.system_status_notification_service import create_system_status_notification
from app.schemas import (
    LyricDraftCreate,
    LyricDraftRead,
    LyricDraftUpdate,
    MusicStyleCreate,
    MusicStyleRead,
    MusicStyleUpdate,
    PlaylistCreate,
    PlaylistItemCreate,
    PlaylistRead,
    PlaylistUpdate,
)
from app.utils.time_utils import utc_now_naive

router = APIRouter(prefix="/api/library", tags=["library"])


_EXPORT_FORMATS = {"csv", "markdown", "md"}
_EXPORT_MODES = {"simple", "extended"}


def _iso(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _json_text(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        return str(value)


def _clean_export_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        value = _json_text(value)
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    # CSV darf Mehrzeiler enthalten, Markdown-Tabellen nicht. Die konkrete Markdown-Umwandlung passiert separat.
    return text


def _markdown_cell(value: Any) -> str:
    text = _clean_export_text(value)
    text = text.replace("\n", "<br>")
    text = text.replace("|", "\\|")
    return text


def _safe_export_filename(value: str, fallback: str = "suno_export") -> str:
    raw = str(value or fallback).strip() or fallback
    raw = re.sub(r"[^A-Za-z0-9ÄÖÜäöüß._ -]+", "_", raw)
    raw = re.sub(r"\s+", "_", raw).strip("._- ")
    return (raw or fallback)[:120]


def _normalize_export_format(value: str | None) -> str:
    normalized = str(value or "csv").lower().strip()
    if normalized not in _EXPORT_FORMATS:
        raise HTTPException(status_code=400, detail="Exportformat ist nicht unterstützt. Erlaubt: csv, markdown.")
    return "markdown" if normalized == "md" else normalized


def _normalize_export_mode(value: str | None) -> str:
    normalized = str(value or "simple").lower().strip()
    if normalized not in _EXPORT_MODES:
        raise HTTPException(status_code=400, detail="Exportmodus ist nicht unterstützt. Erlaubt: simple, extended.")
    return normalized


def _rows_to_csv(rows: list[dict[str, Any]], columns: list[str]) -> str:
    buffer = io.StringIO()
    # UTF-8 BOM hilft Excel/LibreOffice beim deutschen Umlauten-Import.
    buffer.write("\ufeff")
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({column: _clean_export_text(row.get(column)) for column in columns})
    return buffer.getvalue()


def _rows_to_markdown(rows: list[dict[str, Any]], columns: list[str], title: str) -> str:
    lines = [f"# {title}", "", f"Exportiert: {_iso(utc_now_naive())} UTC", "", "| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(_markdown_cell(row.get(column)) for column in columns) + " |")
    lines.append("")
    return "\n".join(lines)


def _export_response(rows: list[dict[str, Any]], columns: list[str], *, basename: str, title: str, format: str) -> Response:
    fmt = _normalize_export_format(format)
    timestamp = utc_now_naive().strftime("%Y%m%d_%H%M%S")
    filename = f"{_safe_export_filename(basename)}_{timestamp}.{'md' if fmt == 'markdown' else 'csv'}"
    if fmt == "markdown":
        body = _rows_to_markdown(rows, columns, title)
        media_type = "text/markdown; charset=utf-8"
    else:
        body = _rows_to_csv(rows, columns)
        media_type = "text/csv; charset=utf-8"
    return Response(
        content=body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _library_export_rows(db: Session, mode: str = "simple") -> tuple[list[dict[str, Any]], list[str]]:
    mode = _normalize_export_mode(mode)
    assets = (
        db.query(AudioAsset)
        .filter(AudioAsset.is_deleted.is_(False))
        .order_by(AudioAsset.created_at.desc(), AudioAsset.id.desc())
        .all()
    )
    song_ids = {asset.song_id for asset in assets if asset.song_id}
    project_ids = {asset.project_id for asset in assets if asset.project_id}
    task_local_ids = {asset.task_local_id for asset in assets if asset.task_local_id}
    songs = {row.id: row for row in db.query(Song).filter(Song.id.in_(song_ids)).all()} if song_ids else {}
    projects = {row.id: row for row in db.query(AudioProject).filter(AudioProject.id.in_(project_ids)).all()} if project_ids else {}
    tasks = {row.id: row for row in db.query(SunoTask).filter(SunoTask.id.in_(task_local_ids)).all()} if task_local_ids else {}

    simple_columns = [
        "audio_asset_id", "song_id", "project_id", "title", "display_title", "project_title", "song_title",
        "audio_id", "suno_task_id", "task_local_id", "operation", "status", "favorite", "final",
        "duration_seconds", "filename", "public_url", "image_url", "created_at", "updated_at",
    ]
    extended_columns = simple_columns + [
        "content_type", "file_size_bytes", "checksum_sha256", "source_url", "local_path", "model", "style",
        "prompt", "lyrics", "song_model", "song_task_id", "song_audio_url", "song_cover_image_url", "song_wav_url",
        "task_type", "task_status", "task_external_id", "request_payload_json", "response_payload_json", "result_payload_json",
        "asset_metadata_json", "song_metadata_json", "project_metadata_json",
    ]
    columns = extended_columns if mode == "extended" else simple_columns
    rows: list[dict[str, Any]] = []
    for asset in assets:
        song = songs.get(asset.song_id)
        project = projects.get(asset.project_id)
        task = tasks.get(asset.task_local_id)
        row = {
            "audio_asset_id": asset.id,
            "song_id": asset.song_id,
            "project_id": asset.project_id,
            "title": asset.display_title or asset.title or (song.title if song else ""),
            "display_title": asset.display_title,
            "project_title": project.title if project else "",
            "song_title": song.title if song else "",
            "audio_id": asset.audio_id,
            "suno_task_id": asset.suno_task_id,
            "task_local_id": asset.task_local_id,
            "operation": asset.operation_label,
            "status": asset.status,
            "favorite": asset.is_favorite,
            "final": asset.is_final,
            "duration_seconds": asset.duration_seconds,
            "filename": asset.filename,
            "public_url": asset.public_url,
            "image_url": asset.image_url,
            "created_at": _iso(asset.created_at),
            "updated_at": _iso(asset.updated_at),
        }
        if mode == "extended":
            row.update({
                "content_type": asset.content_type,
                "file_size_bytes": asset.file_size_bytes,
                "checksum_sha256": asset.checksum_sha256,
                "source_url": asset.source_url,
                "local_path": asset.local_path,
                "model": asset.model_name,
                "style": asset.style,
                "prompt": asset.prompt,
                "lyrics": asset.lyrics,
                "song_model": song.model if song else "",
                "song_task_id": song.task_id if song else "",
                "song_audio_url": song.audio_url if song else "",
                "song_cover_image_url": song.cover_image_url if song else "",
                "song_wav_url": song.wav_url if song else "",
                "task_type": task.task_type if task else "",
                "task_status": task.status if task else "",
                "task_external_id": task.task_id if task else "",
                "request_payload_json": _json_text(task.request_payload if task else None),
                "response_payload_json": _json_text(task.response_payload if task else None),
                "result_payload_json": _json_text(task.result_payload if task else None),
                "asset_metadata_json": _json_text(asset.metadata_json),
                "song_metadata_json": _json_text(song.metadata_json if song else None),
                "project_metadata_json": _json_text(project.metadata_json if project else None),
            })
        rows.append(row)
    return rows, columns


def _style_export_rows(db: Session, mode: str = "extended") -> tuple[list[dict[str, Any]], list[str]]:
    mode = _normalize_export_mode(mode)
    styles = db.query(MusicStyle).filter(MusicStyle.is_deleted.is_(False)).order_by(MusicStyle.is_favorite.desc(), MusicStyle.updated_at.desc()).all()
    simple_columns = ["id", "name", "genre", "bpm", "tags", "favorite", "usage_count", "created_at", "updated_at"]
    extended_columns = simple_columns + ["description", "style_text", "is_profile", "profile_json"]
    columns = extended_columns if mode == "extended" else simple_columns
    rows = []
    for style in styles:
        row = {
            "id": style.id,
            "name": style.name,
            "genre": style.genre,
            "bpm": style.bpm,
            "tags": style.tags,
            "favorite": style.is_favorite,
            "usage_count": style.usage_count,
            "created_at": _iso(style.created_at),
            "updated_at": _iso(style.updated_at),
        }
        if mode == "extended":
            row.update({"description": style.description, "style_text": style.style_text, "is_profile": style.is_profile, "profile_json": _json_text(style.profile_json)})
        rows.append(row)
    return rows, columns


def _lyric_export_rows(db: Session, mode: str = "extended") -> tuple[list[dict[str, Any]], list[str]]:
    mode = _normalize_export_mode(mode)
    drafts = db.query(LyricDraft).filter(LyricDraft.is_deleted.is_(False)).order_by(LyricDraft.updated_at.desc()).all()
    simple_columns = ["id", "title", "status", "language", "tags", "structure_template", "line_count", "char_count", "created_at", "updated_at"]
    extended_columns = simple_columns + ["content", "metadata_json"]
    columns = extended_columns if mode == "extended" else simple_columns
    rows = []
    for draft in drafts:
        content = draft.content or ""
        row = {
            "id": draft.id,
            "title": draft.title,
            "status": draft.status,
            "language": draft.language,
            "tags": draft.tags,
            "structure_template": draft.structure_template,
            "line_count": len(content.splitlines()) if content else 0,
            "char_count": len(content),
            "created_at": _iso(draft.created_at),
            "updated_at": _iso(draft.updated_at),
        }
        if mode == "extended":
            row.update({"content": content, "metadata_json": _json_text(draft.metadata_json)})
        rows.append(row)
    return rows, columns


def _vocal_tag_export_rows(db: Session, mode: str = "extended") -> tuple[list[dict[str, Any]], list[str]]:
    mode = _normalize_export_mode(mode)
    tags = db.query(VocalTag).filter(VocalTag.is_deleted.is_(False)).order_by(VocalTag.category.asc(), VocalTag.sort_order.asc(), VocalTag.label.asc()).all()
    simple_columns = ["id", "label", "tag", "category", "sort_order", "is_active", "created_at", "updated_at"]
    extended_columns = simple_columns + ["description", "metadata_json"]
    columns = extended_columns if mode == "extended" else simple_columns
    rows: list[dict[str, Any]] = []
    for tag in tags:
        row = {
            "id": tag.id,
            "label": tag.label,
            "tag": tag.tag,
            "category": tag.category,
            "sort_order": tag.sort_order,
            "is_active": tag.is_active,
            "created_at": _iso(tag.created_at),
            "updated_at": _iso(tag.updated_at),
        }
        if mode == "extended":
            row.update({"description": tag.description, "metadata_json": _json_text(tag.metadata_json)})
        rows.append(row)
    return rows, columns


def _playlist_export_rows(db: Session, mode: str = "extended") -> tuple[list[dict[str, Any]], list[str]]:
    mode = _normalize_export_mode(mode)
    playlists = db.query(Playlist).filter(Playlist.is_deleted.is_(False)).order_by(Playlist.sort_order.asc(), Playlist.name.asc()).all()
    simple_columns = ["id", "name", "description", "track_count", "sort_order", "created_at", "updated_at"]
    extended_columns = simple_columns + ["cover_image_url", "audio_asset_ids", "song_ids", "track_titles", "metadata_json"]
    columns = extended_columns if mode == "extended" else simple_columns
    rows: list[dict[str, Any]] = []
    for playlist in playlists:
        items = db.query(PlaylistItem).filter(PlaylistItem.playlist_id == playlist.id).order_by(PlaylistItem.position.asc(), PlaylistItem.id.asc()).all()
        asset_ids = [item.audio_asset_id for item in items if item.audio_asset_id]
        song_ids = [item.song_id for item in items if item.song_id]
        assets = {asset.id: asset for asset in db.query(AudioAsset).filter(AudioAsset.id.in_(asset_ids)).all()} if asset_ids else {}
        row = {
            "id": playlist.id,
            "name": playlist.name,
            "description": playlist.description,
            "track_count": len(items),
            "sort_order": playlist.sort_order,
            "created_at": _iso(playlist.created_at),
            "updated_at": _iso(playlist.updated_at),
        }
        if mode == "extended":
            row.update({
                "cover_image_url": playlist.cover_image_url,
                "audio_asset_ids": ",".join(str(value) for value in asset_ids),
                "song_ids": ",".join(str(value) for value in song_ids),
                "track_titles": " | ".join((assets.get(value).display_title or assets.get(value).title or str(value)) for value in asset_ids if assets.get(value)),
                "metadata_json": _json_text(playlist.metadata_json),
            })
        rows.append(row)
    return rows, columns


def _parse_bool(value: Any, default: bool = False) -> bool:
    if value in (None, ""):
        return default
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "ja", "y", "aktiv", "active"}


def _parse_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(str(value).strip()))
    except Exception:
        return default


def _parse_json_field(value: Any) -> Any:
    if value in (None, ""):
        return None
    if isinstance(value, (dict, list)):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return {"raw": text}


def _norm_key(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _row_value(row: dict[str, Any], *keys: str) -> str:
    lookup = {str(k).strip().lower().replace(" ", "_"): v for k, v in row.items()}
    for key in keys:
        value = lookup.get(key.strip().lower().replace(" ", "_"))
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _parse_markdown_table(text: str) -> list[dict[str, str]]:
    lines = [line.strip() for line in text.splitlines() if line.strip().startswith("|") and line.strip().endswith("|")]
    if len(lines) < 2:
        return []
    def split(line: str) -> list[str]:
        return [cell.strip().replace("<br>", "\n").replace("\\|", "|") for cell in line.strip().strip("|").split("|")]
    headers = split(lines[0])
    rows: list[dict[str, str]] = []
    for line in lines[1:]:
        cells = split(line)
        if cells and all(re.fullmatch(r"[-: ]+", cell or "") for cell in cells):
            continue
        rows.append({headers[index]: cells[index] if index < len(cells) else "" for index in range(len(headers))})
    return rows


async def _uploaded_import_rows(file: UploadFile, format: str = "auto") -> list[dict[str, str]]:
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Importdatei ist leer.")
    text = raw.decode("utf-8-sig", errors="replace")
    fmt = str(format or "auto").lower().strip()
    if fmt in {"markdown", "md"} or (fmt == "auto" and text.lstrip().startswith("|")):
        rows = _parse_markdown_table(text)
    else:
        reader = csv.DictReader(io.StringIO(text))
        rows = [dict(row) for row in reader]
    if not rows:
        raise HTTPException(status_code=400, detail="Keine Importzeilen gefunden. Unterstützt werden CSV und Markdown-Tabellen.")
    return rows


def _import_summary(kind: str, imported: int, skipped: int, errors: list[str]) -> dict[str, Any]:
    return {"ok": True, "kind": kind, "imported": imported, "skipped": skipped, "errors": errors[:50]}

@router.get("/export/library")
def export_library_table(format: str = "csv", mode: str = "simple", db: Session = Depends(get_db)) -> Response:
    rows, columns = _library_export_rows(db, mode)
    normalized_mode = _normalize_export_mode(mode)
    return _export_response(rows, columns, basename=f"suno_library_{normalized_mode}", title=f"Suno Library Export ({normalized_mode})", format=format)


@router.get("/export/styles")
def export_styles_table(format: str = "csv", mode: str = "extended", db: Session = Depends(get_db)) -> Response:
    rows, columns = _style_export_rows(db, mode)
    normalized_mode = _normalize_export_mode(mode)
    return _export_response(rows, columns, basename=f"suno_styles_{normalized_mode}", title=f"Suno Styles Export ({normalized_mode})", format=format)


@router.get("/export/lyrics")
def export_lyrics_table(format: str = "csv", mode: str = "extended", db: Session = Depends(get_db)) -> Response:
    rows, columns = _lyric_export_rows(db, mode)
    normalized_mode = _normalize_export_mode(mode)
    return _export_response(rows, columns, basename=f"suno_lyrics_{normalized_mode}", title=f"Suno Songtexte Export ({normalized_mode})", format=format)


@router.get("/export/vocal-tags")
def export_vocal_tags_table(format: str = "csv", mode: str = "extended", db: Session = Depends(get_db)) -> Response:
    rows, columns = _vocal_tag_export_rows(db, mode)
    normalized_mode = _normalize_export_mode(mode)
    return _export_response(rows, columns, basename=f"suno_vocal_tags_{normalized_mode}", title=f"Suno Vocal Tags Export ({normalized_mode})", format=format)


@router.get("/export/playlists")
def export_playlists_table(format: str = "csv", mode: str = "extended", db: Session = Depends(get_db)) -> Response:
    rows, columns = _playlist_export_rows(db, mode)
    normalized_mode = _normalize_export_mode(mode)
    return _export_response(rows, columns, basename=f"suno_playlists_{normalized_mode}", title=f"Suno Playlists Export ({normalized_mode})", format=format)


@router.post("/import/vocal-tags")
async def import_vocal_tags(format: str = "auto", file: UploadFile = File(...), db: Session = Depends(get_db)) -> dict[str, Any]:
    rows = await _uploaded_import_rows(file, format)
    existing_labels = {_norm_key(row.label) for row in db.query(VocalTag).filter(VocalTag.is_deleted.is_(False)).all()}
    existing_tags = {_norm_key(row.tag) for row in db.query(VocalTag).filter(VocalTag.is_deleted.is_(False)).all()}
    imported = skipped = 0
    errors: list[str] = []
    for index, row in enumerate(rows, start=1):
        label = _row_value(row, "label", "name", "title")
        tag_text = _row_value(row, "tag", "content", "text")
        if not label or not tag_text:
            skipped += 1; errors.append(f"Zeile {index}: label/tag fehlt."); continue
        if _norm_key(label) in existing_labels or _norm_key(tag_text) in existing_tags:
            skipped += 1; continue
        tag = VocalTag(
            label=label,
            tag=tag_text,
            category=_row_value(row, "category", "kategorie") or "Vocal Tags",
            description=_row_value(row, "description", "beschreibung") or None,
            sort_order=_parse_int(_row_value(row, "sort_order", "sortierung"), 100),
            is_active=_parse_bool(_row_value(row, "is_active", "active", "aktiv"), True),
            metadata_json=_parse_json_field(_row_value(row, "metadata_json", "metadata")),
        )
        db.add(tag)
        existing_labels.add(_norm_key(label)); existing_tags.add(_norm_key(tag_text)); imported += 1
    db.commit()
    return _import_summary("vocal-tags", imported, skipped, errors)


@router.post("/import/styles")
async def import_styles(format: str = "auto", file: UploadFile = File(...), db: Session = Depends(get_db)) -> dict[str, Any]:
    rows = await _uploaded_import_rows(file, format)
    existing_names = {_norm_key(row.name) for row in db.query(MusicStyle).filter(MusicStyle.is_deleted.is_(False)).all()}
    existing_texts = {_norm_key(row.style_text) for row in db.query(MusicStyle).filter(MusicStyle.is_deleted.is_(False)).all()}
    imported = skipped = 0
    errors: list[str] = []
    for index, row in enumerate(rows, start=1):
        name = _row_value(row, "name", "title")
        style_text = _row_value(row, "style_text", "style", "content", "prompt")
        if not name or not style_text:
            skipped += 1; errors.append(f"Zeile {index}: name/style_text fehlt."); continue
        if _norm_key(name) in existing_names or _norm_key(style_text) in existing_texts:
            skipped += 1; continue
        style = MusicStyle(
            name=name,
            style_text=style_text,
            genre=_row_value(row, "genre") or None,
            bpm=_parse_int(_row_value(row, "bpm"), 0) or None,
            description=_row_value(row, "description", "beschreibung") or None,
            tags=_row_value(row, "tags") or None,
            is_favorite=_parse_bool(_row_value(row, "favorite", "is_favorite"), False),
            usage_count=_parse_int(_row_value(row, "usage_count"), 0),
            profile_json=_parse_json_field(_row_value(row, "profile_json")),
            is_profile=_parse_bool(_row_value(row, "is_profile"), False),
        )
        db.add(style); existing_names.add(_norm_key(name)); existing_texts.add(_norm_key(style_text)); imported += 1
    db.commit()
    return _import_summary("styles", imported, skipped, errors)


@router.post("/import/lyrics")
async def import_lyrics(format: str = "auto", file: UploadFile = File(...), db: Session = Depends(get_db)) -> dict[str, Any]:
    rows = await _uploaded_import_rows(file, format)
    existing = {(_norm_key(row.title), _norm_key(row.content)) for row in db.query(LyricDraft).filter(LyricDraft.is_deleted.is_(False)).all()}
    imported = skipped = 0
    errors: list[str] = []
    for index, row in enumerate(rows, start=1):
        title = _row_value(row, "title", "name")
        content = _row_value(row, "content", "lyrics", "songtext", "prompt")
        if not title or not content:
            skipped += 1; errors.append(f"Zeile {index}: title/content fehlt."); continue
        key = (_norm_key(title), _norm_key(content))
        if key in existing:
            skipped += 1; continue
        draft = LyricDraft(
            title=title,
            content=content,
            status=_row_value(row, "status") or "draft",
            language=_row_value(row, "language", "sprache") or None,
            tags=_row_value(row, "tags") or None,
            structure_template=_row_value(row, "structure_template", "struktur") or None,
            metadata_json=_parse_json_field(_row_value(row, "metadata_json", "metadata")),
        )
        db.add(draft); existing.add(key); imported += 1
    db.commit()
    return _import_summary("lyrics", imported, skipped, errors)


@router.post("/import/playlists")
async def import_playlists(format: str = "auto", file: UploadFile = File(...), db: Session = Depends(get_db)) -> dict[str, Any]:
    rows = await _uploaded_import_rows(file, format)
    existing_names = {_norm_key(row.name): row for row in db.query(Playlist).filter(Playlist.is_deleted.is_(False)).all()}
    imported = skipped = 0
    errors: list[str] = []
    for index, row in enumerate(rows, start=1):
        name = _row_value(row, "name", "title")
        if not name:
            skipped += 1; errors.append(f"Zeile {index}: name fehlt."); continue
        key = _norm_key(name)
        if key in existing_names:
            playlist = existing_names[key]
            skipped += 1
        else:
            playlist = Playlist(
                name=name,
                description=_row_value(row, "description", "beschreibung") or None,
                cover_image_url=_row_value(row, "cover_image_url", "cover") or None,
                sort_order=_parse_int(_row_value(row, "sort_order", "sortierung"), 0),
                metadata_json=_parse_json_field(_row_value(row, "metadata_json", "metadata")),
            )
            db.add(playlist); db.flush(); existing_names[key] = playlist; imported += 1
        raw_ids = _row_value(row, "audio_asset_ids", "audio_asset_id", "asset_ids")
        if raw_ids:
            ids = [int(part) for part in re.findall(r"\d+", raw_ids)]
            current_ids = {item.audio_asset_id for item in db.query(PlaylistItem).filter(PlaylistItem.playlist_id == playlist.id).all() if item.audio_asset_id}
            pos = len(current_ids)
            for asset_id in ids:
                if asset_id in current_ids:
                    continue
                if not db.query(AudioAsset.id).filter(AudioAsset.id == asset_id, AudioAsset.is_deleted.is_(False)).first():
                    errors.append(f"Zeile {index}: AudioAsset {asset_id} nicht gefunden.")
                    continue
                db.add(PlaylistItem(playlist_id=playlist.id, audio_asset_id=asset_id, position=pos))
                current_ids.add(asset_id); pos += 1
    db.commit()
    return _import_summary("playlists", imported, skipped, errors)


def _audio_to_dict(asset: AudioAsset | None) -> dict[str, Any] | None:
    if not asset:
        return None
    return {
        "id": asset.id,
        "title": asset.title,
        "audio_id": asset.audio_id,
        "suno_task_id": asset.suno_task_id,
        "image_url": asset.image_url,
        "source_url": asset.source_url,
        "public_url": asset.public_url,
        "filename": asset.filename,
        "status": asset.status,
        "duration_seconds": asset.duration_seconds,
        "content_type": asset.content_type,
        "file_size_bytes": asset.file_size_bytes,
    }


def _song_to_dict(song: Song | None) -> dict[str, Any] | None:
    if not song:
        return None
    return {
        "id": song.id,
        "title": song.title,
        "model": song.model,
        "prompt": song.prompt,
        "lyrics": song.lyrics,
        "audio_url": song.audio_url,
        "cover_image_url": song.cover_image_url,
        "task_id": song.task_id,
    }


def _playlist_to_dict(playlist: Playlist, db: Session) -> dict[str, Any]:
    items = (
        db.query(PlaylistItem)
        .filter(PlaylistItem.playlist_id == playlist.id)
        .order_by(PlaylistItem.position.asc(), PlaylistItem.id.asc())
        .all()
    )
    # N+1 beseitigt: Assets und Songs für ALLE Items in je einer Query laden.
    asset_ids = {item.audio_asset_id for item in items if item.audio_asset_id}
    song_ids = {item.song_id for item in items if item.song_id}
    asset_map = {a.id: a for a in db.query(AudioAsset).filter(AudioAsset.id.in_(asset_ids)).all()} if asset_ids else {}
    song_map = {s.id: s for s in db.query(Song).filter(Song.id.in_(song_ids)).all()} if song_ids else {}
    serialized_items = []
    for item in items:
        asset = asset_map.get(item.audio_asset_id) if item.audio_asset_id else None
        song = song_map.get(item.song_id) if item.song_id else None
        serialized_items.append(
            {
                "id": item.id,
                "playlist_id": item.playlist_id,
                "audio_asset_id": item.audio_asset_id,
                "song_id": item.song_id,
                "position": item.position,
                "note": item.note,
                "created_at": item.created_at,
                "updated_at": item.updated_at,
                "audio_asset": _audio_to_dict(asset),
                "song": _song_to_dict(song),
            }
        )
    return {
        "id": playlist.id,
        "name": playlist.name,
        "description": playlist.description,
        "cover_image_url": playlist.cover_image_url,
        "sort_order": playlist.sort_order,
        "metadata_json": playlist.metadata_json,
        "created_at": playlist.created_at,
        "updated_at": playlist.updated_at,
        "items": serialized_items,
    }


@router.get("/playlists", response_model=list[PlaylistRead])
def list_playlists(db: Session = Depends(get_db)):
    playlists = db.query(Playlist).filter(Playlist.is_deleted.is_(False)).order_by(Playlist.sort_order.asc(), Playlist.updated_at.desc()).all()
    return [_playlist_to_dict(playlist, db) for playlist in playlists]


@router.post("/playlists", response_model=PlaylistRead)
def create_playlist(payload: PlaylistCreate, db: Session = Depends(get_db)):
    playlist = Playlist(**payload.model_dump(exclude_none=True))
    db.add(playlist)
    db.commit()
    db.refresh(playlist)
    return _playlist_to_dict(playlist, db)


@router.get("/playlists/{playlist_id}", response_model=PlaylistRead)
def get_playlist(playlist_id: int, db: Session = Depends(get_db)):
    playlist = db.query(Playlist).filter(Playlist.id == playlist_id, Playlist.is_deleted.is_(False)).first()
    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist wurde nicht gefunden.")
    return _playlist_to_dict(playlist, db)


@router.put("/playlists/{playlist_id}", response_model=PlaylistRead)
def update_playlist(playlist_id: int, payload: PlaylistUpdate, db: Session = Depends(get_db)):
    playlist = db.query(Playlist).filter(Playlist.id == playlist_id, Playlist.is_deleted.is_(False)).first()
    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist wurde nicht gefunden.")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(playlist, key, value)
    db.commit()
    db.refresh(playlist)
    return _playlist_to_dict(playlist, db)


@router.delete("/playlists/{playlist_id}")
def delete_playlist(playlist_id: int, db: Session = Depends(get_db)):
    playlist = db.query(Playlist).filter(Playlist.id == playlist_id, Playlist.is_deleted.is_(False)).first()
    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist wurde nicht gefunden.")
    _delete_content_item(db, "playlist", playlist_id, delete_files=False, reason="Direktes Löschen einer Playlist")
    db.commit()
    return {"ok": True, "deleted_playlist_id": playlist_id, "mode": "soft-delete"}


@router.post("/playlists/{playlist_id}/items", response_model=PlaylistRead)
def add_playlist_item(playlist_id: int, payload: PlaylistItemCreate, db: Session = Depends(get_db)):
    playlist = db.query(Playlist).filter(Playlist.id == playlist_id, Playlist.is_deleted.is_(False)).first()
    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist wurde nicht gefunden.")
    if payload.audio_asset_id and not db.query(AudioAsset).filter(AudioAsset.id == payload.audio_asset_id).first():
        raise HTTPException(status_code=404, detail="Audio-Datei wurde nicht gefunden.")
    if payload.song_id and not db.query(Song).filter(Song.id == payload.song_id).first():
        raise HTTPException(status_code=404, detail="Song wurde nicht gefunden.")
    max_position = db.query(PlaylistItem).filter(PlaylistItem.playlist_id == playlist_id).count()
    item = PlaylistItem(
        playlist_id=playlist_id,
        audio_asset_id=payload.audio_asset_id,
        song_id=payload.song_id,
        note=payload.note,
        position=max_position + 1,
    )
    db.add(item)
    db.commit()
    db.refresh(playlist)
    return _playlist_to_dict(playlist, db)


@router.delete("/playlists/{playlist_id}/items/{item_id}", response_model=PlaylistRead)
def delete_playlist_item(playlist_id: int, item_id: int, db: Session = Depends(get_db)):
    playlist = db.query(Playlist).filter(Playlist.id == playlist_id, Playlist.is_deleted.is_(False)).first()
    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist wurde nicht gefunden.")
    item = db.query(PlaylistItem).filter(PlaylistItem.id == item_id, PlaylistItem.playlist_id == playlist_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Playlist-Eintrag wurde nicht gefunden.")
    db.delete(item)
    db.commit()
    db.refresh(playlist)
    return _playlist_to_dict(playlist, db)


@router.get("/lyrics", response_model=list[LyricDraftRead])
def list_lyric_drafts(db: Session = Depends(get_db)):
    return db.query(LyricDraft).filter(LyricDraft.is_deleted.is_(False)).order_by(LyricDraft.updated_at.desc()).all()


@router.post("/lyrics", response_model=LyricDraftRead)
def create_lyric_draft(payload: LyricDraftCreate, db: Session = Depends(get_db)):
    draft = LyricDraft(**payload.model_dump(exclude_none=True))
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


@router.put("/lyrics/{draft_id}", response_model=LyricDraftRead)
def update_lyric_draft(draft_id: int, payload: LyricDraftUpdate, db: Session = Depends(get_db)):
    draft = db.query(LyricDraft).filter(LyricDraft.id == draft_id, LyricDraft.is_deleted.is_(False)).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Songtext wurde nicht gefunden.")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(draft, key, value)
    db.commit()
    db.refresh(draft)
    return draft


@router.delete("/lyrics/{draft_id}")
def delete_lyric_draft(draft_id: int, db: Session = Depends(get_db)):
    draft = db.query(LyricDraft).filter(LyricDraft.id == draft_id, LyricDraft.is_deleted.is_(False)).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Songtext wurde nicht gefunden.")
    _delete_content_item(db, "lyric", draft_id, delete_files=False, reason="Direktes Löschen eines Songtextes")
    db.commit()
    return {"ok": True, "deleted_lyric_id": draft_id, "mode": "soft-delete"}


@router.get("/styles", response_model=list[MusicStyleRead])
def list_music_styles(db: Session = Depends(get_db)):
    return db.query(MusicStyle).filter(MusicStyle.is_deleted.is_(False)).order_by(MusicStyle.is_favorite.desc(), MusicStyle.updated_at.desc()).all()


@router.post("/styles", response_model=MusicStyleRead)
def create_music_style(payload: MusicStyleCreate, db: Session = Depends(get_db)):
    style = MusicStyle(**payload.model_dump(exclude_none=True))
    db.add(style)
    db.commit()
    db.refresh(style)
    create_system_status_notification(
        db,
        event_type="music_style_created",
        title=f"Music Style erstellt: {style.name}",
        message="Der Music Style wurde gespeichert und ist in der Style-Library verfügbar.",
        severity="success",
        target_tab="styles",
        target_payload={"target_tab": "styles", "style_id": style.id, "style_name": style.name, "status": "SUCCESS"},
        content_type="style",
        content_id=style.id,
    )
    return style


@router.put("/styles/{style_id}", response_model=MusicStyleRead)
def update_music_style(style_id: int, payload: MusicStyleUpdate, db: Session = Depends(get_db)):
    style = db.query(MusicStyle).filter(MusicStyle.id == style_id, MusicStyle.is_deleted.is_(False)).first()
    if not style:
        raise HTTPException(status_code=404, detail="Music Style wurde nicht gefunden.")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(style, key, value)
    db.commit()
    db.refresh(style)
    create_system_status_notification(
        db,
        event_type="music_style_updated",
        title=f"Music Style aktualisiert: {style.name}",
        message="Der Music Style wurde aktualisiert.",
        severity="success",
        target_tab="styles",
        target_payload={"target_tab": "styles", "style_id": style.id, "style_name": style.name, "status": "SUCCESS"},
        content_type="style",
        content_id=style.id,
    )
    return style


@router.post("/styles/{style_id}/use", response_model=MusicStyleRead)
def use_music_style(style_id: int, db: Session = Depends(get_db)):
    style = db.query(MusicStyle).filter(MusicStyle.id == style_id, MusicStyle.is_deleted.is_(False)).first()
    if not style:
        raise HTTPException(status_code=404, detail="Music Style wurde nicht gefunden.")
    style.usage_count += 1
    db.commit()
    db.refresh(style)
    return style


@router.delete("/styles/{style_id}")
def delete_music_style(style_id: int, db: Session = Depends(get_db)):
    style = db.query(MusicStyle).filter(MusicStyle.id == style_id, MusicStyle.is_deleted.is_(False)).first()
    if not style:
        raise HTTPException(status_code=404, detail="Music Style wurde nicht gefunden.")
    style_name = style.name
    _delete_content_item(db, "style", style_id, delete_files=False, reason="Direktes Löschen eines Styles")
    create_system_status_notification(
        db,
        event_type="music_style_deleted",
        title=f"Music Style gelöscht: {style_name}",
        message="Der Music Style wurde in den Papierkorb verschoben.",
        severity="success",
        target_tab="styles",
        target_payload={"target_tab": "styles", "style_id": style_id, "style_name": style_name, "status": "SUCCESS", "deleted": True},
        content_type="style",
        content_id=style_id,
        commit=False,
    )
    db.commit()
    return {"ok": True, "deleted_style_id": style_id, "mode": "soft-delete"}


@router.get("/vocal-tags", response_model=list[dict[str, Any]])
def list_vocal_tag_suggestions(db: Session = Depends(get_db)):
    rows = (
        db.query(VocalTag)
        .filter(VocalTag.is_deleted.is_(False), VocalTag.is_active.is_(True))
        .order_by(VocalTag.category.asc(), VocalTag.sort_order.asc(), VocalTag.label.asc())
        .all()
    )
    if rows:
        return [
            {
                "id": row.id,
                "label": row.label,
                "tag": row.tag,
                "category": row.category or "Tags",
                "description": row.description,
                "sort_order": row.sort_order,
            }
            for row in rows
        ]
    return []


# ---------------------------------------------------------------------------
# Zentrale Inhaltsverwaltung: Suche, Filter, Einzel-Löschung, Mehrfach-Löschung
# ---------------------------------------------------------------------------

def _safe_lower(value: Any) -> str:
    return str(value or "").lower()


def _match_query(*values: Any, query: str | None = None) -> bool:
    if not query:
        return True
    haystack = " ".join(_safe_lower(value) for value in values)
    return _safe_lower(query).strip() in haystack


def _delete_audio_asset(db: Session, asset_id: int, *, delete_file: bool = True) -> bool:
    asset = db.query(AudioAsset).filter(AudioAsset.id == asset_id).first()
    if not asset:
        return False

    db.query(PlaylistItem).filter(PlaylistItem.audio_asset_id == asset.id).delete(synchronize_session=False)

    try:
        from app.models import AudioProject
        for project in db.query(AudioProject).filter(AudioProject.final_audio_asset_id == asset.id).all():
            project.final_audio_asset_id = None
    except Exception:
        pass

    local_path = asset.local_path
    db.delete(asset)
    db.commit()

    if delete_file and local_path:
        try:
            from pathlib import Path
            path = Path(local_path)
            if path.exists() and path.is_file():
                path.unlink()
        except OSError:
            pass

    return True


def _delete_song(db: Session, song_id: int) -> bool:
    song = db.query(Song).filter(Song.id == song_id).first()
    if not song:
        return False
    db.query(PlaylistItem).filter(PlaylistItem.song_id == song.id).delete(synchronize_session=False)
    db.query(AudioAsset).filter(AudioAsset.song_id == song.id).update({"song_id": None}, synchronize_session=False)
    db.delete(song)
    db.commit()
    return True


def _delete_lyric(db: Session, lyric_id: int) -> bool:
    draft = db.query(LyricDraft).filter(LyricDraft.id == lyric_id).first()
    if not draft:
        return False
    db.delete(draft)
    db.commit()
    return True


def _delete_style(db: Session, style_id: int) -> bool:
    style = db.query(MusicStyle).filter(MusicStyle.id == style_id, MusicStyle.is_deleted.is_(False)).first()
    if not style:
        return False
    db.delete(style)
    db.commit()
    return True


def _delete_playlist(db: Session, playlist_id: int) -> bool:
    playlist = db.query(Playlist).filter(Playlist.id == playlist_id, Playlist.is_deleted.is_(False)).first()
    if not playlist:
        return False
    db.query(PlaylistItem).filter(PlaylistItem.playlist_id == playlist.id).delete(synchronize_session=False)
    db.delete(playlist)
    db.commit()
    return True


def _delete_persona(db: Session, persona_id: int) -> bool:
    from app.models import Persona
    persona = db.query(Persona).filter(Persona.id == persona_id).first()
    if not persona:
        return False
    db.delete(persona)
    db.commit()
    return True


def _delete_task(db: Session, task_id: int) -> bool:
    from app.models import SunoTask
    task = db.query(SunoTask).filter(SunoTask.id == task_id).first()
    if not task:
        return False
    db.delete(task)
    db.commit()
    return True


def _delete_project(db: Session, project_id: int) -> bool:
    from app.models import AudioProject
    project = db.query(AudioProject).filter(AudioProject.id == project_id).first()
    if not project:
        return False
    db.query(AudioAsset).filter(AudioAsset.project_id == project.id).update({"project_id": None}, synchronize_session=False)
    db.query(Song).filter(Song.project_id == project.id).update({"project_id": None}, synchronize_session=False)
    db.delete(project)
    db.commit()
    return True


def _delete_profile(db: Session, profile_id: int) -> bool:
    from app.models import ProductionProfile
    profile = db.query(ProductionProfile).filter(ProductionProfile.id == profile_id).first()
    if not profile:
        return False
    db.delete(profile)
    db.commit()
    return True



def _clean_title(value: Any) -> str:
    title = str(value or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Titel darf nicht leer sein.")
    if len(title) > 255:
        raise HTTPException(status_code=400, detail=f"Titel ist zu lang. Erlaubt: 255 Zeichen, aktuell: {len(title)}.")
    return title


def _update_content_title(db: Session, content_type: str, item_id: int, title: str) -> dict[str, Any]:
    normalized = _safe_lower(content_type).strip().replace("_", "-")
    new_title = _clean_title(title)

    if normalized in {"audio", "asset", "audio-asset"}:
        asset = db.query(AudioAsset).filter(AudioAsset.id == item_id).first()
        if not asset:
            raise HTTPException(status_code=404, detail="Audio-Datei wurde nicht gefunden.")
        asset.title = new_title
        asset.display_title = new_title
        if asset.song_id:
            song = db.query(Song).filter(Song.id == asset.song_id).first()
            if song:
                song.title = new_title
        id3_result = sync_audio_asset_id3_title(asset, new_title)
        db.add(asset)
        db.commit()
        db.refresh(asset)
        return {"ok": True, "type": "audio", "id": asset.id, "title": asset.display_title or asset.title, "id3_title": id3_result}

    if normalized in {"song", "songs"}:
        song = db.query(Song).filter(Song.id == item_id).first()
        if not song:
            raise HTTPException(status_code=404, detail="Song wurde nicht gefunden.")
        song.title = new_title
        for asset in db.query(AudioAsset).filter(AudioAsset.song_id == song.id).all():
            if not asset.display_title or _safe_lower(asset.display_title).startswith("audio"):
                asset.display_title = new_title
            if not asset.title or _safe_lower(asset.title).startswith("audio"):
                asset.title = new_title
        id3_results = sync_song_assets_id3_title(db, song, new_title)
        db.commit()
        db.refresh(song)
        return {"ok": True, "type": "song", "id": song.id, "title": song.title, "id3_titles": id3_results}

    if normalized in {"lyric", "lyrics", "songtext"}:
        draft = db.query(LyricDraft).filter(LyricDraft.id == item_id).first()
        if not draft:
            raise HTTPException(status_code=404, detail="Songtext wurde nicht gefunden.")
        draft.title = new_title
        db.commit()
        db.refresh(draft)
        return {"ok": True, "type": "lyric", "id": draft.id, "title": draft.title}

    if normalized in {"style", "styles", "music-style"}:
        style = db.query(MusicStyle).filter(MusicStyle.id == item_id).first()
        if not style:
            raise HTTPException(status_code=404, detail="Music Style wurde nicht gefunden.")
        style.name = new_title
        db.commit()
        db.refresh(style)
        return {"ok": True, "type": "style", "id": style.id, "title": style.name}

    if normalized in {"playlist", "playlists"}:
        playlist = db.query(Playlist).filter(Playlist.id == item_id).first()
        if not playlist:
            raise HTTPException(status_code=404, detail="Playlist wurde nicht gefunden.")
        playlist.name = new_title
        db.commit()
        db.refresh(playlist)
        return {"ok": True, "type": "playlist", "id": playlist.id, "title": playlist.name}

    if normalized in {"persona", "personas"}:
        persona = db.query(Persona).filter(Persona.id == item_id).first()
        if not persona:
            raise HTTPException(status_code=404, detail="Persona wurde nicht gefunden.")
        persona.name = new_title
        db.commit()
        db.refresh(persona)
        return {"ok": True, "type": "persona", "id": persona.id, "title": persona.name}

    if normalized in {"project", "projects"}:
        project = db.query(AudioProject).filter(AudioProject.id == item_id).first()
        if not project:
            raise HTTPException(status_code=404, detail="Projekt wurde nicht gefunden.")
        project.title = new_title
        id3_results = sync_project_assets_id3_title(db, project, new_title)
        db.commit()
        db.refresh(project)
        return {"ok": True, "type": "project", "id": project.id, "title": project.title, "id3_titles": id3_results}

    if normalized in {"profile", "production-profile", "production-profiles"}:
        profile = db.query(ProductionProfile).filter(ProductionProfile.id == item_id).first()
        if not profile:
            raise HTTPException(status_code=404, detail="Produktionsprofil wurde nicht gefunden.")
        profile.name = new_title
        db.commit()
        db.refresh(profile)
        return {"ok": True, "type": "production-profile", "id": profile.id, "title": profile.name}

    if normalized in {"task", "tasks"}:
        task = db.query(SunoTask).filter(SunoTask.id == item_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="Task wurde nicht gefunden.")
        request_payload = dict(task.request_payload or {})
        request_payload["title"] = new_title
        task.request_payload = request_payload
        db.commit()
        db.refresh(task)
        return {"ok": True, "type": "task", "id": task.id, "title": new_title}

    raise HTTPException(status_code=400, detail=f"Titelbearbeitung für diesen Inhaltstyp ist nicht unterstützt: {content_type}")




def _get_visible_query(db: Session, model):
    if hasattr(model, "is_deleted"):
        return db.query(model).filter(model.is_deleted.is_(False))
    return db.query(model)


def _get_content_model(normalized_type: str):
    normalized = _safe_lower(normalized_type).strip().replace("_", "-")
    mapping = {
        "audio": AudioAsset,
        "asset": AudioAsset,
        "audio-asset": AudioAsset,
        "song": Song,
        "songs": Song,
        "lyric": LyricDraft,
        "lyrics": LyricDraft,
        "songtext": LyricDraft,
        "style": MusicStyle,
        "styles": MusicStyle,
        "music-style": MusicStyle,
        "playlist": Playlist,
        "playlists": Playlist,
        "persona": Persona,
        "personas": Persona,
        "task": SunoTask,
        "tasks": SunoTask,
        "project": AudioProject,
        "projects": AudioProject,
        "profile": ProductionProfile,
        "production-profile": ProductionProfile,
        "production-profiles": ProductionProfile,
    }
    return mapping.get(normalized)


def _content_title(instance: Any) -> str | None:
    for attr in ("display_title", "title", "name", "task_type", "filename"):
        if hasattr(instance, attr):
            value = getattr(instance, attr)
            if value:
                return str(value)
    if isinstance(instance, SunoTask):
        payload = instance.request_payload or {}
        if isinstance(payload, dict) and payload.get("title"):
            return str(payload["title"])
    return None


def _snapshot(instance: Any) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for attr in (
        "id", "title", "display_title", "name", "task_type", "status", "audio_id", "suno_task_id",
        "task_id", "project_id", "song_id", "is_favorite", "is_final", "is_deleted", "deleted_at",
        "deleted_reason", "local_path", "public_url", "source_url",
    ):
        if hasattr(instance, attr):
            value = getattr(instance, attr)
            data[attr] = value.isoformat() if hasattr(value, "isoformat") else value
    return data


def _log_activity(
    db: Session,
    action: str,
    content_type: str,
    content_id: int | None,
    *,
    old_value: dict[str, Any] | None = None,
    new_value: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    db.add(ActivityLog(
        action=action,
        content_type=content_type,
        content_id=content_id,
        old_value=old_value,
        new_value=new_value,
        metadata_json=metadata,
    ))


def _soft_delete_instance(db: Session, instance: Any, content_type: str, *, reason: str | None = None, metadata: dict[str, Any] | None = None) -> bool:
    if not instance or bool(getattr(instance, "is_deleted", False)):
        return False
    old = _snapshot(instance)
    instance.is_deleted = True
    instance.deleted_at = utc_now_naive()
    instance.deleted_reason = reason or "Vom Benutzer gelöscht"
    _log_activity(db, "soft_delete", content_type, getattr(instance, "id", None), old_value=old, new_value=_snapshot(instance), metadata=metadata)
    return True


def _restore_instance(db: Session, instance: Any, content_type: str, *, metadata: dict[str, Any] | None = None) -> bool:
    if not instance or not bool(getattr(instance, "is_deleted", False)):
        return False
    old = _snapshot(instance)
    instance.is_deleted = False
    instance.deleted_at = None
    instance.deleted_reason = None
    _log_activity(db, "restore", content_type, getattr(instance, "id", None), old_value=old, new_value=_snapshot(instance), metadata=metadata)
    return True


def _get_content_title(db: Session, content_type: str, item_id: int) -> str | None:
    model = _get_content_model(content_type)
    if not model:
        return None
    instance = db.query(model).filter(model.id == item_id).first()
    return _content_title(instance) if instance else None


def _run_full_audio_asset_file_cleanup(db: Session, asset: AudioAsset) -> dict[str, Any]:
    """Entfernt alle lokal erzeugten Begleitdateien eines AudioAssets.

    Wichtig für die Library-Löschung: Ein gelöschter Eintrag darf keine lokale
    Audiodatei, kein Cover, keine SRT, keine WAV- oder Stem-Datei als
    Dateileiche zurücklassen. Die eigentliche DB-Zeile darf als Papierkorb-/
    Audit-Eintrag bestehen bleiben, aber lokale Pfade werden vorher geleert.
    """
    if not asset or not asset.id:
        return {"ok": False, "removed_files": 0, "steps": []}
    from app.routers.audio_assets import delete_audio_asset_content

    steps: list[dict[str, Any]] = []
    removed_files = 0
    for kind in ("stems", "srt", "wav", "cover", "timestamped_lyrics", "waveform", "structure", "audio"):
        try:
            result = delete_audio_asset_content(db, asset.id, kind)
            if isinstance(result, dict):
                removed_files += int(result.get("removed_files") or 0)
                steps.append({"kind": kind, **result})
            else:
                steps.append({"kind": kind, "result": result})
        except HTTPException as exc:
            # Fehlender optionaler Inhalt ist beim Löschen kein Blocker.
            if exc.status_code not in {404, 422}:
                steps.append({"kind": kind, "warning": str(exc.detail)})
        except Exception as exc:  # pragma: no cover - defensiver Löschpfad
            steps.append({"kind": kind, "warning": str(exc)})
    return {"ok": True, "removed_files": removed_files, "steps": steps}


def _find_replacement_audio_asset_for_deleted_asset(db: Session, asset: AudioAsset) -> tuple[AudioAsset | None, str | None]:
    """Findet nur eindeutig gleiche aktive AudioAssets fuer Soft-Delete-Relinks.

    Die Library darf beim Soft-Delete ohne Dateiloeschung keine aktiven
    AudioTranscript-Zeilen an einem geloeschten AudioAsset zuruecklassen.
    Umhaengen ist aber nur korrekt, wenn der Ersatz eindeutig dasselbe Audio
    beschreibt. Deshalb werden nur stabile Identitaetsmerkmale genutzt:
    source_url zuerst, danach audio_id. Song- oder Projektzuordnung waere fuer
    Varianten zu ungenau und wuerde falsche SRT-Zuordnungen riskieren.
    """
    if not asset or not asset.id:
        return None, None

    def single(query: Any, rule: str) -> tuple[AudioAsset | None, str | None]:
        candidates = query.limit(2).all()
        if len(candidates) == 1:
            return candidates[0], rule
        return None, None

    source_url = str(asset.source_url or "").strip()
    if source_url:
        found, rule = single(
            db.query(AudioAsset).filter(
                AudioAsset.id != asset.id,
                AudioAsset.is_deleted.is_(False),
                AudioAsset.source_url == source_url,
            ),
            "same_source_url",
        )
        if found:
            return found, rule

    audio_id = str(asset.audio_id or "").strip()
    if audio_id:
        found, rule = single(
            db.query(AudioAsset).filter(
                AudioAsset.id != asset.id,
                AudioAsset.is_deleted.is_(False),
                AudioAsset.audio_id == audio_id,
            ),
            "same_audio_id",
        )
        if found:
            return found, rule

    return None, None


def _reassign_or_archive_audio_transcripts_for_soft_deleted_asset(db: Session, asset: AudioAsset) -> dict[str, Any]:
    """Verhindert aktive SRT-Orphans beim Soft-Delete ohne Dateiloeschung."""
    if not asset or not asset.id:
        return {"mode": "soft_delete_without_files", "reassigned": 0, "archived": 0, "replacement_audio_asset_id": None}

    transcripts = db.query(AudioTranscript).filter(AudioTranscript.audio_asset_id == asset.id).all()
    if not transcripts:
        return {"mode": "soft_delete_without_files", "reassigned": 0, "archived": 0, "replacement_audio_asset_id": None}

    replacement, replacement_rule = _find_replacement_audio_asset_for_deleted_asset(db, asset)
    now_text = utc_now_naive().isoformat()
    reassigned = 0
    archived = 0

    if replacement:
        for transcript in transcripts:
            transcript.audio_asset_id = replacement.id
            db.add(transcript)
            reassigned += 1
        return {
            "mode": "soft_delete_without_files",
            "reassigned": reassigned,
            "archived": 0,
            "replacement_audio_asset_id": replacement.id,
            "replacement_rule": replacement_rule,
        }

    note = f"Quell-AudioAsset wurde ohne Dateiloeschung soft-geloescht; kein eindeutiger aktiver Ersatz gefunden (alte audio_asset_id={asset.id}, {now_text})."
    for transcript in transcripts:
        status = str(transcript.status or "").strip().lower()
        if status not in {"archived_orphan", "orphaned", "deleted_asset_archived"}:
            transcript.status = "archived_orphan"
        error_message = str(transcript.error_message or "").strip()
        if note not in error_message:
            transcript.error_message = f"{note}\n{error_message}".strip()
        db.add(transcript)
        archived += 1

    return {"mode": "soft_delete_without_files", "reassigned": 0, "archived": archived, "replacement_audio_asset_id": None}


def _has_active_audio_assets_for_task_id(db: Session, task_id: str) -> bool:
    return bool(
        db.query(AudioAsset.id)
        .filter(AudioAsset.suno_task_id == task_id, AudioAsset.is_deleted.is_(False))
        .first()
    )


def _has_active_songs_for_task_id(db: Session, task_id: str) -> bool:
    return bool(
        db.query(Song.id)
        .filter(Song.task_id == task_id, Song.is_deleted.is_(False))
        .first()
    )


def _soft_delete_orphaned_tasks_for_task_ids(db: Session, task_ids: set[str], *, reason: str | None = None, metadata: dict[str, Any] | None = None) -> list[int]:
    deleted_task_ids: list[int] = []
    for task_id in {str(item).strip() for item in task_ids if str(item or "").strip()}:
        if _has_active_audio_assets_for_task_id(db, task_id) or _has_active_songs_for_task_id(db, task_id):
            continue
        for task in db.query(SunoTask).filter(SunoTask.task_id == task_id, SunoTask.is_deleted.is_(False)).all():
            if _soft_delete_instance(db, task, "task", reason=reason or "Letzter Library-Track zur Task-ID gelöscht", metadata=metadata):
                deleted_task_ids.append(task.id)
    return deleted_task_ids


def _soft_delete_orphaned_import_links(db: Session, asset: AudioAsset, *, delete_orphan_song: bool = True, reason: str | None = None) -> dict[str, Any]:
    task_ids = {str(asset.suno_task_id).strip()} if str(asset.suno_task_id or "").strip() else set()
    deleted_song_ids: list[int] = []
    task_local = db.query(SunoTask).filter(SunoTask.id == asset.task_local_id, SunoTask.is_deleted.is_(False)).first() if asset.task_local_id else None
    if task_local and task_local.task_id:
        task_ids.add(str(task_local.task_id).strip())

    if asset.song_id and delete_orphan_song:
        has_active_song_assets = bool(
            db.query(AudioAsset.id)
            .filter(AudioAsset.song_id == asset.song_id, AudioAsset.is_deleted.is_(False))
            .first()
        )
        if not has_active_song_assets:
            song = db.query(Song).filter(Song.id == asset.song_id, Song.is_deleted.is_(False)).first()
            if song:
                if song.task_id:
                    task_ids.add(str(song.task_id).strip())
                if _soft_delete_instance(
                    db,
                    song,
                    "song",
                    reason=reason or "Letzter Library-Track des Songs gelöscht",
                    metadata={"deleted_after_audio_asset_id": asset.id},
                ):
                    deleted_song_ids.append(song.id)

    db.flush()
    deleted_task_ids = _soft_delete_orphaned_tasks_for_task_ids(
        db,
        task_ids,
        reason=reason or "Letzter Library-Track zur Task-ID gelöscht",
        metadata={"deleted_after_audio_asset_id": asset.id, "deleted_song_ids": deleted_song_ids},
    )
    return {"deleted_song_ids": deleted_song_ids, "deleted_task_ids": deleted_task_ids}


def _delete_audio_asset(db: Session, asset_id: int, *, delete_file: bool = True, reason: str | None = None, delete_orphan_song: bool = True) -> bool:
    asset = db.query(AudioAsset).filter(AudioAsset.id == asset_id, AudioAsset.is_deleted.is_(False)).first()
    if not asset:
        return False

    db.query(PlaylistItem).filter(PlaylistItem.audio_asset_id == asset.id).delete(synchronize_session=False)
    for project in db.query(AudioProject).filter(AudioProject.final_audio_asset_id == asset.id).all():
        project.final_audio_asset_id = None
        db.add(project)

    if delete_file:
        cleanup = _run_full_audio_asset_file_cleanup(db, asset)
        transcript_cleanup = {"mode": "delete_with_files", "handled_by": "full_audio_asset_file_cleanup"}
    else:
        cleanup = {"ok": True, "removed_files": 0, "steps": []}
        transcript_cleanup = _reassign_or_archive_audio_transcripts_for_soft_deleted_asset(db, asset)

    deleted = _soft_delete_instance(
        db,
        asset,
        "audio",
        reason=reason,
        metadata={"delete_file_requested": bool(delete_file), "file_cleanup": cleanup, "transcript_cleanup": transcript_cleanup},
    )
    if deleted:
        db.flush()
        _soft_delete_orphaned_import_links(db, asset, delete_orphan_song=delete_orphan_song, reason=reason)
    return deleted


def _delete_song(db: Session, song_id: int, *, delete_files: bool = True, reason: str | None = None) -> bool:
    song = db.query(Song).filter(Song.id == song_id, Song.is_deleted.is_(False)).first()
    if not song:
        return False
    task_ids = {str(song.task_id).strip()} if str(song.task_id or "").strip() else set()
    asset_ids = [row.id for row in db.query(AudioAsset.id).filter(AudioAsset.song_id == song.id, AudioAsset.is_deleted.is_(False)).all()]
    for asset_id in asset_ids:
        _delete_audio_asset(db, asset_id, delete_file=delete_files, reason=reason or "Songgruppe gelöscht", delete_orphan_song=False)
    deleted = _soft_delete_instance(db, song, "song", reason=reason, metadata={"deleted_audio_asset_ids": asset_ids, "delete_files": bool(delete_files)})
    if deleted:
        db.flush()
        _soft_delete_orphaned_tasks_for_task_ids(
            db,
            task_ids,
            reason=reason or "Songgruppe gelöscht",
            metadata={"deleted_after_song_id": song.id, "deleted_audio_asset_ids": asset_ids},
        )
    return deleted


def _delete_lyric(db: Session, lyric_id: int, *, reason: str | None = None) -> bool:
    draft = db.query(LyricDraft).filter(LyricDraft.id == lyric_id, LyricDraft.is_deleted.is_(False)).first()
    return _soft_delete_instance(db, draft, "lyric", reason=reason) if draft else False


def _delete_style(db: Session, style_id: int, *, reason: str | None = None) -> bool:
    style = db.query(MusicStyle).filter(MusicStyle.id == style_id, MusicStyle.is_deleted.is_(False)).first()
    return _soft_delete_instance(db, style, "style", reason=reason) if style else False


def _delete_playlist(db: Session, playlist_id: int, *, reason: str | None = None) -> bool:
    playlist = db.query(Playlist).filter(Playlist.id == playlist_id, Playlist.is_deleted.is_(False)).first()
    return _soft_delete_instance(db, playlist, "playlist", reason=reason) if playlist else False


def _delete_persona(db: Session, persona_id: int, *, reason: str | None = None) -> bool:
    persona = db.query(Persona).filter(Persona.id == persona_id, Persona.is_deleted.is_(False)).first()
    return _soft_delete_instance(db, persona, "persona", reason=reason) if persona else False


def _delete_task(db: Session, task_id: int, *, reason: str | None = None) -> bool:
    task = db.query(SunoTask).filter(SunoTask.id == task_id, SunoTask.is_deleted.is_(False)).first()
    return _soft_delete_instance(db, task, "task", reason=reason) if task else False


def _delete_project(db: Session, project_id: int, *, delete_files: bool = True, reason: str | None = None) -> bool:
    project = db.query(AudioProject).filter(AudioProject.id == project_id, AudioProject.is_deleted.is_(False)).first()
    if not project:
        return False
    asset_ids = [row.id for row in db.query(AudioAsset.id).filter(AudioAsset.project_id == project.id, AudioAsset.is_deleted.is_(False)).all()]
    song_ids = [row.id for row in db.query(Song.id).filter(Song.project_id == project.id, Song.is_deleted.is_(False)).all()]
    for asset_id in asset_ids:
        _delete_audio_asset(db, asset_id, delete_file=delete_files, reason=reason or "Projektgruppe gelöscht")
    for song_id in song_ids:
        song = db.query(Song).filter(Song.id == song_id, Song.is_deleted.is_(False)).first()
        if song:
            _soft_delete_instance(db, song, "song", reason=reason or "Projektgruppe gelöscht", metadata={"project_id": project.id, "delete_files": bool(delete_files)})
    return _soft_delete_instance(db, project, "project", reason=reason, metadata={"deleted_audio_asset_ids": asset_ids, "deleted_song_ids": song_ids, "delete_files": bool(delete_files)})


def _delete_profile(db: Session, profile_id: int, *, reason: str | None = None) -> bool:
    profile = db.query(ProductionProfile).filter(ProductionProfile.id == profile_id, ProductionProfile.is_deleted.is_(False)).first()
    return _soft_delete_instance(db, profile, "production-profile", reason=reason) if profile else False

def _delete_content_item(db: Session, content_type: str, item_id: int, *, delete_files: bool = True, reason: str | None = None) -> bool:
    normalized = _safe_lower(content_type).strip().replace("_", "-")
    handlers = {
        "audio": lambda: _delete_audio_asset(db, item_id, delete_file=delete_files, reason=reason),
        "audio-asset": lambda: _delete_audio_asset(db, item_id, delete_file=delete_files, reason=reason),
        "song": lambda: _delete_song(db, item_id, delete_files=delete_files, reason=reason),
        "lyric": lambda: _delete_lyric(db, item_id, reason=reason),
        "lyrics": lambda: _delete_lyric(db, item_id, reason=reason),
        "style": lambda: _delete_style(db, item_id, reason=reason),
        "playlist": lambda: _delete_playlist(db, item_id, reason=reason),
        "persona": lambda: _delete_persona(db, item_id, reason=reason),
        "task": lambda: _delete_task(db, item_id, reason=reason),
        "project": lambda: _delete_project(db, item_id, delete_files=delete_files, reason=reason),
        "profile": lambda: _delete_profile(db, item_id, reason=reason),
        "production-profile": lambda: _delete_profile(db, item_id, reason=reason),
    }
    handler = handlers.get(normalized)
    if not handler:
        raise HTTPException(status_code=400, detail=f"Unbekannter Inhaltstyp: {content_type}")
    return bool(handler())


@router.get("/content")
def _ilike_or(query_text: str, *columns):
    like = f"%{query_text.strip().lower()}%"
    return or_(*[func.lower(func.coalesce(column, "")).like(like) for column in columns])


def list_library_content(
    q: str | None = None,
    content_type: str = "all",
    status: str = "all",
    limit: int = 300,
    db: Session = Depends(get_db),
):
    limit = max(1, min(limit, 1000))
    requested = _safe_lower(content_type).strip()
    status_filter = _safe_lower(status).strip()
    has_status = status_filter not in {"", "all"}
    ql = q.strip() if q and q.strip() else None
    results: list[dict[str, Any]] = []

    # Schlanke Spaltenauswahl (keine großen JSON/Text-Felder) und q/status-Filter
    # in SQL – so werden Treffer NICHT mehr hinter den neuesten N Zeilen verloren
    # und es werden keine metadata_json/lyrics/profile_json o.ä. geladen.
    if requested in {"all", "audio", "songs"}:
        query = db.query(
            AudioAsset.id, AudioAsset.title, AudioAsset.display_title, AudioAsset.filename,
            AudioAsset.status, AudioAsset.created_at, AudioAsset.updated_at,
        ).filter(AudioAsset.is_deleted.is_(False))
        if has_status:
            query = query.filter(func.lower(AudioAsset.status) == status_filter)
        if ql:
            query = query.filter(_ilike_or(ql, AudioAsset.title, AudioAsset.display_title, AudioAsset.audio_id, AudioAsset.suno_task_id, AudioAsset.source_url, AudioAsset.operation_label))
        for row in query.order_by(AudioAsset.updated_at.desc()).limit(limit).all():
            results.append({"type": "audio", "id": row.id, "title": row.display_title or row.title or row.filename or f"Audio {row.id}", "status": row.status, "created_at": row.created_at, "updated_at": row.updated_at})

    if requested in {"all", "lyrics", "lyric"}:
        query = db.query(LyricDraft.id, LyricDraft.title, LyricDraft.status, LyricDraft.created_at, LyricDraft.updated_at).filter(LyricDraft.is_deleted.is_(False))
        if has_status:
            query = query.filter(func.lower(LyricDraft.status) == status_filter)
        if ql:
            query = query.filter(_ilike_or(ql, LyricDraft.title, LyricDraft.content, LyricDraft.tags, LyricDraft.language))
        for row in query.order_by(LyricDraft.updated_at.desc()).limit(limit).all():
            results.append({"type": "lyric", "id": row.id, "title": row.title, "status": row.status, "created_at": row.created_at, "updated_at": row.updated_at})

    if requested in {"all", "styles", "style"}:
        query = db.query(MusicStyle.id, MusicStyle.name, MusicStyle.is_favorite, MusicStyle.created_at, MusicStyle.updated_at).filter(MusicStyle.is_deleted.is_(False))
        if ql:
            query = query.filter(_ilike_or(ql, MusicStyle.name, MusicStyle.genre, MusicStyle.style_text, MusicStyle.tags, MusicStyle.description))
        for row in query.order_by(MusicStyle.updated_at.desc()).limit(limit).all():
            results.append({"type": "style", "id": row.id, "title": row.name, "status": "favorite" if row.is_favorite else "active", "created_at": row.created_at, "updated_at": row.updated_at})

    if requested in {"all", "playlists", "playlist"}:
        query = db.query(Playlist.id, Playlist.name, Playlist.created_at, Playlist.updated_at).filter(Playlist.is_deleted.is_(False))
        if ql:
            query = query.filter(_ilike_or(ql, Playlist.name, Playlist.description))
        for row in query.order_by(Playlist.updated_at.desc()).limit(limit).all():
            results.append({"type": "playlist", "id": row.id, "title": row.name, "status": "active", "created_at": row.created_at, "updated_at": row.updated_at})

    results.sort(key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""), reverse=True)
    return results[:limit]



@router.patch("/content/{content_type}/{item_id}/title")
def update_library_content_title(content_type: str, item_id: int, payload: dict[str, Any], db: Session = Depends(get_db)):
    old_title = _get_content_title(db, content_type, item_id)
    result = _update_content_title(db, content_type, item_id, payload.get("title"))
    _log_activity(db, "title_update", content_type, item_id, old_value={"title": old_title}, new_value={"title": result.get("title")})
    db.commit()
    return result


@router.put("/content/{content_type}/{item_id}/title")
def put_library_content_title(content_type: str, item_id: int, payload: dict[str, Any], db: Session = Depends(get_db)):
    old_title = _get_content_title(db, content_type, item_id)
    result = _update_content_title(db, content_type, item_id, payload.get("title"))
    _log_activity(db, "title_update", content_type, item_id, old_value={"title": old_title}, new_value={"title": result.get("title")})
    db.commit()
    return result

@router.delete("/content/{content_type}/{item_id}")
def delete_library_content(content_type: str, item_id: int, delete_files: bool = True, db: Session = Depends(get_db)):
    deleted = _delete_content_item(db, content_type, item_id, delete_files=delete_files, reason="Vom Benutzer in der Library gelöscht")
    if not deleted:
        raise HTTPException(status_code=404, detail="Inhalt wurde nicht gefunden oder ist bereits im Papierkorb.")
    db.commit()
    return {"ok": True, "mode": "soft-delete-files-removed" if delete_files else "soft-delete", "delete_files": delete_files, "deleted": [{"type": content_type, "id": item_id}]}


@router.post("/content/bulk-delete")
def bulk_delete_library_content(payload: dict[str, Any], db: Session = Depends(get_db)):
    raw_items = payload.get("items") or []
    delete_files = bool(payload.get("delete_files", True))
    if not isinstance(raw_items, list) or not raw_items:
        raise HTTPException(status_code=400, detail="Keine Inhalte zur Löschung ausgewählt.")

    deleted: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        content_type = str(item.get("type") or "").strip()
        try:
            item_id = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        if not content_type:
            continue
        if _delete_content_item(db, content_type, item_id, delete_files=delete_files, reason="Mehrfachauswahl in der Library gelöscht"):
            deleted.append({"type": content_type, "id": item_id})
        else:
            missing.append({"type": content_type, "id": item_id})

    db.commit()
    return {"ok": True, "mode": "soft-delete-files-removed" if delete_files else "soft-delete", "delete_files": delete_files, "deleted": deleted, "missing": missing, "deleted_count": len(deleted), "missing_count": len(missing)}


@router.get("/content/trash")
def list_trash(q: str | None = None, content_type: str = "all", limit: int = 300, db: Session = Depends(get_db)):
    limit = max(1, min(limit, 1000))
    requested = _safe_lower(content_type).strip()
    models = [
        ("audio", AudioAsset),
        ("song", Song),
        ("lyric", LyricDraft),
        ("style", MusicStyle),
        ("playlist", Playlist),
        ("persona", Persona),
        ("task", SunoTask),
        ("project", AudioProject),
        ("production-profile", ProductionProfile),
    ]
    results: list[dict[str, Any]] = []
    for type_name, model in models:
        if requested not in {"", "all", type_name, f"{type_name}s"}:
            continue
        for item in db.query(model).filter(model.is_deleted.is_(True)).order_by(model.deleted_at.desc(), model.updated_at.desc()).limit(limit).all():
            title = _content_title(item) or f"{type_name} {item.id}"
            if not _match_query(title, getattr(item, "deleted_reason", None), query=q):
                continue
            results.append({
                "type": type_name,
                "id": item.id,
                "title": title,
                "deleted_at": item.deleted_at,
                "deleted_reason": item.deleted_reason,
                "created_at": item.created_at,
                "updated_at": item.updated_at,
            })
    results.sort(key=lambda item: str(item.get("deleted_at") or item.get("updated_at") or ""), reverse=True)
    return results[:limit]


@router.post("/content/{content_type}/{item_id}/restore")
def restore_library_content(content_type: str, item_id: int, db: Session = Depends(get_db)):
    model = _get_content_model(content_type)
    if not model:
        raise HTTPException(status_code=400, detail=f"Unbekannter Inhaltstyp: {content_type}")
    instance = db.query(model).filter(model.id == item_id, model.is_deleted.is_(True)).first()
    if not instance:
        raise HTTPException(status_code=404, detail="Inhalt wurde im Papierkorb nicht gefunden.")
    _restore_instance(db, instance, content_type)
    db.commit()
    return {"ok": True, "restored": {"type": content_type, "id": item_id}}


def _purge_instance(db: Session, instance: Any, content_type: str, *, delete_files: bool = True) -> bool:
    if not instance:
        return False
    old = _snapshot(instance)
    if isinstance(instance, AudioAsset):
        db.query(PlaylistItem).filter(PlaylistItem.audio_asset_id == instance.id).delete(synchronize_session=False)
        for project in db.query(AudioProject).filter(AudioProject.final_audio_asset_id == instance.id).all():
            project.final_audio_asset_id = None
        if delete_files:
            _run_full_audio_asset_file_cleanup(db, instance)
        db.delete(instance)
    elif isinstance(instance, Song):
        db.query(PlaylistItem).filter(PlaylistItem.song_id == instance.id).delete(synchronize_session=False)
        db.query(AudioAsset).filter(AudioAsset.song_id == instance.id).update({"song_id": None}, synchronize_session=False)
        db.delete(instance)
    elif isinstance(instance, Playlist):
        db.query(PlaylistItem).filter(PlaylistItem.playlist_id == instance.id).delete(synchronize_session=False)
        db.delete(instance)
    elif isinstance(instance, AudioProject):
        db.query(AudioAsset).filter(AudioAsset.project_id == instance.id).update({"project_id": None}, synchronize_session=False)
        db.query(Song).filter(Song.project_id == instance.id).update({"project_id": None}, synchronize_session=False)
        db.delete(instance)
    else:
        db.delete(instance)
    _log_activity(db, "purge", content_type, old.get("id"), old_value=old, new_value=None, metadata={"delete_files": delete_files})
    return True


@router.delete("/content/{content_type}/{item_id}/purge")
def purge_library_content(content_type: str, item_id: int, delete_files: bool = True, db: Session = Depends(get_db)):
    model = _get_content_model(content_type)
    if not model:
        raise HTTPException(status_code=400, detail=f"Unbekannter Inhaltstyp: {content_type}")
    instance = db.query(model).filter(model.id == item_id, model.is_deleted.is_(True)).first()
    if not instance:
        raise HTTPException(status_code=404, detail="Inhalt wurde im Papierkorb nicht gefunden.")
    _purge_instance(db, instance, content_type, delete_files=delete_files)
    db.commit()
    return {"ok": True, "purged": {"type": content_type, "id": item_id}}


@router.post("/content/bulk-restore")
def bulk_restore_library_content(payload: dict[str, Any], db: Session = Depends(get_db)):
    raw_items = payload.get("items") or []
    restored: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        content_type = str(item.get("type") or "").strip()
        try:
            item_id = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        model = _get_content_model(content_type)
        instance = db.query(model).filter(model.id == item_id, model.is_deleted.is_(True)).first() if model else None
        if instance and _restore_instance(db, instance, content_type, metadata={"bulk": True}):
            restored.append({"type": content_type, "id": item_id})
        else:
            missing.append({"type": content_type, "id": item_id})
    db.commit()
    return {"ok": True, "restored": restored, "missing": missing, "restored_count": len(restored), "missing_count": len(missing)}


def _sanitize_cover_stem(value: Any, fallback: str = "cover") -> str:
    raw = str(value or fallback).strip() or fallback
    raw = re.sub(r"[^A-Za-z0-9ÄÖÜäöüß._ -]+", "_", raw)
    raw = re.sub(r"\s+", "_", raw).strip("._- ")
    return (raw or fallback)[:96]


def _write_library_cover_upload(upload: UploadFile, title: str, token: str) -> dict[str, Any]:
    if not upload or not upload.filename:
        raise HTTPException(status_code=400, detail="Keine Cover-Datei hochgeladen.")
    settings = get_settings()
    extension = Path(upload.filename).suffix.lower()
    if extension not in settings.cover_allowed_extensions_list:
        raise HTTPException(status_code=422, detail=f"Ungültiges Cover-Format: {extension or 'unbekannt'}")
    if upload.content_type and upload.content_type.lower() not in settings.cover_allowed_content_types_list:
        raise HTTPException(status_code=422, detail=f"Ungültiger Cover-Content-Type: {upload.content_type}")
    root = settings.cover_storage_path
    root.mkdir(parents=True, exist_ok=True)
    filename = f"{_sanitize_cover_stem(title, 'cover')}_{_sanitize_cover_stem(token, 'item')}_{utc_now_naive().strftime('%Y%m%d_%H%M%S_%f')}{extension}"
    target = (root / filename).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Ungültiger Cover-Speicherpfad.") from exc
    digest = hashlib.sha256()
    total = 0
    with target.open("wb") as handle:
        while True:
            chunk = upload.file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > settings.cover_max_download_bytes:
                target.unlink(missing_ok=True)
                raise HTTPException(status_code=422, detail=f"Cover überschreitet {settings.suno_cover_max_download_mb} MB.")
            digest.update(chunk)
            handle.write(chunk)
    if total <= 0:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="Cover-Datei ist leer.")
    public_route = settings.suno_cover_public_route.rstrip("/")
    public_url = f"{public_route}/{filename}"
    return {
        "local_path": to_portable_path(target, storage_root=root),
        "public_url": public_url,
        "filename": filename,
        "content_type": upload.content_type or mimetypes.guess_type(filename)[0] or "image/*",
        "file_size_bytes": total,
        "checksum_sha256": digest.hexdigest(),
        "cached_at": utc_now_naive().isoformat(),
        "source": "library_manual_cover_upload",
    }


def _apply_cover_info_to_asset(asset: AudioAsset, cover_info: dict[str, Any]) -> None:
    metadata = dict(asset.metadata_json or {})
    if asset.image_url and str(asset.image_url).startswith((get_settings().suno_cover_public_route.rstrip("/") + "/")):
        metadata.setdefault("previous_cover_urls", [])
        if isinstance(metadata["previous_cover_urls"], list):
            metadata["previous_cover_urls"] = (metadata["previous_cover_urls"] + [asset.image_url])[-10:]
    metadata["cover_cache"] = dict(cover_info)
    metadata["manual_cover_updated_at"] = utc_now_naive().isoformat()
    asset.image_url = cover_info.get("public_url")
    asset.metadata_json = metadata


def _apply_cover_info_to_song(song: Song, cover_info: dict[str, Any]) -> None:
    metadata = dict(song.metadata_json or {})
    metadata["cover_cache"] = dict(cover_info)
    metadata["manual_cover_updated_at"] = utc_now_naive().isoformat()
    song.cover_image_url = cover_info.get("public_url")
    song.metadata_json = metadata


def _apply_cover_info_to_project(project: AudioProject, cover_info: dict[str, Any]) -> None:
    metadata = dict(project.metadata_json or {})
    metadata["cover_cache"] = dict(cover_info)
    metadata["manual_cover_updated_at"] = utc_now_naive().isoformat()
    project.cover_image_url = cover_info.get("public_url")
    project.metadata_json = metadata


@router.post("/content/{content_type}/{item_id}/cover")
async def update_library_content_cover(content_type: str, item_id: int, cover: UploadFile = File(...), db: Session = Depends(get_db)):
    normalized = _safe_lower(content_type).strip().replace("_", "-")
    title = _get_content_title(db, normalized, item_id) or f"{normalized}_{item_id}"
    cover_info = _write_library_cover_upload(cover, title, f"{normalized}_{item_id}")
    updated_assets: list[int] = []
    updated_songs: list[int] = []
    updated_projects: list[int] = []

    if normalized in {"audio", "asset", "audio-asset"}:
        asset = db.query(AudioAsset).filter(AudioAsset.id == item_id, AudioAsset.is_deleted.is_(False)).first()
        if not asset:
            raise HTTPException(status_code=404, detail="AudioAsset wurde nicht gefunden.")
        _apply_cover_info_to_asset(asset, cover_info)
        updated_assets.append(asset.id)
        if asset.song_id:
            song = db.query(Song).filter(Song.id == asset.song_id, Song.is_deleted.is_(False)).first()
            if song:
                _apply_cover_info_to_song(song, cover_info)
                updated_songs.append(song.id)
        if asset.project_id:
            project = db.query(AudioProject).filter(AudioProject.id == asset.project_id, AudioProject.is_deleted.is_(False)).first()
            if project:
                _apply_cover_info_to_project(project, cover_info)
                updated_projects.append(project.id)
    elif normalized in {"song", "songs"}:
        song = db.query(Song).filter(Song.id == item_id, Song.is_deleted.is_(False)).first()
        if not song:
            raise HTTPException(status_code=404, detail="Song wurde nicht gefunden.")
        _apply_cover_info_to_song(song, cover_info)
        updated_songs.append(song.id)
        for asset in db.query(AudioAsset).filter(AudioAsset.song_id == song.id, AudioAsset.is_deleted.is_(False)).all():
            _apply_cover_info_to_asset(asset, cover_info)
            updated_assets.append(asset.id)
    elif normalized in {"project", "projects"}:
        project = db.query(AudioProject).filter(AudioProject.id == item_id, AudioProject.is_deleted.is_(False)).first()
        if not project:
            raise HTTPException(status_code=404, detail="Projekt wurde nicht gefunden.")
        _apply_cover_info_to_project(project, cover_info)
        updated_projects.append(project.id)
        for song in db.query(Song).filter(Song.project_id == project.id, Song.is_deleted.is_(False)).all():
            _apply_cover_info_to_song(song, cover_info)
            updated_songs.append(song.id)
        for asset in db.query(AudioAsset).filter(AudioAsset.project_id == project.id, AudioAsset.is_deleted.is_(False)).all():
            _apply_cover_info_to_asset(asset, cover_info)
            updated_assets.append(asset.id)
    else:
        raise HTTPException(status_code=400, detail=f"Cover-Bearbeitung für diesen Inhaltstyp ist nicht unterstützt: {content_type}")

    _log_activity(db, "cover_update", normalized, item_id, new_value={"cover_url": cover_info.get("public_url")}, metadata={"updated_audio_asset_ids": updated_assets, "updated_song_ids": updated_songs, "updated_project_ids": updated_projects})
    target_audio_asset_id = updated_assets[0] if updated_assets else None
    target_payload = {
        "target_tab": "library",
        "content_type": normalized,
        "content_id": item_id,
        "audio_asset_id": target_audio_asset_id,
        "audio_asset_ids": updated_assets,
        "song_ids": updated_songs,
        "project_ids": updated_projects,
        "cover_url": cover_info.get("public_url"),
        "status": "SUCCESS",
    }
    create_system_status_notification(
        db,
        event_type="library_cover_uploaded",
        title=f"Upload-Cover gespeichert: {title}",
        message="Das Cover wurde lokal gespeichert und der Library zugewiesen.",
        severity="success",
        target_tab="library" if target_audio_asset_id else "status",
        target_payload=target_payload,
        content_type="audio" if target_audio_asset_id else normalized,
        content_id=target_audio_asset_id or item_id,
        commit=False,
    )
    db.commit()
    return {"ok": True, "cover": cover_info, "updated_audio_asset_ids": updated_assets, "updated_song_ids": updated_songs, "updated_project_ids": updated_projects}


@router.post("/content/bulk-purge")
def bulk_purge_library_content(payload: dict[str, Any], db: Session = Depends(get_db)):
    raw_items = payload.get("items") or []
    delete_files = bool(payload.get("delete_files", True))
    purged: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        content_type = str(item.get("type") or "").strip()
        try:
            item_id = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        model = _get_content_model(content_type)
        instance = db.query(model).filter(model.id == item_id, model.is_deleted.is_(True)).first() if model else None
        if instance and _purge_instance(db, instance, content_type, delete_files=delete_files):
            purged.append({"type": content_type, "id": item_id})
        else:
            missing.append({"type": content_type, "id": item_id})
    db.commit()
    return {"ok": True, "purged": purged, "missing": missing, "purged_count": len(purged), "missing_count": len(missing)}


@router.get("/activity")
def list_activity(content_type: str | None = None, content_id: int | None = None, limit: int = 200, db: Session = Depends(get_db)):
    limit = max(1, min(limit, 1000))
    query = db.query(ActivityLog)
    if content_type:
        query = query.filter(ActivityLog.content_type == content_type)
    if content_id is not None:
        query = query.filter(ActivityLog.content_id == content_id)
    return query.order_by(ActivityLog.created_at.desc()).limit(limit).all()

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models import ActivityLog, AudioAsset, AudioProject, AudioTranscript, MusicStyle, StatusNotification, SunoTask
from app.utils.time_utils import utc_now_naive

PRODUCTION_META_KEY = "production_suite"
READINESS_CHECKS = [
    {"key": "audio", "label": "Audio vorhanden", "weight": 20},
    {"key": "lyrics", "label": "Songtext/Prompt vorhanden", "weight": 15},
    {"key": "style", "label": "Suno-Style vorhanden", "weight": 10},
    {"key": "cover", "label": "Cover vorhanden", "weight": 10},
    {"key": "srt", "label": "SRT erzeugt", "weight": 15},
    {"key": "stems", "label": "Stems vorhanden", "weight": 10},
    {"key": "rating", "label": "Bewertung gesetzt", "weight": 8},
    {"key": "youtube", "label": "YouTube-Metadaten vorbereitet", "weight": 7},
    {"key": "final", "label": "Final markiert", "weight": 5},
]

DEFAULT_PRODUCTION_STATE: dict[str, Any] = {
    "production_status": "draft",
    "rating": 0,
    "energy": 0,
    "hook_strength": 0,
    "lyrics_quality": 0,
    "mix_quality": 0,
    "release_ready": False,
    "youtube_ready": False,
    "video_ready": False,
    "notes": "",
    "youtube_title": "",
    "youtube_playlist": "",
    "youtube_description": "",
    "youtube_tags": [],
    "genre": "",
    "mood": "",
    "todo": [],
    "checkpoints": {},
    "updated_at": None,
}

ROADMAP: list[dict[str, Any]] = [
    {
        "key": "library",
        "title": "Library als Produktionszentrale",
        "status": "implemented_foundation",
        "items": [
            "Produktionsstatus pro Audio",
            "Bewertung, Energie, Hook, Lyrics- und Mixqualität",
            "Release-/YouTube-/Video-Readiness",
            "Audit-/Ereignisverlauf pro Track",
            "Versionsduplikat ohne Dateikopie",
        ],
    },
    {
        "key": "song_wizard",
        "title": "Song-Erstellungs-Wizard",
        "status": "prepared",
        "items": [
            "Style-Presets über MusicStyle-Profil-Presets",
            "Wiederverwenden/Extend-Ketten bleiben über vorhandenes Frontend aktiv",
            "Produktionsprofil-Metadaten können später direkt in MusicPage einfließen",
        ],
    },
    {
        "key": "lyrics",
        "title": "Lyrics Studio / Rap-Analyse",
        "status": "planned_backend_safe",
        "items": [
            "Lyrics vorhanden/fehlend wird in Readiness bewertet",
            "Qualitätswerte werden trackbezogen gespeichert",
            "Tiefe Silben-/Reimprüfung bleibt separat, damit bestehende Lyrics-Funktionen nicht beschädigt werden",
        ],
    },
    {
        "key": "srt_video",
        "title": "SRT / Musikvideo-Workflow",
        "status": "implemented_foundation",
        "items": [
            "SRT-Erkennung pro Track",
            "Musikvideo-Plan aus vorhandener SRT oder Lyrics-Struktur",
            "YouTube-/Video-Export-Vorbereitung ohne Änderung der bestehenden SRT-Kette",
        ],
    },
    {
        "key": "daw_quality",
        "title": "Mini-DAW / Qualitätsanalyse",
        "status": "implemented_foundation",
        "items": [
            "Basis-Audio-Metadaten werden in Readiness berücksichtigt",
            "Mixqualität kann manuell gepflegt werden",
            "Tiefe LUFS/Peak-Analyse bleibt eigener Audio-Job, damit kein FFMPEG-Zwang im Cockpit entsteht",
        ],
    },
    {
        "key": "admin_ops",
        "title": "Admin / Betrieb / Debugging",
        "status": "implemented_foundation",
        "items": [
            "Cockpit zählt offene Tasks, Benachrichtigungen, SRT, Stems, YouTube-ready",
            "Track-Ereignisse aus ActivityLog, StatusNotification und SunoTask",
            "Keine neue Pflichtmigration für Bestandsdaten",
        ],
    },
    {
        "key": "export_publish",
        "title": "Export / Veröffentlichung",
        "status": "implemented_foundation",
        "items": [
            "YouTube-Paket pro Track",
            "Projekt-Produktionsreport",
            "vollständiger Projekt-ZIP-Export mit Audio/Cover/SRT/Manifest wo lokal verfügbar",
        ],
    },
]

STYLE_PRESETS: list[dict[str, Any]] = [
    {
        "name": "KlangNeural Deutschrap Storytelling",
        "genre": "Deutschrap",
        "bpm": 96,
        "style_text": "German rap storytelling, emotional male rap vocals, cinematic piano, warm bass, clear hook, polished radio-ready mix",
        "description": "Story-Rap mit klarer Hook und Suno-kompatibler Struktur.",
        "tags": "deutschrap,storytelling,hook,cinematic",
        "profile_json": {"preset_type": "song_wizard", "language": "de", "structure": "Intro, Verse 1, Hook, Verse 2, Hook, Outro"},
    },
    {
        "name": "KlangNeural Dirty Boom Bap",
        "genre": "Boom Bap",
        "bpm": 92,
        "style_text": "grimy 90s boom bap, dusty drums, dark piano loop, aggressive German male rap, raw street ambience, strong bassline",
        "description": "Dreckiger Rap-Workflow für harte Verse und stabile Headnod-Beats.",
        "tags": "boombap,dirty,rap,90s",
        "profile_json": {"preset_type": "song_wizard", "language": "de", "negative_tags": "clean pop, overly happy, EDM drop"},
    },
    {
        "name": "KlangNeural Dancehall Rap",
        "genre": "Rap/Dancehall",
        "bpm": 101,
        "style_text": "German rap dancehall, bouncy drums, warm Caribbean rhythm, catchy male hook, summer night vibe, modern polished mix",
        "description": "Für Rap/Dancehall-Hooks und lockere, tanzbare Tracks.",
        "tags": "dancehall,rap,bouncy,hook",
        "profile_json": {"preset_type": "song_wizard", "language": "de", "hook_focus": True},
    },
    {
        "name": "KlangNeural Horror Comedy Rap",
        "genre": "Comedy Rap",
        "bpm": 98,
        "style_text": "dark comedic German rap, eerie cartoon horror atmosphere, gritty drums, theatrical male rap delivery, catchy absurd hook",
        "description": "Für witzige, düstere Storysongs mit starker Bildsprache.",
        "tags": "comedy,horror,rap,story",
        "profile_json": {"preset_type": "song_wizard", "language": "de", "video_ready": True},
    },
]


def utc_now_iso() -> str:
    return utc_now_naive().replace(microsecond=0).isoformat()


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def clamp_score(value: Any) -> int:
    return max(0, min(5, safe_int(value, 0)))


def get_asset_or_none(db: Session, asset_id: int) -> AudioAsset | None:
    return db.query(AudioAsset).filter(AudioAsset.id == asset_id, AudioAsset.is_deleted.is_(False)).first()


def get_project_or_none(db: Session, project_id: int) -> AudioProject | None:
    return db.query(AudioProject).filter(AudioProject.id == project_id, AudioProject.is_deleted.is_(False)).first()


def metadata_dict(obj: Any) -> dict[str, Any]:
    value = getattr(obj, "metadata_json", None)
    return dict(value) if isinstance(value, dict) else {}


def production_state(asset: AudioAsset) -> dict[str, Any]:
    metadata = metadata_dict(asset)
    stored = metadata.get(PRODUCTION_META_KEY)
    if not isinstance(stored, dict):
        stored = {}
    state = {**DEFAULT_PRODUCTION_STATE, **stored}
    state["rating"] = clamp_score(state.get("rating"))
    state["energy"] = clamp_score(state.get("energy"))
    state["hook_strength"] = clamp_score(state.get("hook_strength"))
    state["lyrics_quality"] = clamp_score(state.get("lyrics_quality"))
    state["mix_quality"] = clamp_score(state.get("mix_quality"))
    if not isinstance(state.get("youtube_tags"), list):
        raw_tags = state.get("youtube_tags")
        state["youtube_tags"] = [item.strip() for item in str(raw_tags or "").split(",") if item.strip()]
    if not isinstance(state.get("todo"), list):
        state["todo"] = [item.strip() for item in str(state.get("todo") or "").split("\n") if item.strip()]
    if not isinstance(state.get("checkpoints"), dict):
        state["checkpoints"] = {}
    return state


def set_production_state(db: Session, asset: AudioAsset, patch: dict[str, Any]) -> dict[str, Any]:
    current = production_state(asset)
    allowed = set(DEFAULT_PRODUCTION_STATE.keys()) | {"custom"}
    next_state = dict(current)
    for key, value in patch.items():
        if key not in allowed:
            continue
        if key in {"rating", "energy", "hook_strength", "lyrics_quality", "mix_quality"}:
            next_state[key] = clamp_score(value)
        elif key in {"release_ready", "youtube_ready", "video_ready"}:
            next_state[key] = bool(value)
        elif key == "youtube_tags":
            if isinstance(value, list):
                next_state[key] = [str(item).strip() for item in value if str(item).strip()]
            else:
                next_state[key] = [item.strip() for item in str(value or "").split(",") if item.strip()]
        elif key == "todo":
            if isinstance(value, list):
                next_state[key] = [str(item).strip() for item in value if str(item).strip()]
            else:
                next_state[key] = [item.strip() for item in str(value or "").split("\n") if item.strip()]
        elif key == "checkpoints":
            next_state[key] = dict(value) if isinstance(value, dict) else {}
        else:
            next_state[key] = value
    next_state["updated_at"] = utc_now_iso()
    metadata = metadata_dict(asset)
    metadata[PRODUCTION_META_KEY] = next_state
    asset.metadata_json = metadata
    db.add(asset)
    db.add(ActivityLog(
        action="production_state_update",
        content_type="audio_asset",
        content_id=asset.id,
        old_value={PRODUCTION_META_KEY: current},
        new_value={PRODUCTION_META_KEY: next_state},
        metadata_json={"source": "production_suite"},
    ))
    db.commit()
    db.refresh(asset)
    return production_state(asset)


def latest_transcript(db: Session, asset_id: int) -> AudioTranscript | None:
    return (
        db.query(AudioTranscript)
        .filter(AudioTranscript.audio_asset_id == asset_id)
        .order_by(AudioTranscript.updated_at.desc(), AudioTranscript.id.desc())
        .first()
    )


def has_completed_transcript(db: Session, asset_id: int) -> bool:
    transcript = latest_transcript(db, asset_id)
    return bool(transcript and transcript.status == "completed" and (transcript.srt_text or transcript.srt_path or transcript.segments_json))


def has_stems(asset: AudioAsset) -> bool:
    metadata = metadata_dict(asset)
    stems = metadata.get("stems")
    if not isinstance(stems, dict):
        return False
    files = stems.get("files")
    if not isinstance(files, dict):
        return False
    return any(bool(value) for value in files.values())


def asset_prompt(asset: AudioAsset) -> str:
    return str(asset.prompt or asset.lyrics or "").strip()


def asset_style(asset: AudioAsset) -> str:
    return str(asset.style or asset.tags or "").strip()


def asset_title(asset: AudioAsset) -> str:
    return str(asset.display_title or asset.title or asset.filename or f"Audio #{asset.id}").strip()


def analyze_asset_readiness(db: Session, asset: AudioAsset) -> dict[str, Any]:
    state = production_state(asset)
    youtube_ready = bool(state.get("youtube_ready") or (state.get("youtube_title") and state.get("youtube_playlist")))
    checks = {
        "audio": bool(asset.public_url or asset.source_url or asset.local_path or asset.filename),
        "lyrics": bool(asset_prompt(asset)),
        "style": bool(asset_style(asset)),
        "cover": bool(asset.cover_local_url or asset.image_url or asset.source_image_url),
        "srt": has_completed_transcript(db, asset.id),
        "stems": has_stems(asset),
        "rating": safe_int(state.get("rating"), 0) > 0,
        "youtube": youtube_ready,
        "final": bool(asset.is_final or state.get("release_ready")),
    }
    weighted_score = 0
    total_weight = sum(item["weight"] for item in READINESS_CHECKS)
    details: list[dict[str, Any]] = []
    missing: list[str] = []
    for item in READINESS_CHECKS:
        passed = bool(checks.get(item["key"]))
        if passed:
            weighted_score += item["weight"]
        else:
            missing.append(item["label"])
        details.append({**item, "passed": passed})
    score = round((weighted_score / total_weight) * 100) if total_weight else 0
    if score >= 90:
        level = "release_ready"
        label = "Release-ready"
    elif score >= 70:
        level = "nearly_ready"
        label = "Fast fertig"
    elif score >= 45:
        level = "in_progress"
        label = "In Arbeit"
    else:
        level = "draft"
        label = "Entwurf"
    return {
        "asset_id": asset.id,
        "score": score,
        "level": level,
        "label": label,
        "checks": details,
        "missing": missing,
        "state": state,
        "recommended_next_actions": recommended_next_actions(asset, checks, state),
    }


def recommended_next_actions(asset: AudioAsset, checks: dict[str, bool], state: dict[str, Any]) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []
    if not checks.get("lyrics"):
        actions.append({"key": "lyrics", "label": "Songtext ergänzen", "target": "library"})
    if not checks.get("style"):
        actions.append({"key": "style", "label": "Suno-Style ergänzen", "target": "library"})
    if not checks.get("srt"):
        actions.append({"key": "srt", "label": "SRT erzeugen", "target": "library"})
    if not checks.get("stems"):
        actions.append({"key": "stems", "label": "Stems erzeugen", "target": "library"})
    if not checks.get("youtube"):
        actions.append({"key": "youtube", "label": "YouTube-Daten vorbereiten", "target": "production"})
    if safe_int(state.get("rating"), 0) <= 0:
        actions.append({"key": "rating", "label": "Track bewerten", "target": "production"})
    if not asset.is_final:
        actions.append({"key": "final", "label": "Finale Version markieren", "target": "library"})
    return actions[:5]


def compact_asset_dict(db: Session, asset: AudioAsset) -> dict[str, Any]:
    return {
        "id": asset.id,
        "title": asset.title,
        "display_title": asset.display_title,
        "filename": asset.filename,
        "project_id": asset.project_id,
        "song_id": asset.song_id,
        "audio_id": asset.audio_id,
        "suno_task_id": asset.suno_task_id,
        "operation_label": asset.operation_label,
        "version_label": asset.version_label,
        "is_favorite": bool(asset.is_favorite),
        "is_final": bool(asset.is_final),
        "duration_seconds": asset.duration_seconds,
        "public_url": asset.public_url,
        "source_url": asset.source_url,
        "image_url": asset.image_url,
        "cover_local_url": asset.cover_local_url,
        "status": asset.status,
        "created_at": asset.created_at,
        "updated_at": asset.updated_at,
        "prompt": asset.prompt,
        "lyrics": asset.lyrics,
        "style": asset.style,
        "production": production_state(asset),
        "readiness": analyze_asset_readiness(db, asset),
    }


def project_summary(db: Session, project: AudioProject) -> dict[str, Any]:
    assets = db.query(AudioAsset).filter(AudioAsset.project_id == project.id, AudioAsset.is_deleted.is_(False)).order_by(AudioAsset.created_at.asc(), AudioAsset.id.asc()).all()
    analyzed = [analyze_asset_readiness(db, asset) for asset in assets]
    scores = [item["score"] for item in analyzed]
    return {
        "id": project.id,
        "title": project.title,
        "status": project.status,
        "is_favorite": bool(project.is_favorite),
        "final_audio_asset_id": project.final_audio_asset_id,
        "cover_image_url": project.cover_image_url or next((asset.image_url for asset in assets if asset.image_url), None),
        "asset_count": len(assets),
        "ready_count": sum(1 for item in analyzed if item["score"] >= 90),
        "average_readiness": round(sum(scores) / len(scores)) if scores else 0,
        "assets": [compact_asset_dict(db, asset) for asset in assets],
        "created_at": project.created_at,
        "updated_at": project.updated_at,
    }


def cockpit_payload(db: Session, limit: int = 40) -> dict[str, Any]:
    assets = db.query(AudioAsset).filter(AudioAsset.is_deleted.is_(False)).order_by(AudioAsset.updated_at.desc(), AudioAsset.id.desc()).limit(max(1, min(limit, 200))).all()
    projects = db.query(AudioProject).filter(AudioProject.is_deleted.is_(False)).order_by(AudioProject.updated_at.desc(), AudioProject.id.desc()).limit(20).all()
    analyzed = [compact_asset_dict(db, asset) for asset in assets]
    counts = {
        "audio_assets": db.query(func.count(AudioAsset.id)).filter(AudioAsset.is_deleted.is_(False)).scalar() or 0,
        "projects": db.query(func.count(AudioProject.id)).filter(AudioProject.is_deleted.is_(False)).scalar() or 0,
        "release_ready": sum(1 for item in analyzed if item["readiness"]["score"] >= 90),
        "youtube_ready": sum(1 for item in analyzed if item["production"].get("youtube_ready") or item["production"].get("youtube_title")),
        "needs_srt": sum(1 for item in analyzed if not any(check["key"] == "srt" and check["passed"] for check in item["readiness"]["checks"])),
        "needs_stems": sum(1 for item in analyzed if not any(check["key"] == "stems" and check["passed"] for check in item["readiness"]["checks"])),
        "open_tasks": db.query(func.count(SunoTask.id)).filter(SunoTask.is_deleted.is_(False), SunoTask.status.in_(["created", "pending", "running", "submitted", "processing"])).scalar() or 0,
        "open_notifications": db.query(func.count(StatusNotification.id)).filter(StatusNotification.is_deleted.is_(False), StatusNotification.status != "done").scalar() or 0,
    }
    return {
        "generated_at": utc_now_iso(),
        "counts": counts,
        "roadmap": ROADMAP,
        "assets": analyzed,
        "projects": [project_summary(db, project) for project in projects],
    }


def build_youtube_package(db: Session, asset: AudioAsset) -> dict[str, Any]:
    state = production_state(asset)
    title = str(state.get("youtube_title") or asset_title(asset)).strip()
    playlist = str(state.get("youtube_playlist") or infer_playlist(asset)).strip()
    tags = state.get("youtube_tags") if isinstance(state.get("youtube_tags"), list) else []
    if not tags:
        tags = infer_tags(asset)
    lyrics = asset_prompt(asset)
    style = asset_style(asset)
    description = str(state.get("youtube_description") or "").strip()
    if not description:
        description = "\n".join(line for line in [
            f"{title}",
            "",
            "Produziert mit KlangNeural / Suno Song Studio.",
            f"Style: {style}" if style else "",
            "",
            "Lyrics:",
            lyrics[:4000] if lyrics else "",
        ] if line is not None)
    package = {
        "asset_id": asset.id,
        "title": title,
        "playlist": playlist,
        "description": description,
        "tags": tags[:20],
        "chapters": build_chapters_from_transcript(db, asset),
        "readiness": analyze_asset_readiness(db, asset),
    }
    package["text"] = youtube_package_text(package)
    return package


def infer_playlist(asset: AudioAsset) -> str:
    text = " ".join([asset_title(asset), asset_style(asset), asset_prompt(asset)]).lower()
    if "dancehall" in text or "reggae" in text:
        return "Rap / Dancehall"
    if "boom bap" in text or "boombap" in text:
        return "Deutschrap / Boom Bap"
    if "horror" in text or "dark" in text or "düster" in text:
        return "Dark Rap / Story Rap"
    if "comedy" in text or "witz" in text or "lustig" in text:
        return "Comedy Rap"
    return "Deutschrap"


def infer_tags(asset: AudioAsset) -> list[str]:
    base = ["KlangNeural", "Deutschrap", "Suno", "AI Music"]
    style = asset_style(asset)
    if style:
        for item in style.replace(";", ",").split(","):
            clean = item.strip()
            if clean and clean.lower() not in {tag.lower() for tag in base}:
                base.append(clean[:40])
            if len(base) >= 12:
                break
    return base


def build_chapters_from_transcript(db: Session, asset: AudioAsset) -> list[dict[str, Any]]:
    transcript = latest_transcript(db, asset.id)
    segments = transcript.segments_json if transcript and isinstance(transcript.segments_json, list) else []
    chapters: list[dict[str, Any]] = []
    for index, segment in enumerate(segments[:12], start=1):
        start = safe_float(segment.get("start") if isinstance(segment, dict) else None)
        text = str(segment.get("text") if isinstance(segment, dict) else "").strip()
        if index == 1 or index % 4 == 1:
            chapters.append({"time": seconds_to_chapter_time(start), "label": text[:60] or f"Part {index}"})
    if not chapters:
        chapters.append({"time": "0:00", "label": asset_title(asset)})
    return chapters


def seconds_to_chapter_time(value: float) -> str:
    total = max(0, int(value))
    minutes, seconds = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def youtube_package_text(package: dict[str, Any]) -> str:
    lines = [
        f"Titel: {package.get('title') or ''}",
        f"Playlist: {package.get('playlist') or ''}",
        "",
        "Beschreibung:",
        str(package.get("description") or "").strip(),
        "",
        "Kapitel:",
    ]
    for chapter in package.get("chapters") or []:
        lines.append(f"{chapter.get('time')} {chapter.get('label')}")
    lines.extend(["", "Tags:", ", ".join(package.get("tags") or [])])
    return "\n".join(lines).strip() + "\n"


def build_video_plan(db: Session, asset: AudioAsset) -> dict[str, Any]:
    transcript = latest_transcript(db, asset.id)
    segments = transcript.segments_json if transcript and isinstance(transcript.segments_json, list) else []
    scenes: list[dict[str, Any]] = []
    if segments:
        bucket: list[dict[str, Any]] = []
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            bucket.append(segment)
            if len(bucket) >= 4:
                scenes.append(scene_from_bucket(len(scenes) + 1, bucket, asset))
                bucket = []
        if bucket:
            scenes.append(scene_from_bucket(len(scenes) + 1, bucket, asset))
    else:
        lyrics_lines = [line.strip() for line in asset_prompt(asset).splitlines() if line.strip()]
        for index in range(0, min(len(lyrics_lines), 40), 4):
            lines = lyrics_lines[index:index + 4]
            scenes.append({
                "index": len(scenes) + 1,
                "start": None,
                "end": None,
                "duration": None,
                "lyrics_excerpt": " ".join(lines),
                "prompt_hint": f"Cinematic music video scene for: {' '.join(lines)[:180]}",
            })
    return {
        "asset_id": asset.id,
        "title": asset_title(asset),
        "source": "srt" if segments else "lyrics",
        "scene_count": len(scenes),
        "scenes": scenes[:40],
        "export_hint": "Die Szenen sind bewusst neutral gehalten und können später für FocalML/Midjourney/meta.ai spezifisch formatiert werden.",
    }


def scene_from_bucket(index: int, bucket: list[dict[str, Any]], asset: AudioAsset) -> dict[str, Any]:
    start = safe_float(bucket[0].get("start"), 0.0)
    end = safe_float(bucket[-1].get("end"), start)
    text = " ".join(str(item.get("text") or "").strip() for item in bucket if str(item.get("text") or "").strip())
    return {
        "index": index,
        "start": round(start, 3),
        "end": round(end, 3),
        "duration": round(max(0.0, end - start), 3),
        "lyrics_excerpt": text,
        "prompt_hint": f"Cinematic music video scene for {asset_title(asset)}: {text[:180]}",
    }


def duplicate_asset_version(db: Session, asset: AudioAsset, label: str | None = None, notes: str | None = None) -> AudioAsset:
    metadata = metadata_dict(asset)
    duplicate_meta = dict(metadata)
    history = duplicate_meta.get("version_history") if isinstance(duplicate_meta.get("version_history"), list) else []
    history.append({
        "source_audio_asset_id": asset.id,
        "created_at": utc_now_iso(),
        "label": label or "Neue Version",
        "notes": notes or "",
    })
    duplicate_meta["version_history"] = history
    duplicate_meta["derived_from_audio_asset_id"] = asset.id
    duplicate_meta[PRODUCTION_META_KEY] = {
        **production_state(asset),
        "production_status": "draft",
        "release_ready": False,
        "youtube_ready": False,
        "video_ready": False,
        "notes": notes or "",
        "updated_at": utc_now_iso(),
    }
    duplicate = AudioAsset(
        task_local_id=asset.task_local_id,
        song_id=asset.song_id,
        suno_task_id=asset.suno_task_id,
        audio_id=asset.audio_id,
        title=asset.title,
        image_url=asset.image_url,
        source_url=asset.source_url,
        local_path=asset.local_path,
        public_url=asset.public_url,
        filename=asset.filename,
        content_type=asset.content_type,
        file_size_bytes=asset.file_size_bytes,
        duration_seconds=asset.duration_seconds,
        checksum_sha256=asset.checksum_sha256,
        status=asset.status,
        error_message=asset.error_message,
        metadata_json=duplicate_meta,
        project_id=asset.project_id,
        display_title=f"{asset_title(asset)} - {label or 'Neue Version'}",
        operation_label=asset.operation_label or "Version",
        parent_audio_id=asset.audio_id or str(asset.id),
        parent_task_id=asset.suno_task_id,
        version_label=label or "Neue Version",
        is_favorite=False,
        is_final=False,
        waveform_json=asset.waveform_json,
        waveform_generated_at=asset.waveform_generated_at,
        structure_segments_json=asset.structure_segments_json,
    )
    db.add(duplicate)
    db.flush()
    db.add(ActivityLog(
        action="duplicate_version",
        content_type="audio_asset",
        content_id=duplicate.id,
        old_value={"source_audio_asset_id": asset.id},
        new_value={"new_audio_asset_id": duplicate.id, "version_label": duplicate.version_label},
        metadata_json={"source": "production_suite", "notes": notes or ""},
    ))
    db.commit()
    db.refresh(duplicate)
    return duplicate


def asset_events(db: Session, asset: AudioAsset) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    logs = db.query(ActivityLog).filter(ActivityLog.content_type.in_(["audio", "audio_asset", "project"]), or_(ActivityLog.content_id == asset.id, ActivityLog.content_id == asset.project_id)).order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc()).limit(80).all()
    for log in logs:
        events.append({
            "source": "activity_log",
            "id": log.id,
            "event_type": log.action,
            "title": log.action,
            "message": json.dumps(log.new_value or log.metadata_json or {}, ensure_ascii=False, default=str)[:500],
            "created_at": log.created_at,
            "severity": "info",
        })
    notifications = db.query(StatusNotification).filter(StatusNotification.is_deleted.is_(False), StatusNotification.content_type.in_(["audio", "audio_asset", "srt", "stems", "task_status"]), StatusNotification.content_id == asset.id).order_by(StatusNotification.created_at.desc(), StatusNotification.id.desc()).limit(80).all()
    for notification in notifications:
        events.append({
            "source": "status_notification",
            "id": notification.id,
            "event_type": notification.event_type,
            "title": notification.title,
            "message": notification.message,
            "created_at": notification.created_at,
            "severity": notification.severity,
            "status": notification.status,
        })
    if asset.task_local_id:
        task = db.query(SunoTask).filter(SunoTask.id == asset.task_local_id).first()
        if task:
            events.append({
                "source": "suno_task",
                "id": task.id,
                "event_type": task.task_type,
                "title": task.task_type,
                "message": task.error_message or task.status,
                "created_at": task.created_at,
                "severity": "error" if task.error_message else "info",
                "status": task.status,
            })
    events.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return events[:120]


def seed_style_presets(db: Session) -> dict[str, Any]:
    created = 0
    existing = 0
    items: list[dict[str, Any]] = []
    for preset in STYLE_PRESETS:
        current = db.query(MusicStyle).filter(MusicStyle.name == preset["name"], MusicStyle.is_deleted.is_(False)).first()
        if current:
            existing += 1
            items.append({"id": current.id, "name": current.name, "status": "exists"})
            continue
        style = MusicStyle(
            name=preset["name"],
            genre=preset.get("genre"),
            bpm=preset.get("bpm"),
            style_text=preset["style_text"],
            description=preset.get("description"),
            tags=preset.get("tags"),
            is_favorite=True,
            is_profile=True,
            profile_json=preset.get("profile_json") or {},
        )
        db.add(style)
        db.flush()
        created += 1
        items.append({"id": style.id, "name": style.name, "status": "created"})
    db.commit()
    return {"ok": True, "created": created, "existing": existing, "items": items}


def project_production_report(db: Session, project: AudioProject) -> dict[str, Any]:
    summary = project_summary(db, project)
    missing_actions: dict[str, int] = {}
    for asset in summary["assets"]:
        for action in asset["readiness"].get("recommended_next_actions") or []:
            key = action.get("key") or "unknown"
            missing_actions[key] = missing_actions.get(key, 0) + 1
    return {
        "generated_at": utc_now_iso(),
        "project": summary,
        "missing_action_counts": missing_actions,
        "release_candidates": [asset for asset in summary["assets"] if asset["readiness"]["score"] >= 80],
        "risk_notes": [
            "Projekt enthält keine finale Version." if not summary.get("final_audio_asset_id") else "",
            "Mindestens ein Track ohne SRT." if missing_actions.get("srt") else "",
            "Mindestens ein Track ohne YouTube-Daten." if missing_actions.get("youtube") else "",
        ],
    }

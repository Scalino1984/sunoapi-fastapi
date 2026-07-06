from __future__ import annotations

"""Optional AI tag generation for Library AudioAssets.

Contract:
- Uses the existing configured AI provider/profile stack; no separate provider
  or API-key logic lives here.
- Writes only AudioAsset.metadata_json["ai_tags"] so Suno payloads, playlists,
  imports, SRT, cover and audio-analysis workflows stay independent.
- Keeps tag output intentionally small. The deterministic post-processing caps
  and normalizes AI output so the Library search remains useful.
"""

import json
import re
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.config import get_settings
from app.models import ActivityLog, AiAssistantProfile, AiAssistantProfileFile, AiInstructionFile, AppSetting, AudioAsset, Song, StatusNotification, SunoTask
from app.services.ai_chat_service import AiChatService, AiProviderError
from app.services.task_lifecycle_service import append_task_debug_event, append_task_step_log
from app.utils.time_utils import utc_now_naive


AI_SETTINGS_KEY = "ai_chat_settings"
TAGGING_METADATA_KEY = "ai_tags"
TAGGING_VERSION = "library-ai-tags-v1"
TAGGING_TASK_TYPE = "library_ai_tagging"
BULK_TAGGING_TASK_TYPE = "bulk_library_ai_tagging"

TAG_STOPWORDS = {
    "song",
    "music",
    "track",
    "audio",
    "generated",
    "suno",
    "unknown",
    "misc",
    "other",
    "style",
    "tags",
}

TAG_SYNONYMS = {
    "deutsch": "german",
    "german lyrics": "german",
    "englisch": "english",
    "male": "male vocal",
    "male vocals": "male vocal",
    "female": "female vocal",
    "female vocals": "female vocal",
    "rap vocals": "rap",
    "hip hop": "hip-hop",
    "hiphop": "hip-hop",
    "cinematic music": "cinematic",
    "emotional music": "emotional",
}


def _settings_value(db: Session) -> dict[str, Any]:
    row = db.query(AppSetting).filter(AppSetting.key == AI_SETTINGS_KEY).first()
    return row.value if row and isinstance(row.value, dict) else {}


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def load_library_ai_tagging_settings(db: Session) -> dict[str, Any]:
    settings = get_settings()
    value = _settings_value(db)
    provider = str(value.get("default_provider") or settings.ai_default_provider).strip().lower()
    model = str(value.get("default_model") or settings.ai_default_model).strip()
    allowed = settings.ai_allowed_models
    if provider not in allowed:
        provider = settings.ai_default_provider
    if provider in allowed and model not in allowed[provider]:
        model = settings.ai_default_model if settings.ai_default_model in allowed.get(provider, []) else (allowed.get(provider, [""])[0] or "")
    return {
        "enabled": bool(value.get("library_ai_tagging_enabled", False)),
        "profile_id": value.get("library_ai_tagging_profile_id") or value.get("default_assistant_profile_id"),
        "max_tags": _bounded_int(value.get("library_ai_tagging_max_tags_per_asset"), 5, 2, 8),
        "provider": provider,
        "model": model,
    }


def read_saved_library_ai_tags(asset: AudioAsset | None) -> dict[str, Any] | None:
    if not asset:
        return None
    metadata = asset.metadata_json if isinstance(asset.metadata_json, dict) else {}
    value = metadata.get(TAGGING_METADATA_KEY)
    return value if isinstance(value, dict) else None


def _profile_context(db: Session, profile_id: Any, fallback_provider: str, fallback_model: str) -> tuple[str, str, str, dict[str, Any]]:
    profile = None
    if profile_id is not None:
        try:
            profile = db.query(AiAssistantProfile).filter(
                AiAssistantProfile.id == int(profile_id),
                AiAssistantProfile.is_deleted.is_(False),
                AiAssistantProfile.is_active.is_(True),
            ).first()
        except Exception:
            profile = None
    provider = str(profile.provider if profile else fallback_provider).strip().lower()
    model = str(profile.model if profile else fallback_model).strip()
    instructions: list[str] = []
    if profile and profile.system_instruction:
        instructions.append(str(profile.system_instruction))
    if profile and profile.response_format_instruction:
        instructions.append(str(profile.response_format_instruction))
    if profile:
        file_rows = (
            db.query(AiInstructionFile)
            .join(AiAssistantProfileFile, AiAssistantProfileFile.file_id == AiInstructionFile.id)
            .filter(
                AiAssistantProfileFile.profile_id == profile.id,
                AiAssistantProfileFile.is_active.is_(True),
                AiInstructionFile.is_deleted.is_(False),
                AiInstructionFile.is_active.is_(True),
            )
            .order_by(AiAssistantProfileFile.sort_order.asc(), AiInstructionFile.title.asc())
            .all()
        )
        for file in file_rows:
            if file.content:
                instructions.append(f"{file.title}\n{file.content}")
    profile_options = {
        "profile_id": profile.id if profile else None,
        "profile_name": profile.name if profile else None,
        "temperature": profile.temperature if profile and profile.temperature is not None else 0.1,
        "max_output_tokens": profile.max_output_tokens if profile and profile.max_output_tokens else 700,
    }
    return provider, model, "\n\n".join(instructions).strip(), profile_options


def _short_text(value: Any, limit: int) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}\n..."


def _asset_context(asset: AudioAsset, song: Song | None) -> dict[str, Any]:
    metadata = asset.metadata_json if isinstance(asset.metadata_json, dict) else {}
    request = metadata.get("request_payload") if isinstance(metadata.get("request_payload"), dict) else {}
    analysis = metadata.get("audio_ai_analysis") if isinstance(metadata.get("audio_ai_analysis"), dict) else {}
    return {
        "title": asset.display_title or asset.title or (song.title if song else None),
        "style": asset.style or asset.tags or request.get("style") or request.get("tags") or (song.style if song else None) or (song.tags if song else None),
        "prompt": _short_text(asset.prompt or request.get("prompt") or (song.prompt if song else None), 1800),
        "lyrics": _short_text(asset.lyrics or request.get("lyrics") or (song.lyrics if song else None), 2400),
        "model": asset.model_name or request.get("model") or (song.model if song else None),
        "operation_type": asset.operation_type or asset.task_type,
        "duration_seconds": asset.duration_seconds,
        "generation_options": {key: request.get(key) for key in ("negativeTags", "vocalGender", "styleWeight", "weirdnessConstraint", "audioWeight", "customMode", "instrumental", "personaId", "personaModel") if request.get(key) not in (None, "")},
        "audio_analysis_summary": analysis.get("summary") or analysis.get("ai_report") or analysis.get("overview") if isinstance(analysis, dict) else None,
    }


def _extract_json_object(raw_text: str) -> dict[str, Any]:
    text = str(raw_text or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        pass
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _normalize_tag(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[\[\]{}()\"'`´]", "", text)
    text = re.sub(r"[^a-z0-9äöüß+&/ -]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" -_/")
    text = TAG_SYNONYMS.get(text, text)
    if len(text) > 32:
        text = text[:32].rsplit(" ", 1)[0].strip() or text[:32].strip()
    return text


def normalize_ai_tags(raw_tags: Any, *, max_tags: int) -> list[str]:
    source = raw_tags if isinstance(raw_tags, list) else []
    result: list[str] = []
    seen: set[str] = set()
    for value in source:
        tag = _normalize_tag(value)
        if not tag or tag in TAG_STOPWORDS or len(tag) < 2:
            continue
        if tag in seen:
            continue
        seen.add(tag)
        result.append(tag)
        if len(result) >= max_tags:
            break
    return result


def _fallback_tags(context: dict[str, Any], *, max_tags: int) -> list[str]:
    text = " ".join(str(context.get(key) or "") for key in ("title", "style", "prompt", "lyrics")).lower()
    candidates: list[str] = []
    for needle, tag in (
        ("rap", "rap"),
        ("hip-hop", "hip-hop"),
        ("trap", "trap"),
        ("dancehall", "dancehall"),
        ("reggae", "reggae"),
        ("cinematic", "cinematic"),
        ("dark", "dark"),
        ("emotional", "emotional"),
        ("german", "german"),
        ("deutsch", "german"),
        ("english", "english"),
        ("female", "female vocal"),
        ("male", "male vocal"),
    ):
        if needle in text:
            candidates.append(tag)
    return normalize_ai_tags(candidates, max_tags=max_tags)


async def generate_library_ai_tags_for_asset(db: Session, asset: AudioAsset, *, force: bool = False) -> dict[str, Any]:
    settings = load_library_ai_tagging_settings(db)
    if not settings["enabled"]:
        raise AiProviderError("KI-Tagging ist im Admin-Panel deaktiviert.")
    existing = read_saved_library_ai_tags(asset)
    if existing and not force:
        return existing
    song = db.query(Song).filter(Song.id == asset.song_id, Song.is_deleted.is_(False)).first() if asset.song_id else None
    context = _asset_context(asset, song)
    provider, model, profile_instruction, profile_options = _profile_context(db, settings.get("profile_id"), settings["provider"], settings["model"])
    max_tags = int(settings["max_tags"])
    system_instruction = f"""
Du bist ein kompaktes Library-Tagging-System fuer eine Musik-App.
Erzeuge wenige, wiederverwendbare Such-Tags fuer genau einen Song.
Keine neue Kreativarbeit, keine Bewertung des Nutzers, keine langen Listen.
Nutze bevorzugt stabile Begriffe fuer Genre, Stimmung, Vocal-Typ, Sprache und Produktionscharakter.
Maximal {max_tags} Tags. Keine Synonyme nebeneinander. Keine Kuenstler-Namen. Keine IDs.
Antworte ausschliesslich als JSON-Objekt:
{{"tags":["tag 1","tag 2"],"moods":["mood"],"genres":["genre"],"language":"de|en|unknown","confidence":0.0,"reason":"kurz"}}
""".strip()
    if profile_instruction:
        system_instruction = f"{system_instruction}\n\nZusaetzliche Admin-Anweisungen:\n{profile_instruction}"
    instruction = (
        "Analysiere diesen lokalen Song-Kontext fuer Library-Suche und Filter.\n"
        f"Kontext JSON:\n{json.dumps(context, ensure_ascii=False, default=str)}"
    )
    ai = AiChatService()
    provider_key, model_key, api_model = ai.validate_provider_model(provider, model)
    raw_text, raw = await ai._call_provider(provider_key, api_model, instruction, [], system_instruction, profile_options)
    parsed = _extract_json_object(raw_text)
    tags = normalize_ai_tags(parsed.get("tags"), max_tags=max_tags)
    if not tags:
        tags = _fallback_tags(context, max_tags=max_tags)
    payload = {
        "version": TAGGING_VERSION,
        "tags": tags,
        "moods": normalize_ai_tags(parsed.get("moods"), max_tags=3),
        "genres": normalize_ai_tags(parsed.get("genres"), max_tags=3),
        "language": str(parsed.get("language") or "unknown").strip().lower()[:16] or "unknown",
        "confidence": max(0.0, min(1.0, float(parsed.get("confidence") or 0.0))),
        "reason": _short_text(parsed.get("reason"), 240),
        "generated_at": utc_now_naive().isoformat(),
        "provider": provider_key,
        "model": model_key,
        "profile_id": profile_options.get("profile_id"),
        "source": "library_ai_tagging",
        "raw_response_stored": False,
    }
    if get_settings().ai_store_raw_responses or get_settings().debug:
        payload["raw_response_stored"] = True
        payload["raw_response"] = {"text": raw_text, "provider_payload": raw}
    metadata = dict(asset.metadata_json or {}) if isinstance(asset.metadata_json, dict) else {}
    metadata[TAGGING_METADATA_KEY] = payload
    asset.metadata_json = metadata
    db.add(asset)
    flag_modified(asset, "metadata_json")
    db.add(ActivityLog(
        action="library_ai_tags_generated",
        content_type="audio_asset",
        content_id=asset.id,
        new_value={"tags": tags, "version": TAGGING_VERSION},
        metadata_json={"provider": provider_key, "model": model_key, "profile_id": profile_options.get("profile_id")},
    ))
    db.commit()
    db.refresh(asset)
    return payload


def create_library_ai_tagging_status_task(db: Session, asset: AudioAsset | None, *, asset_ids: list[int], force: bool = False) -> SunoTask:
    is_bulk = len(asset_ids) != 1
    title = "KI-Tagging-Sammellauf gestartet" if is_bulk else f"KI-Tags werden erzeugt: {asset.display_title or asset.title or asset.filename or asset.id}"
    task_type = BULK_TAGGING_TASK_TYPE if is_bulk else TAGGING_TASK_TYPE
    task = SunoTask(
        task_id=None,
        task_type=task_type,
        status="RUNNING",
        request_payload={"audio_asset_ids": asset_ids, "audio_asset_id": asset_ids[0] if len(asset_ids) == 1 else None, "force": force, "background": True, "local_task": True},
        response_payload={"background": True, "local_task": True, "status": "RUNNING"},
        result_payload=None,
        started_at=utc_now_naive(),
        heartbeat_at=utc_now_naive(),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    append_task_debug_event(
        db,
        task,
        event="library_ai_tagging_started",
        detail="KI-Tagging wurde gestartet.",
        data={"task_type": task_type, "audio_asset_ids": asset_ids, "force": force},
        commit=False,
    )
    append_task_step_log(
        db,
        task,
        phase="started",
        phase_label="KI-Tagging gestartet",
        detail=f"KI-Tagging fuer {len(asset_ids)} Library-Inhalt{'e' if len(asset_ids) != 1 else ''} laeuft im Hintergrund.",
        data={"task_type": task_type, "audio_asset_ids": asset_ids},
        commit=False,
    )
    db.add(StatusNotification(
        event_type=f"{task_type}_started",
        title=title,
        message=f"KI-Tagging fuer {len(asset_ids)} Library-Inhalt{'e' if len(asset_ids) != 1 else ''} laeuft im Hintergrund.",
        severity="info",
        status="unread",
        task_local_id=task.id,
        content_type="audio" if asset and len(asset_ids) == 1 else "bulk_audio",
        content_id=asset.id if asset and len(asset_ids) == 1 else None,
        target_tab="status",
        target_payload={"task_local_id": task.id, "task_type": task_type, "status": "RUNNING", "audio_asset_ids": asset_ids},
    ))
    db.commit()
    return task


def finish_library_ai_tagging_status_task(db: Session, task_id: int, *, success: int, failed: int, skipped: int, errors: list[dict[str, Any]], tagged_ids: list[int]) -> None:
    now = utc_now_naive()
    task = db.query(SunoTask).filter(SunoTask.id == task_id).first()
    status = "SUCCESS" if failed == 0 else ("PARTIAL_SUCCESS" if success > 0 else "FAILED")
    message = f"{success} getaggt"
    if skipped:
        message += f" · {skipped} uebersprungen"
    if failed:
        message += f" · {failed} Fehler"
    task_type = task.task_type if task else TAGGING_TASK_TYPE
    if task:
        task.status = status
        task.completed_at = now
        task.heartbeat_at = now
        task.error_message = None if failed == 0 else message
        task.result_payload = {"status": status, "success": success, "failed": failed, "skipped": skipped, "errors": errors, "tagged_audio_asset_ids": tagged_ids, "completed_at": now.isoformat()}
        final_phase = "completed" if status == "SUCCESS" else ("partial_success" if status == "PARTIAL_SUCCESS" else "failed")
        append_task_debug_event(
            db,
            task,
            event="library_ai_tagging_finished",
            detail=message,
            level="info" if status == "SUCCESS" else ("warning" if status == "PARTIAL_SUCCESS" else "error"),
            data={
                "task_type": task_type,
                "status": status,
                "success": success,
                "failed": failed,
                "skipped": skipped,
                "errors_preview": errors[:20],
                "tagged_audio_asset_ids": tagged_ids,
            },
            commit=False,
        )
        append_task_step_log(
            db,
            task,
            phase=final_phase,
            phase_label="KI-Tagging abgeschlossen" if status == "SUCCESS" else ("KI-Tagging teilweise abgeschlossen" if status == "PARTIAL_SUCCESS" else "KI-Tagging fehlgeschlagen"),
            detail=message,
            data={"task_type": task_type, "status": status, "success": success, "failed": failed, "skipped": skipped},
            commit=False,
        )
        db.add(task)
        for row in db.query(StatusNotification).filter(StatusNotification.task_local_id == task.id, StatusNotification.status != "done", StatusNotification.is_deleted.is_(False)).all():
            row.status = "done"
            row.completed_at = now
            row.message = f"Abgeschlossen: {message}"
            db.add(row)
    db.add(StatusNotification(
        event_type=f"{task_type}_completed" if failed == 0 else f"{task_type}_failed",
        title="KI-Tagging abgeschlossen" if failed == 0 else "KI-Tagging teilweise fehlgeschlagen",
        message=message,
        severity="success" if failed == 0 else ("warning" if success > 0 else "error"),
        status="unread",
        task_local_id=task_id,
        content_type="audio" if len(tagged_ids) == 1 else "bulk_audio",
        content_id=tagged_ids[0] if len(tagged_ids) == 1 else None,
        target_tab="library",
        target_payload={"task_local_id": task_id, "task_type": task_type, "status": status, "audio_asset_ids": tagged_ids},
        completed_at=now,
    ))
    db.commit()

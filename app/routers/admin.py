from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from app.auth import get_current_active_user
from app.config import get_settings
from app.database import get_db
from app.models import AppSetting, User, VocalTag, AiAssistantProfile, AiInstructionFile, AiAssistantProfileFile, DawPromptHook
from app.schemas import (
    AiAdminSettingsRead,
    AiAdminSettingsUpdate,
    AiAssistantProfileCreate,
    AiAssistantProfileRead,
    AiAssistantProfileUpdate,
    AiInstructionFileCreate,
    AiInstructionFileRead,
    AiInstructionFileUpdate,
    AiProviderTestRequest,
    DawPromptHookCreate,
    DawPromptHookRead,
    DawPromptHookUpdate,
    UserAdminUpdate,
    UserRead,
    VocalTagCreate,
    VocalTagRead,
    VocalTagUpdate,
)
from app.services.ai_chat_service import AiChatService, AiProviderError
from app.utils.time_utils import utc_now_naive

router = APIRouter(prefix="/api/admin", tags=["admin"])

AI_SETTINGS_KEY = "ai_chat_settings"


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _bounded_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _settings_row(db: Session) -> AppSetting:
    row = db.query(AppSetting).filter(AppSetting.key == AI_SETTINGS_KEY).first()
    if row:
        return row
    settings = get_settings()
    row = AppSetting(
        key=AI_SETTINGS_KEY,
        value={
            "default_provider": settings.ai_default_provider,
            "default_model": settings.ai_default_model,
            "system_instruction": "",
            "default_assistant_profile_id": None,
            "transcription_backend": settings.transcript_backend_default,
            "transcription_language": settings.transcript_language_default,
            "lyrics_template_mode": "lyrics_source_of_truth",
            "lyrics_match_mode": "lenient",
            "srt_output_enabled": True,
            "srt_auto_regenerate": False,
            "srt_generate_vocal_stems_before_transcription": False,
            "srt_ai_cleanup_enabled": True,
            "library_content_polling_enabled": False,
            "library_content_polling_interval_minutes": 15,
            "library_content_polling_limit": 500,
            "extend_auto_continue_at_enabled": False,
            "extend_auto_continue_at_search_window_seconds": 15,
            "extend_auto_continue_at_vocal_threshold_ratio": 0.03,
            "extend_auto_continue_at_fallback_offset_seconds": 4.0,
            "extend_auto_continue_at_timeout_seconds": 180,
            "audio_ai_analysis_enabled": settings.audio_ai_analysis_enabled,
            "audio_ai_analysis_ai_summary_enabled": settings.audio_ai_analysis_ai_summary_enabled,
            "audio_ai_model_analysis_enabled": settings.audio_ai_model_analysis_enabled,
            "audio_ai_analysis_max_seconds": settings.audio_ai_analysis_max_seconds,
            "audio_ai_model_analysis_seconds": settings.audio_ai_model_analysis_seconds,
            "audio_ai_model_analysis_top_k": settings.audio_ai_model_analysis_top_k,
            "library_ai_tagging_enabled": False,
            "library_ai_tagging_profile_id": None,
            "library_ai_tagging_max_tags_per_asset": 5,
        },
        description="Admin-Konfiguration für KI-Canvas-Chat und 1-Click-SRT",
    )
    db.add(row)
    db.flush()
    return row


def get_ai_admin_settings(db: Session) -> dict[str, Any]:
    settings = get_settings()
    row = _settings_row(db)
    value = row.value or {}
    provider = str(value.get("default_provider") or settings.ai_default_provider).strip().lower()
    model = str(value.get("default_model") or settings.ai_default_model).strip()
    allowed = settings.ai_allowed_models
    if provider not in allowed:
        provider = settings.ai_default_provider
    if provider in allowed and model not in allowed[provider]:
        model = settings.ai_default_model if settings.ai_default_model in allowed.get(provider, []) else (allowed.get(provider, [""])[0] or "")
    transcription_backend = str(value.get("transcription_backend") or settings.transcript_backend_default or "voxtral").strip().lower()
    if transcription_backend not in settings.transcript_backends:
        transcription_backend = "voxtral"
    transcription_language = str(value.get("transcription_language") or settings.transcript_language_default or "de").strip().lower()
    if transcription_language not in {"auto", "de", "en"}:
        transcription_language = "auto"

    return {
        "default_provider": provider,
        "default_model": model,
        "default_assistant_profile_id": value.get("default_assistant_profile_id"),
        "system_instruction": str(value.get("system_instruction") or ""),
        "allowed_models": allowed,
        "providers": {
            "openai": {"configured": bool(settings.openai_api_key)},
            "openrouter": {"configured": bool(settings.openrouter_api_key)},
            "gemini": {"configured": bool(settings.gemini_api_key)},
            "groq": {"configured": bool(settings.groq_api_key)},
        },
        "transcription_backend": transcription_backend,
        "transcription_language": transcription_language,
        "lyrics_template_mode": "lyrics_source_of_truth",
        "lyrics_match_mode": "lenient",
        "srt_output_enabled": bool(value.get("srt_output_enabled", True)),
        "srt_auto_regenerate": bool(value.get("srt_auto_regenerate", False)),
        "srt_generate_vocal_stems_before_transcription": bool(value.get("srt_generate_vocal_stems_before_transcription", False)),
        "srt_ai_cleanup_enabled": bool(value.get("srt_ai_cleanup_enabled", True)),
        "library_content_polling_enabled": bool(value.get("library_content_polling_enabled", False)),
        "library_content_polling_interval_minutes": _bounded_int(value.get("library_content_polling_interval_minutes"), 15, 1, 1440),
        "library_content_polling_limit": _bounded_int(value.get("library_content_polling_limit"), 500, 10, 5000),
        "extend_auto_continue_at_enabled": bool(value.get("extend_auto_continue_at_enabled", False)),
        "extend_auto_continue_at_search_window_seconds": _bounded_int(value.get("extend_auto_continue_at_search_window_seconds"), 15, 5, 60),
        "extend_auto_continue_at_vocal_threshold_ratio": _bounded_float(value.get("extend_auto_continue_at_vocal_threshold_ratio"), 0.03, 0.005, 0.25),
        "extend_auto_continue_at_fallback_offset_seconds": _bounded_float(value.get("extend_auto_continue_at_fallback_offset_seconds"), 4.0, 1.0, 30.0),
        "extend_auto_continue_at_timeout_seconds": _bounded_int(value.get("extend_auto_continue_at_timeout_seconds"), 180, 30, 1200),
        "audio_ai_analysis_enabled": bool(value.get("audio_ai_analysis_enabled", settings.audio_ai_analysis_enabled)),
        "audio_ai_analysis_ai_summary_enabled": bool(value.get("audio_ai_analysis_ai_summary_enabled", settings.audio_ai_analysis_ai_summary_enabled)),
        "audio_ai_model_analysis_enabled": bool(value.get("audio_ai_model_analysis_enabled", settings.audio_ai_model_analysis_enabled)),
        "audio_ai_analysis_max_seconds": _bounded_int(value.get("audio_ai_analysis_max_seconds"), settings.audio_ai_analysis_max_seconds, 30, 1200),
        "audio_ai_model_analysis_seconds": _bounded_int(value.get("audio_ai_model_analysis_seconds"), settings.audio_ai_model_analysis_seconds, 8, 90),
        "audio_ai_model_analysis_top_k": _bounded_int(value.get("audio_ai_model_analysis_top_k"), settings.audio_ai_model_analysis_top_k, 5, 25),
        "audio_ai_model_cache_dir": settings.audio_ai_model_cache_dir,
        "audio_ai_acoustid_configured": bool(settings.acoustid_api_key),
        "library_ai_tagging_enabled": bool(value.get("library_ai_tagging_enabled", False)),
        "library_ai_tagging_profile_id": value.get("library_ai_tagging_profile_id"),
        "library_ai_tagging_max_tags_per_asset": _bounded_int(value.get("library_ai_tagging_max_tags_per_asset"), 5, 2, 8),
        "transcription_backends": settings.transcript_backends,
        "transcription_languages": ["auto", "de", "en"],
        "transcription_runtime": {
            "groq": {"configured": settings.transcript_backend_has_runtime("groq")},
            "whisperx": {"configured": settings.transcript_backend_has_runtime("whisperx")},
            "openai_whisper_api": {"configured": settings.transcript_backend_has_runtime("openai_whisper_api")},
            "voxtral": {"configured": settings.transcript_backend_has_runtime("voxtral")},
        },
    }


@router.get("/users", response_model=list[UserRead])
def list_users(db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    return db.query(User).order_by(User.id.asc()).all()


@router.patch("/users/{user_id}", response_model=UserRead)
def update_user(user_id: int, payload: UserAdminUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Benutzer wurde nicht gefunden.")
    data = payload.model_dump(exclude_unset=True)
    # Rollenbasierte Einschränkungen sind deaktiviert: Jeder aktive Benutzer darf alle Bereiche nutzen.
    # Der eigene Benutzer darf trotzdem nicht deaktiviert werden, damit man sich nicht selbst aussperrt.
    if user.id == current_user.id and data.get("is_active") is False:
        raise HTTPException(status_code=400, detail="Der eigene Benutzer kann nicht deaktiviert werden.")
    # is_admin bleibt aus Kompatibilitätsgründen im Modell bestehen, wird aber nicht mehr zur Berechtigung genutzt.
    data.pop("is_admin", None)
    for key, value in data.items():
        setattr(user, key, value)
    db.commit()
    db.refresh(user)
    return user


@router.get("/ai-settings", response_model=AiAdminSettingsRead)
def read_ai_settings(db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    return get_ai_admin_settings(db)


@router.put("/ai-settings", response_model=AiAdminSettingsRead)
def update_ai_settings(payload: AiAdminSettingsUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    settings = get_settings()
    provider = payload.default_provider.strip().lower()
    model = payload.default_model.strip()
    allowed = settings.ai_allowed_models
    if provider not in allowed or model not in allowed[provider]:
        raise HTTPException(status_code=400, detail="Provider oder Modell ist nicht freigegeben.")
    row = _settings_row(db)
    default_profile_id = payload.default_assistant_profile_id
    if default_profile_id is not None:
        profile = db.query(AiAssistantProfile).filter(AiAssistantProfile.id == default_profile_id, AiAssistantProfile.is_deleted.is_(False)).first()
        if not profile:
            raise HTTPException(status_code=404, detail="KI-Profil wurde nicht gefunden.")
    tagging_profile_id = payload.library_ai_tagging_profile_id
    if tagging_profile_id is not None:
        profile = db.query(AiAssistantProfile).filter(AiAssistantProfile.id == tagging_profile_id, AiAssistantProfile.is_deleted.is_(False)).first()
        if not profile:
            raise HTTPException(status_code=404, detail="KI-Tagging-Profil wurde nicht gefunden.")
    transcription_backend = str(payload.transcription_backend or settings.transcript_backend_default or "voxtral").strip().lower()
    if transcription_backend not in settings.transcript_backends:
        raise HTTPException(status_code=400, detail="Transkriptionsbackend ist nicht freigegeben.")
    transcription_language = str(payload.transcription_language or settings.transcript_language_default or "de").strip().lower()
    if transcription_language not in {"auto", "de", "en"}:
        raise HTTPException(status_code=400, detail="Transkriptionssprache ist nicht freigegeben.")

    row.value = {
        "default_provider": provider,
        "default_model": model,
        "default_assistant_profile_id": default_profile_id,
        "system_instruction": payload.system_instruction or "",
        "transcription_backend": transcription_backend,
        "transcription_language": transcription_language,
        "lyrics_template_mode": "lyrics_source_of_truth",
        "lyrics_match_mode": "lenient",
        "srt_output_enabled": bool(payload.srt_output_enabled),
        "srt_auto_regenerate": bool(payload.srt_auto_regenerate),
        "srt_generate_vocal_stems_before_transcription": bool(payload.srt_generate_vocal_stems_before_transcription),
        "srt_ai_cleanup_enabled": bool(payload.srt_ai_cleanup_enabled),
        "library_content_polling_enabled": bool(payload.library_content_polling_enabled),
        "library_content_polling_interval_minutes": _bounded_int(payload.library_content_polling_interval_minutes, 15, 1, 1440),
        "library_content_polling_limit": _bounded_int(payload.library_content_polling_limit, 500, 10, 5000),
        "extend_auto_continue_at_enabled": bool(payload.extend_auto_continue_at_enabled),
        "extend_auto_continue_at_search_window_seconds": _bounded_int(payload.extend_auto_continue_at_search_window_seconds, 15, 5, 60),
        "extend_auto_continue_at_vocal_threshold_ratio": _bounded_float(payload.extend_auto_continue_at_vocal_threshold_ratio, 0.03, 0.005, 0.25),
        "extend_auto_continue_at_fallback_offset_seconds": _bounded_float(payload.extend_auto_continue_at_fallback_offset_seconds, 4.0, 1.0, 30.0),
        "extend_auto_continue_at_timeout_seconds": _bounded_int(payload.extend_auto_continue_at_timeout_seconds, 180, 30, 1200),
        "audio_ai_analysis_enabled": bool(payload.audio_ai_analysis_enabled),
        "audio_ai_analysis_ai_summary_enabled": bool(payload.audio_ai_analysis_ai_summary_enabled),
        "audio_ai_model_analysis_enabled": bool(payload.audio_ai_model_analysis_enabled),
        "audio_ai_analysis_max_seconds": _bounded_int(payload.audio_ai_analysis_max_seconds, settings.audio_ai_analysis_max_seconds, 30, 1200),
        "audio_ai_model_analysis_seconds": _bounded_int(payload.audio_ai_model_analysis_seconds, settings.audio_ai_model_analysis_seconds, 8, 90),
        "audio_ai_model_analysis_top_k": _bounded_int(payload.audio_ai_model_analysis_top_k, settings.audio_ai_model_analysis_top_k, 5, 25),
        "library_ai_tagging_enabled": bool(payload.library_ai_tagging_enabled),
        "library_ai_tagging_profile_id": tagging_profile_id,
        "library_ai_tagging_max_tags_per_asset": _bounded_int(payload.library_ai_tagging_max_tags_per_asset, 5, 2, 8),
    }
    row.updated_at = utc_now_naive()
    db.commit()
    return get_ai_admin_settings(db)


@router.post("/ai-settings/test")
async def test_ai_settings(payload: AiProviderTestRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    try:
        result = await AiChatService().run_canvas_assistant(
            provider=payload.provider,
            model=payload.model,
            user_message=payload.message or "Antworte kurz: Provider-Test erfolgreich.",
            canvas_content="[Test | spoken]\nProvider-Test.",
            history=[],
            system_instruction="Antworte extrem kurz. Dies ist nur ein Verbindungstest.",
            vocal_tags=[],
            allow_canvas_changes=False,
        )
    except AiProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"ok": True, "provider": payload.provider, "model": payload.model, "message": result.assistant_message, "change_summary": result.change_summary}


@router.get("/vocal-tags", response_model=list[VocalTagRead])
def list_vocal_tags(include_inactive: bool = True, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    query = db.query(VocalTag).filter(VocalTag.is_deleted.is_(False))
    if not include_inactive:
        query = query.filter(VocalTag.is_active.is_(True))
    return query.order_by(VocalTag.category.asc(), VocalTag.sort_order.asc(), VocalTag.label.asc()).all()


@router.post("/vocal-tags", response_model=VocalTagRead)
def create_vocal_tag(payload: VocalTagCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    tag = VocalTag(**payload.model_dump(exclude_none=True))
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


@router.put("/vocal-tags/{tag_id}", response_model=VocalTagRead)
def update_vocal_tag(tag_id: int, payload: VocalTagUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    tag = db.query(VocalTag).filter(VocalTag.id == tag_id, VocalTag.is_deleted.is_(False)).first()
    if not tag:
        raise HTTPException(status_code=404, detail="Vocal Tag wurde nicht gefunden.")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(tag, key, value)
    db.commit()
    db.refresh(tag)
    return tag


@router.delete("/vocal-tags/{tag_id}")
def delete_vocal_tag(tag_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    tag = db.query(VocalTag).filter(VocalTag.id == tag_id, VocalTag.is_deleted.is_(False)).first()
    if not tag:
        raise HTTPException(status_code=404, detail="Vocal Tag wurde nicht gefunden.")
    tag.is_deleted = True
    tag.deleted_at = utc_now_naive()
    tag.deleted_reason = "Admin-Löschung"
    db.commit()
    return {"ok": True, "deleted_vocal_tag_id": tag_id}


def _clean_prompt_hook_tags(tags: list[str] | None) -> list[str]:
    cleaned: list[str] = []
    for item in tags or []:
        value = str(item or "").strip()
        if value and value not in cleaned:
            cleaned.append(value[:80])
    return cleaned[:20]


def _apply_prompt_hook_payload(hook: DawPromptHook, values: dict[str, Any]) -> None:
    for key, value in values.items():
        if key == "tags":
            hook.tags_json = _clean_prompt_hook_tags(value)
        elif key == "scope" and value:
            hook.scope = str(value).strip()[:80] or "daw"
        elif key in {"title", "prompt"} and value is not None:
            setattr(hook, key, str(value).strip())
        else:
            setattr(hook, key, value)


@router.get("/daw-prompt-hooks", response_model=list[DawPromptHookRead])
def list_daw_prompt_hooks(include_inactive: bool = True, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    query = db.query(DawPromptHook).filter(DawPromptHook.is_deleted.is_(False))
    if not include_inactive:
        query = query.filter(DawPromptHook.is_active.is_(True))
    return query.order_by(DawPromptHook.scope.asc(), DawPromptHook.sort_order.asc(), DawPromptHook.title.asc()).all()


@router.post("/daw-prompt-hooks", response_model=DawPromptHookRead)
def create_daw_prompt_hook(payload: DawPromptHookCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    hook = DawPromptHook()
    _apply_prompt_hook_payload(hook, payload.model_dump())
    db.add(hook)
    db.commit()
    db.refresh(hook)
    return hook


@router.put("/daw-prompt-hooks/{hook_id}", response_model=DawPromptHookRead)
def update_daw_prompt_hook(hook_id: int, payload: DawPromptHookUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    hook = db.query(DawPromptHook).filter(DawPromptHook.id == hook_id, DawPromptHook.is_deleted.is_(False)).first()
    if not hook:
        raise HTTPException(status_code=404, detail="DAW-Prompt-Aufhänger wurde nicht gefunden.")
    _apply_prompt_hook_payload(hook, payload.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(hook)
    return hook


@router.post("/daw-prompt-hooks/{hook_id}/duplicate", response_model=DawPromptHookRead)
def duplicate_daw_prompt_hook(hook_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    hook = db.query(DawPromptHook).filter(DawPromptHook.id == hook_id, DawPromptHook.is_deleted.is_(False)).first()
    if not hook:
        raise HTTPException(status_code=404, detail="DAW-Prompt-Aufhänger wurde nicht gefunden.")
    duplicate = DawPromptHook(
        title=f"{hook.title} Kopie"[:180],
        prompt=hook.prompt,
        description=hook.description,
        scope=hook.scope,
        tags_json=list(hook.tags),
        sort_order=hook.sort_order + 1,
        is_active=hook.is_active,
        metadata_json={"duplicated_from": hook.id},
    )
    db.add(duplicate)
    db.commit()
    db.refresh(duplicate)
    return duplicate


@router.delete("/daw-prompt-hooks/{hook_id}")
def delete_daw_prompt_hook(hook_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    hook = db.query(DawPromptHook).filter(DawPromptHook.id == hook_id, DawPromptHook.is_deleted.is_(False)).first()
    if not hook:
        raise HTTPException(status_code=404, detail="DAW-Prompt-Aufhänger wurde nicht gefunden.")
    hook.is_deleted = True
    hook.deleted_at = utc_now_naive()
    hook.deleted_reason = "Admin-Löschung"
    db.commit()
    return {"ok": True, "deleted_daw_prompt_hook_id": hook_id}


# === GPT-ähnliche KI-Profile und Instruction-Dateien ===

def _file_to_schema(file: AiInstructionFile, include_content: bool = True) -> AiInstructionFileRead:
    data = AiInstructionFileRead.model_validate(file)
    if not include_content:
        data.content = None
    return data


def _profile_to_schema(db: Session, profile: AiAssistantProfile) -> AiAssistantProfileRead:
    links = (
        db.query(AiAssistantProfileFile)
        .filter(AiAssistantProfileFile.profile_id == profile.id, AiAssistantProfileFile.is_active.is_(True))
        .order_by(AiAssistantProfileFile.sort_order.asc(), AiAssistantProfileFile.id.asc())
        .all()
    )
    file_ids = [link.file_id for link in links]
    files = []
    if file_ids:
        file_map = {
            file.id: file
            for file in db.query(AiInstructionFile)
            .filter(AiInstructionFile.id.in_(file_ids), AiInstructionFile.is_deleted.is_(False), AiInstructionFile.is_active.is_(True))
            .all()
        }
        files = [_file_to_schema(file_map[file_id], include_content=False) for file_id in file_ids if file_id in file_map]
    data = AiAssistantProfileRead.model_validate(profile)
    data.linked_file_ids = file_ids
    data.linked_files = files
    return data


def _validate_profile_provider_model(provider: str, model: str) -> tuple[str, str]:
    settings = get_settings()
    provider_key = str(provider or "").strip().lower()
    model_key = str(model or "").strip()
    allowed = settings.ai_allowed_models
    if provider_key not in allowed or model_key not in allowed[provider_key]:
        raise HTTPException(status_code=400, detail="Provider oder Modell ist nicht freigegeben.")
    return provider_key, model_key


def _sync_profile_links(db: Session, profile_id: int, file_ids: list[int]) -> None:
    normalized_ids = []
    for file_id in file_ids or []:
        try:
            int_id = int(file_id)
        except (TypeError, ValueError):
            continue
        if int_id not in normalized_ids:
            normalized_ids.append(int_id)

    valid_ids = {
        row.id
        for row in db.query(AiInstructionFile)
        .filter(AiInstructionFile.id.in_(normalized_ids), AiInstructionFile.is_deleted.is_(False))
        .all()
    } if normalized_ids else set()

    for link in db.query(AiAssistantProfileFile).filter(AiAssistantProfileFile.profile_id == profile_id).all():
        db.delete(link)

    for position, file_id in enumerate([file_id for file_id in normalized_ids if file_id in valid_ids], start=1):
        db.add(AiAssistantProfileFile(profile_id=profile_id, file_id=file_id, sort_order=position, is_active=True))


def _ensure_single_default_profile(db: Session, profile: AiAssistantProfile) -> None:
    if not profile.is_default:
        return
    db.query(AiAssistantProfile).filter(AiAssistantProfile.id != profile.id).update({"is_default": False}, synchronize_session=False)
    row = _settings_row(db)
    value = row.value or {}
    value["default_provider"] = profile.provider
    value["default_model"] = profile.model
    value["default_assistant_profile_id"] = profile.id
    row.value = value


@router.get("/ai-profiles", response_model=list[AiAssistantProfileRead])
def list_ai_profiles(include_inactive: bool = True, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    query = db.query(AiAssistantProfile).filter(AiAssistantProfile.is_deleted.is_(False))
    if not include_inactive:
        query = query.filter(AiAssistantProfile.is_active.is_(True))
    profiles = query.order_by(AiAssistantProfile.is_default.desc(), AiAssistantProfile.name.asc()).all()
    return [_profile_to_schema(db, profile) for profile in profiles]


@router.post("/ai-profiles", response_model=AiAssistantProfileRead)
def create_ai_profile(payload: AiAssistantProfileCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    provider, model = _validate_profile_provider_model(payload.provider, payload.model)
    profile = AiAssistantProfile(
        name=payload.name.strip(),
        description=payload.description,
        provider=provider,
        model=model,
        system_instruction=payload.system_instruction,
        response_format_instruction=payload.response_format_instruction,
        temperature=payload.temperature,
        max_output_tokens=payload.max_output_tokens,
        is_default=payload.is_default,
        is_active=payload.is_active,
        metadata_json={"created_from": "admin_profile"},
    )
    db.add(profile)
    db.flush()
    _sync_profile_links(db, profile.id, payload.linked_file_ids)
    _ensure_single_default_profile(db, profile)
    db.commit()
    db.refresh(profile)
    return _profile_to_schema(db, profile)


@router.put("/ai-profiles/{profile_id}", response_model=AiAssistantProfileRead)
def update_ai_profile(profile_id: int, payload: AiAssistantProfileUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    profile = db.query(AiAssistantProfile).filter(AiAssistantProfile.id == profile_id, AiAssistantProfile.is_deleted.is_(False)).first()
    if not profile:
        raise HTTPException(status_code=404, detail="KI-Profil wurde nicht gefunden.")
    data = payload.model_dump(exclude_unset=True)
    if "provider" in data or "model" in data:
        provider, model = _validate_profile_provider_model(data.get("provider", profile.provider), data.get("model", profile.model))
        data["provider"] = provider
        data["model"] = model
    linked_file_ids = data.pop("linked_file_ids", None)
    for key, value in data.items():
        setattr(profile, key, value)
    if linked_file_ids is not None:
        _sync_profile_links(db, profile.id, linked_file_ids)
    _ensure_single_default_profile(db, profile)
    db.commit()
    db.refresh(profile)
    return _profile_to_schema(db, profile)


@router.delete("/ai-profiles/{profile_id}")
def delete_ai_profile(profile_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    profile = db.query(AiAssistantProfile).filter(AiAssistantProfile.id == profile_id, AiAssistantProfile.is_deleted.is_(False)).first()
    if not profile:
        raise HTTPException(status_code=404, detail="KI-Profil wurde nicht gefunden.")
    profile.is_deleted = True
    profile.is_active = False
    profile.deleted_at = utc_now_naive()
    profile.deleted_reason = "KI-Profil gelöscht"
    db.commit()
    return {"ok": True, "deleted_profile_id": profile_id}


@router.get("/instruction-files", response_model=list[AiInstructionFileRead])
def list_instruction_files(include_inactive: bool = True, include_content: bool = False, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    query = db.query(AiInstructionFile).filter(AiInstructionFile.is_deleted.is_(False))
    if not include_inactive:
        query = query.filter(AiInstructionFile.is_active.is_(True))
    files = query.order_by(AiInstructionFile.title.asc()).all()
    return [_file_to_schema(file, include_content=include_content) for file in files]


@router.post("/instruction-files", response_model=AiInstructionFileRead)
def create_instruction_file(payload: AiInstructionFileCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    file = AiInstructionFile(**payload.model_dump(exclude_none=True))
    db.add(file)
    db.commit()
    db.refresh(file)
    return _file_to_schema(file)


@router.post("/instruction-files/upload", response_model=AiInstructionFileRead)
async def upload_instruction_file(
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    description: str | None = Form(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    raw = await file.read()
    if len(raw) > 1024 * 1024:
        raise HTTPException(status_code=413, detail="Instruction-Datei ist zu groß. Maximal 1 MB erlaubt.")
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="Instruction-Datei muss UTF-8 Text enthalten.") from exc
    row = AiInstructionFile(
        title=(title or file.filename or "Instruction-Datei").strip(),
        filename=file.filename,
        content_type=file.content_type or "text/plain",
        description=description,
        content=content,
        is_active=True,
        metadata_json={"upload_size": len(raw)},
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _file_to_schema(row)


@router.put("/instruction-files/{file_id}", response_model=AiInstructionFileRead)
def update_instruction_file(file_id: int, payload: AiInstructionFileUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    row = db.query(AiInstructionFile).filter(AiInstructionFile.id == file_id, AiInstructionFile.is_deleted.is_(False)).first()
    if not row:
        raise HTTPException(status_code=404, detail="Instruction-Datei wurde nicht gefunden.")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return _file_to_schema(row)


@router.delete("/instruction-files/{file_id}")
def delete_instruction_file(file_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    row = db.query(AiInstructionFile).filter(AiInstructionFile.id == file_id, AiInstructionFile.is_deleted.is_(False)).first()
    if not row:
        raise HTTPException(status_code=404, detail="Instruction-Datei wurde nicht gefunden.")
    row.is_deleted = True
    row.is_active = False
    row.deleted_at = utc_now_naive()
    row.deleted_reason = "Instruction-Datei gelöscht"
    db.commit()
    return {"ok": True, "deleted_file_id": file_id}

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_current_active_user
from app.config import get_settings
from app.database import get_db
from app.models import AiAssistantProfile, AiAssistantProfileFile, AiChatMessage, AiChatSession, AiInstructionFile, LyricCanvasHistory, LyricDraft, User, VocalTag
from app.schemas import (
    AiCanvasSaveRequest,
    AiChatMessageCreate,
    AiChatMessageRead,
    AiChatRunResponse,
    AiChatSessionCreate,
    AiChatSessionRead,
    AiChatSessionUpdate,
)
from app.services.ai_chat_service import AiChatService, AiProviderError
from app.utils.time_utils import utc_now_naive

router = APIRouter(prefix="/api/ai-chat", tags=["ai-chat"])


def _session_query(db: Session, user: User):
    return db.query(AiChatSession).filter(AiChatSession.user_id == user.id, AiChatSession.is_deleted.is_(False))


def _get_session_or_404(db: Session, session_id: int, user: User) -> AiChatSession:
    session = _session_query(db, user).filter(AiChatSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="KI-Session wurde nicht gefunden.")
    return session


def _message_to_schema(message: AiChatMessage) -> AiChatMessageRead:
    return AiChatMessageRead.model_validate(message)


def _normalize_work_mode(value: str | None) -> str:
    normalized = str(value or "lyrics").strip().lower().replace("-", "_")
    if normalized in {"instrumental", "instrumental_blueprint", "blueprint", "sound_blueprint", "sounds"}:
        return "instrumental_blueprint"
    return "lyrics"

def _session_work_mode(session: AiChatSession) -> str:
    metadata = session.metadata_json or {}
    if isinstance(metadata, dict):
        return _normalize_work_mode(metadata.get("work_mode"))
    return "lyrics"


def _session_to_schema(db: Session, session: AiChatSession, include_messages: bool = True) -> AiChatSessionRead:
    messages = []
    if include_messages:
        rows = db.query(AiChatMessage).filter(AiChatMessage.session_id == session.id).order_by(AiChatMessage.id.asc()).all()
        messages = [_message_to_schema(row) for row in rows]
    data = AiChatSessionRead.model_validate(session)
    data.messages = messages
    return data


def _add_history_version(db: Session, session: AiChatSession, content: str, source: str, change_summary: str | None = None) -> LyricCanvasHistory:
    latest = (
        db.query(LyricCanvasHistory)
        .filter(LyricCanvasHistory.session_id == session.id)
        .order_by(LyricCanvasHistory.version_index.desc())
        .first()
    )
    next_index = 1 if latest is None else latest.version_index + 1
    history = LyricCanvasHistory(session_id=session.id, version_index=next_index, content=content or "", source=source, change_summary=change_summary)
    session.current_history_index = next_index
    session.canvas_content = content or ""
    db.add(history)
    return history


@router.get("/config")
def get_ai_chat_config(db: Session = Depends(get_db)):
    settings = get_settings()
    base = settings.public_runtime_config().get("ai_chat", {})
    try:
        from app.routers.admin import get_ai_admin_settings
        admin_settings = get_ai_admin_settings(db)
        base["default_provider"] = admin_settings.get("default_provider", base.get("default_provider"))
        base["default_model"] = admin_settings.get("default_model", base.get("default_model"))
        base["default_assistant_profile_id"] = admin_settings.get("default_assistant_profile_id")
        base["system_instruction_configured"] = bool(admin_settings.get("system_instruction"))
        try:
            from app.routers.admin import _profile_to_schema
            profiles = db.query(AiAssistantProfile).filter(AiAssistantProfile.is_deleted.is_(False), AiAssistantProfile.is_active.is_(True)).order_by(AiAssistantProfile.is_default.desc(), AiAssistantProfile.name.asc()).all()
            base["assistant_profiles"] = [_profile_to_schema(db, profile).model_dump(mode="json") for profile in profiles]
        except Exception:
            base["assistant_profiles"] = []
    except Exception:
        pass
    return base


@router.get("/sessions", response_model=list[AiChatSessionRead])
def list_sessions(lyric_draft_id: int | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    query = _session_query(db, user)
    if lyric_draft_id is not None:
        query = query.filter(AiChatSession.lyric_draft_id == lyric_draft_id)
    sessions = query.order_by(AiChatSession.updated_at.desc()).all()
    return [_session_to_schema(db, session, include_messages=False) for session in sessions]


@router.post("/sessions", response_model=AiChatSessionRead)
def create_session(payload: AiChatSessionCreate, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    settings = get_settings()
    provider = payload.provider.strip().lower()
    allowed = settings.ai_allowed_models
    if provider not in allowed or payload.model not in allowed[provider]:
        raise HTTPException(status_code=400, detail="Provider oder Modell ist nicht freigegeben.")
    if payload.assistant_profile_id is not None:
        profile = db.query(AiAssistantProfile).filter(AiAssistantProfile.id == payload.assistant_profile_id, AiAssistantProfile.is_deleted.is_(False), AiAssistantProfile.is_active.is_(True)).first()
        if not profile:
            raise HTTPException(status_code=404, detail="KI-Profil wurde nicht gefunden.")
        provider = profile.provider
        payload.model = profile.model
    work_mode = _normalize_work_mode(payload.work_mode)
    session = AiChatSession(
        user_id=user.id,
        lyric_draft_id=payload.lyric_draft_id,
        title=payload.title,
        provider=provider,
        model=payload.model,
        assistant_profile_id=payload.assistant_profile_id,
        canvas_content=payload.canvas_content or "",
        metadata_json={"created_from": "songtext_studio", "work_mode": work_mode},
    )
    db.add(session)
    db.flush()
    _add_history_version(db, session, session.canvas_content or "", "initial", "Initialer Canvas")
    db.commit()
    db.refresh(session)
    return _session_to_schema(db, session)


@router.get("/sessions/{session_id}", response_model=AiChatSessionRead)
def get_session(session_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    session = _get_session_or_404(db, session_id, user)
    return _session_to_schema(db, session)


@router.patch("/sessions/{session_id}", response_model=AiChatSessionRead)
def update_session(session_id: int, payload: AiChatSessionUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    session = _get_session_or_404(db, session_id, user)
    data = payload.model_dump(exclude_unset=True)
    if "provider" in data and data["provider"]:
        data["provider"] = data["provider"].strip().lower()
    if "assistant_profile_id" in data and data["assistant_profile_id"] is not None:
        profile = db.query(AiAssistantProfile).filter(AiAssistantProfile.id == data["assistant_profile_id"], AiAssistantProfile.is_deleted.is_(False), AiAssistantProfile.is_active.is_(True)).first()
        if not profile:
            raise HTTPException(status_code=404, detail="KI-Profil wurde nicht gefunden.")
        data["provider"] = profile.provider
        data["model"] = profile.model
    if "provider" in data or "model" in data:
        provider = data.get("provider", session.provider)
        model = data.get("model", session.model)
        allowed = get_settings().ai_allowed_models
        if provider not in allowed or model not in allowed[provider]:
            raise HTTPException(status_code=400, detail="Provider oder Modell ist nicht freigegeben.")
    if "work_mode" in data:
        metadata = session.metadata_json or {}
        if not isinstance(metadata, dict):
            metadata = {}
        metadata["work_mode"] = _normalize_work_mode(data.pop("work_mode"))
        session.metadata_json = metadata
    for key, value in data.items():
        setattr(session, key, value)
    db.commit()
    db.refresh(session)
    return _session_to_schema(db, session)


@router.delete("/sessions/{session_id}")
def delete_session(session_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    session = _get_session_or_404(db, session_id, user)
    session.is_deleted = True
    session.deleted_at = utc_now_naive()
    session.deleted_reason = "KI-Chat-Session gelöscht"
    db.commit()
    return {"ok": True, "deleted_session_id": session_id}



def _get_profile_context(db: Session, session: AiChatSession) -> tuple[str | None, list[dict[str, str]], dict[str, object]]:
    profile = None
    if session.assistant_profile_id:
        profile = db.query(AiAssistantProfile).filter(AiAssistantProfile.id == session.assistant_profile_id, AiAssistantProfile.is_deleted.is_(False), AiAssistantProfile.is_active.is_(True)).first()
    if not profile:
        try:
            from app.routers.admin import get_ai_admin_settings
            default_id = get_ai_admin_settings(db).get("default_assistant_profile_id")
            if default_id:
                profile = db.query(AiAssistantProfile).filter(AiAssistantProfile.id == default_id, AiAssistantProfile.is_deleted.is_(False), AiAssistantProfile.is_active.is_(True)).first()
        except Exception:
            profile = None
    if not profile:
        return None, [], {}
    links = db.query(AiAssistantProfileFile).filter(AiAssistantProfileFile.profile_id == profile.id, AiAssistantProfileFile.is_active.is_(True)).order_by(AiAssistantProfileFile.sort_order.asc(), AiAssistantProfileFile.id.asc()).all()
    file_ids = [link.file_id for link in links]
    instruction_files = []
    if file_ids:
        rows = db.query(AiInstructionFile).filter(AiInstructionFile.id.in_(file_ids), AiInstructionFile.is_deleted.is_(False), AiInstructionFile.is_active.is_(True)).all()
        row_map = {row.id: row for row in rows}
        for file_id in file_ids:
            row = row_map.get(file_id)
            if row:
                instruction_files.append({"title": row.title, "description": row.description or "", "content": row.content})
    instruction_parts = []
    if profile.system_instruction:
        instruction_parts.append(profile.system_instruction)
    if profile.response_format_instruction:
        instruction_parts.append("Antwort-/Formatvorgaben:\n" + profile.response_format_instruction)
    return "\n\n".join(instruction_parts).strip() or None, instruction_files, {"profile_id": profile.id, "profile_name": profile.name, "temperature": profile.temperature, "max_output_tokens": profile.max_output_tokens}


@router.post("/sessions/{session_id}/messages", response_model=AiChatRunResponse)
async def send_message(session_id: int, payload: AiChatMessageCreate, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    session = _get_session_or_404(db, session_id, user)
    before = payload.canvas_content or session.canvas_content or ""
    user_message = AiChatMessage(session_id=session.id, role="user", content=payload.message, provider=session.provider, model=session.model, canvas_before=before, canvas_after=before)
    db.add(user_message)
    db.flush()
    work_mode = _normalize_work_mode(payload.work_mode or _session_work_mode(session))
    metadata = session.metadata_json or {}
    if not isinstance(metadata, dict):
        metadata = {}
    if metadata.get("work_mode") != work_mode:
        metadata["work_mode"] = work_mode
        session.metadata_json = metadata

    previous_messages = (
        db.query(AiChatMessage)
        .filter(AiChatMessage.session_id == session.id, AiChatMessage.id != user_message.id)
        .order_by(AiChatMessage.id.desc())
        .limit(12)
        .all()
    )
    history = [{"role": message.role if message.role in {"user", "assistant"} else "user", "content": message.content} for message in reversed(previous_messages)]
    try:
        from app.routers.admin import get_ai_admin_settings
        admin_settings = get_ai_admin_settings(db)
        profile_instruction, instruction_files, profile_options = _get_profile_context(db, session)
        system_instruction_parts = [admin_settings.get("system_instruction") or ""]
        if profile_instruction:
            system_instruction_parts.append(profile_instruction)
        effective_system_instruction = "\n\n".join(part.strip() for part in system_instruction_parts if part and part.strip())
        vocal_tags = [
            {"label": tag.label, "tag": tag.tag, "category": tag.category, "description": tag.description}
            for tag in db.query(VocalTag)
            .filter(VocalTag.is_deleted.is_(False), VocalTag.is_active.is_(True))
            .order_by(VocalTag.category.asc(), VocalTag.sort_order.asc(), VocalTag.label.asc())
            .all()
        ]
        result = await AiChatService().run_canvas_assistant(
            provider=session.provider,
            model=session.model,
            user_message=payload.message,
            canvas_content=before,
            history=history,
            system_instruction=effective_system_instruction,
            vocal_tags=vocal_tags,
            instruction_files=instruction_files,
            profile_options=profile_options,
            allow_canvas_changes=payload.apply_to_canvas,
            work_mode=work_mode,
        )
    except AiProviderError as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    after = result.canvas_text if payload.apply_to_canvas and result.canvas_text is not None else before
    assistant = AiChatMessage(
        session_id=session.id,
        role="assistant",
        content=result.assistant_message,
        provider=session.provider,
        model=session.model,
        canvas_before=before,
        canvas_after=after,
        change_summary=result.change_summary,
        raw_response=result.raw_response,
    )
    db.add(assistant)
    if after != before:
        _add_history_version(db, session, after, "ai", result.change_summary)
        if session.lyric_draft_id:
            draft = db.query(LyricDraft).filter(LyricDraft.id == session.lyric_draft_id, LyricDraft.is_deleted.is_(False)).first()
            if draft:
                draft.content = after
    else:
        session.canvas_content = before
    db.commit()
    db.refresh(session)
    db.refresh(assistant)
    return AiChatRunResponse(session=_session_to_schema(db, session), assistant_message=_message_to_schema(assistant), canvas_changed=after != before, canvas_content=after, change_summary=result.change_summary)


@router.post("/sessions/{session_id}/messages/clear", response_model=AiChatSessionRead)
def clear_session_messages(session_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    session = _get_session_or_404(db, session_id, user)
    db.query(AiChatMessage).filter(AiChatMessage.session_id == session.id).delete(synchronize_session=False)
    metadata = session.metadata_json or {}
    if not isinstance(metadata, dict):
        metadata = {}
    metadata["chat_cleared_at"] = utc_now_naive().isoformat()
    session.metadata_json = metadata
    db.commit()
    db.refresh(session)
    return _session_to_schema(db, session)


@router.post("/sessions/{session_id}/canvas", response_model=AiChatSessionRead)
def save_canvas(session_id: int, payload: AiCanvasSaveRequest, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    session = _get_session_or_404(db, session_id, user)
    _add_history_version(db, session, payload.canvas_content, payload.source, payload.change_summary)
    if session.lyric_draft_id:
        draft = db.query(LyricDraft).filter(LyricDraft.id == session.lyric_draft_id, LyricDraft.is_deleted.is_(False)).first()
        if draft:
            draft.content = payload.canvas_content
    db.commit()
    db.refresh(session)
    return _session_to_schema(db, session)


@router.post("/sessions/{session_id}/undo", response_model=AiChatSessionRead)
def undo_canvas(session_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    session = _get_session_or_404(db, session_id, user)
    target_index = max(1, int(session.current_history_index or 1) - 1)
    history = db.query(LyricCanvasHistory).filter(LyricCanvasHistory.session_id == session.id, LyricCanvasHistory.version_index == target_index).first()
    if not history:
        raise HTTPException(status_code=409, detail="Kein älterer Canvas-Stand vorhanden.")
    session.current_history_index = history.version_index
    session.canvas_content = history.content
    db.commit()
    db.refresh(session)
    return _session_to_schema(db, session)


@router.post("/sessions/{session_id}/redo", response_model=AiChatSessionRead)
def redo_canvas(session_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    session = _get_session_or_404(db, session_id, user)
    target_index = int(session.current_history_index or 1) + 1
    history = db.query(LyricCanvasHistory).filter(LyricCanvasHistory.session_id == session.id, LyricCanvasHistory.version_index == target_index).first()
    if not history:
        raise HTTPException(status_code=409, detail="Kein neuerer Canvas-Stand vorhanden.")
    session.current_history_index = history.version_index
    session.canvas_content = history.content
    db.commit()
    db.refresh(session)
    return _session_to_schema(db, session)

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import get_current_active_user
from app.database import get_db
from app.models import User
from app.services.ai_chat_service import AiProviderError
from app.services.global_assistant_service import GlobalAssistantService

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


class AssistantChatRequest(BaseModel):
    message: str = Field(default="", max_length=8000)
    app_context: dict[str, Any] = Field(default_factory=dict)
    action_id: str | None = Field(default=None, max_length=120)
    profile_id: int | None = None
    apply_to_canvas: bool = False
    chat_history: list[dict[str, Any]] = Field(default_factory=list)


class StyleSuggestionFeatures(BaseModel):
    instruments: bool = True
    arrangement: bool = True
    negative_tags: bool = True
    scores: bool = True
    vocal_delivery: bool = True
    lyric_vocal_tags: bool = True


class StyleSuggestionRequest(BaseModel):
    lyrics: str = Field(..., min_length=1, max_length=5000)
    amount: int = Field(default=3, ge=1, le=5)
    extra_prompt: str | None = Field(default=None, max_length=3000)
    title: str | None = Field(default=None, max_length=255)
    current_style: str | None = Field(default=None, max_length=1000)
    profile_id: int | None = None
    features: StyleSuggestionFeatures = Field(default_factory=StyleSuggestionFeatures)
    variant_strategy: str = Field(default="balanced", max_length=80)
    batch_mode: str | None = Field(default=None, max_length=40)


class StyleSuggestionInstrument(BaseModel):
    name: str
    role: str | None = None
    reason: str | None = None


class StyleSuggestionArrangementSection(BaseModel):
    section: str
    idea: str


class StyleSuggestionScores(BaseModel):
    fit: float | None = None
    hook_potential: float | None = None
    suno_clarity: float | None = None
    risk: float | None = None


class StyleSuggestionLyricVocalTag(BaseModel):
    section: str
    tag: str
    reason: str | None = None


class StyleSuggestionItem(BaseModel):
    title: str
    style: str
    reason: str | None = None
    bpm: str | None = None
    key_hint: str | None = None
    energy: str | None = None
    vocal_delivery: str | None = None
    instruments: list[StyleSuggestionInstrument | str] = Field(default_factory=list)
    arrangement: list[StyleSuggestionArrangementSection | str] = Field(default_factory=list)
    negative_tags: str | None = None
    lyric_vocal_tags: list[StyleSuggestionLyricVocalTag | str] = Field(default_factory=list)
    scores: StyleSuggestionScores | None = None
    role: str | None = None


class StyleSuggestionResponse(BaseModel):
    ok: bool = True
    amount: int
    suggestions: list[StyleSuggestionItem]
    runtime_info: dict[str, Any] | None = None




class StyleTaggedLyricsRequest(BaseModel):
    lyrics: str = Field(..., min_length=1, max_length=5000)
    suggestion: StyleSuggestionItem
    title: str | None = Field(default=None, max_length=255)
    profile_id: int | None = None


class StyleTaggedLyricsResponse(BaseModel):
    ok: bool = True
    tagged_lyrics: str
    lyric_vocal_tags: list[StyleSuggestionLyricVocalTag | str] = Field(default_factory=list)
    notes: str | None = None
    runtime_info: dict[str, Any] | None = None


class StyleConsultationMessage(BaseModel):
    role: str = Field(default="user", max_length=40)
    content: str = Field(default="", max_length=5000)


class StyleConsultationRequest(BaseModel):
    lyrics: str = Field(default="", max_length=5000)
    message: str = Field(..., min_length=1, max_length=5000)
    draft: StyleSuggestionItem
    history: list[StyleConsultationMessage] = Field(default_factory=list)
    mode: str = Field(default="advise_or_update", max_length=80)
    profile_id: int | None = None


class StyleConsultationResponse(BaseModel):
    ok: bool = True
    assistant_message: str
    updated_draft: StyleSuggestionItem | None = None
    changed: bool = False
    runtime_info: dict[str, Any] | None = None


class AssistantAction(BaseModel):
    id: str
    label: str
    type: str = "frontend"
    requires_confirmation: bool = False


class AssistantChatResponse(BaseModel):
    ok: bool = True
    reply: str
    suggested_actions: list[dict[str, Any]] = Field(default_factory=list)
    proposed_canvas: str | None = None
    change_summary: str | None = None
    context_summary: str | None = None
    runtime_info: dict[str, Any] | None = None


@router.post("/chat", response_model=AssistantChatResponse)
async def assistant_chat(payload: AssistantChatRequest, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    result = await GlobalAssistantService().run(
        db,
        message=payload.message,
        app_context=payload.app_context or {},
        action_id=payload.action_id,
        profile_id=payload.profile_id,
        apply_to_canvas=payload.apply_to_canvas,
        history=payload.chat_history or [],
    )
    return AssistantChatResponse(
        reply=result.reply,
        suggested_actions=result.suggested_actions,
        proposed_canvas=result.proposed_canvas,
        change_summary=result.change_summary,
        context_summary=result.context_summary,
        runtime_info=result.runtime_info,
    )


@router.post("/actions/preview", response_model=AssistantChatResponse)
async def assistant_action_preview(payload: AssistantChatRequest, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    result = await GlobalAssistantService().run(
        db,
        message=payload.message,
        app_context=payload.app_context or {},
        action_id=payload.action_id,
        profile_id=payload.profile_id,
        apply_to_canvas=False,
    )
    return AssistantChatResponse(
        reply=result.reply,
        suggested_actions=result.suggested_actions,
        proposed_canvas=result.proposed_canvas,
        change_summary=result.change_summary,
        context_summary=result.context_summary,
        runtime_info=result.runtime_info,
    )


@router.post("/style-suggestions", response_model=StyleSuggestionResponse)
async def assistant_style_suggestions(payload: StyleSuggestionRequest, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    try:
        result = await GlobalAssistantService().generate_style_suggestions(
            db,
            lyrics=payload.lyrics,
            amount=payload.amount,
            extra_prompt=payload.extra_prompt,
            title=payload.title,
            current_style=payload.current_style,
            profile_id=payload.profile_id,
            features=payload.features.model_dump(),
            variant_strategy=payload.variant_strategy,
            batch_mode=payload.batch_mode,
        )
        return StyleSuggestionResponse(**result)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AiProviderError as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail=f"KI-Provider-Fehler: {exc}") from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"KI-Style-Vorschläge konnten nicht erstellt werden: {type(exc).__name__}") from exc




@router.post("/style-tagged-lyrics", response_model=StyleTaggedLyricsResponse)
async def assistant_style_tagged_lyrics(payload: StyleTaggedLyricsRequest, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    try:
        result = await GlobalAssistantService().generate_style_tagged_lyrics(
            db,
            lyrics=payload.lyrics,
            suggestion=payload.suggestion.model_dump(),
            title=payload.title,
            profile_id=payload.profile_id,
        )
        return StyleTaggedLyricsResponse(**result)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AiProviderError as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail=f"KI-Provider-Fehler: {exc}") from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Getaggter Songtext konnte nicht erstellt werden: {type(exc).__name__}") from exc


@router.post("/style-consultation", response_model=StyleConsultationResponse)
async def assistant_style_consultation(payload: StyleConsultationRequest, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    try:
        result = await GlobalAssistantService().run_style_consultation(
            db,
            lyrics=payload.lyrics,
            message=payload.message,
            draft=payload.draft.model_dump(),
            history=[item.model_dump() for item in payload.history or []],
            mode=payload.mode,
            profile_id=payload.profile_id,
        )
        return StyleConsultationResponse(**result)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AiProviderError as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail=f"KI-Provider-Fehler: {exc}") from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"KI-Style-Beratung konnte nicht erstellt werden: {type(exc).__name__}") from exc


@router.get("/runtime")
def assistant_runtime(profile_id: int | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    return GlobalAssistantService().get_runtime_info(db, profile_id)


@router.get("/actions")
def assistant_actions(active_tab: str | None = None, user: User = Depends(get_current_active_user)):
    return GlobalAssistantService().default_actions_for_page(active_tab)

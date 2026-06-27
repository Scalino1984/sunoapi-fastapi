from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AudioAsset, Song
from app.services.srt_transcript_service import get_saved_transcript, save_manual_srt_for_audio_asset

router = APIRouter(prefix="/api/songs", tags=["songs-srt"])


class SongSrtUpdateRequest(BaseModel):
    srt_edited: str | None = None
    segments: list[dict[str, Any]] = Field(default_factory=list)
    status: str = "edited"


def _audio_asset_for_song(db: Session, song_id: int) -> AudioAsset:
    song = db.query(Song).filter(Song.id == song_id, Song.is_deleted.is_(False)).first()
    if not song:
        raise HTTPException(status_code=404, detail="Song wurde nicht gefunden.")
    asset = db.query(AudioAsset).filter(AudioAsset.song_id == song_id, AudioAsset.is_deleted.is_(False)).order_by(AudioAsset.id.desc()).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Für diesen Song wurde kein AudioAsset gefunden.")
    return asset


@router.get("/{song_id}/srt")
def read_song_srt(song_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    asset = _audio_asset_for_song(db, song_id)
    result = get_saved_transcript(db, asset.id)
    return {
        "song_id": song_id,
        "audio_asset_id": asset.id,
        "srt_raw": result.get("srt_text") or "",
        "srt_edited": result.get("srt_text") or "",
        "segments": result.get("segments") or [],
        "status": "edited" if result.get("exists") else result.get("status", "missing"),
        "updated_at": result.get("updated_at"),
    }


@router.put("/{song_id}/srt")
def update_song_srt(song_id: int, payload: SongSrtUpdateRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    asset = _audio_asset_for_song(db, song_id)
    result = save_manual_srt_for_audio_asset(
        db=db,
        audio_asset_id=asset.id,
        srt_text=payload.srt_edited,
        segments=payload.segments if payload.segments else None,
    )
    return {
        "song_id": song_id,
        "audio_asset_id": asset.id,
        "srt_raw": result.get("srt_text") or "",
        "srt_edited": result.get("srt_text") or "",
        "segments": result.get("segments") or [],
        "status": payload.status or "edited",
        "updated_at": result.get("updated_at"),
    }

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import GenerateLyricsRequest, TaskRead, TimestampedLyricsRequest
from app.services.music_service import MusicService
from app.suno_client import SunoAPIClient, SunoAPIError


router = APIRouter(prefix="/api/lyrics", tags=["lyrics"])


@router.post("/generate", response_model=TaskRead)
async def generate_lyrics(payload: GenerateLyricsRequest, db: Session = Depends(get_db)):
    try:
        return await MusicService(db).generate_lyrics(payload.model_dump(exclude_none=True))
    except SunoAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/timestamped", response_model=dict)
async def get_timestamped_lyrics(payload: TimestampedLyricsRequest):
    return await SunoAPIClient().get_timestamped_lyrics(payload.model_dump(exclude_none=True))

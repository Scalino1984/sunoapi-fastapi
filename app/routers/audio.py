from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import ConvertToWavRequest, GenerateMidiRequest, SeparateAudioRequest, TaskRead, TimestampedLyricsRequest
from app.services.music_service import MusicService


router = APIRouter(prefix="/api/audio", tags=["audio"])


@router.post("/separate", response_model=TaskRead)
async def separate(payload: SeparateAudioRequest, db: Session = Depends(get_db)):
    return await MusicService(db).call_task_endpoint("separate", payload.model_dump(by_alias=True, exclude_none=True))


@router.post("/wav", response_model=TaskRead)
async def convert_to_wav(payload: ConvertToWavRequest, db: Session = Depends(get_db)):
    return await MusicService(db).call_task_endpoint("convert_to_wav", payload.model_dump(by_alias=True, exclude_none=True))


@router.post("/midi", response_model=TaskRead)
async def generate_midi(payload: GenerateMidiRequest, db: Session = Depends(get_db)):
    return await MusicService(db).call_task_endpoint("generate_midi", payload.model_dump(by_alias=True, exclude_none=True))


@router.post("/timestamped-lyrics", response_model=TaskRead)
async def get_timestamped_lyrics(payload: TimestampedLyricsRequest, db: Session = Depends(get_db)):
    return await MusicService(db).call_task_endpoint("get_timestamped_lyrics", payload.model_dump(by_alias=True, exclude_none=True))

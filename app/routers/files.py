from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session
from pydantic import BaseModel, ConfigDict

from app.database import get_db
from app.schemas import UploadBase64Request, UploadUrlRequest
from app.services.file_service import FileService


class UploadedFileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    upload_method: str
    original_name: str | None = None
    source_url: str | None = None
    uploaded_url: str | None = None
    response_payload: dict | None = None


router = APIRouter(prefix="/api/files", tags=["files"])


@router.post("/base64", response_model=UploadedFileRead)
async def upload_base64(payload: UploadBase64Request, db: Session = Depends(get_db)):
    return await FileService(db).upload_base64(payload.file, original_name=payload.original_name)


@router.post("/url", response_model=UploadedFileRead)
async def upload_url(payload: UploadUrlRequest, db: Session = Depends(get_db)):
    return await FileService(db).upload_url(payload.url)


@router.post("/stream", response_model=UploadedFileRead)
async def upload_stream(upload: UploadFile = File(...), db: Session = Depends(get_db)):
    content = await upload.read()
    return await FileService(db).upload_stream(
        filename=upload.filename or "upload.bin",
        content=content,
        content_type=upload.content_type,
    )


@router.get("", response_model=list[UploadedFileRead])
def list_files(db: Session = Depends(get_db)):
    return FileService(db).list_files()

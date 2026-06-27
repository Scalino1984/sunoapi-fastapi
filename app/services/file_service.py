from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import UploadedFileRecord
from app.suno_client import SunoAPIClient


class FileService:
    def __init__(self, db: Session, client: SunoAPIClient | None = None) -> None:
        self.db = db
        self.client = client or SunoAPIClient()

    async def upload_base64(self, file_base64: str, original_name: str | None = None) -> UploadedFileRecord:
        payload = {"file": file_base64}
        if original_name:
            payload["original_name"] = original_name

        response = await self.client.upload_base64(payload)
        record = UploadedFileRecord(
            upload_method="base64",
            original_name=original_name,
            uploaded_url=self._extract_uploaded_url(response),
            response_payload=response,
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    async def upload_url(self, url: str) -> UploadedFileRecord:
        response = await self.client.upload_url({"url": url})
        record = UploadedFileRecord(
            upload_method="url",
            source_url=url,
            uploaded_url=self._extract_uploaded_url(response),
            response_payload=response,
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    async def upload_stream(self, filename: str, content: bytes, content_type: str | None = None) -> UploadedFileRecord:
        response = await self.client.upload_stream(filename=filename, content=content, content_type=content_type)
        record = UploadedFileRecord(
            upload_method="stream",
            original_name=filename,
            uploaded_url=self._extract_uploaded_url(response),
            response_payload=response,
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def list_files(self, limit: int = 50) -> list[UploadedFileRecord]:
        return (
            self.db.query(UploadedFileRecord)
            .order_by(UploadedFileRecord.created_at.desc())
            .limit(limit)
            .all()
        )

    @staticmethod
    def _extract_uploaded_url(response: dict) -> str | None:
        for key in ("url", "file_url", "audio_url"):
            if response.get(key):
                return str(response[key])
        data = response.get("data")
        if isinstance(data, dict):
            for key in ("url", "file_url", "audio_url"):
                if data.get(key):
                    return str(data[key])
        return None

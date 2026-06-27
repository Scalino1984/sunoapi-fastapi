from __future__ import annotations

import asyncio
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import SunoTask
from app.suno_client import SunoAPIClient


class PollingService:
    def __init__(self, db: Session, client: SunoAPIClient | None = None) -> None:
        self.db = db
        self.client = client or SunoAPIClient()
        self.settings = get_settings()

    async def poll_once(self, task_id: str, vocal_separation: bool = False) -> SunoTask | None:
        task = self.db.query(SunoTask).filter(SunoTask.task_id == task_id).first()
        if not task:
            return None

        if vocal_separation:
            details = await self.client.get_vocal_separation_details(task_id)
        else:
            details = await self.client.get_details(task_id)

        task.result_payload = details
        task.status = self._extract_status(details) or task.status
        self.db.commit()
        self.db.refresh(task)
        return task

    async def poll_until_done(self, task_id: str, vocal_separation: bool = False) -> SunoTask | None:
        last_task: SunoTask | None = None

        for _ in range(self.settings.polling_max_attempts):
            last_task = await self.poll_once(task_id, vocal_separation=vocal_separation)
            if last_task and last_task.status.lower() in {"completed", "complete", "failed", "error"}:
                return last_task
            await asyncio.sleep(self.settings.polling_interval_seconds)

        return last_task

    @staticmethod
    def _extract_status(payload: dict) -> str | None:
        for key in ("status", "state"):
            if payload.get(key):
                return str(payload[key])

        data = payload.get("data")
        if isinstance(data, dict):
            for key in ("status", "state"):
                if data.get(key):
                    return str(data[key])

        return None

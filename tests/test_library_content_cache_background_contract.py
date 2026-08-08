from types import SimpleNamespace

import pytest

from app.models import SunoTask
from app.services.library_content_cache_service import (
    cache_missing_library_content_once,
    create_library_content_cache_task,
    run_library_content_cache_task,
)
from app.services.music_service import MusicService


def test_library_content_cache_public_background_contract_is_exported():
    assert callable(create_library_content_cache_task)
    assert callable(run_library_content_cache_task)


def test_create_library_content_cache_task_creates_local_running_task(isolated_db_session):
    db = isolated_db_session

    task = create_library_content_cache_task(db, limit=321, background=True, notify_always=True)

    assert task.id is not None
    assert task.task_id.startswith("local-library-content-cache-")
    assert task.task_type == "library_content_cache"
    assert task.status == "RUNNING"
    assert task.request_payload["limit"] == 321
    assert task.request_payload["local_task"] is True
    assert task.response_payload["local_task"] is True


@pytest.mark.asyncio
async def test_existing_background_task_is_reused_without_duplicate(
    monkeypatch,
    isolated_db_session,
):
    db = isolated_db_session
    task = create_library_content_cache_task(db, limit=50, background=True, notify_always=False)
    original_id = task.id

    monkeypatch.setattr(
        "app.services.library_content_cache_service.AudioAssetMaterializationService.materialize_recent_tasks",
        lambda self, **kwargs: SimpleNamespace(created=0, updated=0),
    )
    monkeypatch.setattr(
        "app.services.library_content_cache_service._hydrate_generated_cover_sources_from_tasks",
        lambda db, **kwargs: 0,
    )
    monkeypatch.setattr(
        "app.services.library_content_cache_service._repair_generation_options_from_tasks",
        lambda db, **kwargs: 0,
    )
    monkeypatch.setattr(
        "app.services.library_content_cache_service._repair_misclassified_local_provider_checks",
        lambda db: 0,
    )

    async def no_provider_backfill(self, *, limit=40):
        return 0

    monkeypatch.setattr(MusicService, "repair_imported_task_generation_options_from_provider", no_provider_backfill)

    result = await cache_missing_library_content_once(
        db,
        limit=50,
        notify_always=False,
        background=True,
        status_task=task,
    )

    rows = db.query(SunoTask).filter(SunoTask.task_type == "library_content_cache").all()
    assert len(rows) == 1
    assert rows[0].id == original_id
    assert rows[0].status == "SUCCESS"
    assert rows[0].result_payload["failed"] == 0
    assert result["ok"] is True

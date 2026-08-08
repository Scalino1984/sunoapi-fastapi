"""Protect additive schema compatibility across independent patch archives."""

from app.schemas import (
    AiAdminSettingsRead,
    AuditApplyRequest,
    AuditRunRequest,
    BatchImportSunoTaskRequest,
    LibrarySearchIndexUpdate,
)


def test_audit_and_library_schema_models_survive_stem_backend_extension():
    audit = AuditApplyRequest(confirm="REPARATUR ANWENDEN", repair_actions=["backfill_task_completed_at"])
    run = AuditRunRequest(check_ids=["workflow.tasks"])
    index = LibrarySearchIndexUpdate(tags=["rap"], language="de")
    batch = BatchImportSunoTaskRequest(task_ids="abc")

    assert audit.confirm == "REPARATUR ANWENDEN"
    assert run.check_ids == ["workflow.tasks"]
    assert index.tags == ["rap"]
    assert batch.cache_video is True
    assert AiAdminSettingsRead.model_fields["stem_generation_backend"].default == "local_demucs"

from __future__ import annotations

from app.models import AudioAsset, AudioTranscript, StatusNotification, SunoTask
from app.services.audit_registry_service import list_audit_checks, normalize_check_ids
from app.services.audit_runner_service import run_audit_checks, serialize_audit_task
from app.utils.time_utils import utc_now_naive


def test_audit_registry_contains_mvp_checks():
    ids = {item["id"] for item in list_audit_checks()}
    assert {
        "database.integrity",
        "database.references",
        "imports.provenance",
        "workflow.tasks",
        "storage.references",
        "runtime.configuration",
    }.issubset(ids)
    assert normalize_check_ids(["database.integrity"]) == ["database.integrity"]


def test_reference_audit_detects_orphan_task_without_writing(isolated_db_session):
    db = isolated_db_session
    asset = AudioAsset(
        task_local_id=987654,
        source_url="https://example.invalid/test.mp3",
        status="remote",
        is_deleted=False,
    )
    db.add(asset)
    db.commit()

    report = run_audit_checks(db, ["database.references"], {"max_findings": 100})

    findings = report["results"][0]["findings"]
    assert any(item["code"] == "AUDIO_TASK_ORPHAN" and item["entity_id"] == asset.id for item in findings)
    assert db.query(AudioAsset).filter(AudioAsset.id == asset.id).one().task_local_id == 987654


def test_provenance_audit_detects_false_manual_import_marker(isolated_db_session):
    db = isolated_db_session
    task = SunoTask(
        task_type="generate_music",
        status="SUCCESS",
        request_payload={
            "source": "manual_sunoapi_import",
            "callback_url": "http://localhost:8000/api/webhooks/suno",
        },
        response_payload={},
        is_deleted=False,
    )
    db.add(task)
    db.commit()

    report = run_audit_checks(db, ["imports.provenance"], {})
    result = report["results"][0]

    assert result["repairable_count"] == 1
    assert result["repair_plan"]["candidate_task_ids"] == [task.id]
    assert db.query(SunoTask).filter(SunoTask.id == task.id).one().request_payload["source"] == "manual_sunoapi_import"


def test_workflow_audit_reports_invalid_progress(isolated_db_session):
    db = isolated_db_session
    task = SunoTask(
        task_type="generate_srt",
        status="FAILED",
        progress=140,
        request_payload={"local_task": True, "audio_asset_id": 1},
        response_payload={},
        is_deleted=False,
    )
    db.add(task)
    db.commit()

    report = run_audit_checks(db, ["workflow.tasks"], {})
    findings = report["results"][0]["findings"]

    assert any(item["code"] == "TASK_PROGRESS_INVALID" for item in findings)
    assert db.query(SunoTask).filter(SunoTask.id == task.id).one().progress == 140
    assert report["problem_type_count"] >= 1


def test_compact_audit_serialization_keeps_problem_type_count(isolated_db_session):
    db = isolated_db_session
    report = run_audit_checks(db, ["database.integrity"], {})
    report["problem_type_count"] = 3
    report["finding_count"] = 12
    task = SunoTask(
        task_type="maintenance_audit",
        status="SUCCESS",
        progress=100,
        request_payload={"check_ids": ["database.integrity"]},
        response_payload={},
        result_payload=report,
        is_deleted=False,
    )
    db.add(task)
    db.commit()

    compact = serialize_audit_task(task, include_result=False)

    assert compact["result_payload"]["problem_type_count"] == 3
    assert compact["result_payload"]["finding_count"] == 12


def test_reference_audit_ignores_archived_orphan_and_offers_safe_archive(isolated_db_session):
    db = isolated_db_session
    archived = AudioTranscript(
        audio_asset_id=900001,
        backend="groq",
        status="archived_orphan",
        error_message="Bereits bewusst archiviert.",
    )
    open_orphan = AudioTranscript(
        audio_asset_id=900002,
        backend="groq",
        status="success",
        srt_path="storage/transcripts/orphan.srt",
    )
    db.add_all([archived, open_orphan])
    db.commit()

    report = run_audit_checks(db, ["database.references"], {})
    result = report["results"][0]
    findings = [item for item in result["findings"] if item["code"] == "TRANSCRIPT_AUDIO_ORPHAN"]

    assert [item["entity_id"] for item in findings] == [open_orphan.id]
    assert findings[0]["repairable"] is True
    assert findings[0]["repair_action"] == "archive_orphan_transcript"
    assert result["repair_plan"]["orphan_transcript_ids"] == [open_orphan.id]


def test_workflow_audit_offers_completion_backfill_and_ignores_user_cancel_notice(isolated_db_session):
    db = isolated_db_session
    task = SunoTask(
        task_type="generate_srt",
        status="SUCCESS",
        progress=100,
        request_payload={"local_task": True, "audio_asset_id": 1},
        response_payload={},
        is_deleted=False,
    )
    db.add(task)
    db.flush()
    progress_notice = StatusNotification(
        event_type="generate_srt_started",
        title="SRT gestartet",
        status="unread",
        task_local_id=task.id,
        is_deleted=False,
    )
    user_notice = StatusNotification(
        event_type="task_cancel_requested",
        title="Abbruch angefordert",
        status="unread",
        task_local_id=task.id,
        is_deleted=False,
    )
    db.add_all([progress_notice, user_notice])
    db.commit()

    report = run_audit_checks(db, ["workflow.tasks"], {})
    result = report["results"][0]
    findings = result["findings"]

    completion = next(item for item in findings if item["code"] == "TERMINAL_TASK_WITHOUT_COMPLETED_AT")
    assert completion["repairable"] is True
    assert completion["repair_action"] == "backfill_task_completed_at"
    notification_ids = [item["entity_id"] for item in findings if item["code"] == "OPEN_NOTIFICATION_FOR_TERMINAL_TASK"]
    assert notification_ids == [progress_notice.id]
    assert result["repair_plan"]["terminal_task_ids_without_completed_at"] == [task.id]
    assert result["repair_plan"]["open_terminal_notification_ids"] == [progress_notice.id]


def test_audit_routes_are_registered():
    from app.main import app

    paths = app.openapi()["paths"]
    assert "/api/audit/checks" in paths
    assert "/api/audit/runs" in paths
    assert "/api/audit/runs/{task_id}" in paths
    assert "/api/audit/runs/{task_id}/report" in paths
    assert "/api/audit/runs/{task_id}/apply" in paths
    assert "/api/audit/runs/{task_id}/cancel" in paths


def test_provenance_repair_worker_rechecks_and_preserves_metadata(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.models import Base, AudioAsset, Song, SunoTask
    import app.services.audit_runner_service as audit_service

    db_path = tmp_path / "audit-repair.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=True, autocommit=False)
    monkeypatch.setattr(audit_service, "SessionLocal", Session)

    db = Session()
    try:
        target = SunoTask(
            task_id="provider-task-1",
            task_type="generate_music",
            status="SUCCESS",
            request_payload={"source": "manual_sunoapi_import", "callback_url": "http://localhost/callback", "keep": "value"},
            response_payload={},
            is_deleted=False,
        )
        db.add(target)
        db.flush()
        song = Song(task_id=target.task_id, title="Test", metadata_json={"request_payload": {"source": "manual_sunoapi_import", "keep": 1}}, is_deleted=False)
        asset = AudioAsset(task_local_id=target.id, suno_task_id=target.task_id, source_url="https://example.invalid/audio.mp3", status="remote", metadata_json={"request_payload": {"source": "manual_sunoapi_import", "keep": 2}, "other": {"preserve": True}}, is_deleted=False)
        db.add_all([song, asset])
        db.commit()

        report = audit_service.run_audit_checks(db, ["imports.provenance"], {})
        source_run = SunoTask(task_type="maintenance_audit", status="SUCCESS", progress=100, result_payload=report, request_payload={"local_task": True}, response_payload={}, is_deleted=False)
        repair_run = SunoTask(task_type="maintenance_repair", status="QUEUED", progress=0, request_payload={"local_task": True}, response_payload={}, is_deleted=False)
        db.add_all([source_run, repair_run])
        db.commit()
        target_id, song_id, asset_id = target.id, song.id, asset.id
        source_id, repair_id = source_run.id, repair_run.id
    finally:
        db.close()

    audit_service._run_repair_worker(repair_id, source_id)

    db = Session()
    try:
        repaired_target = db.query(SunoTask).filter(SunoTask.id == target_id).one()
        repaired_song = db.query(Song).filter(Song.id == song_id).one()
        repaired_asset = db.query(AudioAsset).filter(AudioAsset.id == asset_id).one()
        repaired_run = db.query(SunoTask).filter(SunoTask.id == repair_id).one()
        assert repaired_target.request_payload == {"callback_url": "http://localhost/callback", "keep": "value"}
        assert repaired_song.metadata_json["request_payload"] == {"keep": 1}
        assert repaired_asset.metadata_json["request_payload"] == {"keep": 2}
        assert repaired_asset.metadata_json["other"] == {"preserve": True}
        assert repaired_run.status == "SUCCESS"
        assert repaired_run.result_payload["backup_path"]
        assert repaired_run.result_payload["repair_summary"]["action_count"] == 1
        assert repaired_run.result_payload["repair_summary"]["changed_records"] == 3
        assert __import__('pathlib').Path(repaired_run.result_payload["backup_path"]).exists()
    finally:
        db.close()
        engine.dispose()


def test_compact_repair_serialization_contains_repair_summary(isolated_db_session):
    db = isolated_db_session
    task = SunoTask(
        task_type="maintenance_repair",
        status="SUCCESS",
        progress=100,
        request_payload={"source_audit_task_id": 11},
        response_payload={},
        result_payload={
            "source_audit_task_id": 11,
            "selected_repair_actions": ["backfill_task_completed_at"],
            "actions": {
                "workflow.tasks": {
                    "backfill_task_completed_at": {
                        "backfilled": 7,
                        "already_completed": 2,
                    }
                }
            },
        },
        is_deleted=False,
    )
    db.add(task)
    db.commit()

    compact = serialize_audit_task(task, include_result=False)
    summary = compact["result_payload"]["repair_summary"]

    assert summary == {
        "action_count": 1,
        "changed_records": 7,
        "skipped_records": 2,
        "failed_records": 0,
    }


def test_selected_workflow_repair_only_backfills_completion(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.models import Base
    import app.services.audit_runner_service as audit_service

    db_path = tmp_path / "audit-workflow-repair.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=True, autocommit=False)
    monkeypatch.setattr(audit_service, "SessionLocal", Session)

    db = Session()
    try:
        target = SunoTask(
            task_type="generate_srt",
            status="SUCCESS",
            progress=100,
            request_payload={"local_task": True, "audio_asset_id": 77},
            response_payload={},
            is_deleted=False,
        )
        db.add(target)
        db.flush()
        notice = StatusNotification(
            event_type="generate_srt_started",
            title="SRT gestartet",
            status="unread",
            task_local_id=target.id,
            is_deleted=False,
        )
        db.add(notice)
        db.commit()

        report = audit_service.run_audit_checks(db, ["workflow.tasks"], {})
        source_run = SunoTask(
            task_type="maintenance_audit",
            status="SUCCESS",
            progress=100,
            completed_at=utc_now_naive(),
            result_payload=report,
            request_payload={"local_task": True},
            response_payload={},
            is_deleted=False,
        )
        repair_run = SunoTask(
            task_type="maintenance_repair",
            status="QUEUED",
            progress=0,
            request_payload={"local_task": True, "repair_actions": ["backfill_task_completed_at"]},
            response_payload={},
            is_deleted=False,
        )
        db.add_all([source_run, repair_run])
        db.commit()
        target_id, notice_id = target.id, notice.id
        source_id, repair_id = source_run.id, repair_run.id
    finally:
        db.close()

    audit_service._run_repair_worker(repair_id, source_id)

    db = Session()
    try:
        repaired_target = db.query(SunoTask).filter(SunoTask.id == target_id).one()
        untouched_notice = db.query(StatusNotification).filter(StatusNotification.id == notice_id).one()
        repaired_run = db.query(SunoTask).filter(SunoTask.id == repair_id).one()
        assert repaired_target.completed_at is not None
        assert untouched_notice.status == "unread"
        assert untouched_notice.completed_at is None
        assert repaired_run.status == "SUCCESS"
        assert repaired_run.result_payload["selected_repair_actions"] == ["backfill_task_completed_at"]
        assert "backfill_task_completed_at" in repaired_run.result_payload["actions"]["workflow.tasks"]
        assert "complete_terminal_task_notification" not in repaired_run.result_payload["actions"]["workflow.tasks"]
    finally:
        db.close()
        engine.dispose()

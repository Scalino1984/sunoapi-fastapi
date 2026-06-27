from app.models import AudioAsset, AudioProject, Playlist, PlaylistItem, StatusNotification, SunoTask
from app.services.database_maintenance_service import inspect_database_maintenance, run_database_maintenance


def test_database_maintenance_reports_and_repairs_orphan_references(isolated_db_session):
    db = isolated_db_session
    stale_task = SunoTask(task_type="bulk_generate_srt", status="RUNNING", request_payload={"local_task": True})
    project = AudioProject(title="Project", final_audio_asset_id=999)
    playlist = Playlist(name="Playlist")
    item = PlaylistItem(playlist_id=1, audio_asset_id=999, position=1)
    notification = StatusNotification(event_type="task_status", title="n", status="unread", task_local_id=999)
    db.add_all([stale_task, project, playlist, item, notification])
    db.commit()

    before = inspect_database_maintenance(db)
    assert before["actions"]
    assert any(action["count"] >= 1 for action in before["actions"])

    result = run_database_maintenance(db, dry_run=False, backup=False)
    db.refresh(project)
    db.refresh(item)
    db.refresh(notification)

    assert result.dry_run is False
    assert project.final_audio_asset_id is None
    assert item.audio_asset_id == 999
    assert notification.target_tab is None
    assert any(action.count >= 1 for action in result.actions)


def test_database_maintenance_counts_active_core_tables(isolated_db_session):
    db = isolated_db_session
    db.add(AudioAsset(source_url="https://cdn.example.test/song.mp3", status="remote"))
    db.add(SunoTask(task_type="generate_music", status="SUCCESS"))
    db.commit()

    status = inspect_database_maintenance(db)

    assert status["counts"]["audio_assets"] == 1
    assert status["counts"]["suno_tasks"] == 1
    assert status["integrity"] in {"ok", "unknown", "warning", "error"}

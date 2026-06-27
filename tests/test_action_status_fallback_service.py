from app.models import StatusNotification
from app.services.action_status_fallback_service import (
    create_action_status_fallback,
    has_action_status_since,
    should_track_api_action,
    snapshot_action_status_marker,
)
from app.services.system_status_notification_service import create_system_status_notification


def test_should_track_persistent_mutating_api_actions():
    assert should_track_api_action("POST", "/api/library/playlists")
    assert should_track_api_action("PATCH", "/api/audio-assets/12/favorite")
    assert should_track_api_action("DELETE", "/api/library/content/audio/12")

    assert not should_track_api_action("GET", "/api/library/playlists")
    assert not should_track_api_action("POST", "/api/notifications/bulk-done")
    assert not should_track_api_action("POST", "/api/music/tasks/refresh-pending")
    assert not should_track_api_action("POST", "/api/music/tasks/123/refresh")


def test_fallback_creates_linkable_library_status_notification(isolated_db_session):
    db = isolated_db_session

    notification = create_action_status_fallback(
        db,
        method="PATCH",
        path="/api/audio-assets/42/favorite",
        status_code=200,
        response_payload={"id": 42, "audio_asset_id": 42},
        path_params={"asset_id": 42},
    )

    assert notification is not None
    row = db.query(StatusNotification).one()
    assert row.event_type == "api_action_completed"
    assert row.target_tab == "library"
    assert row.content_type == "audio"
    assert row.content_id == 42
    assert row.target_payload["audio_asset_id"] == 42
    assert row.target_payload["status"] == "SUCCESS"


def test_existing_status_notification_suppresses_fallback(isolated_db_session):
    db = isolated_db_session
    marker = snapshot_action_status_marker(db)

    create_system_status_notification(
        db,
        event_type="explicit_test_status",
        title="Expliziter Status",
        target_tab="status",
        target_payload={"status": "SUCCESS"},
    )

    assert has_action_status_since(db, marker) is True

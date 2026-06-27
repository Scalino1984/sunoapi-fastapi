from datetime import datetime, timedelta

from app.models import AudioAsset, Song, SunoTask
from app.services.audio_asset_repair_service import (
    active_usable_audio_assets,
    attach_audio_asset_identity_context,
    auto_group_audio_projects,
    deduplicate_audio_assets,
    is_audio_url,
    is_bad_image_asset,
    is_image_url,
    is_suno_share_page_url,
    reconstruct_audio_assets_from_tasks,
    repair_audio_asset_song_links,
)
from app.utils.time_utils import utc_now_naive


def test_url_classification_separates_audio_images_and_suno_share_pages():
    assert is_audio_url("https://cdn.example.test/song.mp3") is True
    assert is_audio_url("https://cdn.example.test/cover.jpg") is False
    assert is_image_url("https://cdn.example.test/cover.webp") is True
    assert is_suno_share_page_url("https://suno.com/song/abc-def") is True


def test_reconstruct_audio_assets_from_successful_task_payload(isolated_db_session):
    db = isolated_db_session
    task = SunoTask(
        task_id="task-reconstruct",
        task_type="generate_music",
        status="SUCCESS",
        request_payload={"title": "Task Title"},
        result_payload={"data": [{"id": "a1", "title": "Song A", "audioUrl": "https://cdn.example.test/a1.mp3"}]},
    )
    db.add(task)
    db.commit()

    assert reconstruct_audio_assets_from_tasks(db) == 1
    asset = db.query(AudioAsset).one()
    assert asset.audio_id == "a1"
    assert asset.suno_task_id == "task-reconstruct"
    assert asset.operation_label == "Generiert"
    assert asset.status == "remote"


def test_deduplicate_audio_assets_prefers_cached_asset_and_soft_deletes_loser(isolated_db_session):
    db = isolated_db_session
    older = utc_now_naive() - timedelta(minutes=5)
    loser = AudioAsset(audio_id="dup", source_url="https://cdn.example.test/dup.mp3", status="remote", title="Loser", created_at=older)
    winner = AudioAsset(
        audio_id="dup",
        source_url="https://cdn.example.test/dup.mp3",
        status="cached",
        title="Winner",
        local_path="storage/audio/dup.mp3",
        public_url="/media/audio/dup.mp3",
    )
    db.add_all([loser, winner])
    db.commit()

    assert deduplicate_audio_assets(db) == 1
    db.flush()
    db.refresh(loser)
    db.refresh(winner)
    assert loser.is_deleted is True
    assert winner.is_deleted is False
    assert winner.title == "Winner"


def test_repair_song_link_requires_unambiguous_task_scope(isolated_db_session):
    db = isolated_db_session
    task = SunoTask(task_id="task-link", task_type="generate_music", status="SUCCESS")
    song = Song(title="Linked Song", task_id="task-link", audio_url="https://cdn.example.test/linked.mp3")
    asset = AudioAsset(suno_task_id="task-link", source_url="https://cdn.example.test/linked.mp3", status="remote")
    db.add_all([task, song, asset])
    db.commit()

    assert repair_audio_asset_song_links(db) == 1
    db.flush()
    db.refresh(asset)
    assert asset.song_id == song.id


def test_auto_group_audio_projects_groups_assets_with_shared_task_context(isolated_db_session):
    db = isolated_db_session
    first = AudioAsset(title="Virus Inna Di System", display_title="Virus Inna Di System", suno_task_id="task-x", source_url="https://cdn.example.test/v1.mp3", status="remote")
    second = AudioAsset(title="Virus Inna Di System Extended", display_title="Virus Inna Di System Extended", suno_task_id="task-x", source_url="https://cdn.example.test/v2.mp3", status="remote")
    db.add_all([first, second])
    db.commit()

    assert auto_group_audio_projects(db) == 2
    db.flush()
    attach_audio_asset_identity_context(db, [first, second])

    rows = active_usable_audio_assets(db)
    assert [row.id for row in rows] == [second.id, first.id]
    assert first.project_id == second.project_id
    assert first.display_title == "Virus Inna Di System"


def test_bad_image_asset_detection_prevents_playable_classification():
    image = AudioAsset(title="Bad Cover", source_url="https://cdn.example.test/cover.jpg", status="remote", content_type="image/jpeg")
    assert is_bad_image_asset(image) is True

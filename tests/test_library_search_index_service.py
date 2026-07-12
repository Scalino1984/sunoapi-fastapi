from __future__ import annotations

import pytest

from app.models import AppSetting, AudioAsset, Song, SunoTask
from app.services.library_ai_tagging_service import generate_library_ai_tags_for_asset
from app.services.library_search_index_service import (
    active_library_tagging_tasks_by_asset,
    delete_library_search_index,
    list_library_search_index,
    update_library_search_index,
)


def _asset(*, title: str, metadata: dict | None = None, song_id: int | None = None) -> AudioAsset:
    return AudioAsset(
        title=title,
        display_title=title,
        song_id=song_id,
        source_url=f"https://cdn.example.test/{title}.mp3",
        status="remote",
        metadata_json=metadata or {},
    )


@pytest.mark.asyncio
async def test_ai_tagging_uses_song_metadata_style_without_nonexistent_song_attributes(monkeypatch, isolated_db_session):
    db = isolated_db_session
    db.add(AppSetting(
        key="ai_chat_settings",
        value={
            "library_ai_tagging_enabled": True,
            "library_ai_tagging_max_tags_per_asset": 5,
            "default_provider": "openrouter",
            "default_model": "test-model",
        },
    ))
    song = Song(
        title="Metadaten Song",
        prompt="Dunkler deutscher Rap",
        lyrics="Ich gehe meinen Weg",
        model="suno-v4",
        metadata_json={"request_payload": {"style": "gritty german boom bap", "tags": "boom bap"}},
    )
    db.add(song)
    db.flush()
    asset = _asset(title="Metadaten Song V1", song_id=song.id, metadata={"keep": {"value": 1}})
    db.add(asset)
    db.commit()

    monkeypatch.setattr(
        "app.services.library_ai_tagging_service.load_library_ai_tagging_settings",
        lambda _db: {"enabled": True, "profile_id": None, "max_tags": 5, "provider": "openrouter", "model": "test-model"},
    )
    monkeypatch.setattr(
        "app.services.library_ai_tagging_service.AiChatService.validate_provider_model",
        lambda self, provider, model: (provider, model, model),
    )

    async def fake_call_provider(self, provider, model, instruction, history, system_instruction, options):
        assert "gritty german boom bap" in instruction
        return '{"tags":["Boom Bap","Deutsch"],"moods":["Dark"],"genres":["Hip Hop"],"language":"de","confidence":0.9,"reason":"Passend"}', {"ok": True}

    monkeypatch.setattr("app.services.library_ai_tagging_service.AiChatService._call_provider", fake_call_provider)

    result = await generate_library_ai_tags_for_asset(db, asset)

    db.refresh(asset)
    assert result["tags"] == ["boom bap", "german"]
    assert result["genres"] == ["hip-hop"]
    assert asset.metadata_json["keep"] == {"value": 1}
    assert asset.metadata_json["ai_tags"]["language"] == "de"


def test_manual_search_index_update_and_delete_preserve_other_metadata(isolated_db_session):
    db = isolated_db_session
    asset = _asset(
        title="Indexpflege",
        metadata={
            "request_payload": {"prompt": "bestehen bleiben"},
            "waveform": {"points": [1, 2, 3]},
            "ai_tags": {"tags": ["old"], "provider": "openrouter", "confidence": 0.8},
        },
    )
    db.add(asset)
    db.commit()

    updated = update_library_search_index(
        db,
        asset,
        tags=["Rap", "rap", "Deutsch"],
        moods=["Dunkel"],
        genres=["Hip Hop"],
        language="DE",
        reason="Manuell geprüft",
    )

    db.refresh(asset)
    assert updated["tags"] == ["rap", "german"]
    assert updated["genres"] == ["hip-hop"]
    assert updated["source"] == "manual_library_search_index"
    assert asset.metadata_json["request_payload"] == {"prompt": "bestehen bleiben"}
    assert asset.metadata_json["waveform"] == {"points": [1, 2, 3]}

    removed = delete_library_search_index(db, asset)

    db.refresh(asset)
    assert removed is True
    assert "ai_tags" not in asset.metadata_json
    assert asset.metadata_json["request_payload"] == {"prompt": "bestehen bleiben"}
    assert asset.metadata_json["waveform"] == {"points": [1, 2, 3]}


def test_search_index_listing_reports_present_running_failed_and_missing(isolated_db_session):
    db = isolated_db_session
    present = _asset(title="Vorhanden", metadata={"ai_tags": {"tags": ["boom bap"], "language": "de"}})
    running = _asset(title="Laufend")
    failed = _asset(title="Fehler")
    missing = _asset(title="Fehlt")
    db.add_all([present, running, failed, missing])
    db.flush()
    db.add(SunoTask(
        task_type="library_ai_tagging",
        status="RUNNING",
        request_payload={"audio_asset_ids": [running.id], "local_task": True},
    ))
    db.add(SunoTask(
        task_type="library_ai_tagging",
        status="FAILED",
        request_payload={"audio_asset_ids": [failed.id], "local_task": True},
        error_message="Providerfehler",
    ))
    db.commit()

    result = list_library_search_index(db, page=1, page_size=50)
    states = {item["title"]: item["tag_status"] for item in result["items"]}

    assert states == {
        "Vorhanden": "present",
        "Laufend": "running",
        "Fehler": "failed",
        "Fehlt": "missing",
    }
    assert result["summary"] == {"all": 4, "present": 1, "missing": 1, "running": 1, "failed": 1}
    assert list_library_search_index(db, search="boom bap")["total"] == 1
    assert list_library_search_index(db, status="running")["total"] == 1


def test_active_task_map_prevents_duplicate_asset_processing(isolated_db_session):
    db = isolated_db_session
    asset = _asset(title="Doppelschutz")
    db.add(asset)
    db.flush()
    older = SunoTask(
        task_type="bulk_library_ai_tagging",
        status="RUNNING",
        request_payload={"audio_asset_ids": [asset.id], "local_task": True},
    )
    db.add(older)
    db.commit()

    active = active_library_tagging_tasks_by_asset(db)

    assert active[asset.id].id == older.id


def test_single_tag_generation_reuses_existing_active_task(monkeypatch, isolated_db_session):
    from app.routers.audio_assets import LibraryAiTaggingRequest, generate_library_ai_tags

    db = isolated_db_session
    db.add(AppSetting(key="ai_chat_settings", value={"library_ai_tagging_enabled": True}))
    asset = _asset(title="Einzel Doppelschutz")
    db.add(asset)
    db.flush()
    task = SunoTask(
        task_type="library_ai_tagging",
        status="RUNNING",
        request_payload={"audio_asset_ids": [asset.id], "local_task": True},
    )
    db.add(task)
    db.commit()
    monkeypatch.setattr("app.routers.audio_assets.run_detached_process", lambda *args, **kwargs: None)

    result = generate_library_ai_tags(asset.id, LibraryAiTaggingRequest(force=True), db)

    assert result["queued"] is False
    assert result["task_local_id"] == task.id
    assert db.query(SunoTask).filter(SunoTask.task_type == "library_ai_tagging").count() == 1


def test_bulk_tag_generation_skips_assets_with_active_tasks(monkeypatch, isolated_db_session):
    from app.routers.audio_assets import BulkLibraryAiTaggingRequest, bulk_generate_library_ai_tags

    db = isolated_db_session
    db.add(AppSetting(key="ai_chat_settings", value={"library_ai_tagging_enabled": True}))
    active_asset = _asset(title="Schon aktiv")
    new_asset = _asset(title="Neu starten")
    db.add_all([active_asset, new_asset])
    db.flush()
    active_task = SunoTask(
        task_type="library_ai_tagging",
        status="RUNNING",
        request_payload={"audio_asset_ids": [active_asset.id], "local_task": True},
    )
    db.add(active_task)
    db.commit()
    calls = []
    monkeypatch.setattr("app.routers.audio_assets.run_detached_process", lambda *args, **kwargs: calls.append((args, kwargs)))

    result = bulk_generate_library_ai_tags(
        BulkLibraryAiTaggingRequest(ids=[active_asset.id, new_asset.id], force=False),
        db,
    )

    assert result["queued"] is True
    assert result["count"] == 1
    assert result["already_running_audio_asset_ids"] == [active_asset.id]
    created = db.query(SunoTask).filter(SunoTask.task_type == "bulk_library_ai_tagging", SunoTask.id != active_task.id).one()
    assert created.request_payload["audio_asset_ids"] == [new_asset.id]
    assert len(calls) == 1

from types import SimpleNamespace

from app.models import SunoTask
from app.services.audio_cache_service import AudioCacheService


def _service_with_audio_cache_gate() -> AudioCacheService:
    service = AudioCacheService(db=None)
    service.settings = SimpleNamespace(
        suno_audio_cache_mode="on_success",
        local_content_storage_enabled=True,
        suno_auto_download_only_music=True,
    )
    return service


def test_should_cache_audio_producing_followup_tasks_when_only_music_is_enabled():
    service = _service_with_audio_cache_gate()

    assert service.should_cache_task(SunoTask(task_type="extend_music", status="SUCCESS")) is True
    assert service.should_cache_task(SunoTask(task_type="convert_to_wav", status="SUCCESS")) is True
    assert service.should_cache_task(SunoTask(task_type="separate", status="SUCCESS")) is True


def test_should_not_cache_non_audio_followup_tasks_when_only_music_is_enabled():
    service = _service_with_audio_cache_gate()

    assert service.should_cache_task(SunoTask(task_type="generate_midi", status="SUCCESS")) is False
    assert service.should_cache_task(SunoTask(task_type="create_video", status="SUCCESS")) is False

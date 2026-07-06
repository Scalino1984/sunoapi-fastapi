from app.routers.webhooks import _webhook_status, _webhook_task_id
from app.schemas import WebhookPayload
from app.services.audio_cache_service import collect_audio_candidates


def test_collect_audio_candidates_prefers_official_audio_url_over_source_and_stream_urls():
    payload = {
        "data": {
            "callbackType": "complete",
            "task_id": "task-1",
            "data": [
                {
                    "id": "audio-1",
                    "audio_url": "https://cdn.example/final.mp3",
                    "source_audio_url": "https://cdn.example/source.mp3",
                    "stream_audio_url": "https://cdn.example/stream",
                    "source_stream_audio_url": "https://cdn.example/source-stream",
                    "duration": 243.62,
                    "title": "Zeit zu gehn",
                }
            ],
        }
    }

    candidates = collect_audio_candidates(payload)

    assert len(candidates) == 1
    assert candidates[0].source_url == "https://cdn.example/final.mp3"
    assert candidates[0].duration_seconds == 243


def test_webhook_official_nested_task_id_and_complete_status_are_mapped():
    payload = WebhookPayload.model_validate(
        {
            "code": 200,
            "msg": "All generated successfully.",
            "data": {"callbackType": "complete", "task_id": "task-1", "data": []},
        }
    )
    body = payload.model_dump(exclude_none=True)

    assert _webhook_task_id(payload, body) == "task-1"
    assert _webhook_status(payload, body) == "SUCCESS"

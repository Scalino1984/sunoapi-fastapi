from __future__ import annotations

from app.services.ai_chat_service import AiJsonResult
from app.services.global_assistant_service import GlobalAssistantService


async def test_style_generation_runtime_flag_exists_and_does_not_break(monkeypatch, isolated_db_session):
    """Regression: /api/assistant/style-suggestions darf nicht wegen fehlender Settings-Attribute abbrechen."""

    service = GlobalAssistantService()

    def fake_runtime(db, profile_id):
        return (
            "openai",
            "gpt-test",
            "Systemprompt fuer Test",
            [],
            [],
            {"profile_id": None, "temperature": 0.2, "max_output_tokens": 1000},
        )

    async def fake_json_task(self, *, provider, model, system_prompt, instruction_payload, profile_options=None):
        return AiJsonResult(
            data={
                "suggestions": [
                    {
                        "title": "Grimy Test Style",
                        "style": "Grimy NYC boom bap, 96 BPM, dusty drums, punchy bass, male rap vocals",
                        "reason": "Passt zum rauen Songtext.",
                        "bpm": "96",
                        "negative_tags": "polished pop, EDM drop",
                    }
                ]
            },
            raw_text="{}",
            raw_response={},
        )

    monkeypatch.setattr(service, "_get_ai_runtime", fake_runtime)
    monkeypatch.setattr("app.services.global_assistant_service.AiChatService.run_json_task", fake_json_task)

    result = await service.generate_style_suggestions(
        isolated_db_session,
        lyrics="[Verse 1]\nIch laufe durch die Nacht und suche einen harten Beat.",
        amount=1,
        features={"lyric_vocal_tags": True},
        variant_strategy="balanced",
    )

    assert result["ok"] is True
    assert result["amount"] == 1
    assert result["runtime_info"]["deferred_lyric_tagging"] is True
    assert result["suggestions"][0]["style"]

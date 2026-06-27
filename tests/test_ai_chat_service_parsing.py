import pytest

from app.services.ai_chat_service import AiChatService


def test_parse_json_response_accepts_fenced_and_plain_json():
    service = AiChatService()

    parsed = service._parse_json_response('```json\n{"assistant_message":"ok","canvas_text":null}\n```')
    assert parsed["assistant_message"] == "ok"

    plain = service._parse_json_response('{"assistant_message":"plain","canvas_text":"[Verse]"}')
    assert plain["canvas_text"] == "[Verse]"


def test_normalize_canvas_result_strips_leading_meta_content_for_lyrics_mode():
    service = AiChatService()

    canvas, notes = service._normalize_canvas_result("Analyse:\n- Reime prüfen\n[Verse]\nText", work_mode="lyrics")

    assert canvas == "[Verse]\nText"
    assert "Analyse" in notes


def test_validate_provider_model_rejects_unknown_provider_before_any_http_call(monkeypatch):
    service = AiChatService()
    monkeypatch.setattr(service, "settings", type("S", (), {"ai_allowed_models": {"openai": ["GPT-5.4-mini"]}})())

    with pytest.raises(Exception) as exc:
        service.validate_provider_model("unknown", "x")
    assert "Unbekannter KI-Provider" in str(exc.value)

from app.services.assistant_action_registry import (
    clone_action,
    default_actions_for_page,
    detect_action_by_keywords,
    normalize_actions,
)


def test_default_actions_are_known_and_deduplicated_for_library():
    actions = default_actions_for_page("library")
    ids = [action["id"] for action in actions]

    assert ids[:2] == ["play_latest_audio", "navigate_lyrics"]
    assert len(ids) == len(set(ids))
    assert all("label" in action and "requires_confirmation" in action for action in actions)


def test_keyword_detection_redirects_canvas_actions_from_non_canvas_pages():
    assert detect_action_by_keywords("Mach den Text härter und mit mehr Punch", "status") == "navigate_lyrics"
    assert detect_action_by_keywords("Mach den Text härter und mit mehr Punch", "lyrics") == "lyrics_make_harder"
    assert detect_action_by_keywords("erstelle neue Style Vorschläge", "music") == "music_generate_styles"


def test_normalize_actions_keeps_first_action_and_clones_unknown_actions():
    result = normalize_actions([
        {"id": "lyrics_suno_ready", "label": "Suno-ready"},
        {"id": "lyrics_suno_ready", "label": "Duplikat"},
        {"id": "custom_frontend_action", "type": "frontend", "requires_confirmation": False},
        {"id": ""},
        "invalid",
    ])

    assert [action["id"] for action in result] == ["lyrics_suno_ready", "custom_frontend_action"]
    assert result[0]["label"] == "Suno-ready"
    assert result[0]["type"] == "ai_canvas"
    assert result[1] == clone_action("custom_frontend_action", action_type="frontend", requires_confirmation=False)

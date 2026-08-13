from app.services.global_assistant_service import (
    GlobalAssistantService,
    SUNO_MIXING_NEGATIVE_TAGS,
    SUNO_MIXING_STYLE_TAGS,
    SUNO_STYLE_PROMPT_MAX_LENGTH,
)


def test_master_style_appends_the_complete_mixing_suffix_and_negative_tags():
    service = GlobalAssistantService()

    result = service._normalize_style_item({
        "title": "Test",
        "style": "dark cinematic boom bap, 96 BPM, dusty drums, sub bass, male rap vocals, nocturnal atmosphere",
        "negative_tags": "EDM drop, polished pop",
    })

    assert result is not None
    style = result["style"]
    negative_tags = result["negative_tags"]
    assert style.index("dark cinematic boom bap") < style.index(SUNO_MIXING_STYLE_TAGS[0])
    assert len(style) <= SUNO_STYLE_PROMPT_MAX_LENGTH
    assert all(tag in style for tag in SUNO_MIXING_STYLE_TAGS)
    assert all(tag not in style for tag in SUNO_MIXING_NEGATIVE_TAGS)
    assert "EDM drop" in negative_tags
    assert "polished pop" in negative_tags
    assert all(tag in negative_tags for tag in SUNO_MIXING_NEGATIVE_TAGS)


def test_master_style_reserves_space_for_mixing_suffix_on_long_ai_answers():
    service = GlobalAssistantService()
    long_style = "genre-led production detail, " * 120

    result = service._normalize_style_item({"title": "Test", "style": long_style, "bpm": "100"})

    assert result is not None
    assert len(result["style"]) <= SUNO_STYLE_PROMPT_MAX_LENGTH
    assert result["style"].endswith(", ".join(SUNO_MIXING_STYLE_TAGS))


def test_mixing_negative_suffix_survives_an_overlong_existing_negative_list():
    service = GlobalAssistantService()
    long_negative_list = ", ".join(f"exclude-{index:03d}" for index in range(100))

    result = service._normalize_style_item({"title": "Test", "style": "dark pop, 100 BPM", "negative_tags": long_negative_list})

    assert result is not None
    assert len(result["negative_tags"]) <= 500
    assert result["negative_tags"].endswith(", ".join(SUNO_MIXING_NEGATIVE_TAGS))


def test_mixing_tags_are_not_injected_into_songtext_vocal_section_tags():
    service = GlobalAssistantService()
    result = service._normalize_style_item({
        "title": "Test",
        "style": "dark pop, 100 BPM",
        "lyric_vocal_tags": [{"section": "Verse", "tag": "[Verse: intimate male vocals, precise flow]"}],
    })

    assert result is not None
    assert result["lyric_vocal_tags"] == [{
        "section": "Verse",
        "tag": "[Verse: intimate male vocals, precise flow]",
    }]

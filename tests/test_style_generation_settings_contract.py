from app.config import Settings


def test_style_generation_settings_are_present():
    settings = Settings()
    assert settings.ai_style_lyrics_max_chars == 5000
    assert settings.ai_style_music_style_max_chars == 1000
    assert settings.ai_style_generation_batch_mode in {"auto", "batch", "chunked", "single"}
    assert settings.ai_style_generation_default_batch_size >= 1
    assert settings.ai_style_generation_low_token_batch_size >= 1
    assert isinstance(settings.ai_style_generation_low_token_models, str)
    assert isinstance(settings.ai_style_generation_deferred_lyric_tagging_enabled, bool)

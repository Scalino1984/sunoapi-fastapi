from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.config import get_settings
from app.models import AppSetting
from app.routers.admin import AI_SETTINGS_KEY, get_ai_admin_settings, update_ai_settings
from app.schemas import AiAdminSettingsUpdate


def _valid_provider_and_model() -> tuple[str, str]:
    settings = get_settings()
    allowed = settings.ai_allowed_models
    provider = settings.ai_default_provider if settings.ai_default_provider in allowed else next(iter(allowed))
    models = allowed.get(provider) or []
    model = settings.ai_default_model if settings.ai_default_model in models else models[0]
    return provider, model


def _payload(**overrides) -> AiAdminSettingsUpdate:
    provider, model = _valid_provider_and_model()
    data = {
        "default_provider": provider,
        "default_model": model,
        "srt_alignment_engine": "forced_alignment",
        "srt_quality_gate_enabled": True,
        "srt_quality_gate_min_score": 0.82,
        "stem_separation_backend": "local_demucs",
    }
    data.update(overrides)
    return AiAdminSettingsUpdate(**data)


def test_quality_gate_survives_save_and_reload(isolated_db_session):
    result = update_ai_settings(
        _payload(),
        db=isolated_db_session,
        current_user=SimpleNamespace(id=1),
    )

    assert result["srt_alignment_engine"] == "forced_alignment"
    assert result["srt_quality_gate_enabled"] is True
    assert result["srt_quality_gate_min_score"] == pytest.approx(0.82)

    row = isolated_db_session.query(AppSetting).filter(AppSetting.key == AI_SETTINGS_KEY).one()
    assert row.value["srt_alignment_engine"] == "forced_alignment"
    assert row.value["srt_quality_gate_enabled"] is True
    assert row.value["srt_quality_gate_min_score"] == pytest.approx(0.82)

    reloaded = get_ai_admin_settings(isolated_db_session)
    assert reloaded["srt_alignment_engine"] == "forced_alignment"
    assert reloaded["srt_quality_gate_enabled"] is True
    assert reloaded["srt_quality_gate_min_score"] == pytest.approx(0.82)


def test_quality_gate_defaults_are_returned_for_existing_legacy_row(isolated_db_session):
    provider, model = _valid_provider_and_model()
    isolated_db_session.add(
        AppSetting(
            key=AI_SETTINGS_KEY,
            value={
                "default_provider": provider,
                "default_model": model,
                "stem_separation_backend": "local_demucs",
            },
        )
    )
    isolated_db_session.commit()

    result = get_ai_admin_settings(isolated_db_session)

    assert result["srt_alignment_engine"] == "heuristic"
    assert result["srt_quality_gate_enabled"] is False
    assert result["srt_quality_gate_min_score"] == pytest.approx(0.7)


def test_invalid_alignment_engine_is_rejected(isolated_db_session):
    with pytest.raises(HTTPException) as exc_info:
        update_ai_settings(
            _payload(srt_alignment_engine="unknown"),
            db=isolated_db_session,
            current_user=SimpleNamespace(id=1),
        )

    assert exc_info.value.status_code == 400
    assert "Alignment-Engine" in str(exc_info.value.detail)

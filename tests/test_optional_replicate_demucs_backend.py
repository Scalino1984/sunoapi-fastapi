from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from app.models import AppSetting, AudioAsset
from app.services.stem_separation_service import (
    LOCAL_DEMUCS_BACKEND,
    REPLICATE_DEMUCS_BACKEND,
    ReplicateDemucsError,
    StemSeparationSettings,
    load_stem_separation_settings,
    parse_stem_backend,
    run_replicate_demucs,
)


def test_stem_backend_parser_is_backward_compatible_and_strict():
    assert parse_stem_backend(None) == LOCAL_DEMUCS_BACKEND
    assert parse_stem_backend("demucs") == LOCAL_DEMUCS_BACKEND
    assert parse_stem_backend("replicate") == REPLICATE_DEMUCS_BACKEND
    assert parse_stem_backend("replicate-demucs") == REPLICATE_DEMUCS_BACKEND
    with pytest.raises(ValueError):
        parse_stem_backend("unknown-cloud")


def test_admin_setting_selects_optional_replicate_backend(monkeypatch, isolated_db_session):
    import app.services.stem_separation_service as service

    isolated_db_session.add(AppSetting(key="ai_chat_settings", value={"stem_separation_backend": "replicate_demucs"}))
    isolated_db_session.commit()

    monkeypatch.setattr(service.importlib.util, "find_spec", lambda name: object() if name in {"replicate", "demucs"} else None)
    monkeypatch.setattr(
        service,
        "get_settings",
        lambda: types.SimpleNamespace(
            stem_separation_backend=LOCAL_DEMUCS_BACKEND,
            replicate_api_token="r8_test",
            replicate_demucs_model="cjwbw/demucs:test-version",
            replicate_demucs_model_name="htdemucs",
            replicate_demucs_max_input_mb=100,
        ),
    )
    settings = load_stem_separation_settings(isolated_db_session)

    assert settings.backend == REPLICATE_DEMUCS_BACKEND
    assert settings.local_demucs_available is True
    assert settings.replicate_available is True
    assert settings.replicate_token_configured is True
    assert settings.replicate_model.startswith("cjwbw/demucs:")


def test_replicate_demucs_uses_async_prediction_polling_and_saves_outputs(monkeypatch, tmp_path: Path):
    import app.services.stem_separation_service as service

    audio_path = tmp_path / "song.mp3"
    audio_path.write_bytes(b"ID3" + b"audio" * 64)

    class FakeFileOutput:
        def __init__(self, payload: bytes, url: str):
            self.payload = payload
            self.url = url

        def read(self) -> bytes:
            return self.payload

    class FakePrediction:
        def __init__(self, status: str, output=None):
            self.id = "prediction-123"
            self.status = status
            self.output = output
            self.error = None
            self.logs = ""
            self.urls = {
                "web": "https://replicate.com/p/prediction-123",
                "get": "https://api.replicate.com/v1/predictions/prediction-123",
            }

    calls: list[dict] = []
    progress: list[dict] = []

    class FakePredictions:
        def __init__(self):
            self.get_calls = 0

        def create(self, *, version: str, input: dict, wait: bool):
            calls.append({"version": version, "input": dict(input), "wait": wait})
            assert input["audio"].read(3) == b"ID3"
            assert wait is False
            return FakePrediction("starting")

        def get(self, prediction_id: str):
            assert prediction_id == "prediction-123"
            self.get_calls += 1
            if self.get_calls == 1:
                return FakePrediction("processing")
            return FakePrediction(
                "succeeded",
                {
                    "vocals": FakeFileOutput(b"RIFF-vocals", "https://replicate.delivery/vocals.wav"),
                    "other": FakeFileOutput(b"RIFF-instrumental", "https://replicate.delivery/instrumental.wav"),
                },
            )

        def cancel(self, prediction_id: str):
            raise AssertionError("Prediction darf bei Erfolg nicht abgebrochen werden")

    class FakeClient:
        def __init__(self, api_token: str, timeout):
            assert api_token == "r8_test"
            assert timeout.read == 300.0
            self.predictions = FakePredictions()
            self.models = types.SimpleNamespace(predictions=self.predictions)

    fake_module = types.ModuleType("replicate")
    fake_module.Client = FakeClient
    monkeypatch.setitem(sys.modules, "replicate", fake_module)
    monkeypatch.setattr(service.time, "sleep", lambda _seconds: None)

    result = run_replicate_demucs(
        audio_path,
        tmp_path / "output",
        token="r8_test",
        model_id="cjwbw/demucs:test-version",
        model_name="htdemucs",
        max_input_mb=100,
        progress_callback=progress.append,
    )

    assert Path(result["vocals_path"]).read_bytes() == b"RIFF-vocals"
    assert Path(result["instrumental_path"]).read_bytes() == b"RIFF-instrumental"
    assert result["source_urls"]["vocals"].startswith("https://replicate.delivery/")
    assert result["prediction_id"] == "prediction-123"
    assert result["prediction_status"] == "succeeded"
    assert calls[0]["version"] == "test-version"
    assert calls[0]["input"]["stem"] == "vocals"
    assert calls[0]["input"]["output_format"] == "wav"
    assert calls[0]["wait"] is False
    assert {entry["status"] for entry in progress} >= {"starting", "processing", "succeeded"}


def test_replicate_demucs_retries_transient_poll_errors(monkeypatch, tmp_path: Path):
    import app.services.stem_separation_service as service

    audio_path = tmp_path / "song.mp3"
    audio_path.write_bytes(b"ID3-audio")

    class FakePrediction:
        id = "prediction-retry"
        status = "starting"
        output = None
        error = None
        logs = ""
        urls = {"web": "https://replicate.com/p/prediction-retry"}

    class FakePredictions:
        def __init__(self):
            self.get_calls = 0

        def create(self, **_kwargs):
            return FakePrediction()

        def get(self, _prediction_id: str):
            self.get_calls += 1
            if self.get_calls == 1:
                raise TimeoutError("temporary read timeout")
            prediction = FakePrediction()
            prediction.status = "succeeded"
            prediction.output = {
                "vocals": "https://replicate.delivery/vocals.wav",
                "other": "https://replicate.delivery/other.wav",
            }
            return prediction

        def cancel(self, _prediction_id: str):
            return None

    predictions = FakePredictions()

    class FakeClient:
        def __init__(self, **_kwargs):
            self.predictions = predictions
            self.models = types.SimpleNamespace(predictions=predictions)

    fake_module = types.ModuleType("replicate")
    fake_module.Client = FakeClient
    monkeypatch.setitem(sys.modules, "replicate", fake_module)
    monkeypatch.setattr(service.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(service, "_save_output_file", lambda item, target, **_kwargs: str(item))

    events: list[dict] = []
    result = run_replicate_demucs(
        audio_path,
        tmp_path / "output",
        token="r8_test",
        model_id="cjwbw/demucs:test-version",
        progress_callback=events.append,
    )

    assert result["prediction_id"] == "prediction-retry"
    assert predictions.get_calls == 2
    assert any(event.get("phase") == "prediction_poll_retry" for event in events)


def test_replicate_demucs_cancels_prediction_after_total_timeout(monkeypatch, tmp_path: Path):
    import app.services.stem_separation_service as service

    audio_path = tmp_path / "song.mp3"
    audio_path.write_bytes(b"ID3-audio")

    class FakePrediction:
        id = "prediction-timeout"
        status = "processing"
        output = None
        error = None
        logs = ""
        urls = {"web": "https://replicate.com/p/prediction-timeout"}

    cancelled: list[str] = []

    class FakePredictions:
        def create(self, **_kwargs):
            return FakePrediction()

        def get(self, _prediction_id: str):
            return FakePrediction()

        def cancel(self, prediction_id: str):
            cancelled.append(prediction_id)
            return FakePrediction()

    predictions = FakePredictions()

    class FakeClient:
        def __init__(self, **_kwargs):
            self.predictions = predictions
            self.models = types.SimpleNamespace(predictions=predictions)

    clock = iter([0.0, 0.0, 0.0, 61.0, 61.0])
    fake_module = types.ModuleType("replicate")
    fake_module.Client = FakeClient
    monkeypatch.setitem(sys.modules, "replicate", fake_module)
    monkeypatch.setattr(service.time, "monotonic", lambda: next(clock, 61.0))
    monkeypatch.setattr(service.time, "sleep", lambda _seconds: None)

    with pytest.raises(ReplicateDemucsError, match="Gesamtzeitlimit"):
        run_replicate_demucs(
            audio_path,
            tmp_path / "output",
            token="r8_test",
            model_id="cjwbw/demucs:test-version",
            timeout_seconds=60,
        )

    assert cancelled == ["prediction-timeout"]

def test_replicate_demucs_rejects_oversized_input(tmp_path: Path):
    audio_path = tmp_path / "large.mp3"
    audio_path.write_bytes(b"x" * (2 * 1024 * 1024))

    with pytest.raises(ReplicateDemucsError, match="größer als das konfigurierte Replicate-Limit"):
        run_replicate_demucs(
            audio_path,
            tmp_path / "output",
            token="r8_test",
            model_id="cjwbw/demucs:test-version",
            max_input_mb=0,
        )


def test_audio_asset_generation_uses_replicate_without_changing_local_default(
    monkeypatch,
    isolated_db_session,
    tmp_path: Path,
):
    import app.routers.audio_assets as router

    audio_path = tmp_path / "source.mp3"
    audio_path.write_bytes(b"ID3" + b"audio-data")
    asset = AudioAsset(
        source_url=str(audio_path),
        local_path=str(audio_path),
        filename=audio_path.name,
        title="Replicate Stem Test",
        status="cached",
        metadata_json={},
    )
    isolated_db_session.add(asset)
    isolated_db_session.commit()
    isolated_db_session.refresh(asset)

    runtime = StemSeparationSettings(
        backend=REPLICATE_DEMUCS_BACKEND,
        replicate_model="cjwbw/demucs:test-version",
        replicate_model_name="htdemucs",
        replicate_max_input_mb=100,
        local_demucs_available=True,
        replicate_available=True,
        replicate_token_configured=True,
    )
    monkeypatch.setattr(router, "load_stem_separation_settings", lambda db: runtime)
    monkeypatch.setattr(router, "_resolve_asset_audio_file", lambda current_asset: audio_path)
    monkeypatch.setattr(router, "_stem_storage_path", lambda: tmp_path / "stems")
    monkeypatch.setattr(
        router,
        "get_settings",
        lambda: types.SimpleNamespace(replicate_api_token="r8_test", cover_storage_path=tmp_path / "covers"),
    )

    def fake_run(audio_path_arg, output_dir, **kwargs):
        kwargs["progress_callback"]({
            "phase": "prediction_created",
            "prediction_id": "prediction-router-test",
            "prediction_url": "https://replicate.com/p/prediction-router-test",
            "status": "starting",
            "elapsed_seconds": 0.1,
            "timeout_seconds": kwargs["timeout_seconds"],
        })
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        vocals = output_dir / "vocals.wav"
        instrumental = output_dir / "instrumental.wav"
        vocals.write_bytes(b"RIFF-vocals")
        instrumental.write_bytes(b"RIFF-instrumental")
        return {
            "vocals_path": vocals,
            "instrumental_path": instrumental,
            "model": kwargs["model_id"],
            "demucs_model": kwargs["model_name"],
            "prediction_id": "prediction-router-test",
            "prediction_url": "https://replicate.com/p/prediction-router-test",
            "prediction_status": "succeeded",
            "elapsed_seconds": 83.4,
            "source_urls": {},
        }

    monkeypatch.setattr(router, "run_replicate_demucs", fake_run)

    result = router.generate_stems_for_asset(
        isolated_db_session,
        asset.id,
        backend=REPLICATE_DEMUCS_BACKEND,
    )
    isolated_db_session.refresh(asset)

    stems = asset.metadata_json["stems"]
    assert result["exists"] is True
    assert result["backend"] == "replicate_demucs"
    assert stems["stem_separation_backend"] == REPLICATE_DEMUCS_BACKEND
    assert stems["provider"] == "replicate"
    assert stems["provider_prediction_id"] == "prediction-router-test"
    assert stems["provider_status"] == "succeeded"
    assert stems["files"]["vocals"]["filename"].endswith("_vocals.wav")
    assert stems["files"]["instrumental"]["filename"].endswith("_instrumental.wav")


def test_local_demucs_remains_default_and_keeps_existing_command(
    monkeypatch,
    isolated_db_session,
    tmp_path: Path,
):
    import app.routers.audio_assets as router

    audio_path = tmp_path / "local-source.mp3"
    audio_path.write_bytes(b"ID3" + b"local-audio")
    asset = AudioAsset(
        source_url=str(audio_path),
        local_path=str(audio_path),
        filename=audio_path.name,
        title="Local Stem Test",
        status="cached",
        metadata_json={},
    )
    isolated_db_session.add(asset)
    isolated_db_session.commit()
    isolated_db_session.refresh(asset)

    runtime = StemSeparationSettings(
        backend=LOCAL_DEMUCS_BACKEND,
        replicate_model="cjwbw/demucs:test-version",
        replicate_model_name="htdemucs",
        replicate_max_input_mb=100,
        local_demucs_available=True,
        replicate_available=False,
        replicate_token_configured=False,
    )
    monkeypatch.setattr(router, "load_stem_separation_settings", lambda db: runtime)
    monkeypatch.setattr(router, "_resolve_asset_audio_file", lambda current_asset: audio_path)
    monkeypatch.setattr(router, "_stem_storage_path", lambda: tmp_path / "stems")

    commands: list[list[str]] = []

    def fake_subprocess_run(command, **kwargs):
        commands.append(list(command))
        output_root = Path(command[command.index("--out") + 1])
        stem_dir = output_root / "htdemucs" / audio_path.stem
        stem_dir.mkdir(parents=True, exist_ok=True)
        (stem_dir / "vocals.wav").write_bytes(b"RIFF-local-vocals")
        (stem_dir / "no_vocals.wav").write_bytes(b"RIFF-local-instrumental")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(router.subprocess, "run", fake_subprocess_run)

    result = router.generate_stems_for_asset(isolated_db_session, asset.id)
    isolated_db_session.refresh(asset)

    assert result["exists"] is True
    assert result["backend"] == "demucs"
    assert asset.metadata_json["stems"]["stem_separation_backend"] == LOCAL_DEMUCS_BACKEND
    assert len(commands) == 1
    command = commands[0]
    assert command[:8] == [
        sys.executable,
        "-m",
        "demucs",
        "--two-stems",
        "vocals",
        "-n",
        "htdemucs",
        "--out",
    ]
    assert command[-1] == str(audio_path)

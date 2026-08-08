from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from app.models import AppSetting, AudioAsset
from app.services.stem_generation_service import (
    DEFAULT_REPLICATE_DEMUCS_MODEL,
    LOCAL_DEMUCS_BACKEND,
    REPLICATE_DEMUCS_BACKEND,
    find_replicate_stem_files,
    load_stem_generation_settings,
    materialize_replicate_output,
    normalize_replicate_model,
    normalize_stem_backend,
)


ROOT = Path(__file__).resolve().parents[1]


class _FakeFileOutput:
    def __init__(self, name: str, data: bytes):
        self._name = name
        self._data = data

    def read(self) -> bytes:
        return self._data

    def url(self) -> str:
        return f"https://replicate.delivery/example/{self._name}"


def _wav_bytes(marker: bytes) -> bytes:
    return b"RIFF" + (36 + len(marker)).to_bytes(4, "little") + b"WAVEfmt " + marker


def test_stem_backend_normalization_is_backward_compatible():
    assert normalize_stem_backend(None) == LOCAL_DEMUCS_BACKEND
    assert normalize_stem_backend("demucs") == LOCAL_DEMUCS_BACKEND
    assert normalize_stem_backend("local") == LOCAL_DEMUCS_BACKEND
    assert normalize_stem_backend("replicate") == REPLICATE_DEMUCS_BACKEND
    assert normalize_stem_backend("replicate_demucs") == REPLICATE_DEMUCS_BACKEND
    assert normalize_stem_backend("unknown") == LOCAL_DEMUCS_BACKEND
    assert normalize_replicate_model("invalid model id") == DEFAULT_REPLICATE_DEMUCS_MODEL



def test_stem_settings_can_select_replicate_without_changing_the_default(isolated_db_session):
    db = isolated_db_session
    db.query(AppSetting).filter(AppSetting.key == "ai_chat_settings").delete(synchronize_session=False)
    db.add(AppSetting(
        key="ai_chat_settings",
        value={
            "stem_generation_backend": "replicate_demucs",
            "stem_replicate_model": DEFAULT_REPLICATE_DEMUCS_MODEL,
        },
    ))
    db.commit()
    settings = load_stem_generation_settings(db)
    assert settings["backend"] == REPLICATE_DEMUCS_BACKEND
    assert settings["replicate_model"] == DEFAULT_REPLICATE_DEMUCS_MODEL
    assert normalize_stem_backend(None) == LOCAL_DEMUCS_BACKEND

def test_replicate_outputs_are_materialized_and_assigned_by_role(tmp_path: Path):
    paths = materialize_replicate_output(
        {
            "vocals": _FakeFileOutput("vocals.wav", _wav_bytes(b"vocals")),
            "no_vocals": _FakeFileOutput("no_vocals.wav", _wav_bytes(b"instrumental")),
        },
        tmp_path,
    )
    vocals, instrumental = find_replicate_stem_files(paths)
    assert "vocals" in vocals.name.lower()
    assert "no_vocals" in instrumental.name.lower()
    assert vocals != instrumental


def test_replicate_output_requires_both_stem_roles(tmp_path: Path):
    paths = materialize_replicate_output(
        {"vocals": _FakeFileOutput("vocals.wav", _wav_bytes(b"vocals"))},
        tmp_path,
    )
    with pytest.raises(RuntimeError, match="Instrumental"):
        find_replicate_stem_files(paths)


def test_replicate_other_output_is_treated_as_no_vocals(tmp_path: Path):
    paths = materialize_replicate_output(
        {
            "vocals": _FakeFileOutput("vocals.wav", _wav_bytes(b"vocals")),
            "other": _FakeFileOutput("other.wav", _wav_bytes(b"instrumental")),
        },
        tmp_path,
    )
    vocals, instrumental = find_replicate_stem_files(paths)
    assert "vocals" in vocals.name.lower()
    assert "other" in instrumental.name.lower()


def test_generate_stems_can_use_replicate_without_local_demucs(monkeypatch, isolated_db_session, tmp_path: Path):
    from app.routers import audio_assets as audio_assets_router

    db = isolated_db_session
    source = tmp_path / "source.wav"
    source.write_bytes(_wav_bytes(b"source-audio"))
    remote_vocals = tmp_path / "remote_vocals.wav"
    remote_instrumental = tmp_path / "remote_no_vocals.wav"
    remote_vocals.write_bytes(_wav_bytes(b"remote-vocals"))
    remote_instrumental.write_bytes(_wav_bytes(b"remote-instrumental"))
    stem_root = tmp_path / "stems"

    asset = AudioAsset(
        source_url="https://example.test/source.wav",
        local_path=str(source),
        filename=source.name,
        content_type="audio/wav",
        status="cached",
        title="Replicate Test",
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)

    monkeypatch.setattr(audio_assets_router, "_resolve_asset_audio_file", lambda _asset: source)
    monkeypatch.setattr(audio_assets_router, "_stem_storage_path", lambda: stem_root)
    monkeypatch.setattr(audio_assets_router, "to_portable_path", lambda value, storage_root=None: str(value))
    monkeypatch.setattr(
        audio_assets_router,
        "get_settings",
        lambda: type("Settings", (), {"replicate_api_token": "test-token"})(),
    )
    monkeypatch.setattr(
        audio_assets_router,
        "load_stem_generation_settings",
        lambda _db: {
            "backend": REPLICATE_DEMUCS_BACKEND,
            "replicate_model": DEFAULT_REPLICATE_DEMUCS_MODEL,
            "local_configured": False,
            "replicate_configured": True,
            "selected_configured": True,
        },
    )
    calls = []

    def fake_replicate(audio_path, output_root, *, model_id, api_token):
        calls.append((audio_path, output_root, model_id, api_token))
        return remote_vocals, remote_instrumental, {"model": model_id, "output_files": [remote_vocals.name, remote_instrumental.name]}

    monkeypatch.setattr(audio_assets_router, "run_replicate_demucs", fake_replicate)

    result = audio_assets_router.generate_stems_for_asset(
        db,
        asset.id,
        backend_override=REPLICATE_DEMUCS_BACKEND,
        replicate_model_override=DEFAULT_REPLICATE_DEMUCS_MODEL,
    )

    assert calls and calls[0][0] == source
    assert result["backend"] == REPLICATE_DEMUCS_BACKEND
    assert result["files"]["vocals"]["filename"].endswith("_vocals.wav")
    assert result["files"]["instrumental"]["filename"].endswith("_instrumental.wav")
    db.refresh(asset)
    assert asset.metadata_json["stems"]["backend"] == REPLICATE_DEMUCS_BACKEND
    assert asset.metadata_json["stems"]["execution"]["model"] == DEFAULT_REPLICATE_DEMUCS_MODEL

def test_structure_normalization_handles_nested_duplicates_and_overlaps():
    module_uri = (ROOT / "frontend-react/src/utils/songStructure.js").resolve().as_uri()
    script = f"""
      import {{ normalizeStructureSegments }} from {json.dumps(module_uri)};
      const source = {{ segments: [
        {{ label: '[Intro | atmospheric]', start: 0, end: 30 }},
        {{ label: 'Verse 1 | deep rap', start: 30, end: 101 }},
        {{ label: 'Verse 1', start: 30.1, end: 100.8 }},
        {{ label: 'Chorus', start: 96, end: 125 }},
        {{ label: 'Hook', start: 100, end: 124.8 }},
        {{ label: 'Verse 2', start: 124, end: 204 }},
        {{ label: 'Final Chorus x2', start: 202.5, end: 245 }}
      ] }};
      const result = normalizeStructureSegments(source, 245);
      if (result.length !== 5) throw new Error(JSON.stringify(result));
      if (result.map((row) => row.label).join('|') !== 'Intro|Verse 1|Chorus|Verse 2|Final Chorus') throw new Error(JSON.stringify(result));
      for (let index = 1; index < result.length; index += 1) {{
        if (result[index].start < result[index - 1].end - 0.001) throw new Error('overlap:' + JSON.stringify(result));
      }}
    """
    completed = subprocess.run(
        ["node", "--input-type=module"],
        input=script,
        text=True,
        capture_output=True,
        cwd=ROOT,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout



def test_frontend_structure_marker_uses_only_primary_tag_clause():
    module_uri = (ROOT / "frontend-react/src/utils/songStructure.js").resolve().as_uri()
    script = f"""
      import {{ structureMarker }} from {json.dumps(module_uri)};
      const cases = [
        ['Deep Male Rapper | Hard Straight Rap Break | No Singing', null],
        ['Outro | Stripped Chorus Reprise | Fade-Out', 'Outro'],
        ['Intro | Build-Up | Clear Alternation', 'Intro'],
        ['Final Chorus x2 | Maximum Climax', 'Final Chorus'],
        ['Chorus x2 | Repeat Entire Hook Twice', 'Chorus'],
      ];
      for (const [input, expected] of cases) {{
        const result = structureMarker(input);
        const actual = result ? result.label : null;
        if (actual !== expected) throw new Error(input + ':' + JSON.stringify(result));
        if (/x\\s*2/i.test(input) && !/x\\s*2/i.test(result?.rawLabel || '')) throw new Error('repeat metadata lost:' + JSON.stringify(result));
      }}
    """
    completed = subprocess.run(
        ["node", "--input-type=module"],
        input=script,
        text=True,
        capture_output=True,
        cwd=ROOT,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout

def test_shared_waveform_and_stem_backend_are_wired_into_all_runtime_paths():
    waveform = (ROOT / "frontend-react/src/components/Waveform.jsx").read_text(encoding="utf-8")
    library = (ROOT / "frontend-react/src/pages/LibraryPage.jsx").read_text(encoding="utf-8")
    mini_player = (ROOT / "frontend-react/src/components/MiniPlayer.jsx").read_text(encoding="utf-8")
    admin = (ROOT / "frontend-react/src/pages/AdminPage.jsx").read_text(encoding="utf-8")
    audio_router = (ROOT / "app/routers/audio_assets.py").read_text(encoding="utf-8")
    srt_service = (ROOT / "app/services/srt_transcript_service.py").read_text(encoding="utf-8")

    assert "normalizeStructureSegments" in waveform
    assert "labelMode" in waveform
    assert "compactSegmentLabel" in waveform
    assert "<Waveform" in library
    assert "<Waveform" in mini_player
    assert "library.messages.stemsStarted" in library
    assert "result?.queued || result?.task_local_id" in library
    assert "stem_generation_backend" in admin
    assert "replicate_demucs" in admin
    assert "run_replicate_demucs" in audio_router
    assert "backend_override=selected_backend" in audio_router
    assert '"stem_backend": stems.get("backend") or "demucs"' in srt_service

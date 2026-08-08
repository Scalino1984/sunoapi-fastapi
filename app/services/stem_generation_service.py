from __future__ import annotations

"""Backend-Auswahl und Replicate-Ausführung für Demucs-Stems.

Der bestehende lokale Demucs-Pfad bleibt Standard. Replicate ist eine optionale
Ausführungsumgebung für schwache Server und liefert weiterhin dieselben zwei
lokal gespeicherten Dateien (Vocals + Instrumental) an den bestehenden
AudioAsset-/Download-Workflow.
"""

from collections.abc import Iterable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zipfile import BadZipFile, ZipFile
import importlib.util
import mimetypes
import re
import shutil

import httpx
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AppSetting


AI_SETTINGS_KEY = "ai_chat_settings"
LOCAL_DEMUCS_BACKEND = "local_demucs"
REPLICATE_DEMUCS_BACKEND = "replicate_demucs"
STEM_GENERATION_BACKENDS = {LOCAL_DEMUCS_BACKEND, REPLICATE_DEMUCS_BACKEND}
DEFAULT_REPLICATE_DEMUCS_MODEL = (
    "cjwbw/demucs:25a173108cff36ef9f80f854c162d01df9e6528be175794b81158fa03836d953"
)
REPLICATE_LOCAL_FILE_LIMIT_BYTES = 100 * 1024 * 1024


def normalize_stem_backend(value: Any) -> str:
    backend = str(value or LOCAL_DEMUCS_BACKEND).strip().lower()
    aliases = {
        "demucs": LOCAL_DEMUCS_BACKEND,
        "local": LOCAL_DEMUCS_BACKEND,
        "replicate": REPLICATE_DEMUCS_BACKEND,
    }
    backend = aliases.get(backend, backend)
    return backend if backend in STEM_GENERATION_BACKENDS else LOCAL_DEMUCS_BACKEND


def normalize_replicate_model(value: Any) -> str:
    model = str(value or DEFAULT_REPLICATE_DEMUCS_MODEL).strip()
    if not model or len(model) > 240 or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?::[A-Fa-f0-9]{16,128})?", model):
        return DEFAULT_REPLICATE_DEMUCS_MODEL
    return model


def load_stem_generation_settings(db: Session) -> dict[str, Any]:
    app_settings = get_settings()
    row = db.query(AppSetting).filter(AppSetting.key == AI_SETTINGS_KEY).first()
    value = row.value if row and isinstance(row.value, dict) else {}
    backend = normalize_stem_backend(value.get("stem_generation_backend"))
    model = normalize_replicate_model(value.get("stem_replicate_model"))
    local_configured = importlib.util.find_spec("demucs") is not None
    replicate_configured = bool(str(app_settings.replicate_api_token or "").strip())
    return {
        "backend": backend,
        "replicate_model": model,
        "local_configured": local_configured,
        "replicate_configured": replicate_configured,
        "selected_configured": local_configured if backend == LOCAL_DEMUCS_BACKEND else replicate_configured,
    }


def stem_backend_label(backend: str) -> str:
    normalized = normalize_stem_backend(backend)
    return "Demucs lokal" if normalized == LOCAL_DEMUCS_BACKEND else "Demucs über Replicate"


def _safe_filename(value: str, fallback: str) -> str:
    candidate = Path(str(value or "").split("?", 1)[0]).name
    candidate = re.sub(r"[^A-Za-z0-9._-]+", "_", candidate).strip("._")
    return candidate or fallback


def _output_url(value: Any) -> str | None:
    url_attr = getattr(value, "url", None)
    if callable(url_attr):
        try:
            url_attr = url_attr()
        except Exception:
            url_attr = None
    if isinstance(url_attr, str) and url_attr.startswith(("http://", "https://")):
        return url_attr
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        return value
    return None


def _iter_output_items(value: Any, key: str = "output") -> Iterable[tuple[str, Any]]:
    if value is None:
        return
    if isinstance(value, dict):
        for child_key, child in value.items():
            yield from _iter_output_items(child, str(child_key))
        return
    if isinstance(value, (list, tuple, set)):
        for index, child in enumerate(value):
            yield from _iter_output_items(child, f"{key}_{index + 1}")
        return
    yield key, value


def _read_output_bytes(value: Any, timeout_seconds: float = 180.0) -> tuple[bytes, str | None]:
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value), None
    read = getattr(value, "read", None)
    if callable(read):
        data = read()
        if isinstance(data, str):
            data = data.encode("utf-8")
        if isinstance(data, (bytes, bytearray, memoryview)):
            return bytes(data), _output_url(value)
    url = _output_url(value)
    if url:
        with httpx.Client(timeout=timeout_seconds, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()
            return response.content, url
    raise RuntimeError(f"Replicate-Ausgabe {type(value).__name__} enthält keine lesbaren Dateidaten.")


def _safe_extract_zip(path: Path, destination: Path) -> list[Path]:
    extracted: list[Path] = []
    try:
        with ZipFile(path) as archive:
            root = destination.resolve()
            for member in archive.infolist():
                if member.is_dir():
                    continue
                target = (root / member.filename).resolve()
                try:
                    target.relative_to(root)
                except ValueError:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
                if target.stat().st_size > 0:
                    extracted.append(target)
    except BadZipFile:
        return []
    return extracted


def materialize_replicate_output(output: Any, output_root: Path) -> list[Path]:
    output_root.mkdir(parents=True, exist_ok=True)
    materialized: list[Path] = []
    for index, (key, value) in enumerate(_iter_output_items(output), start=1):
        data, remote_url = _read_output_bytes(value)
        if not data:
            continue
        remote_name = Path(urlparse(remote_url).path).name if remote_url else ""
        guessed_extension = Path(remote_name).suffix or mimetypes.guess_extension(
            mimetypes.guess_type(remote_name)[0] or ""
        ) or ".bin"
        key_name = _safe_filename(key, f"output_{index}")
        if Path(key_name).suffix:
            filename = key_name
        elif remote_name:
            filename = f"{key_name}_{_safe_filename(remote_name, f'output_{index}{guessed_extension}') }"
        else:
            filename = f"{key_name}{guessed_extension}"
        target = output_root / filename
        target.write_bytes(data)
        materialized.append(target)
        if data[:4] == b"PK\x03\x04" or target.suffix.lower() == ".zip":
            materialized.extend(_safe_extract_zip(target, output_root / f"{target.stem}_files"))
    return materialized


def _role_score(path: Path, role: str) -> int:
    name = path.name.lower().replace("-", "_")
    if role == "vocals":
        if "no_vocals" in name or "instrumental" in name or "accompaniment" in name:
            return -100
        if re.search(r"(^|_)vocals?($|[_.])", name):
            return 100
        if "voice" in name:
            return 80
        return 0
    if "no_vocals" in name:
        return 110
    if "instrumental" in name:
        return 100
    if "accompaniment" in name:
        return 90
    if "other" in name and "vocals" not in name:
        return 20
    return 0


def find_replicate_stem_files(paths: Iterable[Path]) -> tuple[Path, Path]:
    audio_extensions = {".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg"}
    candidates = [path for path in paths if path.is_file() and path.suffix.lower() in audio_extensions and path.stat().st_size > 0]
    vocals = max(candidates, key=lambda path: _role_score(path, "vocals"), default=None)
    instrumental = max(candidates, key=lambda path: _role_score(path, "instrumental"), default=None)
    if not vocals or _role_score(vocals, "vocals") <= 0:
        raise RuntimeError("Replicate-Demucs-Ausgabe enthält keinen eindeutig erkennbaren Vocal-Stem.")
    if not instrumental or _role_score(instrumental, "instrumental") <= 0:
        raise RuntimeError("Replicate-Demucs-Ausgabe enthält keinen eindeutig erkennbaren Instrumental-/no_vocals-Stem.")
    if vocals.resolve() == instrumental.resolve():
        raise RuntimeError("Replicate-Demucs hat Vocal- und Instrumental-Stem nicht getrennt geliefert.")
    return vocals, instrumental


def run_replicate_demucs(audio_path: Path, output_root: Path, *, model_id: str, api_token: str) -> tuple[Path, Path, dict[str, Any]]:
    if not api_token.strip():
        raise RuntimeError("Replicate ist nicht konfiguriert. Setze REPLICATE_API_TOKEN in der Backend-Umgebung.")
    if audio_path.stat().st_size > REPLICATE_LOCAL_FILE_LIMIT_BYTES:
        raise RuntimeError("Die Audiodatei ist größer als 100 MB und kann nicht als lokaler Replicate-Input hochgeladen werden.")
    try:
        import replicate
    except ImportError as exc:  # pragma: no cover - durch requirements.txt abgedeckt
        raise RuntimeError("Das Python-Paket 'replicate' ist nicht installiert.") from exc

    model = normalize_replicate_model(model_id)
    with audio_path.open("rb") as audio_handle:
        client_class = getattr(replicate, "Client", None)
        if client_class is not None:
            client = client_class(api_token=api_token)
            output = client.run(
                model,
                input={
                    "audio": audio_handle,
                    "model_name": "htdemucs",
                    "stem": "vocals",
                    "output_format": "wav",
                    "clip_mode": "rescale",
                    "shifts": 1,
                },
            )
        else:  # Kompatibilität mit älteren replicate-Python-Versionen
            import os
            old_token = os.environ.get("REPLICATE_API_TOKEN")
            os.environ["REPLICATE_API_TOKEN"] = api_token
            try:
                output = replicate.run(
                    model,
                    input={
                        "audio": audio_handle,
                        "model_name": "htdemucs",
                        "stem": "vocals",
                        "output_format": "wav",
                        "clip_mode": "rescale",
                        "shifts": 1,
                    },
                )
            finally:
                if old_token is None:
                    os.environ.pop("REPLICATE_API_TOKEN", None)
                else:
                    os.environ["REPLICATE_API_TOKEN"] = old_token

    materialized = materialize_replicate_output(output, output_root)
    vocals, instrumental = find_replicate_stem_files(materialized)
    return vocals, instrumental, {
        "model": model,
        "output_files": [path.name for path in materialized if path.is_file()],
    }

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
import importlib.util
import time
import urllib.request

import httpx

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AppSetting

AI_SETTINGS_KEY = "ai_chat_settings"
LOCAL_DEMUCS_BACKEND = "local_demucs"
REPLICATE_DEMUCS_BACKEND = "replicate_demucs"
ALLOWED_STEM_BACKENDS = (LOCAL_DEMUCS_BACKEND, REPLICATE_DEMUCS_BACKEND)


class ReplicateDemucsError(RuntimeError):
    """Klarer Laufzeitfehler für die optionale Replicate-Demucs-Ausführung."""


@dataclass(frozen=True)
class StemSeparationSettings:
    backend: str
    replicate_model: str
    replicate_model_name: str
    replicate_max_input_mb: int
    local_demucs_available: bool
    replicate_available: bool
    replicate_token_configured: bool
    replicate_timeout_seconds: int = 1200
    replicate_poll_interval_seconds: float = 2.0
    replicate_http_timeout_seconds: float = 300.0


_STEM_BACKEND_ALIASES = {
    "demucs": LOCAL_DEMUCS_BACKEND,
    "local": LOCAL_DEMUCS_BACKEND,
    "local_demucs": LOCAL_DEMUCS_BACKEND,
    "replicate": REPLICATE_DEMUCS_BACKEND,
    "replicate_demucs": REPLICATE_DEMUCS_BACKEND,
}


def normalize_stem_backend(value: Any) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    return _STEM_BACKEND_ALIASES.get(normalized, LOCAL_DEMUCS_BACKEND)


def parse_stem_backend(value: Any, *, default: Any = LOCAL_DEMUCS_BACKEND) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if not normalized:
        return normalize_stem_backend(default)
    if normalized not in _STEM_BACKEND_ALIASES:
        raise ValueError(f"Unbekanntes Stem-Separation-Backend: {value}")
    return _STEM_BACKEND_ALIASES[normalized]


def load_stem_separation_settings(db: Session | None = None) -> StemSeparationSettings:
    settings = get_settings()
    configured_backend = getattr(settings, "stem_separation_backend", LOCAL_DEMUCS_BACKEND)
    if db is not None:
        row = db.query(AppSetting).filter(AppSetting.key == AI_SETTINGS_KEY).first()
        value = row.value if row and isinstance(row.value, dict) else {}
        configured_backend = value.get("stem_separation_backend") or configured_backend

    token = str(getattr(settings, "replicate_api_token", "") or "").strip()
    replicate_package_available = importlib.util.find_spec("replicate") is not None
    return StemSeparationSettings(
        backend=normalize_stem_backend(configured_backend),
        replicate_model=str(
            getattr(
                settings,
                "replicate_demucs_model",
                "cjwbw/demucs:25a173108cff36ef9f80f854c162d01df9e6528be175794b81158fa03836d953",
            )
            or ""
        ).strip(),
        replicate_model_name=str(getattr(settings, "replicate_demucs_model_name", "htdemucs") or "htdemucs").strip(),
        replicate_max_input_mb=max(1, int(getattr(settings, "replicate_demucs_max_input_mb", 100) or 100)),
        local_demucs_available=importlib.util.find_spec("demucs") is not None,
        replicate_available=bool(token and replicate_package_available),
        replicate_token_configured=bool(token),
        replicate_timeout_seconds=max(60, min(1800, int(getattr(settings, "replicate_demucs_timeout_seconds", 1200) or 1200))),
        replicate_poll_interval_seconds=max(0.5, min(30.0, float(getattr(settings, "replicate_demucs_poll_interval_seconds", 2.0) or 2.0))),
        replicate_http_timeout_seconds=max(30.0, min(900.0, float(getattr(settings, "replicate_demucs_http_timeout_seconds", 300.0) or 300.0))),
    )


def stem_backend_label(backend: str) -> str:
    return "Replicate Demucs" if normalize_stem_backend(backend) == REPLICATE_DEMUCS_BACKEND else "lokales Demucs"


def _first_output_value(output: Any, keys: tuple[str, ...]) -> Any:
    if isinstance(output, dict):
        for key in keys:
            value = output.get(key)
            if value is not None:
                return value
    return None


def _source_url(item: Any) -> str | None:
    if isinstance(item, str) and item.startswith("https://"):
        return item
    for attribute in ("url", "uri", "source_url"):
        value = getattr(item, attribute, None)
        if value and str(value).startswith("https://"):
            return str(value)
    return None


def _save_output_file(item: Any, target: Path, *, timeout_seconds: float = 300.0) -> str | None:
    if item is None:
        raise ReplicateDemucsError("Replicate hat keine verwertbare Stem-Datei geliefert.")

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(f"{target.suffix}.part")
    temporary.unlink(missing_ok=True)
    source_url = _source_url(item)

    try:
        if hasattr(item, "read"):
            data = item.read()
            if not isinstance(data, (bytes, bytearray)):
                raise ReplicateDemucsError("Replicate FileOutput enthält keine Binärdaten.")
            temporary.write_bytes(bytes(data))
        elif source_url:
            with urllib.request.urlopen(source_url, timeout=max(30.0, float(timeout_seconds))) as response, temporary.open("wb") as output_handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    output_handle.write(chunk)
        else:
            raise ReplicateDemucsError("Replicate-Ausgabe enthält weder FileOutput noch eine HTTPS-URL.")

        if not temporary.is_file() or temporary.stat().st_size <= 0:
            raise ReplicateDemucsError("Replicate hat eine leere Stem-Datei geliefert.")
        temporary.replace(target)
        return source_url
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _prediction_value(prediction: Any, key: str, default: Any = None) -> Any:
    if isinstance(prediction, dict):
        return prediction.get(key, default)
    return getattr(prediction, key, default)


def _prediction_url(prediction: Any, key: str) -> str | None:
    urls = _prediction_value(prediction, "urls", {})
    if isinstance(urls, dict):
        value = urls.get(key)
    else:
        value = getattr(urls, key, None)
    return str(value) if value else None


def _emit_progress(callback: Callable[[dict[str, Any]], None] | None, payload: dict[str, Any]) -> None:
    if callback is None:
        return
    try:
        callback(payload)
    except Exception:
        # Statusfortschreibung darf den bereits laufenden Provider-Job nicht abbrechen.
        return


def _cancel_prediction(client: Any, prediction_id: str | None) -> None:
    if not prediction_id:
        return
    try:
        client.predictions.cancel(prediction_id)
    except Exception:
        # Best-Effort: der eigentliche Timeout-/Abbruchfehler bleibt maßgeblich.
        return


def _create_async_prediction(client: Any, model_id: str, input_payload: dict[str, Any]) -> Any:
    model_ref = str(model_id or "").strip()
    if not model_ref:
        raise ReplicateDemucsError("REPLICATE_DEMUCS_MODEL ist nicht konfiguriert.")

    model_name, separator, version_id = model_ref.rpartition(":")
    if separator and version_id and "/" in model_name:
        return client.predictions.create(version=version_id, input=input_payload, wait=False)

    if "/" in model_ref:
        owner, name = model_ref.split("/", 1)
        return client.models.predictions.create(model=(owner, name), input=input_payload, wait=False)

    # Erlaubt zusätzlich eine reine Replicate-Version-ID.
    return client.predictions.create(version=model_ref, input=input_payload, wait=False)


def run_replicate_demucs(
    audio_path: Path,
    output_dir: Path,
    *,
    token: str,
    model_id: str,
    model_name: str = "htdemucs",
    max_input_mb: int = 100,
    timeout_seconds: int = 1200,
    poll_interval_seconds: float = 2.0,
    http_timeout_seconds: float = 300.0,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    cancel_requested: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    audio_path = Path(audio_path).expanduser().resolve()
    if not audio_path.is_file():
        raise ReplicateDemucsError("Die lokale Audiodatei für Replicate wurde nicht gefunden.")
    if not token.strip():
        raise ReplicateDemucsError("REPLICATE_API_TOKEN ist nicht konfiguriert.")
    if not model_id.strip():
        raise ReplicateDemucsError("REPLICATE_DEMUCS_MODEL ist nicht konfiguriert.")

    input_size = audio_path.stat().st_size
    max_bytes = max(1, int(max_input_mb)) * 1024 * 1024
    if input_size > max_bytes:
        raise ReplicateDemucsError(
            f"Die Audiodatei ist mit {input_size / 1024 / 1024:.1f} MB größer als das konfigurierte Replicate-Limit von {max_input_mb} MB."
        )

    try:
        import replicate
    except ImportError as exc:  # pragma: no cover - durch Runtime-Check abgesichert
        raise ReplicateDemucsError("Das Python-Paket 'replicate' ist nicht installiert.") from exc

    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    vocals_path = output_dir / "vocals.wav"
    instrumental_path = output_dir / "instrumental.wav"

    timeout_seconds = max(60, min(1800, int(timeout_seconds or 1200)))
    poll_interval_seconds = max(0.5, min(30.0, float(poll_interval_seconds or 2.0)))
    http_timeout_seconds = max(30.0, min(900.0, float(http_timeout_seconds or 300.0)))
    prediction: Any = None
    prediction_id: str | None = None
    prediction_web_url: str | None = None
    started_at = time.monotonic()
    deadline = started_at + timeout_seconds
    last_status = ""
    last_progress_at = 0.0
    consecutive_poll_errors = 0

    try:
        client = replicate.Client(
            api_token=token.strip(),
            timeout=httpx.Timeout(
                connect=min(30.0, http_timeout_seconds),
                read=http_timeout_seconds,
                write=http_timeout_seconds,
                pool=min(30.0, http_timeout_seconds),
            ),
        )
        with audio_path.open("rb") as audio_handle:
            prediction = _create_async_prediction(
                client,
                model_id,
                {
                    "audio": audio_handle,
                    "model": model_name.strip() or "htdemucs",
                    "stem": "vocals",
                    "output_format": "wav",
                },
            )

        prediction_id = str(_prediction_value(prediction, "id", "") or "").strip() or None
        prediction_web_url = _prediction_url(prediction, "web")
        if not prediction_id:
            raise ReplicateDemucsError("Replicate hat keine Prediction-ID zurückgegeben.")

        while True:
            status = str(_prediction_value(prediction, "status", "") or "").strip().lower()
            elapsed = max(0.0, time.monotonic() - started_at)
            now = time.monotonic()
            status_changed = status != last_status
            if status_changed or now - last_progress_at >= 10.0:
                _emit_progress(
                    progress_callback,
                    {
                        "phase": "prediction_created" if not last_status else "prediction_polling",
                        "prediction_id": prediction_id,
                        "prediction_url": prediction_web_url,
                        "status": status or "unknown",
                        "status_changed": status_changed,
                        "elapsed_seconds": round(elapsed, 1),
                        "timeout_seconds": timeout_seconds,
                    },
                )
                last_progress_at = now
                last_status = status

            if status in {"succeeded", "successful", "failed", "canceled", "cancelled", "aborted"}:
                break

            if cancel_requested is not None and cancel_requested():
                _cancel_prediction(client, prediction_id)
                raise ReplicateDemucsError("Replicate-Demucs-Aufruf wurde abgebrochen.")

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _cancel_prediction(client, prediction_id)
                raise ReplicateDemucsError(
                    f"Replicate-Demucs-Aufruf hat das Gesamtzeitlimit von {timeout_seconds} Sekunden überschritten und wurde abgebrochen."
                )

            time.sleep(min(poll_interval_seconds, remaining))
            try:
                prediction = client.predictions.get(prediction_id)
                prediction_web_url = _prediction_url(prediction, "web") or prediction_web_url
                consecutive_poll_errors = 0
            except Exception as exc:
                consecutive_poll_errors += 1
                _emit_progress(
                    progress_callback,
                    {
                        "phase": "prediction_poll_retry",
                        "prediction_id": prediction_id,
                        "prediction_url": prediction_web_url,
                        "status": last_status or "unknown",
                        "status_changed": False,
                        "elapsed_seconds": round(max(0.0, time.monotonic() - started_at), 1),
                        "timeout_seconds": timeout_seconds,
                        "poll_error_count": consecutive_poll_errors,
                        "poll_error": str(exc),
                    },
                )
                if consecutive_poll_errors >= 5:
                    raise ReplicateDemucsError(
                        f"Replicate-Prediction konnte nach {consecutive_poll_errors} Versuchen nicht mehr abgefragt werden: {exc}"
                    ) from exc
                time.sleep(min(10.0, poll_interval_seconds * consecutive_poll_errors))

        final_status = str(_prediction_value(prediction, "status", "") or "").strip().lower()
        if final_status not in {"succeeded", "successful"}:
            provider_error = str(_prediction_value(prediction, "error", "") or "").strip()
            provider_logs = str(_prediction_value(prediction, "logs", "") or "").strip()
            detail = provider_error or provider_logs[-1200:] or f"Prediction-Status: {final_status or 'unbekannt'}"
            raise ReplicateDemucsError(f"Replicate Demucs wurde nicht erfolgreich abgeschlossen: {detail}")

        output = _prediction_value(prediction, "output")
        _emit_progress(
            progress_callback,
            {
                "phase": "prediction_completed",
                "prediction_id": prediction_id,
                "prediction_url": prediction_web_url,
                "status": final_status,
                "status_changed": final_status != last_status,
                "elapsed_seconds": round(max(0.0, time.monotonic() - started_at), 1),
                "timeout_seconds": timeout_seconds,
            },
        )
    except ReplicateDemucsError:
        raise
    except Exception as exc:
        raise ReplicateDemucsError(f"Replicate-Demucs-Aufruf fehlgeschlagen: {exc}") from exc

    vocals_output = _first_output_value(output, ("vocals", "vocal"))
    instrumental_output = _first_output_value(output, ("other", "no_vocals", "instrumental", "accompaniment"))
    if vocals_output is None or instrumental_output is None:
        keys = ", ".join(sorted(str(key) for key in output.keys())) if isinstance(output, dict) else type(output).__name__
        raise ReplicateDemucsError(f"Replicate-Ausgabe enthält nicht beide benötigten Stems (Ausgabe: {keys}).")

    vocals_url = _save_output_file(vocals_output, vocals_path, timeout_seconds=http_timeout_seconds)
    instrumental_url = _save_output_file(instrumental_output, instrumental_path, timeout_seconds=http_timeout_seconds)
    return {
        "vocals_path": vocals_path,
        "instrumental_path": instrumental_path,
        "model": model_id.strip(),
        "demucs_model": model_name.strip() or "htdemucs",
        "prediction_id": prediction_id,
        "prediction_url": prediction_web_url,
        "prediction_status": str(_prediction_value(prediction, "status", "succeeded") or "succeeded"),
        "elapsed_seconds": round(max(0.0, time.monotonic() - started_at), 1),
        "source_urls": {
            "vocals": vocals_url,
            "instrumental": instrumental_url,
        },
    }

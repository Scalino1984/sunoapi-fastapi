"""Optional auto-continueAt analysis for Suno Extend.

This service is deliberately isolated from the normal Extend flow. It only runs
when the admin setting is enabled and a request explicitly asks for
autoContinueAt. Manual continueAt behavior must keep working without this file.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from array import array
import importlib.util
import math
import shutil
import subprocess
import sys
import tempfile

import requests
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AppSetting, AudioAsset
from app.services.audio_metadata_service import read_audio_duration_seconds


AI_SETTINGS_KEY = "ai_chat_settings"


@dataclass
class ExtendContinueAtSettings:
    enabled: bool = False
    search_window_seconds: int = 15
    vocal_threshold_ratio: float = 0.03
    fallback_offset_seconds: float = 4.0
    timeout_seconds: int = 180


@dataclass
class ExtendContinueAtAnalysisResult:
    continue_at: float
    method: str
    confidence: float
    reason: str
    duration_seconds: float
    search_window_seconds: float
    vocal_candidate_seconds: float | None = None
    beat_synced: bool = False
    bpm: float | None = None
    warnings: list[str] | None = None

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        return {key: value for key, value in payload.items() if value is not None}


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _bounded_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def load_extend_continue_at_settings(db: Session) -> ExtendContinueAtSettings:
    row = db.query(AppSetting).filter(AppSetting.key == AI_SETTINGS_KEY).first()
    value = row.value if row and isinstance(row.value, dict) else {}
    return ExtendContinueAtSettings(
        enabled=bool(value.get("extend_auto_continue_at_enabled", False)),
        search_window_seconds=_bounded_int(value.get("extend_auto_continue_at_search_window_seconds"), 15, 5, 60),
        vocal_threshold_ratio=_bounded_float(value.get("extend_auto_continue_at_vocal_threshold_ratio"), 0.03, 0.005, 0.25),
        fallback_offset_seconds=_bounded_float(value.get("extend_auto_continue_at_fallback_offset_seconds"), 4.0, 1.0, 30.0),
        timeout_seconds=_bounded_int(value.get("extend_auto_continue_at_timeout_seconds"), 180, 30, 1200),
    )


def _is_public_http_url(value: str | None) -> bool:
    text = str(value or "").strip()
    if not text.startswith(("http://", "https://")):
        return False
    try:
        parsed = urlparse(text)
    except Exception:
        return False
    host = (parsed.hostname or "").lower()
    return bool(host and host not in {"localhost", "127.0.0.1", "0.0.0.0", "::1"})


def _resolve_local_audio_path(asset: AudioAsset) -> Path | None:
    settings = get_settings()
    storage_path = settings.audio_storage_path
    candidates: list[Path] = []

    for value in (asset.local_path, asset.filename):
        if not value:
            continue
        candidate = Path(str(value))
        candidates.append(candidate)
        if candidate.name:
            candidates.append(storage_path / candidate.name)

    for candidate in candidates:
        try:
            resolved = candidate if candidate.is_absolute() else candidate.resolve()
        except Exception:
            resolved = candidate
        if resolved.exists() and resolved.is_file() and resolved.stat().st_size > 0:
            return resolved
    return None


def _download_audio_to_temp(url: str, target: Path, max_bytes: int, timeout_seconds: float) -> Path:
    total = 0
    with requests.get(url, stream=True, timeout=timeout_seconds, allow_redirects=True) as response:
        response.raise_for_status()
        content_length = response.headers.get("content-length")
        if content_length and int(content_length) > max_bytes:
            raise RuntimeError("Audio-Download ueberschreitet das konfigurierte Limit.")
        with target.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 256):
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    raise RuntimeError("Audio-Download ueberschreitet das konfigurierte Limit.")
                handle.write(chunk)
    if total <= 0 or not target.exists():
        raise RuntimeError("Audio-Download hat keine Daten geliefert.")
    return target


def _probe_duration_seconds(path: Path) -> float:
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        try:
            result = subprocess.run(
                [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                capture_output=True,
                text=True,
                timeout=20,
                check=True,
            )
            duration = float(str(result.stdout or "").strip())
            if duration > 0:
                return duration
        except Exception:
            pass
    return float(read_audio_duration_seconds(path) or 0)


def _extract_tail_wav(source_path: Path, target_path: Path, duration_seconds: float, search_window_seconds: float) -> tuple[Path, float]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg ist fuer die Auto-continueAt-Analyse nicht verfuegbar.")
    start = max(0.0, duration_seconds - search_window_seconds)
    window = max(1.0, min(search_window_seconds, duration_seconds or search_window_seconds))
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{start:.3f}",
        "-t",
        f"{window:.3f}",
        "-i",
        str(source_path),
        "-ac",
        "2",
        "-ar",
        "44100",
        "-y",
        str(target_path),
    ]
    subprocess.run(command, capture_output=True, text=True, timeout=60, check=True)
    if not target_path.exists() or target_path.stat().st_size <= 0:
        raise RuntimeError("ffmpeg hat keinen gueltigen Analyse-Ausschnitt erzeugt.")
    return target_path, start


def _find_demucs_output(root: Path, stem_name: str) -> Path | None:
    for candidate in (
        root / "htdemucs" / stem_name / "vocals.wav",
        root / "htdemucs_ft" / stem_name / "vocals.wav",
    ):
        if candidate.exists() and candidate.stat().st_size > 0:
            return candidate
    matches = sorted(root.glob(f"*/{stem_name}/vocals.wav"))
    return matches[0] if matches else None


def _run_demucs_vocals(source_path: Path, output_root: Path, timeout_seconds: int) -> Path:
    if importlib.util.find_spec("demucs") is None:
        raise RuntimeError("Demucs ist nicht im FastAPI-Python-Environment installiert.")
    command = [
        sys.executable,
        "-m",
        "demucs",
        "--two-stems",
        "vocals",
        "-n",
        "htdemucs",
        "--out",
        str(output_root),
        str(source_path),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout_seconds)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "Demucs fehlgeschlagen.").strip()[-1000:]
        raise RuntimeError(detail)
    vocals = _find_demucs_output(output_root, source_path.stem)
    if not vocals:
        raise RuntimeError("Demucs hat keine vocals.wav erzeugt.")
    return vocals


def _read_pcm16_mono(path: Path, timeout_seconds: int = 45) -> tuple[array, int]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg ist fuer die Vocals-RMS-Analyse nicht verfuegbar.")
    sample_rate = 16000
    result = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-f",
            "s16le",
            "pipe:1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_seconds,
        check=True,
    )
    samples = array("h")
    samples.frombytes(result.stdout)
    if sys.byteorder != "little":
        samples.byteswap()
    return samples, sample_rate


def _find_vocal_end_in_window(vocals_path: Path, threshold_ratio: float) -> tuple[float | None, str]:
    samples, sample_rate = _read_pcm16_mono(vocals_path)
    if not samples:
        return None, "Vocals-Spur enthaelt keine auswertbaren Samples."

    frame_size = max(1, int(sample_rate * 0.05))
    rms_values: list[float] = []
    for start in range(0, len(samples), frame_size):
        frame = samples[start:start + frame_size]
        if not frame:
            continue
        rms_values.append(math.sqrt(sum(sample * sample for sample in frame) / len(frame)) / 32768.0)

    maximum = max(rms_values) if rms_values else 0.0
    if maximum <= 0.0005:
        return None, "Keine relevante Vocal-Energie im Suchfenster erkannt."

    threshold = maximum * threshold_ratio
    last_loud_index = None
    for index in range(len(rms_values) - 1, -1, -1):
        if rms_values[index] > threshold:
            last_loud_index = index
            break

    if last_loud_index is None:
        return None, "Vocals liegen im gesamten Suchfenster unter dem Schwellenwert."

    frame_duration = frame_size / sample_rate
    return (last_loud_index + 1) * frame_duration, "Letztes Vocal-Signal oberhalb des Schwellenwerts erkannt."


def _snap_to_beat(source_path: Path, candidate_seconds: float, tail_start_seconds: float) -> tuple[float, bool, float | None, str | None]:
    if importlib.util.find_spec("librosa") is None:
        return candidate_seconds, False, None, "librosa ist nicht installiert; Beat-Sync wurde uebersprungen."

    try:
        import librosa  # type: ignore

        y, sr = librosa.load(str(source_path), sr=22050, mono=True)
        tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
        beat_times = [float(value) + tail_start_seconds for value in librosa.frames_to_time(beat_frames, sr=sr)]
        if not beat_times:
            return candidate_seconds, False, None, "librosa hat keine Beat-Zeitpunkte erkannt."

        future_beats = [beat for beat in beat_times if beat >= candidate_seconds]
        if future_beats:
            snapped = min(future_beats, key=lambda beat: abs(beat - candidate_seconds))
        else:
            snapped = min(beat_times, key=lambda beat: abs(beat - candidate_seconds))

        if isinstance(tempo, (list, tuple)):
            bpm = float(tempo[0]) if tempo else None
        else:
            try:
                bpm = float(tempo)
            except Exception:
                bpm = None
        return snapped, True, bpm, None
    except Exception as exc:
        return candidate_seconds, False, None, f"Beat-Sync fehlgeschlagen: {exc.__class__.__name__}"


def _fallback_result(
    *,
    duration_seconds: float,
    search_window_seconds: float,
    fallback_offset_seconds: float,
    reason: str,
    warnings: list[str] | None = None,
) -> ExtendContinueAtAnalysisResult:
    continue_at = max(1.0, duration_seconds - fallback_offset_seconds) if duration_seconds > 0 else 1.0
    return ExtendContinueAtAnalysisResult(
        continue_at=round(continue_at, 3),
        method="fallback_duration_minus_offset",
        confidence=0.35,
        reason=reason,
        duration_seconds=round(duration_seconds, 3),
        search_window_seconds=search_window_seconds,
        warnings=warnings or [],
    )


def analyze_continue_at_for_path(path: Path, settings: ExtendContinueAtSettings) -> ExtendContinueAtAnalysisResult:
    try:
        duration = _probe_duration_seconds(path)
    except Exception as exc:
        return _fallback_result(
            duration_seconds=0,
            search_window_seconds=settings.search_window_seconds,
            fallback_offset_seconds=settings.fallback_offset_seconds,
            reason=f"Audiodauer konnte nicht ermittelt werden: {exc.__class__.__name__}",
        )

    if duration <= 0:
        return _fallback_result(
            duration_seconds=duration,
            search_window_seconds=settings.search_window_seconds,
            fallback_offset_seconds=settings.fallback_offset_seconds,
            reason="Audiodauer konnte nicht ermittelt werden.",
        )

    warnings: list[str] = []
    try:
        with tempfile.TemporaryDirectory(prefix="songstudio_extend_continue_at_") as tmp:
            tmp_path = Path(tmp)
            tail_path, tail_start = _extract_tail_wav(path, tmp_path / "tail.wav", duration, settings.search_window_seconds)
            try:
                vocals_path = _run_demucs_vocals(tail_path, tmp_path / "demucs", settings.timeout_seconds)
                vocal_window_seconds, reason = _find_vocal_end_in_window(vocals_path, settings.vocal_threshold_ratio)
            except Exception as exc:
                return _fallback_result(
                    duration_seconds=duration,
                    search_window_seconds=settings.search_window_seconds,
                    fallback_offset_seconds=settings.fallback_offset_seconds,
                    reason=f"Vocal-Analyse nicht verfuegbar: {exc}",
                    warnings=[exc.__class__.__name__],
                )

            if vocal_window_seconds is None:
                fallback_candidate = max(1.0, duration - settings.fallback_offset_seconds)
                snapped, beat_synced, bpm, warning = _snap_to_beat(tail_path, fallback_candidate, tail_start)
                if warning:
                    warnings.append(warning)
                return ExtendContinueAtAnalysisResult(
                    continue_at=round(max(1.0, min(duration, snapped)), 3),
                    method="instrumental_fallback_beat_sync" if beat_synced else "instrumental_fallback",
                    confidence=0.5 if beat_synced else 0.4,
                    reason=reason,
                    duration_seconds=round(duration, 3),
                    search_window_seconds=settings.search_window_seconds,
                    beat_synced=beat_synced,
                    bpm=bpm,
                    warnings=warnings,
                )

            candidate = max(1.0, min(duration, tail_start + vocal_window_seconds))
            snapped, beat_synced, bpm, warning = _snap_to_beat(tail_path, candidate, tail_start)
            if warning:
                warnings.append(warning)
            continue_at = max(1.0, min(duration, snapped))
            return ExtendContinueAtAnalysisResult(
                continue_at=round(continue_at, 3),
                method="demucs_vocals_beat_sync" if beat_synced else "demucs_vocals",
                confidence=0.86 if beat_synced else 0.72,
                reason=reason,
                duration_seconds=round(duration, 3),
                search_window_seconds=settings.search_window_seconds,
                vocal_candidate_seconds=round(candidate, 3),
                beat_synced=beat_synced,
                bpm=bpm,
                warnings=warnings,
            )
    except Exception as exc:
        return _fallback_result(
            duration_seconds=duration,
            search_window_seconds=settings.search_window_seconds,
            fallback_offset_seconds=settings.fallback_offset_seconds,
            reason=f"Auto-continueAt-Analyse fehlgeschlagen: {exc}",
            warnings=[exc.__class__.__name__],
        )


def analyze_continue_at_for_audio_url(url: str, settings: ExtendContinueAtSettings) -> ExtendContinueAtAnalysisResult:
    if not _is_public_http_url(url):
        return _fallback_result(
            duration_seconds=0,
            search_window_seconds=settings.search_window_seconds,
            fallback_offset_seconds=settings.fallback_offset_seconds,
            reason="Keine oeffentlich erreichbare Audio-URL fuer die Analyse vorhanden.",
        )
    with tempfile.TemporaryDirectory(prefix="songstudio_extend_download_") as tmp:
        target = Path(tmp) / "source_audio"
        try:
            path = _download_audio_to_temp(
                url,
                target,
                get_settings().audio_max_download_bytes,
                get_settings().suno_audio_download_timeout_seconds,
            )
        except Exception as exc:
            return _fallback_result(
                duration_seconds=0,
                search_window_seconds=settings.search_window_seconds,
                fallback_offset_seconds=settings.fallback_offset_seconds,
                reason=f"Temporaerer Audio-Download fehlgeschlagen: {exc}",
                warnings=[exc.__class__.__name__],
            )
        return analyze_continue_at_for_path(path, settings)


def analyze_continue_at_for_asset(asset: AudioAsset, settings: ExtendContinueAtSettings) -> ExtendContinueAtAnalysisResult:
    local_path = _resolve_local_audio_path(asset)
    if local_path:
        return analyze_continue_at_for_path(local_path, settings)
    url = str(asset.source_url or asset.public_url or "").strip()
    return analyze_continue_at_for_audio_url(url, settings)

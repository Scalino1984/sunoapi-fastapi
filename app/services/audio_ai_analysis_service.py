from __future__ import annotations

# AUDIO AI ANALYSIS CONTRACT
# Zweck: Lokale, optionale Audioanalyse fuer bestehende AudioAssets.
# Speichern: AudioAsset.metadata_json["audio_ai_analysis"] plus Exportdateien unter storage/analysis/audio_<id>/.
# Nicht koppeln an: Suno-Payloads, Importlogik, SRT-Erzeugung, Extend-continueAt oder Cover-Workflows.
# Heavy-Modelle und KI-Zusammenfassung bleiben optional; fehlende Pakete/API-Keys duerfen die Basisanalyse nicht brechen.

import asyncio
import base64
import csv
import html as html_lib
import json
import math
import mimetypes
import os
import statistics
import time
from dataclasses import dataclass
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import ActivityLog, AppSetting, AudioAsset, Song, StatusNotification, SunoTask
from app.services.ai_chat_service import AiChatService, AiProviderError
from app.services.audio_metadata_service import normalize_audio_content_type, read_audio_duration_seconds
from app.services.portable_path_service import resolve_portable_path, to_portable_path
from app.services.task_lifecycle_service import heartbeat_task, is_cancel_requested, mark_task_finished, mark_task_started
from app.utils.time_utils import utc_now_naive


ANALYSIS_METADATA_KEY = "audio_ai_analysis"
ANALYSIS_TASK_TYPE = "audio_ai_analysis"
AI_SETTINGS_KEY = "ai_chat_settings"


@dataclass
class AudioAiAnalysisOptions:
    profile: str = "standard"
    include_ai_report: bool = True
    force: bool = False


def _asset_title(asset: AudioAsset) -> str:
    return asset.display_title or asset.title or asset.filename or f"AudioAsset {asset.id}"


def _analysis_dir(asset_id: int) -> Path:
    settings = get_settings()
    root = settings.audio_ai_analysis_storage_path / f"audio_{int(asset_id)}"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_filename_part(value: Any, fallback: str = "audio") -> str:
    raw = str(value or fallback).strip() or fallback
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_", ".", " "} else "_" for ch in raw)
    safe = "_".join(safe.split()).strip("._- ")
    return safe[:96] or fallback


def resolve_audio_asset_file(asset: AudioAsset) -> Path | None:
    settings = get_settings()
    return resolve_portable_path(asset.local_path or asset.filename or asset.public_url, [settings.audio_storage_path])


def load_audio_ai_analysis_admin_settings(db: Session | None = None) -> dict[str, Any]:
    """Load persisted admin switches for local audio analysis.

    Defaults come from environment-backed Settings. Persisted AppSetting values
    can disable expensive model/AI steps without changing code or redeploying.
    """

    settings = get_settings()
    value: dict[str, Any] = {}
    if db is not None:
        try:
            row = db.query(AppSetting).filter(AppSetting.key == AI_SETTINGS_KEY).first()
            if row and isinstance(row.value, dict):
                value = row.value
        except Exception:
            value = {}

    def bounded_int(key: str, default: int, minimum: int, maximum: int) -> int:
        try:
            number = int(value.get(key, default))
        except (TypeError, ValueError):
            number = int(default)
        return max(minimum, min(maximum, number))

    provider = str(value.get("default_provider") or settings.ai_default_provider).strip().lower()
    model = str(value.get("default_model") or settings.ai_default_model).strip()
    allowed = settings.ai_allowed_models
    if provider not in allowed:
        provider = settings.ai_default_provider
    if provider in allowed and model not in allowed[provider]:
        model = settings.ai_default_model if settings.ai_default_model in allowed.get(provider, []) else (allowed.get(provider, [""])[0] or "")

    return {
        "enabled": bool(value.get("audio_ai_analysis_enabled", settings.audio_ai_analysis_enabled)),
        "ai_summary_enabled": bool(value.get("audio_ai_analysis_ai_summary_enabled", settings.audio_ai_analysis_ai_summary_enabled)),
        "model_analysis_enabled": bool(value.get("audio_ai_model_analysis_enabled", settings.audio_ai_model_analysis_enabled)),
        "analysis_max_seconds": bounded_int("audio_ai_analysis_max_seconds", settings.audio_ai_analysis_max_seconds, 30, 1200),
        "model_analysis_seconds": bounded_int("audio_ai_model_analysis_seconds", settings.audio_ai_model_analysis_seconds, 8, 90),
        "model_analysis_top_k": bounded_int("audio_ai_model_analysis_top_k", settings.audio_ai_model_analysis_top_k, 5, 25),
        "model_cache_path": settings.audio_ai_model_cache_path,
        "ai_provider": provider,
        "ai_model": model,
        "acoustid_api_key": settings.acoustid_api_key,
    }


def read_saved_audio_ai_analysis(asset: AudioAsset | None) -> dict[str, Any] | None:
    if not asset:
        return None
    metadata = asset.metadata_json if isinstance(asset.metadata_json, dict) else {}
    value = metadata.get(ANALYSIS_METADATA_KEY)
    return value if isinstance(value, dict) else None


def create_audio_ai_status_task(db: Session, asset: AudioAsset, options: AudioAiAnalysisOptions) -> SunoTask:
    title = _asset_title(asset)
    task = SunoTask(
        task_id=None,
        task_type=ANALYSIS_TASK_TYPE,
        status="RUNNING",
        request_payload={
            "audio_asset_id": asset.id,
            "title": title,
            "profile": options.profile,
            "include_ai_report": bool(options.include_ai_report),
            "force": bool(options.force),
            "local_task": True,
            "background": True,
        },
        response_payload={"background": True, "local_task": True, "status": "RUNNING"},
        result_payload=None,
        error_message=None,
        started_at=utc_now_naive(),
        heartbeat_at=utc_now_naive(),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    mark_task_started(db, task, payload={"audio_asset_id": asset.id, "profile": options.profile})
    db.add(StatusNotification(
        event_type="audio_ai_analysis_started",
        title=f"Audioanalyse läuft: {title}",
        message="Lokale Audioanalyse und Report-Erstellung laufen im Hintergrund.",
        severity="info",
        status="unread",
        task_local_id=task.id,
        suno_task_id=None,
        content_type="audio",
        content_id=asset.id,
        target_tab="status",
        target_payload={"audio_asset_id": asset.id, "task_local_id": task.id, "task_type": ANALYSIS_TASK_TYPE, "status": "RUNNING"},
    ))
    db.commit()
    return task


def _probe_file(path: Path, asset: AudioAsset) -> dict[str, Any]:
    stat = path.stat()
    duration = read_audio_duration_seconds(path) or asset.duration_seconds
    return {
        "path": str(path),
        "filename": path.name,
        "extension": path.suffix.lower(),
        "content_type": normalize_audio_content_type(asset.content_type, path),
        "size_bytes": int(stat.st_size),
        "duration_seconds": float(duration) if duration else None,
        "checksum_sha256": asset.checksum_sha256,
    }


def _load_audio_for_analysis(path: Path, max_seconds: int) -> tuple[Any, int, dict[str, Any]]:
    try:
        import librosa  # type: ignore
    except Exception as exc:
        return None, 0, {
            "available": False,
            "reason": f"librosa nicht verfügbar: {exc.__class__.__name__}",
        }

    try:
        y, sr = librosa.load(str(path), sr=22050, mono=True, duration=max(5, int(max_seconds or 240)))
        if y is None or len(y) <= 0:
            return None, 0, {"available": False, "reason": "Audiodaten konnten nicht gelesen werden."}
        return y, int(sr), {"available": True, "sample_rate": int(sr), "samples": int(len(y)), "max_seconds": int(max_seconds or 240)}
    except Exception as exc:
        return None, 0, {"available": False, "reason": f"Audioanalyse fehlgeschlagen: {exc.__class__.__name__}: {exc}"}


def _finite_float(value: Any, default: float | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _compute_signal_analysis(y: Any, sr: int) -> dict[str, Any]:
    try:
        import librosa  # type: ignore
        import numpy as np  # type: ignore
    except Exception as exc:
        return {"available": False, "reason": f"Signalpakete nicht verfügbar: {exc.__class__.__name__}"}

    try:
        rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=512)[0]
        rms_values = [float(item) for item in rms if math.isfinite(float(item))]
        if not rms_values:
            return {"available": False, "reason": "Keine RMS-Werte berechnet."}
        peak = max(float(np.max(np.abs(y))), 1e-9)
        rms_max = max(rms_values)
        rms_mean = statistics.fmean(rms_values)
        rms_median = statistics.median(rms_values)
        quiet_threshold = max(rms_max * 0.03, 1e-7)
        quiet_ratio = sum(1 for item in rms_values if item <= quiet_threshold) / max(1, len(rms_values))
        return {
            "available": True,
            "peak_amplitude": round(peak, 6),
            "rms_mean": round(rms_mean, 6),
            "rms_median": round(rms_median, 6),
            "rms_max": round(rms_max, 6),
            "quiet_ratio": round(float(quiet_ratio), 4),
            "estimated_loudness": "leise" if rms_mean < 0.025 else "mittel" if rms_mean < 0.08 else "laut",
            "dynamic_hint": "dynamisch" if rms_max / max(rms_median, 1e-9) > 6 else "kompakt",
        }
    except Exception as exc:
        return {"available": False, "reason": f"RMS-Analyse fehlgeschlagen: {exc.__class__.__name__}: {exc}"}


def _compute_tempo_analysis(y: Any, sr: int) -> dict[str, Any]:
    try:
        import librosa  # type: ignore
        import numpy as np  # type: ignore
    except Exception as exc:
        return {"available": False, "reason": f"librosa nicht verfügbar: {exc.__class__.__name__}", "beatgrid": []}

    try:
        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
        tempo, beats = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr, units="frames")
        tempo_value = _finite_float(np.atleast_1d(tempo)[0], 0.0) or 0.0
        beat_times = librosa.frames_to_time(beats, sr=sr)
        beatgrid = [{"index": index + 1, "time": round(float(time_value), 3)} for index, time_value in enumerate(beat_times[:1000])]
        intervals = [beatgrid[index]["time"] - beatgrid[index - 1]["time"] for index in range(1, min(len(beatgrid), 80))]
        confidence = 0.0
        if intervals:
            median_interval = statistics.median(intervals)
            spread = statistics.pstdev(intervals) if len(intervals) > 1 else 0.0
            confidence = max(0.0, min(1.0, 1.0 - (spread / max(median_interval, 1e-9))))
        return {
            "available": True,
            "bpm": round(tempo_value, 2) if tempo_value else None,
            "beat_count": len(beatgrid),
            "confidence": round(confidence, 3),
            "beatgrid": beatgrid,
            "analysis_hint": "stabil" if confidence >= 0.72 else "prüfen",
        }
    except Exception as exc:
        return {"available": False, "reason": f"Tempoanalyse fehlgeschlagen: {exc.__class__.__name__}: {exc}", "beatgrid": []}


def _analyze_copyright_acoustid(audio_path: Path, api_key: str | None) -> dict[str, Any]:
    """Chromaprint/AcoustID check for known recordings.

    Das ist eine Bekanntaufnahme-/Fingerprint-Pruefung, keine Rechtsberatung.
    Kein Treffer beweist nicht, dass ein Track rechtlich frei ist.
    """

    started = time.monotonic()
    try:
        import acoustid  # type: ignore
    except Exception as exc:
        return {
            "ok": False,
            "available": False,
            "method": "chromaprint/acoustid",
            "runtime_seconds": round(time.monotonic() - started, 3),
            "verdict": "nicht verfügbar",
            "risk_level": "unknown",
            "error": f"pyacoustid fehlt oder konnte nicht geladen werden: {exc.__class__.__name__}: {exc}",
            "install_hint": "Debian/Ubuntu/WSL: sudo apt-get install -y libchromaprint-tools ffmpeg && pip install pyacoustid",
        }

    try:
        duration, fingerprint = acoustid.fingerprint_file(str(audio_path))
        fingerprint_len = len(fingerprint) if fingerprint is not None else 0
        result: dict[str, Any] = {
            "ok": True,
            "available": True,
            "method": "chromaprint/acoustid",
            "duration_s": round(float(duration), 1),
            "fingerprint_len": int(fingerprint_len),
            "runtime_seconds": round(time.monotonic() - started, 3),
            "db_lookup_performed": bool(api_key),
            "db_matches": [],
        }
        if not api_key:
            result.update({
                "verdict": "Nur lokaler Fingerprint berechnet. Kein ACOUSTID_API_KEY gesetzt.",
                "risk_level": "unknown",
                "user_explanation": "Die Datei wurde fingerprinted, aber nicht gegen die AcoustID-Datenbank geprüft.",
            })
            return result

        try:
            response = acoustid.lookup(api_key, fingerprint, duration, meta="recordings")
        except Exception as exc:
            result.update({
                "verdict": f"AcoustID Lookup fehlgeschlagen: {exc}",
                "risk_level": "unknown",
                "user_explanation": "Der Fingerprint wurde berechnet, aber die Online-Datenbankabfrage schlug fehl.",
            })
            return result

        if response.get("status") != "ok":
            error = response.get("error", {}) if isinstance(response, dict) else {}
            result.update({
                "verdict": f"AcoustID-Fehler code {error.get('code')}: {error.get('message', 'unbekannt')}",
                "risk_level": "unknown",
                "user_explanation": "Die Datenbankabfrage konnte nicht sauber ausgewertet werden.",
            })
            return result

        matches = []
        for row in response.get("results") or []:
            recordings = row.get("recordings") or []
            recording = recordings[0] if recordings else {}
            artists = ", ".join(artist.get("name", "") for artist in recording.get("artists", []) if artist.get("name")) or None
            matches.append({
                "score": round(float(row.get("score", 0.0)), 4),
                "title": recording.get("title"),
                "artist": artists,
                "recording_id": recording.get("id"),
            })
            if len(matches) >= 5:
                break

        result["db_matches"] = matches
        if matches:
            top_score = float(matches[0].get("score") or 0.0)
            result.update({
                "risk_level": "high" if top_score >= 0.8 else "medium",
                "verdict": "Treffer in AcoustID-Datenbank -> bekannte Aufnahme / Match-Kandidat.",
                "user_explanation": "Es wurde mindestens ein Datenbanktreffer gefunden. Rechte/Lizenzstatus manuell prüfen.",
            })
        else:
            result.update({
                "risk_level": "low_unknown",
                "verdict": "Kein AcoustID-Treffer -> vermutlich Original / unbekannt.",
                "user_explanation": "Kein Treffer ist gut, aber kein rechtlicher Freibrief.",
            })
        return result
    except Exception as exc:
        return {
            "ok": False,
            "available": True,
            "method": "chromaprint/acoustid",
            "runtime_seconds": round(time.monotonic() - started, 3),
            "verdict": "nicht auswertbar",
            "risk_level": "unknown",
            "error": f"{exc.__class__.__name__}: {exc}",
            "install_hint": "Prüfe, ob fpcalc installiert ist: fpcalc -version",
        }


def _score_label(score: float | None) -> str:
    if score is None:
        return "unbekannt"
    if score >= 0.75:
        return "hoch"
    if score >= 0.45:
        return "mittel"
    return "niedrig"


def _compute_local_content_insights(y: Any, sr: int, signal: dict[str, Any], tempo: dict[str, Any]) -> dict[str, Any]:
    try:
        import librosa  # type: ignore
        import numpy as np  # type: ignore
    except Exception as exc:
        reason = f"librosa/numpy nicht verfügbar: {exc.__class__.__name__}"
        return {
            "genre": {"ok": False, "method": "local_audio_features", "reason": reason},
            "mood": {"ok": False, "method": "local_audio_features", "reason": reason},
            "vocals": {"ok": False, "method": "local_audio_features", "reason": reason},
            "instruments": {"ok": False, "method": "local_audio_features", "reason": reason, "candidates": []},
            "authenticity": {"ok": False, "method": "model_required", "reason": "Echtheits-/Deepfake-Aussage benötigt ein Klassifikationsmodell."},
        }

    try:
        harmonic, percussive = librosa.effects.hpss(y)
        harmonic_energy = float(np.mean(np.abs(harmonic)))
        percussive_energy = float(np.mean(np.abs(percussive)))
        total_energy = max(harmonic_energy + percussive_energy, 1e-9)
        percussive_ratio = percussive_energy / total_energy
        harmonic_ratio = harmonic_energy / total_energy
        centroid = float(np.mean(librosa.feature.spectral_centroid(y=y, sr=sr)))
        bandwidth = float(np.mean(librosa.feature.spectral_bandwidth(y=y, sr=sr)))
        rolloff = float(np.mean(librosa.feature.spectral_rolloff(y=y, sr=sr)))
        zcr = float(np.mean(librosa.feature.zero_crossing_rate(y)))
        flatness = float(np.mean(librosa.feature.spectral_flatness(y=y)))
        tempo_bpm = _finite_float(tempo.get("bpm"), 0.0) or 0.0
        rms_mean = _finite_float(signal.get("rms_mean"), 0.0) or 0.0

        genre_scores: list[dict[str, Any]] = []
        genre_scores.append({"label": "hip hop / rap / rhythmic pop", "score": round(min(0.9, 0.35 + percussive_ratio * 0.55 + (0.1 if 75 <= tempo_bpm <= 115 else 0)), 4)})
        genre_scores.append({"label": "electronic / synth / pop", "score": round(min(0.85, 0.2 + flatness * 1.8 + (0.15 if tempo_bpm >= 105 else 0)), 4)})
        genre_scores.append({"label": "rock / guitar-oriented", "score": round(min(0.75, 0.18 + harmonic_ratio * 0.35 + (0.12 if centroid > 2200 else 0)), 4)})
        genre_scores.append({"label": "cinematic / ballad / ambient", "score": round(min(0.75, 0.18 + harmonic_ratio * 0.4 + (0.16 if tempo_bpm < 85 else 0)), 4)})
        genre_scores.sort(key=lambda row: row["score"], reverse=True)

        mood_scores: list[dict[str, Any]] = []
        mood_scores.append({"label": "energetic / driving", "score": round(min(0.95, 0.25 + percussive_ratio * 0.45 + rms_mean * 2.0 + (0.15 if tempo_bpm >= 105 else 0)), 4)})
        mood_scores.append({"label": "dark / dense", "score": round(min(0.9, 0.25 + (0.2 if centroid < 2300 else 0) + rms_mean * 1.2 + (0.15 if flatness > 0.02 else 0)), 4)})
        mood_scores.append({"label": "calm / reflective", "score": round(min(0.85, 0.25 + harmonic_ratio * 0.4 + (0.18 if tempo_bpm < 90 else 0) - min(0.18, rms_mean)), 4)})
        mood_scores.append({"label": "bright / open", "score": round(min(0.85, 0.2 + (0.25 if centroid > 2600 else 0) + (0.15 if rolloff > 5000 else 0)), 4)})
        mood_scores.sort(key=lambda row: row["score"], reverse=True)

        speech_score = max(0.0, min(1.0, 0.18 + zcr * 4.0 + percussive_ratio * 0.25 - flatness * 0.8))
        singing_score = max(0.0, min(1.0, 0.18 + harmonic_ratio * 0.55 + (0.12 if bandwidth > 1600 else 0) - zcr * 1.5))
        instrumental_score = max(0.0, min(1.0, 0.25 + harmonic_ratio * 0.35 + percussive_ratio * 0.25 - max(speech_score, singing_score) * 0.18))
        dominant = max(
            [("speech/rap", speech_score), ("singing", singing_score), ("instrumental/music", instrumental_score)],
            key=lambda item: item[1],
        )[0]

        candidates = [
            {"label": "drums/percussion", "score": round(min(1.0, percussive_ratio * 1.35), 4)},
            {"label": "bass / low rhythmic foundation", "score": round(min(1.0, 0.35 + (0.25 if centroid < 2200 else 0) + percussive_ratio * 0.25), 4)},
            {"label": "synth/pad/texture", "score": round(min(1.0, 0.22 + flatness * 2.0 + harmonic_ratio * 0.25), 4)},
            {"label": "piano/guitar/harmonic instrument", "score": round(min(1.0, 0.25 + harmonic_ratio * 0.5 + (0.1 if 1400 <= centroid <= 3200 else 0)), 4)},
        ]
        candidates = [item for item in sorted(candidates, key=lambda row: row["score"], reverse=True) if item["score"] >= 0.25]

        return {
            "features": {
                "spectral_centroid_mean": round(centroid, 3),
                "spectral_bandwidth_mean": round(bandwidth, 3),
                "spectral_rolloff_mean": round(rolloff, 3),
                "zero_crossing_rate_mean": round(zcr, 6),
                "spectral_flatness_mean": round(flatness, 6),
                "harmonic_ratio": round(harmonic_ratio, 4),
                "percussive_ratio": round(percussive_ratio, 4),
            },
            "genre": {
                "ok": True,
                "method": "local_audio_feature_heuristic",
                "note": "Lokale Heuristik aus Tempo, Spektrum, RMS und HPSS. Für belastbare Genre-Aussagen externe Klassifikationsmodelle nutzen.",
                "scores": genre_scores,
                "top": genre_scores[0] if genre_scores else None,
                "confidence": _score_label(genre_scores[0]["score"] if genre_scores else None),
            },
            "mood": {
                "ok": True,
                "method": "local_audio_feature_heuristic",
                "scores": mood_scores,
                "top": mood_scores[0] if mood_scores else None,
                "confidence": _score_label(mood_scores[0]["score"] if mood_scores else None),
            },
            "vocals": {
                "ok": True,
                "method": "local_audio_feature_heuristic",
                "dominant": dominant,
                "speech_score": round(speech_score, 4),
                "singing_score": round(singing_score, 4),
                "instrumental_score": round(instrumental_score, 4),
                "note": "Heuristik, keine getrennte Vocal-Stem- oder AST-Klassifikation.",
            },
            "instruments": {
                "ok": True,
                "method": "local_audio_feature_heuristic",
                "candidates": candidates,
                "note": "Instrumente sind Indizien aus Spektral-/HPSS-Merkmalen, keine sichere Instrumentenerkennung.",
            },
            "authenticity": {
                "ok": False,
                "method": "model_required",
                "verdict": "nicht geprüft",
                "reason": "Echtheits-/Deepfake-Aussage benötigt das optionale lokale Klassifikationsmodell.",
            },
        }
    except Exception as exc:
        reason = f"Lokale Inhaltsanalyse fehlgeschlagen: {exc.__class__.__name__}: {exc}"
        return {
            "genre": {"ok": False, "method": "local_audio_features", "reason": reason},
            "mood": {"ok": False, "method": "local_audio_features", "reason": reason},
            "vocals": {"ok": False, "method": "local_audio_features", "reason": reason},
            "instruments": {"ok": False, "method": "local_audio_features", "reason": reason, "candidates": []},
            "authenticity": {"ok": False, "method": "model_required", "reason": reason},
        }


INSTRUMENT_TERMS = {
    "guitar", "electric guitar", "acoustic guitar", "bass", "drum", "drum kit", "drum machine",
    "piano", "keyboard", "organ", "synthesizer", "synth", "violin", "fiddle", "cello",
    "viola", "trumpet", "trombone", "french horn", "saxophone", "flute", "clarinet",
    "oboe", "harmonica", "accordion", "banjo", "mandolin", "ukulele", "sitar", "harp",
    "marimba", "xylophone", "glockenspiel", "vibraphone", "cymbal", "hi-hat", "snare",
    "tambourine", "cowbell", "percussion", "brass instrument", "string section",
    "scratching", "turntable", "steelpan", "plucked string instrument",
}

VOCAL_BUCKET_KEYWORDS = {
    "singing": ["singing", "vocal music", "choir", "chant", "yodeling", "rapping"],
    "speech": ["speech", "narration", "conversation", "male speech", "female speech"],
    "music": ["music", "instrumental"],
}


def _normalize_scores(raw: Any, limit: int = 10) -> list[dict[str, Any]]:
    rows = raw if isinstance(raw, list) else []
    result: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        label = str(row.get("label") or row.get("class") or "").strip()
        if not label:
            continue
        score = _finite_float(row.get("score"), 0.0) or 0.0
        result.append({"label": label, "score": round(float(score), 4)})
    result.sort(key=lambda item: item["score"], reverse=True)
    return result[:limit]


def _derive_vocal_buckets_from_scores(scores: list[dict[str, Any]]) -> dict[str, float]:
    buckets = {"singing": 0.0, "speech": 0.0, "music": 0.0}
    for row in scores:
        label = str(row.get("label") or "").lower()
        score = _finite_float(row.get("score"), 0.0) or 0.0
        for bucket, keywords in VOCAL_BUCKET_KEYWORDS.items():
            if any(keyword in label for keyword in keywords):
                buckets[bucket] += score
    return {key: round(value, 4) for key, value in buckets.items()}


def _derive_instruments_from_scores(scores: list[dict[str, Any]]) -> dict[str, Any]:
    hits: list[dict[str, Any]] = []
    for row in scores:
        label = str(row.get("label") or "")
        lower = label.lower()
        score = _finite_float(row.get("score"), 0.0) or 0.0
        if any(term in lower for term in INSTRUMENT_TERMS):
            hits.append({"label": label, "score": round(score, 4)})
    hits.sort(key=lambda item: item["score"], reverse=True)
    return {
        "ok": True,
        "method": "derived_from_ast_audioset",
        "note": "Instrumente werden aus AST/AudioSet-Labels abgeleitet. Das ist eine Indizliste, keine getrennte Instrumentenerkennung.",
        "candidates": hits[:10],
        "has_candidates": bool(hits),
    }


def _interpret_deepfake_scores(scores: list[dict[str, Any]]) -> dict[str, Any]:
    synthetic = 0.0
    human = 0.0
    for row in scores:
        label = str(row.get("label") or "").lower()
        score = _finite_float(row.get("score"), 0.0) or 0.0
        if any(key in label for key in ("fake", "synthetic", "generated", "ai", "spoof")):
            synthetic = max(synthetic, score)
        if any(key in label for key in ("real", "human", "bonafide", "bona fide", "authentic")):
            human = max(human, score)
    if synthetic >= 0.75:
        verdict = "starkes Synthetic-/KI-Indiz"
    elif synthetic >= 0.5:
        verdict = "mittleres Synthetic-/KI-Indiz"
    elif human >= 0.5:
        verdict = "eher echt / human laut Modell"
    elif scores:
        verdict = "unklar"
    else:
        verdict = "nicht geprüft"
    return {
        "ok": bool(scores),
        "method": "local_transformers_audio_classification",
        "verdict": verdict,
        "synthetic_score": round(synthetic, 4),
        "human_score": round(human, 4),
        "scores": scores,
        "note": "Deepfake/Synthetic Detection ist ein Modell-Indiz, kein Beweis.",
    }


def _export_model_clip(y: Any, sr: int, target_dir: Path, seconds_value: int) -> Path | None:
    seconds = max(8, min(90, int(seconds_value or 30)))
    try:
        import soundfile as sf  # type: ignore
    except Exception:
        return None
    try:
        total_samples = len(y)
        sample_count = min(total_samples, int(sr * seconds))
        if sample_count <= 0:
            return None
        start = max(0, int((total_samples - sample_count) / 2))
        clip = y[start:start + sample_count]
        target = target_dir / "model_analysis_clip.wav"
        sf.write(str(target), clip, sr)
        return target
    except Exception:
        return None


def _run_audio_classification_model(model: str, audio_path: Path, *, top_k: int, cache_dir: Path) -> dict[str, Any]:
    try:
        from transformers import pipeline  # type: ignore
    except Exception as exc:
        return {"ok": False, "model": model, "method": "transformers_pipeline", "reason": f"transformers nicht verfügbar: {exc.__class__.__name__}: {exc}", "scores": []}
    try:
        os.environ.setdefault("HF_HOME", str(cache_dir))
        os.environ.setdefault("TRANSFORMERS_CACHE", str(cache_dir))
        classifier = pipeline("audio-classification", model=model, top_k=top_k, device=-1, model_kwargs={"cache_dir": str(cache_dir)})
        scores = _normalize_scores(classifier(str(audio_path)), limit=max(top_k, 10))
        return {"ok": True, "model": model, "method": "transformers_pipeline", "scores": scores}
    except Exception as exc:
        return {"ok": False, "model": model, "method": "transformers_pipeline", "reason": f"{exc.__class__.__name__}: {exc}", "scores": []}


def _run_internal_model_analysis(audio_path: Path, y: Any, sr: int, target_dir: Path, local_content: dict[str, Any], runtime_settings: dict[str, Any]) -> dict[str, Any]:
    if not runtime_settings.get("model_analysis_enabled", True):
        return {"ok": False, "enabled": False, "reason": "Interne Modellanalyse ist deaktiviert."}
    cache_dir = Path(runtime_settings.get("model_cache_path") or get_settings().audio_ai_model_cache_path).expanduser().resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)
    top_k = max(5, min(25, int(runtime_settings.get("model_analysis_top_k") or 8)))
    model_audio_path = _export_model_clip(y, sr, target_dir, int(runtime_settings.get("model_analysis_seconds") or 30)) or audio_path
    results: dict[str, Any] = {
        "ok": True,
        "enabled": True,
        "method": "internal_transformers_models",
        "cache_dir": to_portable_path(cache_dir, storage_root=cache_dir.parent),
        "audio_path": to_portable_path(model_audio_path, storage_root=target_dir) or str(model_audio_path.name),
    }

    genre_result = _run_audio_classification_model("dima806/music_genres_classification", model_audio_path, top_k=top_k, cache_dir=cache_dir)
    ast_result = _run_audio_classification_model("MIT/ast-finetuned-audioset-10-10-0.4593", model_audio_path, top_k=max(top_k, 16), cache_dir=cache_dir)
    deepfake_candidates = [
        "Hemgg/Deepfake-audio-detection",
        "MelodyMachine/Deepfake-audio-detection-V2",
        "mo-thecreator/Deepfake-audio-detection",
    ]
    deepfake_result = None
    for model in deepfake_candidates:
        candidate = _run_audio_classification_model(model, model_audio_path, top_k=top_k, cache_dir=cache_dir)
        if candidate.get("ok"):
            deepfake_result = candidate
            break
        if deepfake_result is None:
            deepfake_result = candidate

    if genre_result.get("ok"):
        genre_scores = _normalize_scores(genre_result.get("scores"), limit=top_k)
        results["genre"] = {
            "ok": True,
            "method": "transformers_audio_classification",
            "model": genre_result.get("model"),
            "scores": genre_scores,
            "top": genre_scores[0] if genre_scores else None,
            "confidence": _score_label(genre_scores[0]["score"] if genre_scores else None),
        }
    else:
        results["genre"] = {**(local_content.get("genre") or {}), "model_error": genre_result.get("reason")}

    if ast_result.get("ok"):
        ast_scores = _normalize_scores(ast_result.get("scores"), limit=max(top_k, 16))
        buckets = _derive_vocal_buckets_from_scores(ast_scores)
        results["vocals"] = {
            "ok": True,
            "method": "transformers_ast_audioset",
            "model": ast_result.get("model"),
            "scores": ast_scores[:top_k],
            "buckets": buckets,
            "dominant": max(buckets.items(), key=lambda item: item[1])[0] if buckets else None,
        }
        results["instruments"] = _derive_instruments_from_scores(ast_scores)
    else:
        results["vocals"] = {**(local_content.get("vocals") or {}), "model_error": ast_result.get("reason")}
        results["instruments"] = {**(local_content.get("instruments") or {}), "model_error": ast_result.get("reason")}

    if deepfake_result and deepfake_result.get("ok"):
        results["authenticity"] = _interpret_deepfake_scores(_normalize_scores(deepfake_result.get("scores"), limit=top_k))
        results["authenticity"]["model"] = deepfake_result.get("model")
    else:
        results["authenticity"] = {**(local_content.get("authenticity") or {}), "model_error": (deepfake_result or {}).get("reason")}

    # CLAP-Zero-Shot ist bewusst nicht als separater harter Pfad integriert; Mood bleibt stabil ueber lokale Features,
    # bis ein app-internes, getestetes Zero-Shot-Modul ergaenzt wird.
    results["mood"] = local_content.get("mood") or {}
    results["features"] = local_content.get("features") or {}
    return results


def _derive_overview(asset: AudioAsset, file_info: dict[str, Any], signal: dict[str, Any], tempo: dict[str, Any]) -> dict[str, Any]:
    bpm = tempo.get("bpm") if isinstance(tempo, dict) else None
    duration = file_info.get("duration_seconds")
    return {
        "title": _asset_title(asset),
        "duration": duration,
        "duration_label": f"{duration:.1f}s" if isinstance(duration, (int, float)) else "unbekannt",
        "bpm": bpm,
        "tempo_confidence": tempo.get("confidence") if isinstance(tempo, dict) else None,
        "loudness": signal.get("estimated_loudness") if isinstance(signal, dict) else None,
        "dynamic_hint": signal.get("dynamic_hint") if isinstance(signal, dict) else None,
        "storage": "lokale Datei",
        "local_models_note": "Basisanalyse lokal. Erweiterte Transformer-/Fingerprint-Modelle bleiben optional und werden nicht vorausgesetzt.",
    }


def _default_report_blocks(report: dict[str, Any]) -> list[dict[str, str]]:
    overview = report.get("overview") if isinstance(report.get("overview"), dict) else {}
    tempo = report.get("tempo_analysis") if isinstance(report.get("tempo_analysis"), dict) else {}
    signal = report.get("signal_analysis") if isinstance(report.get("signal_analysis"), dict) else {}
    file_info = report.get("file") if isinstance(report.get("file"), dict) else {}
    copyright_info = report.get("copyright_analysis") if isinstance(report.get("copyright_analysis"), dict) else {}
    content = report.get("content_analysis") if isinstance(report.get("content_analysis"), dict) else {}
    genre = content.get("genre") if isinstance(content.get("genre"), dict) else {}
    mood = content.get("mood") if isinstance(content.get("mood"), dict) else {}
    vocals = content.get("vocals") if isinstance(content.get("vocals"), dict) else {}
    instruments = content.get("instruments") if isinstance(content.get("instruments"), dict) else {}
    authenticity = content.get("authenticity") if isinstance(content.get("authenticity"), dict) else {}
    model_analysis = report.get("model_analysis") if isinstance(report.get("model_analysis"), dict) else {}

    def score_lines(rows: Any, limit: int = 5) -> list[str]:
        if not isinstance(rows, list):
            return []
        lines: list[str] = []
        for row in rows[:limit]:
            if not isinstance(row, dict):
                continue
            label = row.get("label") or row.get("title") or "—"
            score = row.get("score")
            lines.append(f"- {label}: {score if score is not None else '—'}")
        return lines

    model_genre_scores = (model_analysis.get("genre") or {}).get("scores") if isinstance(model_analysis.get("genre"), dict) else None
    model_vocal_buckets = (model_analysis.get("vocals") or {}).get("buckets") if isinstance(model_analysis.get("vocals"), dict) else None
    model_instruments = (model_analysis.get("instruments") or {}).get("candidates") if isinstance(model_analysis.get("instruments"), dict) else None
    model_deepfake_scores = (model_analysis.get("authenticity") or {}).get("scores") if isinstance(model_analysis.get("authenticity"), dict) else None

    copyright_matches = copyright_info.get("db_matches") if isinstance(copyright_info.get("db_matches"), list) else []
    blocks = [
        {
            "title": "Kurzüberblick",
            "text": "\n".join([
                f"Titel: {overview.get('title') or '—'}",
                f"Dauer: {overview.get('duration_label') or '—'}",
                f"BPM: {overview.get('bpm') or '—'}",
                f"Lautheit: {overview.get('loudness') or '—'}",
                f"Dynamik: {overview.get('dynamic_hint') or '—'}",
            ]),
        },
        {
            "title": "Copyright / bekannte Aufnahme",
            "text": "\n".join([
                f"Methode: {copyright_info.get('method') or '—'}",
                f"Ergebnis: {copyright_info.get('verdict') or '—'}",
                f"Risiko-Level: {copyright_info.get('risk_level') or '—'}",
                f"Fingerprint-Länge: {copyright_info.get('fingerprint_len') if copyright_info.get('fingerprint_len') is not None else '—'}",
                f"DB-Abfrage: {'ja' if copyright_info.get('db_lookup_performed') else 'nein'}",
                "Treffer:",
                *(score_lines(copyright_matches, 5) or ["- keine"]),
                f"Hinweis: {copyright_info.get('user_explanation') or copyright_info.get('error') or 'Kein Treffer ist keine Rechtsfreigabe.'}",
            ]),
        },
        {
            "title": "Genre & Stimmung",
            "text": "\n".join([
                f"Genre Modell: {(model_analysis.get('genre') or {}).get('model') if isinstance(model_analysis.get('genre'), dict) else '—'}",
                f"Genre lokal: {(genre.get('top') or {}).get('label') or '—'} ({(genre.get('top') or {}).get('score') if isinstance(genre.get('top'), dict) else '—'})",
                f"Genre Methode: {genre.get('method') or '—'}",
                "Genre Scores:",
                *(score_lines(model_genre_scores or genre.get('scores'), 5) or ["- keine"]),
                "Stimmung Modell: lokale Feature-Heuristik",
                f"Stimmung lokal: {(mood.get('top') or {}).get('label') or '—'} ({(mood.get('top') or {}).get('score') if isinstance(mood.get('top'), dict) else '—'})",
                "Mood Scores:",
                *(score_lines(mood.get('scores'), 5) or ["- keine"]),
            ]),
        },
        {
            "title": "Vocals / Rap / Instrumente",
            "text": "\n".join([
                f"Vocal Modell: {(model_analysis.get('vocals') or {}).get('model') if isinstance(model_analysis.get('vocals'), dict) else '—'}",
                f"Lokal dominant: {vocals.get('dominant') or '—'}",
                f"Speech Score: {vocals.get('speech_score') if vocals.get('speech_score') is not None else '—'}",
                f"Singing Score: {vocals.get('singing_score') if vocals.get('singing_score') is not None else '—'}",
                f"Instrumental Score: {vocals.get('instrumental_score') if vocals.get('instrumental_score') is not None else '—'}",
                f"AST Buckets: {json.dumps(model_vocal_buckets, ensure_ascii=False) if model_vocal_buckets else '—'}",
                "Instrument-Kandidaten:",
                *(score_lines(model_instruments or instruments.get('candidates'), 8) or ["- keine"]),
                f"Hinweis: {(model_analysis.get('instruments') or {}).get('note') if isinstance(model_analysis.get('instruments'), dict) else instruments.get('note') or '—'}",
            ]),
        },
        {
            "title": "Echtheit / KI-Indiz",
            "text": "\n".join([
                f"Modell: {(model_analysis.get('authenticity') or {}).get('model') if isinstance(model_analysis.get('authenticity'), dict) else '—'}",
                f"Lokal: {authenticity.get('verdict') or 'nicht geprüft'}",
                f"Methode: {authenticity.get('method') or '—'}",
                "Deepfake/Synthetic Scores:",
                *(score_lines(model_deepfake_scores, 5) or ["- keine Modellwerte"]),
                f"Hinweis: {authenticity.get('reason') or 'Deepfake/Synthetic Detection ist ein Indiz, kein Beweis.'}",
            ]),
        },
        {
            "title": "Tempo & Beatgrid",
            "text": "\n".join([
                f"Tempoanalyse: {'verfügbar' if tempo.get('available') else 'nicht verfügbar'}",
                f"BPM: {tempo.get('bpm') or '—'}",
                f"Beats: {tempo.get('beat_count') or 0}",
                f"Konfidenz: {tempo.get('confidence') if tempo.get('confidence') is not None else '—'}",
                f"Hinweis: {tempo.get('analysis_hint') or tempo.get('reason') or '—'}",
            ]),
        },
        {
            "title": "Signal & Lautheit",
            "text": "\n".join([
                f"RMS Mittel: {signal.get('rms_mean') if signal.get('rms_mean') is not None else '—'}",
                f"RMS Median: {signal.get('rms_median') if signal.get('rms_median') is not None else '—'}",
                f"Quiet Ratio: {signal.get('quiet_ratio') if signal.get('quiet_ratio') is not None else '—'}",
                f"Spektral-Features: {json.dumps(content.get('features') or {}, ensure_ascii=False)}",
            ]),
        },
        {
            "title": "Datei & Speicherung",
            "text": "\n".join([
                f"Datei: {file_info.get('filename') or '—'}",
                f"Typ: {file_info.get('content_type') or '—'}",
                f"Größe: {file_info.get('size_bytes') or '—'} Bytes",
                f"Speicher: {overview.get('local_models_note') or '—'}",
            ]),
        },
    ]
    return blocks


async def _build_ai_report(report: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    runtime_settings = report.get("runtime_settings") if isinstance(report.get("runtime_settings"), dict) else {}
    provider = str(runtime_settings.get("ai_provider") or settings.ai_default_provider)
    model = str(runtime_settings.get("ai_model") or settings.ai_default_model)
    if not runtime_settings.get("ai_summary_enabled", settings.audio_ai_analysis_ai_summary_enabled) or not settings.ai_provider_has_key(provider):
        return {"provider": "deterministic", "model": "local-template", "blocks": _default_report_blocks(report)}

    compact = {
        "overview": report.get("overview"),
        "file": {key: report.get("file", {}).get(key) for key in ("filename", "content_type", "size_bytes", "duration_seconds")},
        "tempo_analysis": {key: report.get("tempo_analysis", {}).get(key) for key in ("available", "bpm", "beat_count", "confidence", "analysis_hint", "reason")},
        "signal_analysis": {key: report.get("signal_analysis", {}).get(key) for key in ("available", "rms_mean", "rms_median", "quiet_ratio", "estimated_loudness", "dynamic_hint", "reason")},
        "copyright_analysis": report.get("copyright_analysis"),
        "content_analysis": report.get("content_analysis"),
        "model_analysis": report.get("model_analysis"),
    }
    try:
        result = await AiChatService().run_json_task(
            provider=provider,
            model=model,
            system_prompt=(
                "Du bereitest lokale Audioanalyse-Daten fuer Songstudio-Nutzer auf. "
                "Keine erfundenen Modell-Ergebnisse. Nutze Copyright, Genre, Mood, Vocals, Instrumente, Tempo, Signal und interne Modellanalyse, wenn vorhanden. "
                "Wenn ein Bereich nur heuristisch oder nicht per Modell bestimmt wurde, markiere ihn klar als Heuristik bzw. nicht geprueft. "
                "Liefere JSON mit blocks: Array aus {title,text}. Erzeuge mindestens diese Blocktitel: Übersicht, Copyright, Genre & Stimmung, Vocals & Instrumente, Echtheit / KI-Indiz, Tempo, Signal."
            ),
            instruction_payload={"task": "audio_analysis_report", "data": compact},
            profile_options={"temperature": 0.2, "max_output_tokens": 2600},
        )
        blocks = result.data.get("blocks") if isinstance(result.data, dict) else None
        if not isinstance(blocks, list) or not blocks:
            blocks = _default_report_blocks(report)
        normalized_blocks = []
        for item in blocks[:8]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "Abschnitt").strip()
            text = str(item.get("text") or "").strip()
            if title and text:
                normalized_blocks.append({"title": title[:80], "text": text})
        return {
            "provider": provider,
            "model": model,
            "blocks": normalized_blocks or _default_report_blocks(report),
            "raw_response": result.raw_response,
        }
    except (AiProviderError, Exception) as exc:
        return {
            "provider": "deterministic",
            "model": "local-template",
            "error": f"KI-Report nicht verfügbar: {exc.__class__.__name__}: {exc}",
            "blocks": _default_report_blocks(report),
        }


def _render_markdown(report: dict[str, Any]) -> str:
    blocks = report.get("ai_report", {}).get("blocks") if isinstance(report.get("ai_report"), dict) else None
    if not isinstance(blocks, list):
        blocks = _default_report_blocks(report)
    title = report.get("overview", {}).get("title") if isinstance(report.get("overview"), dict) else "Audioanalyse"
    lines = [f"# Audioanalyse: {title}", "", f"Erstellt: {report.get('generated_at') or '—'}", ""]
    for block in blocks:
        if not isinstance(block, dict):
            continue
        lines.extend([f"## {block.get('title') or 'Abschnitt'}", "", str(block.get("text") or "").strip(), ""])
    return "\n".join(lines).strip() + "\n"


def _method_label(value: Any) -> str:
    text = str(value or "").strip()
    labels = {
        "local_audio_feature_heuristic": "Lokale Audio-Heuristik",
        "transformers_audio_classification": "Internes Audio-Modell",
        "transformers_ast_audioset": "AST / AudioSet Modell",
        "acoustid_chromaprint": "AcoustID / Chromaprint",
        "internal_models": "Interne Modelle",
        "ai_report": "KI-Bericht",
    }
    return labels.get(text, text or "nicht bestimmt")


def _top_label(section: Any) -> str:
    if not isinstance(section, dict):
        return "—"
    top = section.get("top") if isinstance(section.get("top"), dict) else None
    if top and top.get("label"):
        score = top.get("score")
        return f"{top.get('label')}{f' · {score}' if score is not None else ''}"
    return str(section.get("verdict") or section.get("dominant") or "—")


def _copyright_summary(copyright: Any) -> dict[str, str]:
    copyright = copyright if isinstance(copyright, dict) else {}
    matches = copyright.get("db_matches") if isinstance(copyright.get("db_matches"), list) else []
    if matches:
        first = matches[0] if isinstance(matches[0], dict) else {}
        detail = f"{first.get('title') or 'Unbekannter Titel'}"
        if first.get("artist"):
            detail += f" - {first.get('artist')}"
        if first.get("score") is not None:
            detail += f" ({first.get('score')})"
        return {"label": "Copyright", "value": "Datenbanktreffer", "detail": detail, "tone": "danger"}
    if copyright.get("ok") and copyright.get("db_lookup_performed"):
        return {
            "label": "Copyright",
            "value": "Kein AcoustID-Treffer",
            "detail": "Fingerprint geprüft. Das ist ein Hinweis, aber keine Rechtsfreigabe.",
            "tone": "success",
        }
    if copyright.get("ok"):
        return {
            "label": "Copyright",
            "value": "Fingerprint erstellt",
            "detail": "Keine AcoustID-Abfrage konfiguriert. API-Key im Adminbereich hinterlegen.",
            "tone": "warning",
        }
    return {
        "label": "Copyright",
        "value": "Nicht belastbar",
        "detail": str(copyright.get("error") or copyright.get("verdict") or "Copyright-Prüfung nicht abgeschlossen."),
        "tone": "warning",
    }


def _summary_cards(report: dict[str, Any]) -> list[dict[str, str]]:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    content = report.get("content_analysis") if isinstance(report.get("content_analysis"), dict) else {}
    genre = content.get("genre") if isinstance(content.get("genre"), dict) else {}
    mood = content.get("mood") if isinstance(content.get("mood"), dict) else {}
    vocals = content.get("vocals") if isinstance(content.get("vocals"), dict) else {}
    authenticity = content.get("authenticity") if isinstance(content.get("authenticity"), dict) else {}
    cards = [_copyright_summary(report.get("copyright_analysis"))]
    cards.extend([
        {"label": "Genre", "value": _top_label(genre), "detail": _method_label(genre.get("method")), "tone": "success" if genre.get("ok") else "warning"},
        {"label": "Stimmung", "value": _top_label(mood), "detail": _method_label(mood.get("method")), "tone": "success" if mood.get("ok") else "neutral"},
        {"label": "Vocals", "value": _top_label(vocals), "detail": _method_label(vocals.get("method")), "tone": "success" if vocals.get("ok") else "neutral"},
        {"label": "KI-Indiz", "value": str(authenticity.get("verdict") or "nicht geprüft"), "detail": str(authenticity.get("model") or _method_label(authenticity.get("method"))), "tone": "warning" if "unknown" in str(authenticity.get("verdict") or "").lower() else "neutral"},
        {"label": "Tempo", "value": f"{summary.get('bpm')} BPM" if summary.get("bpm") else "—", "detail": f"Sicherheit {summary.get('tempo_confidence')}" if summary.get("tempo_confidence") is not None else "—", "tone": "success"},
    ])
    return cards


def _report_blocks(report: dict[str, Any]) -> list[dict[str, str]]:
    blocks = report.get("ai_report", {}).get("blocks") if isinstance(report.get("ai_report"), dict) else None
    if not isinstance(blocks, list) or not blocks:
        blocks = _default_report_blocks(report)
    normalized: list[dict[str, str]] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        title = str(block.get("title") or "Abschnitt").strip()
        text = str(block.get("text") or "").strip()
        if title and text:
            normalized.append({"title": title, "text": text})
    return normalized


def _block_tone(title: Any) -> str:
    text = str(title or "").lower()
    if "copyright" in text or "recht" in text:
        return "copyright"
    if "vocal" in text or "gesang" in text:
        return "vocals"
    if "genre" in text or "stimmung" in text or "mood" in text:
        return "mood"
    if "tempo" in text or "beat" in text:
        return "tempo"
    if "signal" in text or "lautheit" in text:
        return "signal"
    return "default"


def _resolve_cover_file(asset: AudioAsset) -> Path | None:
    settings = get_settings()
    metadata = asset.metadata_json if isinstance(asset.metadata_json, dict) else {}
    cover_cache = metadata.get("cover_cache") if isinstance(metadata.get("cover_cache"), dict) else {}
    candidates = [
        cover_cache.get("local_path"),
        cover_cache.get("public_url"),
        asset.cover_local_url,
        asset.image_url,
    ]
    for candidate in candidates:
        path = resolve_portable_path(candidate, [settings.cover_storage_path])
        if path and path.exists() and path.is_file():
            return path
        text = str(candidate or "")
        route = settings.suno_cover_public_route.rstrip("/") + "/"
        if text.startswith(route):
            local = settings.cover_storage_path / text[len(route):]
            if local.exists() and local.is_file():
                return local
    return None


def _cover_data_uri(asset: AudioAsset) -> str | None:
    path = _resolve_cover_file(asset)
    if not path:
        return None
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if not raw:
        return None
    content_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    return f"data:{content_type};base64,{base64.b64encode(raw).decode('ascii')}"


def _html_paragraphs(text: Any) -> str:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    parts = []
    for line in lines:
        clean = line.lstrip("-• ").strip()
        cls = " class=\"bullet-line\"" if line.startswith(("-", "•")) else ""
        parts.append(f"<p{cls}>{html_lib.escape(clean)}</p>")
    return "\n".join(parts)


def _render_html(report: dict[str, Any], asset: AudioAsset) -> str:
    overview = report.get("overview") if isinstance(report.get("overview"), dict) else {}
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    file_info = report.get("file") if isinstance(report.get("file"), dict) else {}
    title = str(overview.get("title") or _asset_title(asset))
    blocks = _report_blocks(report)
    lead = " ".join(str(blocks[0].get("text") or "").splitlines()[:3]) if blocks else "Analyse lokal gespeichert."
    cards = _summary_cards(report)
    cover_uri = _cover_data_uri(asset)

    def esc(value: Any) -> str:
        return html_lib.escape(str(value if value is not None else "—"))

    card_html = "\n".join(
        f"<article class=\"summary-card tone-{esc(card.get('tone'))}\"><span>{esc(card.get('label'))}</span><strong>{esc(card.get('value'))}</strong><small>{esc(card.get('detail'))}</small></article>"
        for card in cards
    )
    block_html = "\n".join(
        f"<article class=\"report-block tone-{esc(_block_tone(block.get('title')))}\"><h2>{esc(block.get('title'))}</h2><div class=\"block-text\">{_html_paragraphs(block.get('text'))}</div></article>"
        for block in blocks
    )
    cover_html = f"<img src=\"{cover_uri}\" alt=\"Cover\">" if cover_uri else "<div class=\"cover-placeholder\">Cover</div>"

    return f"""<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Audioanalyse: {esc(title)}</title>
<style>
:root {{
  color-scheme: dark;
  --bg: #0f172a;
  --panel: #182235;
  --panel-soft: #1d2a3f;
  --line: #334155;
  --text: #e5e7eb;
  --muted: #94a3b8;
  --blue: #38bdf8;
  --green: #22c55e;
  --amber: #f59e0b;
  --red: #ef4444;
  --violet: #8b5cf6;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  padding: 32px;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  color: var(--text);
  background: linear-gradient(135deg, #0f172a, #111827 55%, #102033);
}}
.page {{ max-width: 1180px; margin: 0 auto; display: grid; gap: 14px; }}
.hero {{
  display: grid;
  grid-template-columns: minmax(170px, 220px) minmax(0, 1fr);
  gap: 16px;
  align-items: stretch;
  padding: 14px;
  border: 1px solid color-mix(in srgb, var(--line) 72%, var(--blue) 28%);
  border-radius: 8px;
  background: linear-gradient(135deg, color-mix(in srgb, var(--panel) 93%, var(--blue) 7%), color-mix(in srgb, var(--panel) 96%, var(--green) 4%));
}}
.cover {{
  min-height: 170px;
  display: grid;
  place-items: center;
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--line) 72%, var(--blue) 28%);
  border-radius: 8px;
  background: color-mix(in srgb, var(--panel) 94%, #020617 6%);
}}
.cover img {{ width: 100%; height: auto; max-height: 220px; object-fit: contain; display: block; }}
.cover-placeholder {{ color: var(--muted); }}
.eyebrow {{ margin: 0; color: var(--blue); text-transform: uppercase; font-size: 12px; }}
h1 {{ margin: 0; font-size: clamp(28px, 4vw, 44px); line-height: 1.1; }}
.headline {{ min-width: 0; display: grid; align-content: start; gap: 8px; }}
.meta-row {{ display: flex; flex-wrap: wrap; gap: 7px; color: var(--muted); font-size: 14px; }}
.meta-row span {{ padding: 5px 8px; border: 1px solid var(--line); border-radius: 999px; background: color-mix(in srgb, var(--panel) 92%, #94a3b8 8%); }}
.lead-card {{ display: grid; gap: 5px; padding: 11px 12px; border: 1px solid color-mix(in srgb, var(--line) 70%, var(--green) 30%); border-radius: 8px; background: color-mix(in srgb, var(--panel) 91%, var(--green) 9%); }}
.lead-card span, .summary-card span {{ color: var(--muted); font-size: 12px; text-transform: uppercase; }}
.lead-card p {{ margin: 0; line-height: 1.45; }}
.summary-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(185px, 1fr)); gap: 10px; }}
.summary-card {{ position: relative; display: grid; gap: 5px; min-height: 112px; padding: 14px 14px 13px; border: 1px solid var(--line); border-radius: 8px; background: color-mix(in srgb, var(--panel) 96%, #94a3b8 4%); overflow: hidden; }}
.summary-card::before {{ content: ""; position: absolute; inset: 0 auto 0 0; width: 4px; background: var(--blue); }}
.summary-card strong {{ font-size: 16px; line-height: 1.25; }}
.summary-card small {{ color: var(--muted); line-height: 1.35; }}
.tone-success {{ border-color: color-mix(in srgb, var(--green) 42%, var(--line) 58%); background: color-mix(in srgb, var(--panel) 93%, var(--green) 7%); }}
.tone-success::before {{ background: var(--green); }}
.tone-warning, .tone-copyright {{ border-color: color-mix(in srgb, var(--amber) 42%, var(--line) 58%); background: color-mix(in srgb, var(--panel) 90%, var(--amber) 10%); }}
.tone-warning::before, .tone-copyright::before {{ background: var(--amber); }}
.tone-danger {{ border-color: color-mix(in srgb, var(--red) 48%, var(--line) 52%); background: color-mix(in srgb, var(--panel) 91%, var(--red) 9%); }}
.tone-danger::before {{ background: var(--red); }}
.tone-vocals {{ border-color: color-mix(in srgb, var(--violet) 34%, var(--line) 66%); background: color-mix(in srgb, var(--panel) 90%, var(--violet) 10%); }}
.tone-vocals::before {{ background: var(--violet); }}
.tone-mood {{ border-color: color-mix(in srgb, var(--green) 34%, var(--line) 66%); background: color-mix(in srgb, var(--panel) 91%, var(--green) 9%); }}
.tone-mood::before {{ background: var(--green); }}
.tone-tempo {{ border-color: color-mix(in srgb, var(--blue) 34%, var(--line) 66%); background: color-mix(in srgb, var(--panel) 90%, var(--blue) 10%); }}
.tone-tempo::before {{ background: var(--blue); }}
.tone-signal {{ border-color: color-mix(in srgb, #64748b 38%, var(--line) 62%); background: color-mix(in srgb, var(--panel) 90%, #64748b 10%); }}
.tone-signal::before {{ background: #64748b; }}
.report-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 12px; }}
.report-block {{ position: relative; display: grid; align-content: start; gap: 10px; padding: 16px 14px 14px; border: 1px solid var(--line); border-radius: 8px; background: color-mix(in srgb, var(--panel) 91%, var(--blue) 9%); overflow: hidden; }}
.report-block::before {{ content: ""; position: absolute; inset: 0 0 auto; height: 3px; background: var(--blue); }}
.report-block h2 {{ margin: 0; font-size: 18px; }}
.block-text {{ display: grid; gap: 7px; }}
.block-text p {{ margin: 0; line-height: 1.48; }}
.bullet-line {{ padding: 7px 9px; border: 1px solid color-mix(in srgb, var(--line) 80%, #94a3b8 20%); border-radius: 8px; background: color-mix(in srgb, var(--panel) 92%, #94a3b8 8%); }}
.footer {{ color: var(--muted); font-size: 12px; text-align: center; }}
@media print {{
  body {{ background: #ffffff; color: #111827; padding: 18px; }}
  .page {{ max-width: none; }}
  .hero, .summary-card, .report-block, .lead-card {{ break-inside: avoid; }}
}}
</style>
</head>
<body>
<main class="page">
  <section class="hero">
    <div class="cover">{cover_html}</div>
    <div class="headline">
      <p class="eyebrow">Lokaler Analysebericht</p>
      <h1>{esc(title)}</h1>
      <div class="meta-row">
        <span>Asset #{esc(asset.id)}</span>
        <span>{esc(summary.get('duration_label') or overview.get('duration_label') or file_info.get('duration_seconds'))}</span>
        <span>{esc(report.get('generated_at'))}</span>
        <span>App-interne Analyse</span>
      </div>
      <div class="lead-card"><span>Einschätzung</span><p>{esc(lead)}</p></div>
    </div>
  </section>
  <section class="summary-grid">{card_html}</section>
  <section class="report-grid">{block_html}</section>
  <p class="footer">Export aus Songstudio · lokal gespeicherte Audioanalyse · {esc(report.get('generated_at'))}</p>
</main>
</body>
</html>
"""


def _pdf_escape(value: Any) -> str:
    text = str(value if value is not None else "—")
    data = text.encode("cp1252", "replace")
    parts: list[str] = []
    for byte in data:
        if byte in (40, 41, 92):
            parts.append("\\" + chr(byte))
        elif 32 <= byte <= 126:
            parts.append(chr(byte))
        else:
            parts.append(f"\\{byte:03o}")
    return "".join(parts)


def _pdf_cover_image(asset: AudioAsset) -> dict[str, Any] | None:
    path = _resolve_cover_file(asset)
    if not path:
        return None
    try:
        from PIL import Image  # type: ignore
    except Exception:
        return None
    try:
        with Image.open(path) as image:
            image = image.convert("RGB")
            image.thumbnail((420, 420))
            buffer = BytesIO()
            image.save(buffer, format="JPEG", quality=88, optimize=True)
            return {"width": image.width, "height": image.height, "data": buffer.getvalue()}
    except Exception:
        return None


def _pdf_wrap(text: Any, max_chars: int) -> list[str]:
    words = str(text if text is not None else "—").replace("\n", " ").split()
    lines: list[str] = []
    current = ""
    for word in words:
        if len(current) + len(word) + 1 > max_chars and current:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines or ["—"]


def _render_pdf(report: dict[str, Any], asset: AudioAsset) -> bytes:
    width, height = 595, 842
    margin = 36
    y = height - margin
    pages: list[list[str]] = []
    commands: list[str] = []
    cover_image = _pdf_cover_image(asset)

    def color(hex_value: str) -> tuple[float, float, float]:
        value = hex_value.lstrip("#")
        return int(value[0:2], 16) / 255, int(value[2:4], 16) / 255, int(value[4:6], 16) / 255

    def set_fill(hex_value: str) -> None:
        r, g, b = color(hex_value)
        commands.append(f"{r:.3f} {g:.3f} {b:.3f} rg")

    def set_stroke(hex_value: str) -> None:
        r, g, b = color(hex_value)
        commands.append(f"{r:.3f} {g:.3f} {b:.3f} RG")

    def rect(x: float, top: float, w: float, h: float, fill: str, stroke: str | None = None) -> None:
        set_fill(fill)
        if stroke:
            set_stroke(stroke)
            commands.append(f"{x:.1f} {top - h:.1f} {w:.1f} {h:.1f} re B")
        else:
            commands.append(f"{x:.1f} {top - h:.1f} {w:.1f} {h:.1f} re f")

    def text(x: float, top: float, value: Any, size: int = 10, fill: str = "#e5e7eb", font: str = "F1") -> None:
        set_fill(fill)
        commands.append(f"BT /{font} {size} Tf {x:.1f} {top:.1f} Td ({_pdf_escape(value)}) Tj ET")

    def image(name: str, x: float, top: float, box_w: float, box_h: float, image_w: int, image_h: int) -> None:
        scale = min(box_w / max(1, image_w), box_h / max(1, image_h))
        draw_w = image_w * scale
        draw_h = image_h * scale
        draw_x = x + (box_w - draw_w) / 2
        draw_y = top - box_h + (box_h - draw_h) / 2
        commands.append(f"q {draw_w:.1f} 0 0 {draw_h:.1f} {draw_x:.1f} {draw_y:.1f} cm /{name} Do Q")

    def new_page() -> None:
        nonlocal commands, y
        if commands:
            pages.append(commands)
        commands = []
        rect(0, height, width, height, "#0f172a")
        y = height - margin

    def ensure(space: float) -> None:
        if y - space < margin:
            new_page()

    new_page()
    overview = report.get("overview") if isinstance(report.get("overview"), dict) else {}
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    title = str(overview.get("title") or _asset_title(asset))
    blocks = _report_blocks(report)
    cards = _summary_cards(report)

    rect(margin, y, width - margin * 2, 130, "#182235", "#334155")
    rect(margin + 12, y - 14, 96, 96, "#111827", "#38bdf8")
    if cover_image:
        image("ImCover", margin + 12, y - 14, 96, 96, int(cover_image["width"]), int(cover_image["height"]))
    else:
        text(margin + 34, y - 68, "Cover", 14, "#94a3b8", "F2")
    text(margin + 126, y - 26, "Lokaler Analysebericht", 9, "#38bdf8", "F2")
    for index, line in enumerate(_pdf_wrap(title, 46)[:2]):
        text(margin + 126, y - 48 - index * 18, line, 16, "#ffffff", "F2")
    meta = f"Asset #{asset.id} · {summary.get('duration_label') or 'Dauer unbekannt'} · {report.get('generated_at') or '—'}"
    text(margin + 126, y - 92, meta, 9, "#94a3b8")
    y -= 148

    card_w = (width - margin * 2 - 20) / 3
    for index, card in enumerate(cards[:6]):
        col = index % 3
        if col == 0:
            ensure(82)
            row_top = y
        x = margin + col * (card_w + 10)
        tone = card.get("tone")
        fill = {"success": "#173525", "warning": "#3b2a12", "danger": "#3b1717"}.get(str(tone), "#1d2a3f")
        accent = {"success": "#22c55e", "warning": "#f59e0b", "danger": "#ef4444"}.get(str(tone), "#38bdf8")
        rect(x, row_top, card_w, 70, fill, "#334155")
        rect(x, row_top, 4, 70, accent)
        text(x + 10, row_top - 16, card.get("label"), 8, "#94a3b8", "F2")
        text(x + 10, row_top - 34, card.get("value"), 11, "#ffffff", "F2")
        text(x + 10, row_top - 52, _pdf_wrap(card.get("detail"), 28)[0], 8, "#94a3b8")
        if col == 2:
            y -= 82
    if len(cards) % 3:
        y -= 82

    for block in blocks:
        lines = []
        for raw_line in str(block.get("text") or "").splitlines():
            clean = raw_line.strip().lstrip("-• ").strip()
            if clean:
                lines.extend(_pdf_wrap(clean, 78))
        lines = lines or ["—"]
        block_h = 44 + min(len(lines), 10) * 13
        ensure(block_h + 12)
        tone = _block_tone(block.get("title"))
        fill = {"copyright": "#3b2a12", "vocals": "#2b2142", "mood": "#173525", "tempo": "#123040", "signal": "#202938"}.get(tone, "#1d2a3f")
        accent = {"copyright": "#f59e0b", "vocals": "#8b5cf6", "mood": "#22c55e", "tempo": "#38bdf8", "signal": "#64748b"}.get(tone, "#38bdf8")
        rect(margin, y, width - margin * 2, block_h, fill, "#334155")
        rect(margin, y, width - margin * 2, 4, accent)
        text(margin + 12, y - 22, block.get("title"), 13, "#ffffff", "F2")
        line_y = y - 42
        for line in lines[:10]:
            text(margin + 12, line_y, line, 9, "#e5e7eb")
            line_y -= 13
        y -= block_h + 12

    text(margin, margin - 10, "Export aus Songstudio · lokal gespeicherte Audioanalyse", 8, "#94a3b8")
    pages.append(commands)

    objects: list[bytes] = []

    def add_object(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    font_regular = add_object(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    font_bold = add_object(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    image_id = None
    if cover_image:
        image_data = cover_image["data"]
        image_id = add_object(
            b"<< /Type /XObject /Subtype /Image /Width "
            + str(int(cover_image["width"])).encode("ascii")
            + b" /Height "
            + str(int(cover_image["height"])).encode("ascii")
            + b" /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length "
            + str(len(image_data)).encode("ascii")
            + b" >>\nstream\n"
            + image_data
            + b"\nendstream"
        )
    page_ids: list[int] = []
    content_ids: list[int] = []
    for page_commands in pages:
        stream = "\n".join(page_commands).encode("latin-1", "replace")
        content_ids.append(add_object(b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream"))
        page_ids.append(0)
    pages_id = len(objects) + len(page_ids) + 1
    for index, content_id in enumerate(content_ids):
        xobject = f" /XObject << /ImCover {image_id} 0 R >>" if image_id else ""
        page_ids[index] = add_object(
            f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {width} {height}] /Resources << /Font << /F1 {font_regular} 0 R /F2 {font_bold} 0 R >>{xobject} >> /Contents {content_id} 0 R >>".encode("ascii")
        )
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    add_object(f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode("ascii"))
    catalog_id = add_object(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode("ascii"))

    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode("ascii"))
        output.extend(body)
        output.extend(b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii"))
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii"))
    return bytes(output)


def _render_beatgrid_csv(beatgrid: list[dict[str, Any]]) -> str:
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=["index", "time"])
    writer.writeheader()
    for item in beatgrid:
        writer.writerow({"index": item.get("index"), "time": item.get("time")})
    return buffer.getvalue()


def _write_report_files(asset: AudioAsset, report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    target_dir = _analysis_dir(asset.id)
    safe_title = _safe_filename_part(_asset_title(asset), f"audio_{asset.id}")
    json_path = target_dir / f"{safe_title}_audio_ai_analysis.json"
    md_path = target_dir / f"{safe_title}_audio_ai_analysis.md"
    html_path = target_dir / f"{safe_title}_audio_ai_analysis.html"
    pdf_path = target_dir / f"{safe_title}_audio_ai_analysis.pdf"
    csv_path = target_dir / f"{safe_title}_beatgrid.csv"

    markdown_text = _render_markdown(report)
    html_text = _render_html(report, asset)
    pdf_bytes = _render_pdf(report, asset)
    beatgrid = report.get("tempo_analysis", {}).get("beatgrid") if isinstance(report.get("tempo_analysis"), dict) else []
    beatgrid_text = _render_beatgrid_csv(beatgrid if isinstance(beatgrid, list) else [])

    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    md_path.write_text(markdown_text, encoding="utf-8")
    html_path.write_text(html_text, encoding="utf-8")
    pdf_path.write_bytes(pdf_bytes)
    csv_path.write_text(beatgrid_text, encoding="utf-8")

    settings = get_settings()
    exports = {
        "json": {"path": to_portable_path(json_path, storage_root=settings.audio_ai_analysis_storage_path), "filename": json_path.name, "content_type": "application/json"},
        "markdown": {"path": to_portable_path(md_path, storage_root=settings.audio_ai_analysis_storage_path), "filename": md_path.name, "content_type": "text/markdown"},
        "html": {"path": to_portable_path(html_path, storage_root=settings.audio_ai_analysis_storage_path), "filename": html_path.name, "content_type": "text/html"},
        "pdf": {"path": to_portable_path(pdf_path, storage_root=settings.audio_ai_analysis_storage_path), "filename": pdf_path.name, "content_type": "application/pdf"},
        "beatgrid_csv": {"path": to_portable_path(csv_path, storage_root=settings.audio_ai_analysis_storage_path), "filename": csv_path.name, "content_type": "text/csv"},
    }
    return exports


def _run_async(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    raise RuntimeError("Audioanalyse-KI-Report kann nicht in einem bereits laufenden Event-Loop synchron ausgeführt werden.")


def run_audio_ai_analysis(db: Session, audio_asset_id: int, *, options: AudioAiAnalysisOptions | None = None, task: SunoTask | None = None) -> dict[str, Any]:
    options = options or AudioAiAnalysisOptions()
    start = time.monotonic()
    runtime_settings = load_audio_ai_analysis_admin_settings(db)
    if not runtime_settings.get("enabled", True):
        raise RuntimeError("Audioanalyse ist im Admin-Panel deaktiviert.")
    asset = db.query(AudioAsset).filter(AudioAsset.id == int(audio_asset_id), AudioAsset.is_deleted.is_(False)).first()
    if not asset:
        raise ValueError("AudioAsset wurde nicht gefunden.")
    if task and is_cancel_requested(db, task.id):
        raise RuntimeError("Audioanalyse wurde vor dem Start abgebrochen.")

    heartbeat_task(db, task, progress={"current": 1, "total": 7, "phase": "audio_resolving", "audio_asset_id": asset.id})
    audio_path = resolve_audio_asset_file(asset)
    if not audio_path:
        raise ValueError("Keine lokale Audiodatei für die Analyse gefunden.")

    file_info = _probe_file(audio_path, asset)
    heartbeat_task(db, task, progress={"current": 2, "total": 7, "phase": "audio_loading", "audio_asset_id": asset.id, "path": str(audio_path)})

    y, sr, load_info = _load_audio_for_analysis(audio_path, int(runtime_settings.get("analysis_max_seconds") or get_settings().audio_ai_analysis_max_seconds))
    if y is not None and sr > 0:
        heartbeat_task(db, task, progress={"current": 3, "total": 7, "phase": "signal_analysis", "audio_asset_id": asset.id})
        signal = _compute_signal_analysis(y, sr)
        tempo = _compute_tempo_analysis(y, sr)
        content_analysis = _compute_local_content_insights(y, sr, signal, tempo)
    else:
        signal = {"available": False, "reason": load_info.get("reason") or "Audio konnte nicht geladen werden."}
        tempo = {"available": False, "reason": load_info.get("reason") or "Audio konnte nicht geladen werden.", "beatgrid": []}
        content_analysis = {
            "genre": {"ok": False, "reason": load_info.get("reason") or "Audio konnte nicht geladen werden."},
            "mood": {"ok": False, "reason": load_info.get("reason") or "Audio konnte nicht geladen werden."},
            "vocals": {"ok": False, "reason": load_info.get("reason") or "Audio konnte nicht geladen werden."},
            "instruments": {"ok": False, "reason": load_info.get("reason") or "Audio konnte nicht geladen werden.", "candidates": []},
            "authenticity": {"ok": False, "reason": load_info.get("reason") or "Audio konnte nicht geladen werden."},
        }

    heartbeat_task(db, task, progress={"current": 4, "total": 7, "phase": "copyright_analysis", "audio_asset_id": asset.id})
    copyright_analysis = _analyze_copyright_acoustid(audio_path, runtime_settings.get("acoustid_api_key"))

    heartbeat_task(db, task, progress={"current": 5, "total": 7, "phase": "model_analysis", "audio_asset_id": asset.id})
    model_analysis = _run_internal_model_analysis(audio_path, y, sr, _analysis_dir(asset.id), content_analysis, runtime_settings) if y is not None and sr > 0 else {"ok": False, "enabled": False, "reason": "Audiodaten nicht geladen."}
    for key in ("genre", "vocals", "instruments", "authenticity"):
        if isinstance(model_analysis.get(key), dict) and model_analysis[key].get("ok"):
            content_analysis[key] = model_analysis[key]

    overview = _derive_overview(asset, file_info, signal, tempo)
    report: dict[str, Any] = {
        "schema_version": 1,
        "audio_asset_id": asset.id,
        "song_id": asset.song_id,
        "title": _asset_title(asset),
        "profile": options.profile,
        "generated_at": utc_now_naive().isoformat(),
        "runtime_seconds": None,
        "source": "local_audio_ai_analysis",
        "runtime_settings": {
            "enabled": bool(runtime_settings.get("enabled")),
            "ai_summary_enabled": bool(runtime_settings.get("ai_summary_enabled")),
            "model_analysis_enabled": bool(runtime_settings.get("model_analysis_enabled")),
            "analysis_max_seconds": runtime_settings.get("analysis_max_seconds"),
            "model_analysis_seconds": runtime_settings.get("model_analysis_seconds"),
            "model_analysis_top_k": runtime_settings.get("model_analysis_top_k"),
            "ai_provider": runtime_settings.get("ai_provider"),
            "ai_model": runtime_settings.get("ai_model"),
            "acoustid_configured": bool(runtime_settings.get("acoustid_api_key")),
        },
        "file": file_info,
        "audio_load": load_info,
        "overview": overview,
        "signal_analysis": signal,
        "tempo_analysis": tempo,
        "copyright_analysis": copyright_analysis,
        "content_analysis": content_analysis,
        "model_analysis": model_analysis,
        "optional_models": {
            "transformer_models": "run" if model_analysis.get("enabled") else "disabled",
            "copyright_fingerprint": "run",
            "note": "Alle Analysefunktionen liegen innerhalb der App. Fehlende Modelle oder Keys werden im Report dokumentiert, ohne andere Workflows zu verändern.",
        },
    }

    heartbeat_task(db, task, progress={"current": 6, "total": 7, "phase": "report_building", "audio_asset_id": asset.id})
    if options.include_ai_report:
        try:
            report["ai_report"] = _run_async(_build_ai_report(report))
        except Exception as exc:
            report["ai_report"] = {
                "provider": "deterministic",
                "model": "local-template",
                "error": f"KI-Report nicht verfügbar: {exc.__class__.__name__}: {exc}",
                "blocks": _default_report_blocks(report),
            }
    else:
        report["ai_report"] = {"provider": "deterministic", "model": "local-template", "blocks": _default_report_blocks(report)}

    report["runtime_seconds"] = round(time.monotonic() - start, 3)
    exports = _write_report_files(asset, report)
    report["exports"] = exports
    # JSON mit Exportpfaden erneut schreiben.
    _write_report_files(asset, report)

    metadata = dict(asset.metadata_json) if isinstance(asset.metadata_json, dict) else {}
    metadata[ANALYSIS_METADATA_KEY] = {
        "status": "SUCCESS",
        "audio_asset_id": asset.id,
        "song_id": asset.song_id,
        "title": _asset_title(asset),
        "profile": options.profile,
        "generated_at": report["generated_at"],
        "runtime_seconds": report["runtime_seconds"],
        "summary": overview,
        "ai_report": report.get("ai_report"),
        "signal_analysis": signal,
        "tempo_analysis": {key: value for key, value in tempo.items() if key != "beatgrid"},
        "copyright_analysis": copyright_analysis,
        "content_analysis": content_analysis,
        "model_analysis": model_analysis,
        "exports": report["exports"],
        "task_local_id": task.id if task else None,
    }
    asset.metadata_json = metadata
    db.add(asset)
    if asset.song_id:
        song = db.query(Song).filter(Song.id == asset.song_id, Song.is_deleted.is_(False)).first()
        if song:
            song_meta = dict(song.metadata_json) if isinstance(song.metadata_json, dict) else {}
            song_meta.setdefault("audio_ai_analysis_assets", {})
            if isinstance(song_meta["audio_ai_analysis_assets"], dict):
                song_meta["audio_ai_analysis_assets"][str(asset.id)] = {
                    "generated_at": report["generated_at"],
                    "summary": overview,
                    "task_local_id": task.id if task else None,
                }
            song.metadata_json = song_meta
            db.add(song)
    db.add(ActivityLog(
        action="audio_ai_analysis",
        content_type="audio",
        content_id=asset.id,
        new_value={"status": "SUCCESS", "exports": report["exports"], "summary": overview},
        metadata_json={"task_local_id": task.id if task else None, "profile": options.profile},
    ))
    db.commit()
    db.refresh(asset)

    heartbeat_task(db, task, progress={"current": 7, "total": 7, "phase": "completed", "audio_asset_id": asset.id})
    if task:
        mark_task_finished(
            db,
            task,
            status="SUCCESS",
            message="Audioanalyse wurde erstellt.",
            result_payload={"audio_asset_id": asset.id, "status": "SUCCESS", "analysis": metadata[ANALYSIS_METADATA_KEY]},
            response_payload={"audio_asset_id": asset.id},
            notify=False,
        )
        db.add(StatusNotification(
            event_type="audio_ai_analysis_completed",
            title=f"Audioanalyse fertig: {_asset_title(asset)}",
            message="Der Audioanalyse-Report ist in den Songdetails verfügbar.",
            severity="success",
            status="unread",
            task_local_id=task.id,
            suno_task_id=None,
            content_type="audio",
            content_id=asset.id,
            target_tab="library",
            target_payload={"audio_asset_id": asset.id, "task_local_id": task.id, "task_type": ANALYSIS_TASK_TYPE, "status": "SUCCESS"},
            completed_at=utc_now_naive(),
        ))
        db.commit()
    return metadata[ANALYSIS_METADATA_KEY]


def fail_audio_ai_analysis_task(db: Session, task_id: int, audio_asset_id: int, message: str) -> None:
    task = db.query(SunoTask).filter(SunoTask.id == int(task_id)).first()
    asset = db.query(AudioAsset).filter(AudioAsset.id == int(audio_asset_id)).first()
    if task:
        mark_task_finished(
            db,
            task,
            status="FAILED",
            message=message,
            result_payload={"audio_asset_id": audio_asset_id, "status": "FAILED", "message": message},
            response_payload={"audio_asset_id": audio_asset_id},
            notify=False,
        )
    title = _asset_title(asset) if asset else f"AudioAsset {audio_asset_id}"
    db.add(StatusNotification(
        event_type="audio_ai_analysis_failed",
        title=f"Audioanalyse fehlgeschlagen: {title}",
        message=message,
        severity="error",
        status="unread",
        task_local_id=task.id if task else None,
        suno_task_id=None,
        content_type="audio",
        content_id=audio_asset_id,
        target_tab="status",
        target_payload={"audio_asset_id": audio_asset_id, "task_local_id": task.id if task else None, "task_type": ANALYSIS_TASK_TYPE, "status": "FAILED"},
        completed_at=utc_now_naive(),
    ))
    db.commit()


def resolve_audio_ai_export_path(asset: AudioAsset, kind: str) -> tuple[Path, str, str]:
    analysis = read_saved_audio_ai_analysis(asset)
    exports = analysis.get("exports") if isinstance(analysis, dict) else None
    if not isinstance(exports, dict):
        raise FileNotFoundError("Noch keine Audioanalyse-Exporte vorhanden.")
    normalized = str(kind or "").strip().lower().replace("-", "_")
    aliases = {"md": "markdown", "csv": "beatgrid_csv", "htm": "html"}
    key = aliases.get(normalized, normalized)
    if key in {"html", "pdf"}:
        regenerated = _write_report_files(asset, analysis)
        if isinstance(regenerated, dict):
            exports = {**exports, **regenerated}
    entry = exports.get(key)
    if not isinstance(entry, dict):
        raise FileNotFoundError("Dieser Audioanalyse-Export existiert nicht.")
    settings = get_settings()
    path = resolve_portable_path(entry.get("path") or entry.get("filename"), [settings.audio_ai_analysis_storage_path])
    if not path:
        raise FileNotFoundError("Audioanalyse-Exportdatei wurde nicht gefunden.")
    return path, str(entry.get("filename") or path.name), str(entry.get("content_type") or "application/octet-stream")

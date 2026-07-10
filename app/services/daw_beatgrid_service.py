from __future__ import annotations

import hashlib
import importlib
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import asdict, is_dataclass
from pathlib import Path
from statistics import median
from typing import Any

ANALYSIS_VERSION = "daw_bar_map_allin1_beatthis_madmom_v2"
DEFAULT_ANALYSIS_TIMEOUT = int(os.getenv("DAW_BEATGRID_TIMEOUT_SECONDS", "900") or "900")


class BeatgridAnalyzerError(RuntimeError):
    pass


def _safe_float(value: Any, fallback: float | None = None) -> float | None:
    try:
        if value is None or value == "":
            return fallback
        if isinstance(value, str):
            value = value.strip().replace(",", ".")
        parsed = float(value)
        if math.isfinite(parsed):
            return parsed
    except Exception:
        pass
    return fallback


def _safe_int(value: Any, fallback: int | None = None) -> int | None:
    try:
        if value is None or value == "":
            return fallback
        parsed = int(float(value))
        return parsed
    except Exception:
        return fallback


def _clock(value: float) -> str:
    value = max(0.0, float(value or 0.0))
    minutes = int(value // 60)
    seconds = value - minutes * 60
    return f"{minutes:02d}:{seconds:04.1f}"


def _fingerprint(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": str(path),
        "size": int(stat.st_size),
        "mtime": int(stat.st_mtime),
        "sha1": hashlib.sha1(f"{path}:{stat.st_size}:{int(stat.st_mtime)}:{ANALYSIS_VERSION}".encode("utf-8", "ignore")).hexdigest()[:16],
    }


def _metadata_segments(asset: Any) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    raw_values: list[Any] = []
    if getattr(asset, "structure_segments_json", None):
        raw_values.append(asset.structure_segments_json)
    metadata = getattr(asset, "metadata_json", None) if isinstance(getattr(asset, "metadata_json", None), dict) else {}
    for key in (
        "structure_segments_json",
        "structure_segments",
        "structureSegments",
        "segments",
        "song_structure",
        "songStructure",
    ):
        if key in metadata:
            raw_values.append(metadata.get(key))
    for raw in raw_values:
        if not isinstance(raw, list):
            continue
        for index, item in enumerate(raw[:240]):
            if not isinstance(item, dict):
                continue
            start = _safe_float(item.get("start") or item.get("start_sec") or item.get("from"), None)
            end = _safe_float(item.get("end") or item.get("end_sec") or item.get("to"), None)
            if start is None or end is None or end <= start:
                continue
            label = str(item.get("label") or item.get("name") or item.get("title") or item.get("section") or item.get("type") or f"Abschnitt {index + 1}")
            kind = str(item.get("kind") or item.get("type") or label).strip().lower()
            segments.append({
                "index": index + 1,
                "label": label[:120],
                "kind": _normalize_segment_kind(kind or label),
                "start": float(start),
                "end": float(end),
                "source": "asset_metadata",
            })
    segments.sort(key=lambda item: item["start"])
    return segments


def _normalize_segment_kind(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9äöüß]+", "_", text).strip("_")
    aliases = {
        "refrain": "chorus",
        "hook": "chorus",
        "chorus_hook": "chorus",
        "strophe": "verse",
        "rap_part": "verse",
        "part": "verse",
        "instrumental": "inst",
        "instrumental_break": "inst",
    }
    for key, mapped in aliases.items():
        if key in text:
            return mapped
    for key in ("intro", "verse", "chorus", "bridge", "outro", "solo", "inst", "break", "pre_chorus", "post_chorus"):
        if key in text:
            return key
    return text or "section"


def _decode_analysis_wav(source_path: Path) -> Path:
    """Create a deterministic WAV analysis copy to avoid MP3 decoder offsets."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return source_path
    temp = tempfile.NamedTemporaryFile(prefix="songstudio_daw_analysis_", suffix=".wav", delete=False)
    target = Path(temp.name)
    temp.close()
    cmd = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source_path),
        "-vn",
        "-ac",
        "2",
        "-ar",
        "44100",
        "-c:a",
        "pcm_s16le",
        str(target),
    ]
    try:
        subprocess.run(cmd, text=True, capture_output=True, check=True, timeout=240)
        if target.exists() and target.stat().st_size > 0:
            return target
    except Exception:
        try:
            target.unlink(missing_ok=True)
        except Exception:
            pass
    return source_path


def _audio_duration_seconds(path: Path) -> float:
    try:
        import soundfile as sf  # type: ignore

        info = sf.info(str(path))
        if info.samplerate and info.frames:
            return max(0.0, float(info.frames) / float(info.samplerate))
    except Exception:
        pass
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        try:
            result = subprocess.run(
                [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                text=True,
                capture_output=True,
                check=True,
                timeout=20,
            )
            return max(0.0, float(result.stdout.strip() or 0))
        except Exception:
            pass
    return 0.0


def _to_plain(value: Any, depth: int = 0) -> Any:
    if depth > 8:
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _to_plain(item, depth + 1) for key, item in value.items() if not str(key).startswith("_")}
    if isinstance(value, (list, tuple, set)):
        return [_to_plain(item, depth + 1) for item in value]
    if is_dataclass(value):
        return _to_plain(asdict(value), depth + 1)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return _to_plain(model_dump(), depth + 1)
        except Exception:
            pass
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            return _to_plain(to_dict(), depth + 1)
        except Exception:
            pass
    if hasattr(value, "tolist"):
        try:
            return _to_plain(value.tolist(), depth + 1)
        except Exception:
            pass
    if hasattr(value, "__dict__"):
        try:
            return {key: _to_plain(item, depth + 1) for key, item in vars(value).items() if not key.startswith("_")}
        except Exception:
            pass
    return str(value)


def _read_json_file(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        return json.loads(path.read_text(encoding="latin-1"))


def _find_analysis_files(directory: Path) -> list[Path]:
    candidates: list[Path] = []
    for pattern in ("*.json", "*.analysis.json", "*.allin1.json"):
        candidates.extend(directory.rglob(pattern))
    # Prefer deeper analysis result files, ignore package metadata if present.
    unique = []
    seen = set()
    for item in candidates:
        if item in seen or item.name.lower() in {"package.json"}:
            continue
        seen.add(item)
        unique.append(item)
    return sorted(unique, key=lambda item: item.stat().st_mtime if item.exists() else 0, reverse=True)


def _extract_time_from_item(item: Any) -> float | None:
    if isinstance(item, (int, float, str)):
        return _safe_float(item, None)
    if isinstance(item, dict):
        for key in ("time", "t", "start", "start_time", "timestamp", "seconds", "sec"):
            value = _safe_float(item.get(key), None)
            if value is not None:
                return value
        if len(item) == 1:
            return _safe_float(next(iter(item.values())), None)
    if isinstance(item, (list, tuple)) and item:
        return _safe_float(item[0], None)
    return None


def _extract_time_list(data: Any, keys: tuple[str, ...]) -> list[float]:
    if not isinstance(data, dict):
        return []
    raw = None
    lower_map = {str(key).lower(): key for key in data.keys()}
    for key in keys:
        actual = data.get(key)
        if actual is None:
            actual = data.get(lower_map.get(key.lower(), ""))
        if actual is not None:
            raw = actual
            break
    if raw is None:
        return []
    if isinstance(raw, dict):
        for nested_key in ("times", "time", "beats", "downbeats", "values"):
            if nested_key in raw:
                raw = raw[nested_key]
                break
    if not isinstance(raw, list):
        return []
    times = []
    for item in raw:
        value = _extract_time_from_item(item)
        if value is not None and value >= 0:
            times.append(float(value))
    return _clean_times(times)


def _extract_positions(data: Any, keys: tuple[str, ...], count: int = 0) -> list[int]:
    if not isinstance(data, dict):
        return []
    raw = None
    lower_map = {str(key).lower(): key for key in data.keys()}
    for key in keys:
        actual = data.get(key)
        if actual is None:
            actual = data.get(lower_map.get(key.lower(), ""))
        if actual is not None:
            raw = actual
            break
    if raw is None and isinstance(data.get("beats"), list):
        raw = []
        for item in data.get("beats") or []:
            if isinstance(item, dict):
                raw.append(item.get("position") or item.get("beat_position") or item.get("beat") or item.get("beat_in_bar"))
            elif isinstance(item, (list, tuple)) and len(item) > 1:
                raw.append(item[1])
    if not isinstance(raw, list):
        return []
    positions = []
    for item in raw:
        if isinstance(item, dict):
            item = item.get("position") or item.get("beat_position") or item.get("beat") or item.get("value")
        parsed = _safe_int(item, None)
        if parsed is not None:
            positions.append(parsed)
    if count and len(positions) > count:
        positions = positions[:count]
    return positions


def _extract_bpm(data: Any) -> float | None:
    if not isinstance(data, dict):
        return None
    for key in ("bpm", "tempo", "estimated_bpm", "global_bpm"):
        value = _safe_float(data.get(key), None)
        if value is not None and 20 <= value <= 300:
            return float(value)
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    for key in ("bpm", "tempo"):
        value = _safe_float(metadata.get(key), None)
        if value is not None and 20 <= value <= 300:
            return float(value)
    return None


def _extract_segments(data: Any, duration: float = 0.0, source: str = "analysis") -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    raw = None
    for key in ("segments", "sections", "structure", "functional_segments", "functionalSegments"):
        if isinstance(data.get(key), list):
            raw = data.get(key)
            break
    if raw is None:
        return []
    segments: list[dict[str, Any]] = []
    for index, item in enumerate(raw[:240]):
        label = f"Abschnitt {index + 1}"
        start: float | None = None
        end: float | None = None
        confidence = None
        if isinstance(item, dict):
            label = str(item.get("label") or item.get("name") or item.get("type") or item.get("section") or label)
            start = _safe_float(item.get("start") or item.get("start_time") or item.get("start_sec") or item.get("from"), None)
            end = _safe_float(item.get("end") or item.get("end_time") or item.get("end_sec") or item.get("to"), None)
            confidence = _safe_float(item.get("confidence") or item.get("probability") or item.get("score"), None)
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            start = _safe_float(item[0], None)
            end = _safe_float(item[1], None)
            if len(item) >= 3:
                label = str(item[2])
            if len(item) >= 4:
                confidence = _safe_float(item[3], None)
        if start is None or end is None or end <= start:
            continue
        if duration > 0:
            start = max(0.0, min(duration, start))
            end = max(start + 0.05, min(duration, end))
        segments.append({
            "index": len(segments) + 1,
            "label": label[:120],
            "kind": _normalize_segment_kind(label),
            "start": float(start),
            "end": float(end),
            "confidence": confidence,
            "source": source,
        })
    return sorted(segments, key=lambda item: item["start"])


def _clean_times(values: list[float], duration: float = 0.0, min_gap: float = 0.025) -> list[float]:
    cleaned: list[float] = []
    for raw in sorted(values):
        value = float(raw)
        if not math.isfinite(value) or value < -0.001:
            continue
        if duration > 0 and value > duration + 0.25:
            continue
        value = max(0.0, value)
        if cleaned and abs(cleaned[-1] - value) < min_gap:
            continue
        cleaned.append(value)
    return cleaned


def _parse_analysis_result(data: Any, *, duration: float, source: str) -> dict[str, Any]:
    plain = _to_plain(data)
    if isinstance(plain, list) and len(plain) == 1:
        plain = plain[0]
    if isinstance(plain, list):
        # allin1 may return a list of result objects for batch mode.
        dict_items = [item for item in plain if isinstance(item, dict)]
        if dict_items:
            plain = dict_items[0]
    if not isinstance(plain, dict):
        raise BeatgridAnalyzerError(f"{source}: Analyseergebnis konnte nicht gelesen werden.")

    beats = _extract_time_list(plain, ("beats", "beat_times", "beatTimes"))
    downbeats = _extract_time_list(plain, ("downbeats", "downbeat_times", "downbeatTimes", "bars", "bar_times", "barTimes"))
    positions = _extract_positions(plain, ("beat_positions", "beatPositions", "positions", "beat_position"), len(beats))

    # Some analyzers return beat objects as [time, beat_position].
    if beats and not positions and isinstance(plain.get("beats"), list):
        positions = _extract_positions({"beats": plain.get("beats")}, ("beats",), len(beats))
    meter = _infer_meter(positions)
    if beats and not downbeats and positions:
        downbeats = [beats[index] for index, pos in enumerate(positions[: len(beats)]) if int(pos) in {0, 1}]
        # allin1 beat_positions are usually 1-based; if 0-based produced too many, prefer pos==1.
        pos_one = [beats[index] for index, pos in enumerate(positions[: len(beats)]) if int(pos) == 1]
        if len(pos_one) >= 2:
            downbeats = pos_one
    bpm = _extract_bpm(plain)
    segments = _extract_segments(plain, duration=duration, source=source)

    beats = _clean_times(beats, duration)
    downbeats = _clean_times(downbeats, duration, min_gap=0.08)
    if not beats and downbeats:
        beats = downbeats[:]
    if len(beats) < 4 and len(downbeats) < 2:
        raise BeatgridAnalyzerError(f"{source}: keine belastbaren Beat-/Downbeat-Daten gefunden.")
    return {
        "source": source,
        "raw_source": source,
        "beats": beats,
        "downbeats": downbeats,
        "beat_positions": positions[: len(beats)] if positions else [],
        "bpm": bpm,
        "meter": meter,
        "segments": segments,
        "raw_summary": _summarize_plain_keys(plain),
    }


def _summarize_plain_keys(data: dict[str, Any]) -> dict[str, Any]:
    summary = {}
    for key in ("path", "bpm", "tempo", "key", "duration"):
        if key in data:
            summary[key] = data.get(key)
    for key in ("beats", "downbeats", "beat_positions", "segments"):
        if isinstance(data.get(key), list):
            summary[f"{key}_count"] = len(data.get(key) or [])
    return summary


def _infer_meter(positions: list[int]) -> int:
    clean = [int(value) for value in positions if int(value) >= 0]
    if not clean:
        return 4
    max_pos = max(clean)
    if max_pos in {3, 4, 5, 6, 7}:
        return max_pos
    # Zero-based positions.
    if max_pos in {2, 3, 5}:
        return max_pos + 1
    return 4


def _run_allin1_python(path: Path, work_dir: Path, duration: float) -> dict[str, Any]:
    module = importlib.import_module("allin1")
    analyze = getattr(module, "analyze", None) or getattr(module, "analyse", None)
    if not callable(analyze):
        raise BeatgridAnalyzerError("allin1 Python-API hat keine analyze/analyse-Funktion.")
    errors: list[str] = []
    call_variants = [
        lambda: analyze(str(path), out_dir=str(work_dir)),
        lambda: analyze([str(path)], out_dir=str(work_dir)),
        lambda: analyze(str(path)),
        lambda: analyze([str(path)]),
    ]
    for variant in call_variants:
        try:
            result = variant()
            parsed = _parse_analysis_result(result, duration=duration, source="allin1_python")
            return parsed
        except TypeError as exc:
            errors.append(str(exc))
            continue
        except BeatgridAnalyzerError:
            # The API may have written result files even if the return object is not useful.
            break
        except Exception as exc:
            errors.append(f"{exc.__class__.__name__}: {exc}")
            break
    for file_path in _find_analysis_files(work_dir):
        try:
            parsed = _parse_analysis_result(_read_json_file(file_path), duration=duration, source="allin1_json")
            return parsed
        except Exception as exc:
            errors.append(f"{file_path.name}: {exc}")
    raise BeatgridAnalyzerError("allin1 konnte nicht ausgewertet werden." + (" " + " | ".join(errors[:3]) if errors else ""))


def _run_allin1_cli(path: Path, work_dir: Path, duration: float) -> dict[str, Any]:
    executable = shutil.which(os.getenv("DAW_ALLIN1_CMD", "allin1"))
    if not executable:
        raise BeatgridAnalyzerError("allin1 CLI nicht im PATH gefunden.")
    commands = [
        [executable, str(path), "--out-dir", str(work_dir)],
        [executable, "analyze", str(path), "--out-dir", str(work_dir)],
    ]
    errors: list[str] = []
    for cmd in commands:
        try:
            subprocess.run(cmd, text=True, capture_output=True, check=True, timeout=DEFAULT_ANALYSIS_TIMEOUT)
            for file_path in _find_analysis_files(work_dir):
                try:
                    return _parse_analysis_result(_read_json_file(file_path), duration=duration, source="allin1_cli")
                except Exception as exc:
                    errors.append(f"{file_path.name}: {exc}")
        except subprocess.CalledProcessError as exc:
            errors.append((exc.stderr or exc.stdout or str(exc))[:500])
        except Exception as exc:
            errors.append(f"{exc.__class__.__name__}: {exc}")
    raise BeatgridAnalyzerError("allin1 CLI konnte keine verwertbare Analyse erzeugen." + (" " + " | ".join(errors[:3]) if errors else ""))


def _run_allin1(path: Path, duration: float) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="songstudio_allin1_") as tmp:
        work_dir = Path(tmp)
        errors: list[str] = []
        try:
            return _run_allin1_python(path, work_dir, duration)
        except Exception as exc:
            errors.append(f"Python: {exc}")
        try:
            result = _run_allin1_cli(path, work_dir, duration)
            result.setdefault("warnings", []).append("allin1 Python-API nicht nutzbar; CLI-Fallback verwendet.")
            return result
        except Exception as exc:
            errors.append(f"CLI: {exc}")
        raise BeatgridAnalyzerError("allin1 nicht verfügbar oder nicht verwertbar. " + " | ".join(errors[:4]))


def _run_madmom(path: Path, duration: float) -> dict[str, Any]:
    try:
        from madmom.features.downbeats import DBNDownBeatTrackingProcessor, RNNDownBeatProcessor  # type: ignore
    except Exception as exc:
        raise BeatgridAnalyzerError(f"madmom nicht verfügbar: {exc}") from exc
    try:
        activations = RNNDownBeatProcessor()(str(path))
        processor = DBNDownBeatTrackingProcessor(beats_per_bar=[3, 4], fps=100)
        decoded = processor(activations)
    except Exception as exc:
        raise BeatgridAnalyzerError(f"madmom Analyse fehlgeschlagen: {exc}") from exc
    data = _to_plain(decoded)
    beats: list[float] = []
    positions: list[int] = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, list) and item:
                time = _safe_float(item[0], None)
                if time is not None:
                    beats.append(time)
                    if len(item) > 1:
                        positions.append(_safe_int(item[1], 1) or 1)
    beats = _clean_times(beats, duration)
    meter = _infer_meter(positions)
    downbeats = [beats[index] for index, pos in enumerate(positions[: len(beats)]) if int(pos) == 1]
    if len(beats) < 4 or len(downbeats) < 2:
        raise BeatgridAnalyzerError("madmom hat zu wenige Beats/Downbeats erkannt.")
    return {
        "source": "madmom_rnn_dbn",
        "beats": beats,
        "downbeats": _clean_times(downbeats, duration, min_gap=0.08),
        "beat_positions": positions[: len(beats)],
        "bpm": _bpm_from_beats(beats),
        "meter": meter,
        "segments": [],
        "raw_summary": {"beats_count": len(beats), "downbeats_count": len(downbeats)},
    }


def _run_beatnet(path: Path, duration: float) -> dict[str, Any]:
    errors: list[str] = []
    beatnet_class = None
    for module_name in ("BeatNet.BeatNet", "beatnet.BeatNet", "BeatNet"):
        try:
            module = importlib.import_module(module_name)
            beatnet_class = getattr(module, "BeatNet", None)
            if beatnet_class:
                break
        except Exception as exc:
            errors.append(f"{module_name}: {exc}")
    if beatnet_class is None:
        raise BeatgridAnalyzerError("BeatNet nicht verfügbar. " + " | ".join(errors[:2]))
    try:
        estimator = beatnet_class(1, mode="offline", inference_model="DBN", plot=[], thread=False)
        output = estimator.process(str(path))
    except Exception as exc:
        raise BeatgridAnalyzerError(f"BeatNet Analyse fehlgeschlagen: {exc}") from exc
    parsed = _parse_array_beats(output, duration=duration, source="beatnet_offline_dbn")
    if len(parsed.get("beats") or []) < 4:
        raise BeatgridAnalyzerError("BeatNet hat zu wenige Beats erkannt.")
    return parsed


def _parse_array_beats(output: Any, *, duration: float, source: str) -> dict[str, Any]:
    plain = _to_plain(output)
    beats: list[float] = []
    positions: list[int] = []
    if isinstance(plain, list):
        for item in plain:
            if isinstance(item, list) and item:
                time = _safe_float(item[0], None)
                if time is None:
                    continue
                beats.append(time)
                pos = _safe_int(item[1], None) if len(item) > 1 else None
                if pos is not None:
                    positions.append(pos)
            else:
                time = _safe_float(item, None)
                if time is not None:
                    beats.append(time)
    beats = _clean_times(beats, duration)
    meter = _infer_meter(positions)
    downbeats = [beats[index] for index, pos in enumerate(positions[: len(beats)]) if int(pos) == 1]
    return {
        "source": source,
        "beats": beats,
        "downbeats": _clean_times(downbeats, duration, min_gap=0.08),
        "beat_positions": positions[: len(beats)],
        "bpm": _bpm_from_beats(beats),
        "meter": meter,
        "segments": [],
        "raw_summary": {"beats_count": len(beats), "downbeats_count": len(downbeats)},
    }



def _parse_beat_this_tsv(path: Path, *, duration: float) -> dict[str, Any] | None:
    """Parse Beat This! CLI .beats/.tsv output.

    The official CLI writes a text-like beat file.  Different versions may use
    tabs, spaces or commas and may store either a beat-position/downbeat flag or
    only raw beat times.  The parser is intentionally tolerant, because the file
    is only used as a validator against the allin1 primary result.
    """
    if not path.exists() or path.stat().st_size <= 0:
        return None
    beats: list[float] = []
    downbeats: list[float] = []
    positions: list[int] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return None
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [part for part in re.split(r"[\t,; ]+", line) if part]
        if not parts:
            continue
        time = _safe_float(parts[0], None)
        if time is None or time < 0:
            continue
        beats.append(float(time))
        marker = parts[1].strip().lower() if len(parts) > 1 else ""
        pos = _safe_int(marker, None)
        if pos is not None:
            positions.append(pos)
            if pos == 1:
                downbeats.append(float(time))
        elif marker in {"downbeat", "db", "bar", "true", "yes", "x"}:
            downbeats.append(float(time))
            positions.append(1)
        elif marker in {"beat", "b"}:
            positions.append(2)
    beats = _clean_times(beats, duration)
    downbeats = _clean_times(downbeats, duration, min_gap=0.08)
    if not beats:
        return None
    return {
        "source": "beat_this_validator_cli",
        "beats": beats,
        "downbeats": downbeats,
        "beat_positions": positions[: len(beats)] if positions else [],
        "bpm": _bpm_from_beats(beats),
        "meter": _infer_meter(positions) if positions else 4,
        "segments": [],
        "raw_summary": {"beats_count": len(beats), "downbeats_count": len(downbeats), "file": str(path)},
    }


def _run_beat_this_python(path: Path, duration: float) -> dict[str, Any] | None:
    """Run Beat This! through its Python API when installed."""
    try:
        from beat_this.inference import File2Beats  # type: ignore
    except Exception:
        return None
    device = os.getenv("DAW_BEAT_THIS_DEVICE", "cpu").strip() or "cpu"
    model = os.getenv("DAW_BEAT_THIS_MODEL", "final0").strip() or "final0"
    dbn = os.getenv("DAW_BEAT_THIS_DBN", "0").strip().lower() in {"1", "true", "yes", "on"}
    try:
        file2beats = File2Beats(checkpoint_path=model, device=device, dbn=dbn)
        beats_raw, downbeats_raw = file2beats(str(path))
        beats = _clean_times([float(value) for value in _to_plain(beats_raw) or []], duration)
        downbeats = _clean_times([float(value) for value in _to_plain(downbeats_raw) or []], duration, min_gap=0.08)
        if not beats:
            return None
        positions: list[int] = []
        if beats and downbeats:
            for beat in beats:
                positions.append(1 if _nearest_distance(beat, downbeats) <= 0.06 else 2)
        return {
            "source": "beat_this_validator_python",
            "beats": beats,
            "downbeats": downbeats,
            "beat_positions": positions[: len(beats)],
            "bpm": _bpm_from_beats(beats),
            "meter": _infer_meter(positions) if positions else 4,
            "segments": [],
            "raw_summary": {"beats_count": len(beats), "downbeats_count": len(downbeats), "model": model, "device": device, "dbn": dbn},
        }
    except Exception:
        return None


def _run_beat_this_validator(path: Path, duration: float) -> dict[str, Any] | None:
    """Best-effort Beat This! validator.

    Beat This! is treated as a validator, not as the only analysis source.  The
    preferred path is the Python API.  The CLI fallback supports the official
    `beat_this input -o output.beats` format and custom commands via
    DAW_BEAT_THIS_CMD with {input}/{output} placeholders.
    """
    python_result = _run_beat_this_python(path, duration)
    if python_result:
        return python_result

    commands: list[list[str]] = []
    configured = os.getenv("DAW_BEAT_THIS_CMD", "").strip()
    if configured:
        commands.append(shlex.split(configured))
    for name in ("beat_this", "beat-this"):
        executable = shutil.which(name)
        if executable:
            commands.append([executable])
    if not commands:
        return None

    with tempfile.TemporaryDirectory(prefix="songstudio_beatthis_") as tmp:
        work_dir = Path(tmp)
        output_path = work_dir / "beat_this_result.beats"
        output_json = work_dir / "beat_this_result.json"
        for base_cmd in commands:
            variants = []
            joined = " ".join(base_cmd)
            if "{input}" in joined or "{output}" in joined:
                variants.append([part.replace("{input}", str(path)).replace("{output}", str(output_path)) for part in base_cmd])
            else:
                variants.extend([
                    base_cmd + [str(path), "-o", str(output_path)],
                    base_cmd + [str(path), "--output", str(output_path)],
                    base_cmd + [str(path), "--out", str(output_path)],
                    base_cmd + [str(path), "--out-dir", str(work_dir)],
                ])
            for cmd in variants:
                try:
                    subprocess.run(cmd, text=True, capture_output=True, check=True, timeout=DEFAULT_ANALYSIS_TIMEOUT)
                    if output_json.exists():
                        try:
                            return _parse_analysis_result(_read_json_file(output_json), duration=duration, source="beat_this_validator_json")
                        except Exception:
                            pass
                    if output_path.exists():
                        parsed = _parse_beat_this_tsv(output_path, duration=duration)
                        if parsed:
                            return parsed
                    for file_path in list(work_dir.glob("*.beats")) + list(work_dir.glob("*.tsv")) + list(work_dir.glob("*.txt")):
                        parsed = _parse_beat_this_tsv(file_path, duration=duration)
                        if parsed:
                            return parsed
                    for file_path in _find_analysis_files(work_dir):
                        try:
                            return _parse_analysis_result(_read_json_file(file_path), duration=duration, source="beat_this_validator_json")
                        except Exception:
                            continue
                except Exception:
                    continue
    return None

def _bpm_from_beats(beats: list[float]) -> float | None:
    intervals = [beats[index + 1] - beats[index] for index in range(len(beats) - 1) if beats[index + 1] - beats[index] > 0.08]
    if not intervals:
        return None
    value = 60.0 / median(intervals)
    if 20 <= value <= 300:
        return float(value)
    return None


def _nearest_distance(value: float, candidates: list[float]) -> float:
    if not candidates:
        return 99.0
    return min(abs(float(value) - float(candidate)) for candidate in candidates)


def _estimate_downbeats_from_beats(beats: list[float], segments: list[dict[str, Any]], meter: int = 4) -> tuple[list[float], int, float, list[str]]:
    warnings: list[str] = []
    if len(beats) < meter * 2:
        return [], 0, 0.15, ["Zu wenige Beats für Downbeat-Schätzung."]
    boundaries: list[float] = []
    for segment in segments:
        start = _safe_float(segment.get("start"), None)
        end = _safe_float(segment.get("end"), None)
        if start is not None and start > 0.05:
            boundaries.append(start)
        if end is not None:
            boundaries.append(end)
    best_phase = 0
    best_score = float("inf")
    best_hits = 0
    for phase in range(max(1, meter)):
        downbeats = [beats[index] for index in range(phase, len(beats), meter)]
        score = 1.0
        hits = 0
        if boundaries and len(downbeats) > 1:
            tolerance = max(0.18, min(1.2, median([downbeats[i + 1] - downbeats[i] for i in range(len(downbeats) - 1)]) * 0.2))
            distances = []
            for boundary in boundaries:
                distance = _nearest_distance(boundary, downbeats)
                distances.append(min(distance, tolerance * 2.5) / tolerance)
                if distance <= tolerance:
                    hits += 1
            score = sum(distances) / max(1, len(distances))
        if score < best_score:
            best_score = score
            best_phase = phase
            best_hits = hits
    confidence = max(0.12, min(0.68, 0.25 + (best_hits / max(1, len(boundaries) or 4)) * 0.35))
    if confidence < 0.45:
        warnings.append("Downbeats mussten aus Beats geschätzt werden; bitte Nahtstelle vorhören.")
    return [beats[index] for index in range(best_phase, len(beats), meter)], best_phase, confidence, warnings


def _build_bars(downbeats: list[float], duration: float) -> list[dict[str, Any]]:
    bars: list[dict[str, Any]] = []
    if not downbeats:
        return bars
    cleaned = _clean_times(downbeats, duration, min_gap=0.12)
    if not cleaned:
        return bars
    if cleaned[0] > 0.12:
        cleaned.insert(0, 0.0)
    median_bar = _median_interval(cleaned) or 2.0
    while cleaned[-1] < duration - max(0.5, median_bar * 0.35) and len(cleaned) < 999:
        cleaned.append(min(duration, cleaned[-1] + median_bar))
    if cleaned[-1] < duration:
        cleaned.append(duration)
    for index in range(len(cleaned) - 1):
        start = cleaned[index]
        end = cleaned[index + 1]
        if end - start < 0.08:
            continue
        bars.append({
            "index": len(bars) + 1,
            "start": round(start, 6),
            "end": round(end, 6),
            "duration": round(end - start, 6),
            "label": f"Takt {len(bars) + 1}",
        })
    return bars


def _median_interval(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    diffs = sorted(max(0.0, values[index + 1] - values[index]) for index in range(len(values) - 1))
    diffs = [value for value in diffs if value > 0.05]
    if not diffs:
        return None
    return float(median(diffs))


def _snap_segments_to_bars(segments: list[dict[str, Any]], bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not segments or not bars:
        return []
    boundaries = [float(bar["start"]) for bar in bars] + [float(bars[-1]["end"])]
    snapped: list[dict[str, Any]] = []
    for segment in segments:
        start = float(segment["start"])
        end = float(segment["end"])
        snapped_start = min(boundaries, key=lambda item: abs(item - start))
        end_candidates = [item for item in boundaries if item > snapped_start + 0.1]
        snapped_end = min(end_candidates or boundaries, key=lambda item: abs(item - end))
        start_bar = 1
        end_bar = 1
        for bar in bars:
            if abs(float(bar["start"]) - snapped_start) < 0.025:
                start_bar = int(bar["index"])
            if float(bar["start"]) < snapped_end - 0.025:
                end_bar = int(bar["index"])
        snapped.append({
            **segment,
            "snapped_start": round(snapped_start, 6),
            "snapped_end": round(snapped_end, 6),
            "bar_start": start_bar,
            "bar_end": end_bar,
            "adjusted": abs(snapped_start - start) > 0.04 or abs(snapped_end - end) > 0.04,
            "snap_delta_start": round(snapped_start - start, 6),
            "snap_delta_end": round(snapped_end - end, 6),
        })
    return snapped


def _merge_segments(primary: list[dict[str, Any]], fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if primary:
        return primary
    return fallback


def _validator_report(primary: dict[str, Any], validator: dict[str, Any] | None) -> tuple[list[str], float | None]:
    if not validator:
        return ["Beat-This-Validator nicht verfügbar oder nicht konfiguriert; primäre Analyse ohne sekundären Validator verwendet."], None
    warnings: list[str] = []
    primary_down = primary.get("downbeats") or []
    valid_down = validator.get("downbeats") or []
    primary_beats = primary.get("beats") or []
    valid_beats = validator.get("beats") or []
    agreement_values = []
    if primary_down and valid_down:
        distances = [_nearest_distance(value, valid_down) for value in primary_down[:160]]
        median_distance = float(median(distances)) if distances else 0.0
        agreement_values.append(max(0.0, 1.0 - median_distance / 0.18))
        if median_distance > 0.22:
            warnings.append(f"Beat-This weicht bei Downbeats ab (Median {median_distance:.3f}s); Schnittpunkte vorhören.")
    if primary_beats and valid_beats:
        distances = [_nearest_distance(value, valid_beats) for value in primary_beats[:240]]
        median_distance = float(median(distances)) if distances else 0.0
        agreement_values.append(max(0.0, 1.0 - median_distance / 0.12))
        if median_distance > 0.18:
            warnings.append(f"Beat-This weicht bei Beats ab (Median {median_distance:.3f}s).")
    if not agreement_values:
        return warnings + ["Beat-This lieferte keine vergleichbaren Beat-/Downbeat-Daten."], None
    return warnings, round(sum(agreement_values) / len(agreement_values), 3)


def _boundary_quality(path: Path, bars: list[dict[str, Any]]) -> dict[str, Any]:
    """Lightweight seam metadata using soundfile + NumPy.

    This does not replace the musical downbeat decision.  It only marks whether
    bar-boundaries are likely to click/pop and gives the renderer/UI a safe
    default crossfade hint.
    """
    try:
        import numpy as np  # type: ignore
        import soundfile as sf  # type: ignore

        data, sr = sf.read(str(path), always_2d=True, dtype="float32")
        if data.size == 0 or sr <= 0:
            return {"available": False}
        mono = np.mean(data, axis=1)
        window = max(64, int(sr * 0.012))
        qualities = []
        for bar in bars[:500]:
            sample = int(float(bar.get("start") or 0) * sr)
            left = mono[max(0, sample - window):sample]
            right = mono[sample:min(len(mono), sample + window)]
            if len(left) < 8 or len(right) < 8:
                continue
            edge = float(abs(float(left[-1]) - float(right[0])))
            rms = float(math.sqrt(float(np.mean(np.concatenate([left, right]) ** 2))))
            quality = max(0.0, min(1.0, 1.0 - (edge * 7.5 + rms * 0.6)))
            qualities.append(quality)
        if not qualities:
            return {"available": False}
        avg = float(sum(qualities) / len(qualities))
        return {
            "available": True,
            "average_boundary_quality": round(avg, 3),
            "recommended_crossfade_ms": 12 if avg >= 0.62 else 25,
        }
    except Exception as exc:
        return {"available": False, "message": f"Seam-Scoring nicht verfügbar: {exc.__class__.__name__}"}


def _build_result(asset: Any, fingerprint: dict[str, Any], duration: float, primary: dict[str, Any], validator: dict[str, Any] | None, source_segments: list[dict[str, Any]], seam_profile: dict[str, Any]) -> dict[str, Any]:
    warnings: list[str] = []
    beats = _clean_times([float(value) for value in primary.get("beats") or []], duration)
    downbeats = _clean_times([float(value) for value in primary.get("downbeats") or []], duration, min_gap=0.08)
    meter = int(primary.get("meter") or 4)
    if meter < 2 or meter > 8:
        meter = 4
    if not downbeats and beats:
        estimated_downbeats, _phase, confidence, downbeat_warnings = _estimate_downbeats_from_beats(beats, source_segments or primary.get("segments") or [], meter=meter)
        downbeats = estimated_downbeats
        primary["downbeat_estimated_confidence"] = confidence
        warnings.extend(downbeat_warnings)
    bars = _build_bars(downbeats, duration)
    if len(bars) < 2:
        raise BeatgridAnalyzerError("Analyse lieferte keine ausreichende Bar-Map.")

    analysis_segments = _merge_segments(primary.get("segments") or [], source_segments)
    snapped_segments = _snap_segments_to_bars(analysis_segments, bars)
    validator_warnings, validator_agreement = _validator_report(primary, validator)
    warnings.extend(validator_warnings)

    bpm = _safe_float(primary.get("bpm"), None) or _bpm_from_beats(beats)
    if bpm is not None:
        bpm = round(float(bpm), 3)
    source = primary.get("source") or "unknown"
    source_label = "allin1" if str(source).startswith("allin1") else source
    if validator:
        source_label = f"{source_label}+BeatThis"
    confidence_base = 0.88 if str(source).startswith("allin1") else 0.72
    if validator_agreement is not None:
        confidence_base = max(0.35, min(0.97, confidence_base * 0.78 + validator_agreement * 0.22))
    if primary.get("downbeat_estimated_confidence") is not None:
        confidence_base = min(confidence_base, float(primary.get("downbeat_estimated_confidence") or 0.4))
    if len(warnings) > 1:
        confidence_base = max(0.2, confidence_base - 0.04 * min(5, len(warnings)))
    revision_seed = json.dumps({
        "version": ANALYSIS_VERSION,
        "fingerprint": fingerprint.get("sha1"),
        "source": source,
        "validator": validator.get("source") if validator else None,
        "beats": len(beats),
        "downbeats": len(downbeats),
        "bars": len(bars),
        "bpm": bpm,
    }, sort_keys=True)
    return {
        "ok": True,
        "status": "ready",
        "analysis_engine": "allin1_primary_beatthis_validator_madmom_fallback",
        "analysis_version": ANALYSIS_VERSION,
        "source": f"ffmpeg_wav+{source}" + ("+beat_this_validator" if validator else ""),
        "source_label": source_label,
        "analysis_revision": hashlib.sha1(revision_seed.encode("utf-8", "ignore")).hexdigest()[:16],
        "source_fingerprint": fingerprint,
        "duration_seconds": round(duration, 6),
        "bpm": bpm,
        "tempo_source": "analysis_beats",
        "time_signature": f"{meter}/4",
        "meter": meter,
        "confidence": round(max(0.05, min(0.98, confidence_base)), 3),
        "validator": {
            "available": bool(validator),
            "source": validator.get("source") if validator else None,
            "agreement": validator_agreement,
        },
        "seam_profile": seam_profile,
        "beats": [round(float(value), 6) for value in beats[:2400]],
        "downbeats": [round(float(value), 6) for value in downbeats[:700]],
        "bars": bars[:700],
        "segments": snapped_segments,
        "warnings": warnings,
        "summary": f"{len(bars)} Takte, {len(beats)} Beats, {round(float(bpm), 1) if bpm else '?'} BPM, Quelle: {source_label}",
    }


def build_daw_beatgrid(asset: Any, audio_path: Path, *, rebuild: bool = False) -> dict[str, Any]:
    """Create a reusable musical bar map for DAW edits.

    Production order:
    1. FFmpeg normalized WAV copy to avoid decoder offsets.
    2. allin1 as primary analyzer for BPM, beats, downbeats and structure.
    3. Beat This! as optional validator via DAW_BEAT_THIS_CMD / CLI when present.
    4. madmom, then BeatNet as downbeat/meter fallbacks.
    5. soundfile + NumPy seam metadata for cut/crossfade hints.

    No global Suno-BPM grid is used here.  Suno/metadata timing is only used as
    fallback segment context when analyzers do not produce structure labels.
    """
    metadata = getattr(asset, "metadata_json", None) if isinstance(getattr(asset, "metadata_json", None), dict) else {}
    fingerprint = _fingerprint(audio_path)
    cached = metadata.get("daw_beatgrid") if isinstance(metadata, dict) else None
    if not rebuild and isinstance(cached, dict) and cached.get("source_fingerprint", {}).get("sha1") == fingerprint["sha1"] and cached.get("analysis_version") == ANALYSIS_VERSION:
        return cached

    analysis_path = _decode_analysis_wav(audio_path)
    delete_analysis_path = analysis_path != audio_path
    duration = _audio_duration_seconds(analysis_path) or _audio_duration_seconds(audio_path)
    source_segments = _metadata_segments(asset)
    analyzer_errors: list[str] = []
    try:
        if duration <= 0.1:
            raise BeatgridAnalyzerError("Audio-Dauer konnte nicht ermittelt werden.")
        try:
            primary = _run_allin1(analysis_path, duration)
        except Exception as exc:
            analyzer_errors.append(str(exc))
            primary = None

        if primary is None:
            for fallback_name, fallback in (("madmom", _run_madmom), ("BeatNet", _run_beatnet)):
                try:
                    primary = fallback(analysis_path, duration)
                    primary.setdefault("warnings", []).append(f"{fallback_name}-Fallback verwendet, weil allin1 nicht verfügbar war.")
                    break
                except Exception as exc:
                    analyzer_errors.append(str(exc))

        if primary is None:
            return {
                "ok": False,
                "status": "missing_dependency",
                "analysis_engine": "allin1_primary_beatthis_validator_madmom_fallback",
                "analysis_version": ANALYSIS_VERSION,
                "source": "none",
                "source_label": "Analyse fehlt",
                "message": "DAW-Bar-Map konnte nicht erstellt werden: allin1 ist nicht verfügbar und Fallbacks lieferten keine Downbeats.",
                "warnings": analyzer_errors[:8],
                "source_fingerprint": fingerprint,
                "duration_seconds": round(duration, 6),
                "beats": [],
                "downbeats": [],
                "bars": [],
                "segments": source_segments,
            }

        validator = _run_beat_this_validator(analysis_path, duration)
        seam_profile = _boundary_quality(analysis_path, _build_bars(primary.get("downbeats") or [], duration))
        result = _build_result(asset, fingerprint, duration, primary, validator, source_segments, seam_profile)
        if analyzer_errors:
            result.setdefault("warnings", []).extend([f"Fallback-Hinweis: {item}" for item in analyzer_errors[:3]])
        if primary.get("warnings"):
            result.setdefault("warnings", []).extend([str(item) for item in primary.get("warnings")[:6]])
        return result
    except Exception as exc:
        return {
            "ok": False,
            "status": "failed",
            "analysis_engine": "allin1_primary_beatthis_validator_madmom_fallback",
            "analysis_version": ANALYSIS_VERSION,
            "source": "none",
            "source_label": "Analyse fehlgeschlagen",
            "message": str(exc),
            "source_fingerprint": fingerprint,
            "duration_seconds": round(duration or 0.0, 6),
            "beats": [],
            "downbeats": [],
            "bars": [],
            "segments": source_segments,
            "warnings": ["Beat-/Downbeat-/Bar-Analyse fehlgeschlagen; bitte allin1/madmom/BeatNet Installation prüfen."] + analyzer_errors[:6],
        }
    finally:
        if delete_analysis_path:
            try:
                analysis_path.unlink(missing_ok=True)
            except Exception:
                pass


def persist_daw_beatgrid(asset: Any, beatgrid: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(getattr(asset, "metadata_json", None) or {}) if isinstance(getattr(asset, "metadata_json", None), dict) else {}
    metadata["daw_beatgrid"] = beatgrid
    asset.metadata_json = metadata
    return beatgrid

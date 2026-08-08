"""forced_alignment_service.py — CTC-Forced-Alignment fuer bekannte Lyrics.

Richtet die bekannten Songtext-Tokens direkt auf das Audio aus (torchaudio
MMS_FA, deutsch-tauglich, laeuft lokal auf CPU in WSL2). Es muss kein einziges
Wort vom ASR erkannt werden; die Wortgrenzen kommen aus dem CTC-Emission-Pfad.

Installation (WSL2 Debian, CPU):
    pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu --break-system-packages

Alle torch-Imports sind lazy; ohne Installation bleibt die App voll
funktionsfaehig (Heuristik-Engine). Das MMS-Modell (~1.2 GB) wird beim ersten
Lauf in den torch-Hub-Cache geladen (`~/.cache/torch`), danach offline nutzbar.
"""

from __future__ import annotations

import logging
import math
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

_TRANSLITERATION = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})
_ALLOWED_RE = re.compile(r"[^a-z']+")

# MMS-CTC arbeitet mit 16 kHz Mono; laengere Songs werden in ueberlappenden
# Fenstern verarbeitet, damit der Speicherbedarf auf CPU planbar bleibt.
_TARGET_SAMPLE_RATE = 16_000
_CHUNK_SECONDS = 240.0


@dataclass
class TokenSpanSeconds:
    """Zeitspanne eines Songtext-Tokens in Sekunden mit CTC-Konfidenz."""

    start: float
    end: float
    score: float


class ForcedAlignmentUnavailable(RuntimeError):
    """torch/torchaudio fehlen oder das MMS-Bundle konnte nicht geladen werden."""


def _normalize_token(token: str) -> str:
    value = unicodedata.normalize("NFKC", str(token or "")).lower().translate(_TRANSLITERATION)
    return _ALLOWED_RE.sub("", value)


def forced_alignment_available() -> bool:
    try:
        import torch  # noqa: F401
        import torchaudio  # noqa: F401
        from torchaudio.pipelines import MMS_FA  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


@lru_cache(maxsize=1)
def _load_bundle():
    try:
        import torch
        from torchaudio.pipelines import MMS_FA
    except Exception as exc:  # noqa: BLE001
        raise ForcedAlignmentUnavailable(
            "torch/torchaudio nicht installiert. Installation (WSL2, CPU): "
            "pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu --break-system-packages"
        ) from exc
    try:
        model = MMS_FA.get_model(with_star=True)
        model.eval()
        tokenizer = MMS_FA.get_tokenizer()
        aligner = MMS_FA.get_aligner()
    except Exception as exc:  # noqa: BLE001
        raise ForcedAlignmentUnavailable(f"MMS-Forced-Alignment-Bundle konnte nicht geladen werden: {exc}") from exc
    return torch, model, tokenizer, aligner


def _load_audio_mono_16k(audio_path: Path):
    torch, _, _, _ = _load_bundle()
    import torchaudio

    waveform, sample_rate = torchaudio.load(str(audio_path))
    if waveform.dim() == 2 and waveform.size(0) > 1:
        waveform = waveform.mean(dim=0, keepdim=True)
    if sample_rate != _TARGET_SAMPLE_RATE:
        waveform = torchaudio.functional.resample(waveform, sample_rate, _TARGET_SAMPLE_RATE)
    return waveform


def force_align_tokens(audio_path: Path, tokens: list[str]) -> list[TokenSpanSeconds | None]:
    """Alignt die Token-Sequenz auf das Audio; Rueckgabe positionsgleich zu `tokens`.

    Tokens ohne alignierbare Zeichen (Zahlen, Emojis) liefern None und werden
    vom Aufrufer interpoliert. Bei langen Songs laeuft das Alignment in einem
    Fenster ueber die gesamte Laenge, solange sie unter dem Chunk-Limit liegt;
    darueber wird sequentiell mit Zeit-Offsets gearbeitet (monoton, da die
    Token-Reihenfolge der Songtext-Reihenfolge entspricht).
    """
    torch, model, tokenizer, aligner = _load_bundle()

    normalized: list[str] = [_normalize_token(token) for token in tokens]
    alignable_positions = [index for index, value in enumerate(normalized) if value]
    alignable_tokens = [normalized[index] for index in alignable_positions]
    results: list[TokenSpanSeconds | None] = [None] * len(tokens)
    if not alignable_tokens:
        return results

    waveform = _load_audio_mono_16k(Path(audio_path))
    total_samples = waveform.size(-1)
    total_seconds = total_samples / _TARGET_SAMPLE_RATE
    if total_seconds <= 0.2:
        return results

    if total_seconds <= _CHUNK_SECONDS:
        spans = _align_window(torch, model, tokenizer, aligner, waveform, alignable_tokens, time_offset=0.0)
    else:
        spans = _align_long_audio(torch, model, tokenizer, aligner, waveform, alignable_tokens)

    for position, span in zip(alignable_positions, spans):
        results[position] = span
    return results


def _align_window(torch, model, tokenizer, aligner, waveform, tokens: list[str], *, time_offset: float) -> list[TokenSpanSeconds | None]:
    with torch.inference_mode():
        emission, _ = model(waveform)
        token_spans = aligner(emission[0], tokenizer(tokens))
    num_frames = emission.size(1)
    seconds_per_frame = (waveform.size(-1) / _TARGET_SAMPLE_RATE) / max(1, num_frames)

    spans: list[TokenSpanSeconds | None] = []
    for word_spans in token_spans:
        if not word_spans:
            spans.append(None)
            continue
        start = word_spans[0].start * seconds_per_frame + time_offset
        end = word_spans[-1].end * seconds_per_frame + time_offset
        scores = [float(span.score) for span in word_spans]
        score = sum(scores) / len(scores) if scores else 0.0
        if not (math.isfinite(start) and math.isfinite(end)) or end <= start:
            spans.append(None)
            continue
        spans.append(TokenSpanSeconds(start=round(start, 3), end=round(end, 3), score=round(score, 3)))
    return spans


_ENERGY_FRAME_SECONDS = 0.05  # 50ms-Frames fuer die grobe Energie-Einhuellende (Aktivitaets-VAD)


def _active_sample_prefix_sums(torch_module, waveform, target_sample_rate: int):
    """Baut ein grobes Aktivitaets-Profil (Energie-Schwellwert) als Praefixsummen-Array.

    Liefert fuer jede Frame-Grenze die kumulierte Anzahl "aktiver" (nicht-stiller)
    Samples bis dahin, sodass sich fuer beliebige Fenstergrenzen in O(1) die
    tatsaechlich gesungenen/gespielten Samples zaehlen lassen -- statt Tokens naiv
    proportional zur reinen Fensterdauer zu verteilen (`len(tokens) / total_samples`).
    Intro-Stille, Breaks oder rein instrumentale Passagen bekamen dabei denselben
    Tokenanteil zugewiesen wie dichte Rap-Passagen; bei Songs > 240s verschob das
    pro Chunk-Grenze die Wortgrenzen und erzeugte den beobachteten
    "driftet -> faengt sich am naechsten Fenster wieder"-Effekt. Fix 2026-07-26.
    """
    samples = waveform[0] if waveform.dim() == 2 else waveform
    frame_len = max(1, int(_ENERGY_FRAME_SECONDS * target_sample_rate))
    total = samples.size(-1)
    num_frames = max(1, math.ceil(total / frame_len))
    padded_len = num_frames * frame_len
    if padded_len > total:
        samples = torch_module.nn.functional.pad(samples, (0, padded_len - total))
    frames = samples.reshape(num_frames, frame_len)
    frame_rms = torch_module.sqrt(torch_module.mean(frames * frames, dim=1) + 1e-12)
    threshold = float(torch_module.quantile(frame_rms, 0.9)) * 0.08 if frame_rms.numel() else 0.0
    active_frames = (frame_rms > threshold).to(torch_module.int64)
    prefix = torch_module.cumsum(active_frames * frame_len, dim=0)
    prefix = torch_module.cat([torch_module.zeros(1, dtype=torch_module.int64), prefix])
    return prefix, frame_len, total


def _active_samples_in_range(prefix, frame_len: int, total_samples: int, start_sample: int, end_sample: int) -> int:
    """Zaehlt aktive Samples in [start_sample, end_sample) anhand der Praefixsummen."""
    start_sample = max(0, min(start_sample, total_samples))
    end_sample = max(start_sample, min(end_sample, total_samples))
    max_frame = prefix.numel() - 1
    start_frame = min(start_sample // frame_len, max_frame)
    end_frame = min(math.ceil(end_sample / frame_len), max_frame)
    active = int(prefix[end_frame] - prefix[start_frame])
    return max(0, min(active, end_sample - start_sample))


def _align_long_audio(torch, model, tokenizer, aligner, waveform, tokens: list[str]) -> list[TokenSpanSeconds | None]:
    """Sequentielles Fenster-Alignment fuer sehr lange Audios (> Chunk-Limit).

    Die Tokens werden proportional zur *aktiven* (nicht-stillen) Audiodauer je
    Fenster aufgeteilt statt proportional zur reinen Fensterlaenge -- siehe
    `_active_sample_prefix_sums`. Jedes Fenster ueberlappt das naechste um 5
    Sekunden, damit Fenstergrenzen keine Tokens zerschneiden. Da Songtext-Tokens
    streng sequentiell gesungen werden, bleibt das Gesamtergebnis monoton.
    """
    chunk_samples = int(_CHUNK_SECONDS * _TARGET_SAMPLE_RATE)
    overlap_samples = int(5.0 * _TARGET_SAMPLE_RATE)
    total_samples = waveform.size(-1)
    windows: list[tuple[int, int]] = []
    cursor = 0
    while cursor < total_samples:
        end = min(total_samples, cursor + chunk_samples)
        windows.append((cursor, end))
        if end >= total_samples:
            break
        cursor = end - overlap_samples

    try:
        activity_prefix, activity_frame_len, activity_total = _active_sample_prefix_sums(torch, waveform, _TARGET_SAMPLE_RATE)
        total_active_samples = int(activity_prefix[-1])
    except Exception:  # noqa: BLE001 -- Aktivitaets-VAD ist ein Optimierungspfad, kein Hard-Requirement.
        logger.exception("Aktivitaets-Praefixsummen fuer Chunk-Verteilung konnten nicht berechnet werden, falle auf zeitproportionale Verteilung zurueck.")
        activity_prefix = None
        total_active_samples = 0

    spans: list[TokenSpanSeconds | None] = []
    if activity_prefix is not None and total_active_samples > 0:
        tokens_per_active_sample = len(tokens) / total_active_samples
    else:
        tokens_per_active_sample = None
    tokens_per_sample = len(tokens) / max(1, total_samples)
    token_cursor = 0
    for window_index, (window_start, window_end) in enumerate(windows):
        is_last = window_index == len(windows) - 1
        if is_last:
            window_tokens = tokens[token_cursor:]
        else:
            window_span_end = window_end - overlap_samples
            if tokens_per_active_sample is not None:
                active_in_window = _active_samples_in_range(activity_prefix, activity_frame_len, activity_total, window_start, window_span_end)
                expected = int(round(active_in_window * tokens_per_active_sample))
            else:
                expected = int(round((window_span_end - window_start) * tokens_per_sample))
            expected = max(1, min(expected, len(tokens) - token_cursor))
            window_tokens = tokens[token_cursor:token_cursor + expected]
        if not window_tokens:
            continue
        window_waveform = waveform[..., window_start:window_end]
        window_spans = _align_window(
            torch, model, tokenizer, aligner, window_waveform, window_tokens,
            time_offset=window_start / _TARGET_SAMPLE_RATE,
        )
        spans.extend(window_spans)
        token_cursor += len(window_tokens)
    while len(spans) < len(tokens):
        spans.append(None)
    return spans

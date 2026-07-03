from __future__ import annotations

# CORE CONTRACT
# Zweck: Erzeugt SRT/Half-SRT aus AudioAssets und Lyrics als Source of Truth.
# Audios ohne verwertbare Lyrics duerfen als Fallback ASR-only-SRT erzeugen;
# dieser Fallback darf den normalen Lyrics-Cleanup-/Alignment-Pfad nicht ersetzen.
# Kritische Logik: Lyrics-Cleanup, Transkriptionsprovider, Alignment, Task-Finalisierung.
# Tasks duerfen nie dauerhaft RUNNING bleiben; Providerfehler muessen FAILED setzen.
# SRT-Zeiten bauen structure_segments_json fuer Waveform-Abschnitte.
# Groq-Sonderfall: Der Groq-Upload nutzt bei Bedarf eine temporaere, klein
# kodierte Mono-Kopie der Audiodatei. Diese Kopie existiert nur fuer den
# Provider-POST und darf nicht die Originaldatei, Lyrics-Bereinigung, Alignment-
# Semantik, SRT-Ausgabe oder Waveform-/Abschnittslogik veraendern.
# Nicht aendern ohne Pruefung: audio_assets.py, MiniPlayer.jsx, LibraryPage.jsx, waveform_service.py.
# Siehe: docs/ARCHITECTURE_CONTRACT.md


import asyncio
import difflib
import json
import os
import re
import shutil
import subprocess
from collections import Counter
import tempfile
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse
from typing import Any, Callable

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AppSetting, AudioAsset, AudioTranscript, Song, StatusNotification, SunoTask
from app.services.srt_parser import export_srt as export_srt_text, parse_srt as parse_srt_text, renumber_segments as renumber_srt_segments
from app.services.srt_validation import normalize_or_raise as validate_and_normalize_srt_segments
from app.services.audio_metadata_service import read_audio_duration_seconds
from app.services.audio_asset_repair_service import is_audio_url, repair_local_file_metadata
from app.services.audio_cache_service import AudioCacheService, AudioCandidate
from app.services.ai_chat_service import AiChatService, AiProviderError
from app.services.waveform_service import extract_structure_marker
from app.utils.time_utils import utc_now_naive

TRANSCRIPTION_SETTINGS_KEY = "ai_chat_settings"
TRANSCRIPTION_MODE = "lyrics_source_of_truth"
TRANSCRIPTION_MATCH_MODE = "lenient"
SUPPORTED_BACKENDS = {"voxtral", "openai_whisper_api", "whisperx", "groq"}
SUPPORTED_LANGUAGES = {"auto", "de", "en"}
STRUCTURE_SEGMENT_LEAD_IN_SECONDS = 2.0

ENGLISH_LANGUAGE_HINTS = {
    "the", "and", "you", "your", "yours", "we", "they", "them", "that", "this", "with", "from", "when",
    "where", "what", "why", "how", "in", "on", "of", "to", "for", "my", "me", "mine", "our", "is",
    "are", "was", "were", "be", "been", "do", "does", "did", "dont", "don't", "cant", "can't", "will",
    "would", "could", "should", "like", "light", "night", "fire", "time", "life", "heart", "world",
    "shadow", "blade", "sword", "fall", "stand", "still", "only", "never", "every", "nothing", "left",
}

PATOIS_LANGUAGE_HINTS = {
    "mi", "yuh", "nuh", "inna", "fi", "deh", "weh", "pon", "dem", "di", "cyaan", "cyaa", "cah",
    "gwaan", "ting", "seh", "wah", "mek", "dung", "col", "weh", "nah", "dehdeh", "yaad", "bwoy",
    "gyal", "riddim", "toasting", "patois", "jamaican", "jamaica", "dancehall",
}

GERMAN_LANGUAGE_HINTS = {
    "der", "die", "das", "und", "oder", "aber", "nicht", "kein", "keine", "ich", "du", "er", "sie",
    "wir", "ihr", "mein", "meine", "dein", "deine", "sein", "seine", "ist", "sind", "war", "waren",
    "bin", "bist", "hat", "habe", "haben", "mit", "von", "für", "auf", "im", "in", "am", "an",
    "wenn", "weil", "doch", "nur", "noch", "schon", "mich", "dich", "uns", "euch", "mir", "dir",
    "ein", "eine", "einen", "einem", "einer", "dem", "den", "des", "zum", "zur", "aus", "bei",
}


def _language_tokens(text: str) -> list[str]:
    normalized = str(text or "").lower()
    normalized = normalized.replace("’", "'").replace("`", "'")
    return [token.strip("'") for token in re.findall(r"[a-zäöüß']+", normalized) if token.strip("'")]


def detect_lyrics_language(lyrics: str) -> dict[str, Any]:
    """Ermittelt eine robuste Transkriptionssprache aus dem Songtext.

    Ziel: Songs mit englischem oder Patois-dominiertem Text dürfen nicht nur wegen
    globaler Admin-Voreinstellung als `de` an Groq/OpenAI/WhisperX gehen.
    Für Jamaican Patois ist `en` die bessere Whisper/Groq-Sprache.
    """
    spoken_text = "\n".join(_spoken_lyrics_lines(lyrics)) or str(lyrics or "")
    tokens = _language_tokens(spoken_text)
    if not tokens:
        return {"language": "auto", "confidence": 0.0, "reason": "no_lyrics_tokens", "english_score": 0.0, "german_score": 0.0}

    token_count = max(1, len(tokens))
    english_hits = sum(1 for token in tokens if token in ENGLISH_LANGUAGE_HINTS)
    patois_hits = sum(1 for token in tokens if token in PATOIS_LANGUAGE_HINTS)
    german_hits = sum(1 for token in tokens if token in GERMAN_LANGUAGE_HINTS)
    german_umlaut_hits = len(re.findall(r"[äöüß]", spoken_text.lower()))

    english_score = (english_hits + (patois_hits * 1.65)) / token_count
    german_score = (german_hits + (german_umlaut_hits * 1.25)) / token_count

    if patois_hits >= 3 and english_score >= 0.035 and german_score < 0.075:
        return {
            "language": "en",
            "confidence": min(0.99, 0.72 + min(0.22, english_score)),
            "reason": "patois_or_english_lyrics",
            "english_score": round(english_score, 4),
            "german_score": round(german_score, 4),
            "patois_hits": patois_hits,
            "token_count": token_count,
        }

    if english_score >= 0.075 and english_score >= german_score * 1.8:
        return {
            "language": "en",
            "confidence": min(0.96, 0.62 + min(0.28, english_score)),
            "reason": "english_lyrics",
            "english_score": round(english_score, 4),
            "german_score": round(german_score, 4),
            "patois_hits": patois_hits,
            "token_count": token_count,
        }

    if german_score >= 0.07 and german_score >= english_score * 1.25:
        return {
            "language": "de",
            "confidence": min(0.96, 0.60 + min(0.30, german_score)),
            "reason": "german_lyrics",
            "english_score": round(english_score, 4),
            "german_score": round(german_score, 4),
            "patois_hits": patois_hits,
            "token_count": token_count,
        }

    return {
        "language": "auto",
        "confidence": 0.35,
        "reason": "ambiguous_lyrics_language",
        "english_score": round(english_score, 4),
        "german_score": round(german_score, 4),
        "patois_hits": patois_hits,
        "token_count": token_count,
    }


def resolve_transcription_language(configured_language: str | None, lyrics: str) -> tuple[str, dict[str, Any]]:
    configured = str(configured_language or "auto").strip().lower()
    if configured not in SUPPORTED_LANGUAGES:
        configured = "auto"

    detected = detect_lyrics_language(lyrics)
    detected_language = str(detected.get("language") or "auto").lower()
    confidence = float(detected.get("confidence") or 0.0)
    resolved = configured
    source = "admin_setting"

    if configured == "auto":
        if detected_language in {"de", "en"} and confidence >= 0.55:
            resolved = detected_language
            source = "lyrics_detection"
        else:
            resolved = "auto"
            source = "provider_auto"
    elif configured == "de" and detected_language == "en" and confidence >= 0.60:
        resolved = "en"
        source = "lyrics_detection_override"
    elif configured == "en" and detected_language == "de" and confidence >= 0.88:
        resolved = "de"
        source = "lyrics_detection_override"

    info = {
        "configured_language": configured,
        "resolved_language": resolved,
        "language_source": source,
        "detected_language": detected_language,
        "detection_confidence": round(confidence, 4),
        "detection_reason": detected.get("reason"),
        "english_score": detected.get("english_score"),
        "german_score": detected.get("german_score"),
        "patois_hits": detected.get("patois_hits", 0),
        "token_count": detected.get("token_count", 0),
    }
    return resolved, info


class TranscriptionBackendError(RuntimeError):
    pass


@dataclass
class WordTiming:
    word: str
    start: float
    end: float


@dataclass
class AsrResult:
    text: str
    words: list[WordTiming]
    segments: list[dict[str, Any]]
    raw: dict[str, Any]


# --------------------------------------------------------------------------- #
# Lyrics-SRT-Alignment nach bewährtem CLI-Skript "lyrics_align_srt.py"
# --------------------------------------------------------------------------- #

SECTION_RE = re.compile(r"^\s*\[.*\]\s*$")
EMPHASIS_RE = re.compile(r"[*_]")
WS_RE = re.compile(r"\s+")
NONWORD_RE = re.compile(r"[^a-z0-9'\s-]")
VOWEL_RE = re.compile(r"[aeiouyäöü]+", re.IGNORECASE)


@dataclass
class LyricLine:
    index: int
    display: str
    words: list[str]
    tok_counts: list[int]
    match_tokens: list[str]
    weight: float = 1.0
    matched: bool = False
    start: float | None = None
    end: float | None = None
    wstart: list[float] | None = None
    wend: list[float] | None = None


@dataclass
class HypWord:
    norm: str
    start: float
    end: float


def _script_syllable_weight(text: str) -> float:
    return float(max(len(VOWEL_RE.findall(text)), 1))


def _script_clean_display(raw: str) -> str:
    s_clean = str(raw or "").strip()
    # Untertitel dürfen keine Prompt-/Regie-Markups anzeigen.
    # Stage-/SFX-Inhalte werden bereits vor dem Alignment entfernt; hier wird
    # zusätzlich sichergestellt, dass gesungene Adlibs wie "(Alla hopp!)"
    # ohne sichtbare Klammern in die SRT-Ausgabe gelangen.
    s_clean = EMPHASIS_RE.sub("", s_clean)
    s_clean = re.sub(r"[\[\]{}()]+", "", s_clean)
    return WS_RE.sub(" ", s_clean).strip()


def _script_tokenize_match(text: str) -> list[str]:
    normalized = EMPHASIS_RE.sub(" ", str(text or "").lower())
    normalized = NONWORD_RE.sub(" ", normalized)
    normalized = normalized.replace("-", " ")
    return [w for w in (tok.strip("'") for tok in normalized.split()) if w]


def _script_is_skippable(raw: str, skip_prefixes: tuple[str, ...] = ("#", "/", ";"), skip_parens: bool = False) -> bool:
    value = str(raw or "").strip()
    if not value:
        return True
    if SECTION_RE.match(value):
        return True
    if any(value.startswith(prefix) for prefix in skip_prefixes):
        return True
    if skip_parens and value.startswith("(") and value.endswith(")"):
        return True
    return False


def _script_parse_lyrics_text(lyrics: str, skip_prefixes: tuple[str, ...] = ("#", "/", ";"), skip_parens: bool = False) -> list[LyricLine]:
    parsed: list[LyricLine] = []
    for raw in str(lyrics or "").replace("\r\n", "\n").replace("\r", "\n").splitlines():
        if _script_is_skippable(raw, skip_prefixes, skip_parens):
            continue
        display = _script_clean_display(raw)
        display_words = display.split()
        token_counts: list[int] = []
        tokens: list[str] = []
        for word in display_words:
            word_tokens = _script_tokenize_match(word)
            token_counts.append(len(word_tokens))
            tokens.extend(word_tokens)
        if not display or not tokens:
            continue
        parsed.append(
            LyricLine(
                index=len(parsed),
                display=display,
                words=display_words,
                tok_counts=token_counts,
                match_tokens=tokens,
                weight=_script_syllable_weight(display),
                wstart=[],
                wend=[],
            )
        )
    return parsed


def _script_expand_word(word: str, start: float | None, end: float | None) -> list[tuple[str, float | None, float | None]]:
    toks = _script_tokenize_match(word)
    if not toks:
        return []
    if len(toks) == 1:
        return [(toks[0], start, end)]
    if start is not None and end is not None and end > start:
        step = (end - start) / len(toks)
        return [(tk, start + i * step, start + (i + 1) * step) for i, tk in enumerate(toks)]
    return [(tk, start, end) for tk in toks]


def _script_finalize_hyp(raw: list[tuple[str, float | None, float | None]]) -> list[HypWord]:
    n = len(raw)
    starts: list[float | None] = [item[1] for item in raw]
    ends: list[float | None] = [item[2] for item in raw]

    for i in range(n):
        if starts[i] is None:
            starts[i] = ends[i - 1] if i > 0 and ends[i - 1] is not None else None
        if ends[i] is None:
            ends[i] = starts[i]
    for i in range(n - 1, -1, -1):
        if ends[i] is None:
            ends[i] = starts[i + 1] if i + 1 < n and starts[i + 1] is not None else None
        if starts[i] is None:
            starts[i] = ends[i]

    words: list[HypWord] = []
    for (token, _, _), start, end in zip(raw, starts, ends):
        if start is None or end is None:
            continue
        words.append(HypWord(norm=token, start=float(start), end=float(max(end, start))))
    return words


def _script_flatten_words_from_segments(segments: list[dict[str, Any]]) -> list[HypWord]:
    raw: list[tuple[str, float | None, float | None]] = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        for word in segment.get("words", []) or []:
            if not isinstance(word, dict):
                continue
            raw += _script_expand_word(str(word.get("word") or word.get("text") or "").strip(), word.get("start"), word.get("end"))
    return _script_finalize_hyp(raw)


def _script_flatten_words_from_payload(payload: dict[str, Any]) -> list[HypWord]:
    raw: list[tuple[str, float | None, float | None]] = []
    direct_words = payload.get("words") if isinstance(payload, dict) else None
    if isinstance(direct_words, list):
        for word in direct_words:
            if not isinstance(word, dict):
                continue
            raw += _script_expand_word(str(word.get("word") or word.get("text") or "").strip(), word.get("start"), word.get("end"))
    if not raw:
        segments = payload.get("segments") if isinstance(payload, dict) else None
        if isinstance(segments, list):
            for segment in segments:
                if not isinstance(segment, dict):
                    continue
                for word in segment.get("words", []) or []:
                    if not isinstance(word, dict):
                        continue
                    raw += _script_expand_word(str(word.get("word") or word.get("text") or "").strip(), word.get("start"), word.get("end"))
    if not raw:
        # Fallback exakt wie das Referenzskript: Segmenttext als Token verwenden,
        # Zeit wird auf die Token verteilt.
        segments = payload.get("segments") if isinstance(payload, dict) else None
        if isinstance(segments, list):
            for segment in segments:
                if not isinstance(segment, dict):
                    continue
                raw += _script_expand_word(str(segment.get("text") or "").strip(), segment.get("start"), segment.get("end"))
    return _script_finalize_hyp(raw)


def _script_align_lines(lines: list[LyricLine], hyp: list[HypWord], warn_factor: float = 0.6) -> list[str]:
    target: list[str] = []
    tok_line: list[int] = []
    for line_index, line in enumerate(lines):
        for token in line.match_tokens:
            target.append(token)
            tok_line.append(line_index)

    hyp_tokens = [word.norm for word in hyp]
    n = len(target)
    token_starts: list[float | None] = [None] * n
    token_ends: list[float | None] = [None] * n

    matcher = difflib.SequenceMatcher(a=hyp_tokens, b=target, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                token_starts[j1 + offset] = hyp[i1 + offset].start
                token_ends[j1 + offset] = hyp[i1 + offset].end

    last = -1.0
    tolerance = 0.30
    for j in range(n):
        if token_starts[j] is None:
            continue
        if token_starts[j] < last - tolerance:
            token_starts[j] = None
            token_ends[j] = None
        else:
            last = max(last, token_ends[j] if token_ends[j] is not None else token_starts[j])

    for line_index, line in enumerate(lines):
        starts = [token_starts[i] for i in range(n) if tok_line[i] == line_index and token_starts[i] is not None]
        ends = [token_ends[i] for i in range(n) if tok_line[i] == line_index and token_ends[i] is not None]
        if starts and ends:
            line.start = min(starts)
            line.end = max(ends)
            line.matched = True

    return _script_resolve_timeline(lines, warn_factor)


def _script_spread(lines: list[LyricLine], i0: int, i1: int, start: float, end: float) -> None:
    total_weight = sum(lines[i].weight for i in range(i0, i1)) or 1.0
    span = max(end - start, 0.0)
    t = start
    for i in range(i0, i1):
        duration = span * (lines[i].weight / total_weight)
        lines[i].start = t
        lines[i].end = t + duration
        t += duration


def _script_resolve_timeline(lines: list[LyricLine], warn_factor: float) -> list[str]:
    report: list[str] = []
    n = len(lines)
    rates = [
        (line.end - line.start) / line.weight
        for line in lines
        if line.matched and line.start is not None and line.end is not None and line.end > line.start and line.weight > 0
    ]
    seconds_per_weight = sorted(rates)[len(rates) // 2] if rates else 0.35
    anchors = [idx for idx in range(n) if lines[idx].matched]
    if not anchors:
        report.append("WARN: keine einzige Zeile sicher gematcht -- komplette Schaetzung.")
        t = 0.0
        for line in lines:
            duration = line.weight * seconds_per_weight
            line.start, line.end = t, t + duration
            t += duration
        return report

    first = anchors[0]
    if first > 0:
        need = sum(lines[i].weight for i in range(first)) * seconds_per_weight
        end = lines[first].start or need
        _script_spread(lines, 0, first, max(0.0, end - need), end)
        report.append(f"INFO: Zeilen 1-{first} vor erstem Anker geschaetzt.")

    for anchor_a, anchor_b in zip(anchors, anchors[1:]):
        gap = anchor_b - anchor_a - 1
        if gap <= 0:
            continue
        window_start = lines[anchor_a].end or 0.0
        window_end = lines[anchor_b].start or window_start
        window = max(window_end - window_start, 0.0)
        expected = sum(lines[i].weight for i in range(anchor_a + 1, anchor_b)) * seconds_per_weight
        _script_spread(lines, anchor_a + 1, anchor_b, window_start, window_end)
        per_line = window / gap if gap else 0.0
        if expected > 0 and window < expected * warn_factor:
            report.append(
                f"WARN: Zeilen {anchor_a + 2}-{anchor_b} ({gap} Stk.) in {window:.1f}s gequetscht "
                f"(erwartet ~{expected:.1f}s, {per_line:.2f}s/Zeile). "
                "Transkription dort lueckenhaft -> Demucs-Vokalstem / groesseres Modell."
            )

    last = anchors[-1]
    if last < n - 1:
        start = lines[last].end or 0.0
        need = sum(lines[i].weight for i in range(last + 1, n)) * seconds_per_weight
        _script_spread(lines, last + 1, n, start, start + need)
        report.append(f"INFO: Zeilen {last + 2}-{n} nach letztem Anker geschaetzt.")

    return report


def _script_enforce_monotonic(lines: list[LyricLine], min_dur: float = 0.6, gap: float = 0.04) -> None:
    floor = 0.05
    for line in lines:
        if line.start is None:
            line.start = 0.0
        if line.end is None or line.end <= line.start:
            line.end = line.start + min_dur

    for i in range(1, len(lines)):
        prev, cur = lines[i - 1], lines[i]
        if cur.start < prev.end + gap:
            if cur.matched:
                prev.end = max(prev.start + floor, cur.start - gap)
            else:
                cur.start = prev.end + gap
                if cur.end <= cur.start:
                    cur.end = cur.start + floor

    for i, line in enumerate(lines):
        desired_end = max(line.end, line.start + min_dur)
        if i + 1 < len(lines):
            cap = lines[i + 1].start - gap
            line.end = min(desired_end, cap) if cap > line.start else line.start + floor
        else:
            line.end = desired_end
        if line.end <= line.start:
            line.end = line.start + floor


def _script_hyp_to_word_timings(words: list[HypWord]) -> list[WordTiming]:
    return [WordTiming(word=item.norm, start=item.start, end=item.end) for item in words]



def _script_word_weight(word: str) -> float:
    vowel_groups = len(VOWEL_RE.findall(str(word or "")))
    return float(vowel_groups) if vowel_groups > 0 else 0.3


def _script_compute_word_times(lines: list[LyricLine]) -> None:
    for line in lines:
        words = line.words or line.display.split()
        line.words = words
        start = float(line.start or 0.0)
        end = float(line.end or start)
        existing_start = line.wstart or []
        existing_end = line.wend or []
        if existing_start and existing_end and len(existing_start) == len(words):
            clamped_start: list[float] = []
            clamped_end: list[float] = []
            previous = start
            for raw_start, raw_end in zip(existing_start, existing_end):
                ws = min(max(float(raw_start), previous), end)
                we = min(max(float(raw_end), ws), end)
                clamped_start.append(ws)
                clamped_end.append(we)
                previous = we
            line.wstart = clamped_start
            line.wend = clamped_end
            continue

        weights = [_script_word_weight(word) for word in words]
        total = sum(weights) or 1.0
        duration = max(end - start, 0.0)
        cursor = start
        starts: list[float] = []
        ends: list[float] = []
        for weight in weights:
            part = duration * (weight / total)
            starts.append(cursor)
            ends.append(cursor + part)
            cursor += part
        line.wstart = starts
        line.wend = ends


def _script_group_text_len(words: list[str], group: list[int]) -> int:
    return len(" ".join(words[index] for index in group))


def _script_rebalance_short_wrap_groups(words: list[str], groups: list[list[int]], max_chars: int) -> list[list[int]]:
    budget = max(8, int(max_chars or 22))
    balanced = [list(group) for group in groups if group]
    for index in range(1, len(balanced)):
        current = balanced[index]
        previous = balanced[index - 1]
        if len(current) != 1 or len(previous) <= 1:
            continue
        candidate = previous[-1]
        shifted_current = [candidate, *current]
        if _script_group_text_len(words, shifted_current) > budget:
            continue
        balanced[index - 1] = previous[:-1]
        balanced[index] = shifted_current
    return [group for group in balanced if group]


def _script_wrap_groups(words: list[str], max_chars: int) -> list[list[int]]:
    groups: list[list[int]] = []
    current: list[int] = []
    current_len = 0
    budget = max(8, int(max_chars or 22))
    for index, word in enumerate(words):
        addition = len(word) + (1 if current else 0)
        if current and current_len + addition > budget:
            groups.append(current)
            current = []
            current_len = 0
            addition = len(word)
        current.append(index)
        current_len += addition
    if current:
        groups.append(current)
    return _script_rebalance_short_wrap_groups(words, groups, budget)


def _script_to_portrait_srt(lines: list[LyricLine], max_chars: int = 22, min_dur: float = 0.6) -> str:
    blocks: list[str] = []
    index = 1
    for line in lines:
        if not line.words:
            continue
        starts = line.wstart or []
        ends = line.wend or []
        if len(starts) != len(line.words) or len(ends) != len(line.words):
            continue
        for group in _script_wrap_groups(line.words, max_chars):
            text = " ".join(line.words[pos] for pos in group).strip()
            if not text:
                continue
            start = float(starts[group[0]])
            end = float(ends[group[-1]])
            if end <= start:
                end = start + min_dur
            blocks.append(f"{index}\n{_srt_timestamp(start)} --> {_srt_timestamp(end)}\n{text}")
            index += 1
    return ("\n\n".join(blocks).strip() + "\n") if blocks else ""


def segments_to_half_srt(segments: list[dict[str, Any]], max_chars: int = 22, min_dur: float = 0.6) -> str:
    """Fallback-Half-SRT aus Segmentzeiten, z. B. nach manuellen Editor-Änderungen."""
    lines: list[LyricLine] = []
    for idx, segment in enumerate(segments or []):
        text = str(segment.get("text") or "").strip()
        words = text.split()
        if not text or not words:
            continue
        line = LyricLine(
            index=idx,
            display=text,
            words=words,
            tok_counts=[len(_script_tokenize_match(word)) for word in words],
            match_tokens=_script_tokenize_match(text),
            weight=_script_syllable_weight(text),
            matched=True,
            start=_seconds(segment.get("start"), 0.0),
            end=_seconds(segment.get("end"), _seconds(segment.get("start"), 0.0) + min_dur),
            wstart=[],
            wend=[],
        )
        lines.append(line)
    _script_compute_word_times(lines)
    return _script_to_portrait_srt(lines, max_chars=max_chars, min_dur=min_dur)


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    return text.strip()


def _nested_values(payload: Any, keys: set[str]) -> list[str]:
    found: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if str(key).lower() in keys:
                text = _clean_text(value)
                if text:
                    found.append(text)
            found.extend(_nested_values(value, keys))
    elif isinstance(payload, list):
        for item in payload:
            found.extend(_nested_values(item, keys))
    return found


def _first_non_empty(*values: Any) -> str:
    for value in values:
        text = _clean_text(value)
        if text:
            return text
    return ""


SRT_CLEANUP_STAGE_MARKERS = {
    "atmen", "atem", "leises atmen", "laut atmen", "raumhall", "hall", "nachhall", "echo", "reverb",
    "geräusch", "geraeusch", "sound", "sfx", "fx", "effekt", "noise", "static", "knistern", "rauschen",
    "applaus", "klatschen", "lachen", "lacht", "laugh", "laughs", "breath", "breathing", "inhale", "exhale",
    "instrumental", "beat", "pause", "stille", "silence", "crowd", "ambience", "ambiente", "intro sound",
    "whisper", "shout", "spoken", "voice", "vocal", "backing", "chor", "choir", "adlib", "adlibs",
    "sample", "drop", "break", "bridge", "build", "buildup", "fade", "fade in", "fade out",
}
SRT_CLEANUP_SECTION_HINT_RE = re.compile(
    r"(?i)^\s*(intro|outro|verse|strophe|hook|chorus|refrain|bridge|pre[-\s]?chorus|post[-\s]?chorus|"
    r"part|teil|drop|break|interlude|spoken|adlibs?|background|backing|choir|instrumental|"
    r"male|female|rap|sung|gesungen|deutsch|german|english|patois|dancehall|energy|bpm|style|genre)\b"
)
SRT_CLEANUP_STAGE_HINT_RE = re.compile(
    r"(?i)\b(raum\s*hall|raumhall|hall|reverb|echo|leises?\s+atmen|atmen|atem|breath(?:ing)?|inhale|exhale|"
    r"sfx|fx|sound|geräusch|geraeusch|knistern|rauschen|applaus|klatschen|lacht|lachen|laughs?|"
    r"instrumental|beat|pause|stille|silence|crowd|ambien(?:ce|te)|whisper|shout|spoken|voice|vocal|"
    r"backing|choir|chor|sample|drop|break|build(?:up)?|fade\s*(?:in|out)?)\b"
)
SRT_CLEANUP_WRAPPED_RE = re.compile(r"([\(\[\{])([^\(\)\[\]\{\}\n]{1,120})([\)\]\}])")
SRT_CLEANUP_ANY_BRACKET_RE = re.compile(r"[\[\]\(\)\{\}]")
SRT_CLEANUP_STAR_WRAPPED_RE = re.compile(r"\*([^*\n]{1,120})\*")


def _normalize_srt_tag_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(text or "")).lower()
    normalized = re.sub(r"[\[\]{}().,_:;|/!¡?¿+*\"“”'`´~-]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized




SRT_VISIBLE_CONSONANT_STRETCH_RE = re.compile(r"([bcdfghjklmnpqrstvwxyzßBCDFGHJKLMNPQRSTVWXYZẞ])\1{2,}")


def _normalize_srt_visible_word_stretches(text: str, normalized: list[str] | None = None) -> str:
    """Normalisiert offensichtliche SRT-Anzeige-Artefakte wie ``Nachttt`` -> ``Nacht``.

    Die Regel ist absichtlich konservativ: Nur Konsonanten mit mindestens drei
    Wiederholungen werden gekürzt. Vokal-Stretchings wie ``ohhh``/``yeahhh``
    bleiben damit weitgehend unangetastet, während typische Suno-/Lyrics-
    Artefakte wie ``Einnn teilll derrr Nachttt`` zuverlässig lesbar werden.
    """
    value = str(text or "")
    if not value:
        return ""

    def repl(match: re.Match[str]) -> str:
        original = match.group(0)
        replacement = match.group(1)
        if normalized is not None and original != replacement:
            normalized.append(f"{original}->{replacement}")
        return replacement

    return SRT_VISIBLE_CONSONANT_STRETCH_RE.sub(repl, value)

def _looks_like_srt_stage_direction(text: str) -> bool:
    normalized = _normalize_srt_tag_text(text)
    if not normalized:
        return False
    if normalized in SRT_CLEANUP_STAGE_MARKERS:
        return True
    words = normalized.split()
    return len(words) <= 10 and bool(SRT_CLEANUP_STAGE_HINT_RE.search(normalized))


def _looks_like_srt_structure_tag(text: str) -> bool:
    normalized = _normalize_srt_tag_text(text)
    if not normalized:
        return False
    # Reine Struktur-/Prompttags wie "[Verse 1 | German Male Rap | Energy: High]"
    # sollen niemals als Untertitelzeile erscheinen.
    if "|" in str(text or ""):
        return True
    return bool(SRT_CLEANUP_SECTION_HINT_RE.search(normalized))


def _clean_srt_text_tags_from_line(line: str, removed: list[str] | None = None, unwrapped: list[str] | None = None, normalized: list[str] | None = None) -> str:
    """Entfernt SRT-unfähige Prompt-Tags aus einer einzelnen Textzeile.

    Regeln:
    - Reine Struktur-/Regiezeilen werden entfernt.
    - Nicht gesungene SFX-/Atmo-Hinweise in Klammern werden entfernt.
    - Potenziell gesungene Klammer-Adlibs wie ``(Alla hopp!)`` bleiben als Text erhalten,
      aber ohne Klammern, damit die SRT niemals sichtbare Prompt-Tags enthält.
    """
    text = str(line or "").strip()
    if not text:
        return ""

    # Ganze Zeile besteht nur aus einem oder mehreren Struktur-Tags.
    if re.fullmatch(r"(?:\[[^\]]+\]\s*)+", text):
        if removed is not None:
            removed.append(text)
        return ""

    # Ganze Zeile ist ein einzelnes Klammer-/Brace-Tag.
    full = SRT_CLEANUP_WRAPPED_RE.fullmatch(text)
    if full:
        inner = full.group(2).strip()
        if _looks_like_srt_stage_direction(inner) or _looks_like_srt_structure_tag(inner):
            if removed is not None:
                removed.append(text)
            return ""
        if unwrapped is not None:
            unwrapped.append(text)
        return re.sub(r"\s+", " ", inner).strip()

    # Führende Struktur-Tags entfernen, z. B. "[Hook] Wir gehen raus".
    def replace_leading_square(match: re.Match[str]) -> str:
        if removed is not None:
            removed.append(match.group(0).strip())
        return ""

    previous = None
    while previous != text:
        previous = text
        text = re.sub(r"^\s*\[([^\]]{1,160})\]\s*", replace_leading_square, text).strip()

    def replace_wrapped(match: re.Match[str]) -> str:
        original = match.group(0).strip()
        inner = match.group(2).strip()
        if _looks_like_srt_stage_direction(inner) or _looks_like_srt_structure_tag(inner):
            if removed is not None:
                removed.append(original)
            return " "
        if unwrapped is not None:
            unwrapped.append(original)
        return f" {inner} "

    text = SRT_CLEANUP_WRAPPED_RE.sub(replace_wrapped, text)

    def replace_star_wrapped(match: re.Match[str]) -> str:
        original = match.group(0).strip()
        inner = match.group(1).strip()
        if _looks_like_srt_stage_direction(inner) or _looks_like_srt_structure_tag(inner):
            if removed is not None:
                removed.append(original)
            return " "
        if unwrapped is not None:
            unwrapped.append(original)
        return f" {inner} "

    text = SRT_CLEANUP_STAR_WRAPPED_RE.sub(replace_star_wrapped, text)

    # Letzte Absicherung: Keine Klammerzeichen in SRT-Texten belassen.
    if SRT_CLEANUP_ANY_BRACKET_RE.search(text):
        if unwrapped is not None:
            unwrapped.append(text)
        text = SRT_CLEANUP_ANY_BRACKET_RE.sub("", text)

    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    text = re.sub(r"[ \t]{2,}", " ", text).strip()
    text = _normalize_srt_visible_word_stretches(text, normalized=normalized)
    text = re.sub(r"[ \t]{2,}", " ", text).strip()
    return text


def _strip_control_markup_from_line(line: str) -> str:
    """Entfernt Suno-/Prompt-Steuerzeichen aus Lyrics für sichtbare SRT-Segmente."""
    return _clean_srt_text_tags_from_line(line)


def _spoken_lyrics_lines(lyrics: str) -> list[str]:
    text = _clean_text(lyrics)
    if not text:
        return []
    lines: list[str] = []
    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = _strip_control_markup_from_line(raw_line)
        if line:
            lines.append(line)
    return lines


def deterministic_prepare_lyrics_for_srt(lyrics: str) -> tuple[str, dict[str, Any]]:
    """Deterministischer Pflichtfilter vor dem SRT-Alignment.

    Dieser Filter ist bewusst strenger als der optionale KI-Schritt: SRT-Ausgaben
    dürfen keine Prompt-Tags, Struktur-Tags oder sichtbare Klammer-Markups enthalten.
    Gesungene Adlibs in Klammern werden nicht verworfen, sondern entklammert.
    """
    source = _clean_text(lyrics)
    if not source:
        return "", {
            "enabled": True,
            "method": "deterministic_strict_tags",
            "changed": False,
            "removed_items": [],
            "removed_count": 0,
            "unwrapped_items": [],
            "unwrapped_count": 0,
        }

    removed: list[str] = []
    unwrapped: list[str] = []
    normalized_stretches: list[str] = []
    cleaned_lines: list[str] = []
    for raw_line in source.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        cleaned = _clean_srt_text_tags_from_line(raw_line.rstrip(), removed=removed, unwrapped=unwrapped, normalized=normalized_stretches)
        if cleaned:
            cleaned_lines.append(cleaned)
        elif raw_line.strip():
            # Leere Ergebniszeilen nur für tatsächlich entfernte Prompt-/Regiezeilen nicht übernehmen.
            continue
        else:
            cleaned_lines.append("")

    cleaned_text = "\n".join(cleaned_lines)
    cleaned_text = re.sub(r"\n{3,}", "\n\n", cleaned_text).strip()
    changed = cleaned_text != source
    return cleaned_text, {
        "enabled": True,
        "method": "deterministic_strict_tags",
        "changed": changed,
        "removed_items": removed[:160],
        "removed_count": len(removed),
        "unwrapped_items": unwrapped[:160],
        "unwrapped_count": len(unwrapped),
        "normalized_stretches": normalized_stretches[:160],
        "normalized_stretch_count": len(normalized_stretches),
        "source_chars": len(source),
        "clean_chars": len(cleaned_text),
        "tag_cleanup_strict": True,
    }


def _structure_markers_from_line(line: str) -> list[dict[str, str]]:
    markers: list[dict[str, str]] = []
    for match in re.finditer(r"\[([^\]\n]{1,260})\]", str(line or "")):
        marker = extract_structure_marker(match.group(1))
        if marker:
            markers.append(marker)
    return markers


def _source_structure_lyrics_lines(source_lyrics: str) -> list[dict[str, Any]]:
    """Map original tagged lyrics to the visible lines used by SRT alignment.

    The SRT pipeline intentionally removes prompt/structure tags before alignment.
    This companion parser keeps the original section context, then applies the
    same visible-line cleanup so generated SRT segment numbers can be mapped back
    by order without leaking tags into subtitle text.
    """

    current_marker: dict[str, str] | None = None
    saw_explicit_marker = False
    mapped: list[dict[str, Any]] = []

    for raw_line in _clean_text(source_lyrics).replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = str(raw_line or "").strip()
        if not line:
            continue

        markers = _structure_markers_from_line(line)
        if markers:
            current_marker = markers[0]
            saw_explicit_marker = True

        visible = _clean_srt_text_tags_from_line(line)
        if not visible:
            continue

        marker = current_marker or {"label": "Intro", "type": "intro"}
        mapped.append({
            "text": visible,
            "marker": marker,
            "explicit": bool(saw_explicit_marker),
        })

    if not saw_explicit_marker:
        return []
    return mapped


def _line_entry_for_srt_segment(
    segment: dict[str, Any],
    source_lines: list[dict[str, Any]],
    cursor: int,
) -> tuple[dict[str, Any] | None, int]:
    segment_token_list = _lyrics_tokens(str(segment.get("text") or ""))
    segment_tokens = " ".join(segment_token_list)
    source_line = segment.get("source_line")
    try:
        index = int(source_line) - 1
    except (TypeError, ValueError):
        index = -1

    def line_token_list(idx: int) -> list[str]:
        return _lyrics_tokens(str(source_lines[idx].get("text") or ""))

    def prefix_repeat(candidate_tokens: list[str]) -> bool:
        return (
            bool(segment_token_list)
            and len(segment_token_list) < len(candidate_tokens)
            and len(segment_token_list) <= 6
            and candidate_tokens[:len(segment_token_list)] == segment_token_list
        )

    def match_score(candidate_tokens: list[str]) -> float:
        candidate_text = " ".join(candidate_tokens)
        if not segment_tokens or not candidate_text:
            return 0.0
        if prefix_repeat(candidate_tokens):
            return 0.98
        return _similarity_score(segment_tokens, candidate_text)

    def next_cursor_for(idx: int, candidate_tokens: list[str]) -> int:
        if prefix_repeat(candidate_tokens):
            return max(cursor, idx)
        return max(cursor, idx + 1)

    if 0 <= index < len(source_lines):
        candidate_tokens = line_token_list(index)
        if not segment_tokens or match_score(candidate_tokens) >= 0.45:
            return source_lines[index], next_cursor_for(index, candidate_tokens)

    if not segment_tokens:
        if cursor < len(source_lines):
            return source_lines[cursor], cursor + 1
        return None, cursor

    best_idx: int | None = None
    best_score = 0.0
    best_tokens: list[str] = []
    search_start = max(0, cursor - 2)
    search_end = min(len(source_lines), cursor + 10)
    for idx in range(search_start, search_end):
        candidate_tokens = line_token_list(idx)
        score = match_score(candidate_tokens)
        if idx < cursor and score < 0.82:
            score *= 0.92
        if score > best_score:
            best_score = score
            best_idx = idx
            best_tokens = candidate_tokens

    if best_idx is not None and best_score >= 0.55:
        return source_lines[best_idx], next_cursor_for(best_idx, best_tokens)
    if cursor < len(source_lines):
        return source_lines[cursor], cursor + 1
    return None, cursor


def build_structure_segments_from_srt_alignment(
    source_lyrics: str,
    srt_segments: list[dict[str, Any]],
    duration_seconds: float | int | None,
) -> list[dict[str, Any]]:
    source_lines = _source_structure_lyrics_lines(source_lyrics)
    if not source_lines or not srt_segments:
        return []

    duration = float(duration_seconds or 0.0)
    cursor = 0
    structure: list[dict[str, Any]] = []

    for segment in srt_segments:
        if not isinstance(segment, dict):
            continue
        entry, cursor = _line_entry_for_srt_segment(segment, source_lines, cursor)
        if not entry:
            continue
        marker = entry.get("marker") if isinstance(entry.get("marker"), dict) else None
        if not marker:
            continue
        start = _seconds(segment.get("start"), -1.0)
        end = _seconds(segment.get("end"), -1.0)
        if start < 0 or end <= start:
            continue
        if duration > 0:
            start = max(0.0, min(duration, start))
            end = max(0.0, min(duration, end))
        if end <= start:
            continue

        label = str(marker.get("label") or "").strip()
        marker_type = str(marker.get("type") or "").strip()
        if not label or not marker_type:
            continue

        current = structure[-1] if structure else None
        if current and current.get("label") == label and current.get("type") == marker_type:
            current["end"] = round(max(float(current.get("end") or end), end), 3)
            continue
        structure.append({
            "label": label,
            "type": marker_type,
            "start": round(start, 3),
            "end": round(end, 3),
            "source": "srt_alignment",
        })

    return _expand_structure_segments_to_arrangement_boundaries(structure, duration)


def _expand_structure_segments_to_arrangement_boundaries(
    structure: list[dict[str, Any]],
    duration_seconds: float | int | None,
) -> list[dict[str, Any]]:
    if not structure:
        return []

    duration = float(duration_seconds or 0.0)
    adjusted: list[dict[str, Any]] = []
    raw_segments = [
        {**segment, "start": float(segment.get("start") or 0.0), "end": float(segment.get("end") or 0.0)}
        for segment in structure
        if float(segment.get("end") or 0.0) > float(segment.get("start") or 0.0)
    ]
    for idx, segment in enumerate(raw_segments):
        raw_start = float(segment["start"])
        raw_end = float(segment["end"])
        start = max(0.0, raw_start - STRUCTURE_SEGMENT_LEAD_IN_SECONDS)

        if adjusted:
            previous = adjusted[-1]
            previous_raw_end = float(raw_segments[idx - 1].get("end") or previous.get("end") or 0.0)
            # Keep section jumps musical without overlapping the previous sung line.
            start = max(start, previous_raw_end)
            if start >= raw_start:
                start = min(raw_start, max(previous_raw_end, raw_start - 0.05))
            start = max(float(previous.get("start") or 0.0) + 0.05, start)
            previous["end"] = round(start, 3)

        adjusted.append({
            **segment,
            "start": round(start, 3),
            "end": round(max(raw_end, start + 0.05), 3),
        })

    if duration > 0 and adjusted:
        max_start = max(0.0, duration - 0.05)
        adjusted[0]["start"] = round(max(0.0, min(max_start, float(adjusted[0]["start"]))), 3)
        for idx, segment in enumerate(adjusted):
            start = max(0.0, min(max_start, float(segment.get("start") or 0.0)))
            if idx < len(adjusted) - 1:
                next_start = max(start + 0.05, min(duration, float(adjusted[idx + 1].get("start") or duration)))
                segment["end"] = round(next_start, 3)
            else:
                segment["end"] = round(duration, 3)
            segment["start"] = round(start, 3)

    return [
        {**segment, "start": round(float(segment["start"]), 3), "end": round(float(segment["end"]), 3)}
        for segment in adjusted
        if float(segment.get("end") or 0) > float(segment.get("start") or 0)
    ]


def _store_structure_segments_from_srt_alignment(
    db: Session,
    asset: AudioAsset,
    source_lyrics: str,
    srt_segments: list[dict[str, Any]],
    duration_seconds: float | int | None,
) -> list[dict[str, Any]]:
    effective_duration = duration_seconds or asset.duration_seconds
    structure_segments = build_structure_segments_from_srt_alignment(source_lyrics, srt_segments, effective_duration)
    if not structure_segments:
        return []

    asset.structure_segments_json = structure_segments
    if isinstance(asset.waveform_json, dict):
        waveform = dict(asset.waveform_json)
        waveform["segments"] = structure_segments
        if effective_duration:
            waveform["duration_seconds"] = effective_duration
        asset.waveform_json = waveform
    db.add(asset)

    if asset.song_id:
        song = db.query(Song).filter(Song.id == asset.song_id, Song.is_deleted.is_(False)).first()
        if song:
            song.structure_segments_json = structure_segments
            if isinstance(song.waveform_json, dict):
                waveform = dict(song.waveform_json)
                waveform["segments"] = structure_segments
                if effective_duration:
                    waveform["duration_seconds"] = effective_duration
                song.waveform_json = waveform
            db.add(song)

    return structure_segments


def _sanitize_ai_clean_lyrics_result(value: Any, fallback: str) -> str:
    text = _clean_text(value)
    if not text:
        return fallback
    # Schutz gegen versehentliche JSON-/Markdown-Wrapper oder Erklärtexte.
    text = re.sub(r"^```(?:text|lyrics)?\s*", "", text.strip(), flags=re.I)
    text = re.sub(r"\s*```$", "", text.strip())
    spoken = _spoken_lyrics_lines(text)
    fallback_spoken = _spoken_lyrics_lines(fallback)
    if fallback_spoken and len(spoken) < max(1, int(len(fallback_spoken) * 0.45)):
        return fallback
    return text.strip()


def _srt_cleanup_fingerprint(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(text or "")).lower()
    normalized = normalized.replace("’", "'").replace("`", "'")
    normalized = re.sub(r"[^a-z0-9äöüß']+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _looks_like_plain_srt_structure_line(text: str) -> bool:
    normalized = _normalize_srt_tag_text(text)
    if not normalized:
        return True
    if re.fullmatch(r"(?:intro|outro|verse|strophe|hook|chorus|refrain|bridge|pre chorus|post chorus|part|teil)\s*\d*", normalized):
        return True
    if _looks_like_style_only_prompt(text):
        return True
    return False


def _content_line_for_ai_preservation(raw_line: str) -> str:
    cleaned = _clean_srt_text_tags_from_line(str(raw_line or "").rstrip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned or _looks_like_plain_srt_structure_line(cleaned):
        return ""
    words = re.findall(r"[A-Za-zÄÖÜäöüß0-9']+", cleaned)
    if not words:
        return ""
    # Reine technische Feldnamen/Promptreste sollen nicht wiederhergestellt werden.
    normalized = _srt_cleanup_fingerprint(cleaned)
    if normalized in {"music", "style", "genre", "energy", "bpm", "vocal", "voice", "fx", "sfx"}:
        return ""
    return cleaned


def _restore_ai_removed_content_lines(source_text: str, ai_text: str) -> tuple[str, dict[str, Any]]:
    """Stellt gesprochene/gesungene Inhaltzeilen wieder her, die die KI zu aggressiv entfernt hat.

    Der KI-Schritt darf Tags, Regie und SFX entfernen. Er darf aber keine echten
    Inhaltszeilen wie ein gesprochenes Intro löschen. Der Guard arbeitet bewusst
    deterministisch auf der bereits tagbereinigten Quelle und fügt nur solche
    Zeilen wieder ein, die nach unserem Pflichtfilter sichtbare SRT-Zeilen wären.
    """
    source_lines = [_content_line_for_ai_preservation(line) for line in _clean_text(source_text).splitlines()]
    source_lines = [line for line in source_lines if line]
    if not source_lines:
        return ai_text, {"enabled": True, "changed": False, "restored_count": 0, "restored_items": []}

    output_lines = [line.strip() for line in _clean_text(ai_text).splitlines() if line.strip()]
    output_by_fp: dict[str, list[tuple[int, str]]] = {}
    for idx, line in enumerate(output_lines):
        fp = _srt_cleanup_fingerprint(line)
        if fp:
            output_by_fp.setdefault(fp, []).append((idx, line))

    rebuilt: list[str] = []
    restored: list[str] = []
    used_output_indexes: set[int] = set()

    for source_line in source_lines:
        source_fp = _srt_cleanup_fingerprint(source_line)
        candidates = output_by_fp.get(source_fp, [])
        chosen: tuple[int, str] | None = None
        for candidate in candidates:
            if candidate[0] not in used_output_indexes:
                chosen = candidate
                break
        if chosen is not None:
            used_output_indexes.add(chosen[0])
            rebuilt.append(chosen[1])
        else:
            restored.append(source_line)
            rebuilt.append(source_line)

    rebuilt_fingerprints = {_srt_cleanup_fingerprint(line) for line in rebuilt if _srt_cleanup_fingerprint(line)}
    # Falls die KI zusätzliche gültige Zeilen ergänzt/erhalten hat, die nicht über
    # die Source-Schleife übernommen wurden, hängen wir sie defensiv hinten an.
    for idx, out_line in enumerate(output_lines):
        out_fp = _srt_cleanup_fingerprint(out_line)
        if idx not in used_output_indexes and out_fp and out_fp not in rebuilt_fingerprints:
            rebuilt.append(out_line)
            rebuilt_fingerprints.add(out_fp)

    if not restored:
        return ai_text, {"enabled": True, "changed": False, "restored_count": 0, "restored_items": []}

    cleaned = "\n".join(line for line in rebuilt if line.strip())
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, {
        "enabled": True,
        "changed": True,
        "restored_count": len(restored),
        "restored_items": restored[:80],
    }


async def prepare_lyrics_for_srt_alignment(db: Session, asset: AudioAsset, lyrics: str, admin_settings: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Bereitet Lyrics vor dem SRT-Alignment auf.

    Ablauf:
    1. Deterministischer Filter entfernt bekannte SFX-/Regieklammern wie `(leises atmen)` oder `(raumhall)`.
    2. Optionaler KI-Schritt nutzt denselben Default-Provider und dasselbe Modell wie der KI-Chat im Admin-Panel.
    3. Bei Providerfehlern bleibt der lokale Filter aktiv, damit die SRT-Erzeugung nicht unnötig abbricht.
    """
    deterministic_text, deterministic_info = deterministic_prepare_lyrics_for_srt(lyrics)
    base_text = deterministic_text or _clean_text(lyrics)
    info: dict[str, Any] = {
        "enabled": bool(admin_settings.get("srt_ai_cleanup_enabled", True)),
        "deterministic": deterministic_info,
        "ai": {"enabled": False, "used": False},
        "source_chars": len(_clean_text(lyrics)),
        "clean_chars": len(base_text),
    }

    if not info["enabled"]:
        info["method"] = "deterministic_only_disabled_ai"
        return base_text, info

    provider = str(admin_settings.get("default_provider") or "").strip().lower()
    model = str(admin_settings.get("default_model") or "").strip()
    if not provider or not model:
        info["method"] = "deterministic_no_ai_config"
        info["ai"] = {"enabled": True, "used": False, "error": "Kein KI-Provider/Modell konfiguriert."}
        return base_text, info

    system_prompt = (
        "Du bist ein konservativer Vorfilter für Songtexte vor einer SRT-Erzeugung. "
        "Deine Aufgabe ist ausschließlich, Lyrics für Untertitel zu bereinigen. "
        "Entferne Regie-, SFX-, Mixing-, Atmo-, Struktur- und Performance-Hinweise aus sichtbaren Textzeilen, "
        "z. B. (leises atmen), (raumhall), (echo), [SFX], [Instrumental], [Beat Pause], [Verse], [Hook]. "
        "SRT-Text darf keine eckigen, runden oder geschweiften Klammern als Tags enthalten. "
        "Wenn ein geklammerter Ausdruck gesungen oder gesprochen wird, entferne nur die Klammern und behalte den Text, "
        "z. B. (Alla hopp!) wird zu Alla hopp!. "
        "Wichtig: Gesprochene Intro-, Outro-, Skit-, Computer-, Roboter-, Voiceover- oder System-Zeilen sind Lyrics-Inhalt und müssen erhalten bleiben, "
        "z. B. 'Boot sequence initialized.', 'Unknown process detected.', 'Firewall breached.' oder 'System integrity compromised.'. "
        "Entferne nur die beschreibenden Tags darüber, nicht den folgenden gesprochenen Inhalt. "
        "Ändere keine Reihenfolge, übersetze nichts und erfinde keine Zeilen. "
        "Offensichtliche Wiederholungs-/Tipp-Artefakte in normalen Wörtern darfst du konservativ normalisieren, "
        "z. B. 'Ein teil der Nachttt' -> 'Ein teil der Nacht' und 'Einnn teilll derrr Nachttt' -> 'Ein teil der Nacht'. "
        "Lass künstlerische Vokal-Adlibs und bewusst gedehnte Ausrufe unverändert, wenn sie nicht klar ein normales Wort beschädigen."
    )
    payload = {
        "mode": "srt_lyrics_cleanup",
        "song_title": _asset_title(asset, f"AudioAsset {asset.id}"),
        "audio_asset_id": asset.id,
        "song_id": asset.song_id,
        "rules": [
            "Alle sichtbaren SRT-Zeilen müssen tagfrei sein: keine [Tags], keine (Tags), keine {Tags}.",
            "Nicht gesungene Regie-/SFX-/Atmo-/Strukturhinweise entfernen.",
            "Gesprochene oder gesungene Inhaltszeilen niemals löschen, auch wenn sie nach Computer-, Roboter-, Skit- oder Intro-Text klingen.",
            "Beispiele für zu erhaltende Inhaltszeilen: Boot sequence initialized.; Unknown process detected.; Firewall breached.; System integrity compromised.",
            "Geklammerte gesungene oder gesprochene Wörter entklammern, nicht löschen, z. B. (Alla hopp!) -> Alla hopp!.",
            "Keine Zeilen umdichten, keine Übersetzung, keine neuen Wörter.",
            "Offensichtliche beschädigte Wort-Stretchings konservativ normalisieren: Nachttt -> Nacht, Einnn teilll derrr Nachttt -> Ein teil der Nacht.",
            "Antwort JSON: clean_lyrics, removed_items, warnings.",
        ],
        "lyrics": base_text,
        "expected_output": {
            "clean_lyrics": "bereinigter Songtext als String",
            "removed_items": ["entfernte Hinweise"],
            "warnings": ["optionale Hinweise"],
        },
    }
    try:
        result = await AiChatService().run_json_task(
            provider=provider,
            model=model,
            system_prompt=system_prompt,
            instruction_payload=payload,
            profile_options={"max_output_tokens": 6000},
        )
        data = result.data if isinstance(result.data, dict) else {}
        clean_lyrics = _sanitize_ai_clean_lyrics_result(data.get("clean_lyrics") or data.get("lyrics") or data.get("canvas_text"), base_text)
        # Nach KI erneut deterministisch filtern, falls die KI offensichtliche SFX-Klammern stehen lässt.
        final_lyrics, final_info = deterministic_prepare_lyrics_for_srt(clean_lyrics)
        final_lyrics = final_lyrics or clean_lyrics
        # Zusätzlicher Sicherheitsgurt: Die KI darf echte gesprochene/gesungene
        # Inhaltszeilen nicht entfernen. Das schützt u. a. Spoken-Intros wie
        # "Boot sequence initialized." vor zu aggressiver Bereinigung.
        final_lyrics, preservation_info = _restore_ai_removed_content_lines(base_text, final_lyrics)
        info.update({
            "method": "ai_plus_deterministic",
            "clean_chars": len(final_lyrics),
            "ai": {
                "enabled": True,
                "used": True,
                "provider": provider,
                "model": model,
                "removed_items": data.get("removed_items") if isinstance(data.get("removed_items"), list) else [],
                "warnings": data.get("warnings") if isinstance(data.get("warnings"), list) else [],
                "raw_text_chars": len(result.raw_text or ""),
            },
            "post_ai_deterministic": final_info,
            "ai_content_preservation": preservation_info,
        })
        return final_lyrics, info
    except AiProviderError as exc:
        info["method"] = "deterministic_ai_provider_failed"
        info["ai"] = {"enabled": True, "used": False, "provider": provider, "model": model, "error": str(exc)}
        return base_text, info
    except Exception as exc:
        info["method"] = "deterministic_ai_failed"
        info["ai"] = {"enabled": True, "used": False, "provider": provider, "model": model, "error": str(exc)}
        return base_text, info


def _looks_like_instrumental_marker(text: str) -> bool:
    normalized = re.sub(r"[\[\]().,_\-:;|]+", " ", str(text or "").lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized:
        return False
    instrumental_markers = {
        "instrumental",
        "no vocals",
        "ohne gesang",
        "ohne vocals",
        "nur instrumental",
        "instrumental only",
    }
    return normalized in instrumental_markers


def _looks_like_style_only_prompt(text: str) -> bool:
    normalized = str(text or "").lower()
    if "\n" in normalized:
        return False
    comma_count = normalized.count(",")
    style_markers = [
        "bpm",
        "boom bap",
        "trap",
        "drill",
        "house",
        "techno",
        "male rap",
        "female vocal",
        "no vocals",
        "instrumental",
        "lo-fi",
        "reverb",
        "snare",
        "bass",
        "kick",
        "synth",
        "style",
    ]
    marker_hits = sum(1 for marker in style_markers if marker in normalized)
    return comma_count >= 4 and marker_hits >= 2


def _usable_lyrics_candidate(value: Any, *, authoritative: bool = False) -> str:
    text = _clean_text(value)
    if not text or _looks_like_instrumental_marker(text):
        return ""

    if authoritative:
        return text

    spoken_lines = _spoken_lyrics_lines(text)
    if len(spoken_lines) >= 2:
        return text

    if len(spoken_lines) == 1:
        line = spoken_lines[0]
        words = re.findall(r"[\wÄÖÜäöüß']+", line)
        if len(words) >= 6 and not _looks_like_style_only_prompt(line):
            return text

    return ""


def _first_usable_lyrics(*values: Any, authoritative: bool = False) -> str:
    for value in values:
        text = _usable_lyrics_candidate(value, authoritative=authoritative)
        if text:
            return text
    return ""


def _is_manual_import_asset(asset: AudioAsset, metadata: dict[str, Any]) -> bool:
    source = str(metadata.get("source") or "").strip().lower()
    audio_id = str(getattr(asset, "audio_id", "") or "").strip().lower()
    candidate = metadata.get("candidate") if isinstance(metadata.get("candidate"), dict) else {}
    model = str(candidate.get("model") or "").strip().lower()
    return source == "manual_import" or bool(metadata.get("manual_import")) or audio_id.startswith("manual-") or model == "manual_import"


def _manual_import_prompt_is_lyrics(candidate: dict[str, Any], request_payload: dict[str, Any], song: Song | None) -> bool:
    lyrics_values = [candidate.get("lyrics"), candidate.get("text"), request_payload.get("lyrics"), getattr(song, "lyrics", None) if song else None]
    prompt_values = [candidate.get("prompt"), request_payload.get("prompt"), getattr(song, "prompt", None) if song else None]
    normalized_lyrics = {_clean_text(value) for value in lyrics_values if _clean_text(value)}
    normalized_prompts = [_clean_text(value) for value in prompt_values if _clean_text(value)]
    return any(prompt in normalized_lyrics for prompt in normalized_prompts)


def resolve_lyrics_for_audio_asset(db: Session, audio_asset_id: int, manual_override: str | None = None, *, allow_missing: bool = False) -> str:
    override = _usable_lyrics_candidate(manual_override, authoritative=True)
    if override:
        return override

    asset = db.query(AudioAsset).filter(AudioAsset.id == audio_asset_id, AudioAsset.is_deleted.is_(False)).first()
    if not asset:
        raise HTTPException(status_code=404, detail="AudioAsset wurde nicht gefunden.")

    metadata = asset.metadata_json if isinstance(asset.metadata_json, dict) else {}
    candidate = metadata.get("candidate") if isinstance(metadata.get("candidate"), dict) else {}
    request_payload = metadata.get("request_payload") if isinstance(metadata.get("request_payload"), dict) else {}
    song = db.query(Song).filter(Song.id == asset.song_id, Song.is_deleted.is_(False)).first() if asset.song_id else None
    is_manual_import = _is_manual_import_asset(asset, metadata)

    if is_manual_import:
        # Bei manuell importierten Audios ist der AudioAsset selbst die Autorität.
        # Kein Fallback auf SunoTask-/Projekt-Daten, weil sonst alter/fremder Text
        # als SRT angezeigt werden kann.
        lyrics = _first_usable_lyrics(
            candidate.get("lyrics"),
            candidate.get("text"),
            request_payload.get("lyrics"),
            getattr(song, "lyrics", None) if song else None,
            authoritative=True,
        )
        if lyrics:
            return lyrics

        # Prompt nur nutzen, wenn er eindeutig derselbe Inhalt wie der gespeicherte
        # Lyrics-Text ist. Freie Beschreibungs-Prompts werden bewusst nicht als
        # Lyrics missbraucht.
        if _manual_import_prompt_is_lyrics(candidate, request_payload, song):
            lyrics = _first_usable_lyrics(
                candidate.get("prompt"),
                request_payload.get("prompt"),
                getattr(song, "prompt", None) if song else None,
            )
            if lyrics:
                return lyrics

        if allow_missing:
            return ""
        raise HTTPException(status_code=422, detail="Für dieses manuell importierte Audio wurde kein verwertbarer Songtext gefunden. Bitte Songtext im Import oder in den Songdetails hinterlegen.")

    if song:
        lyrics = _first_usable_lyrics(getattr(song, "lyrics", None), authoritative=True)
        if lyrics:
            return lyrics

        # Viele SunoAPI-Datensätze speichern den eigentlichen Songtext nicht in
        # songs.lyrics, sondern in songs.prompt. Genau dieser Text wird im
        # Frontend bereits als „Prompt / Lyrics“ angezeigt.
        lyrics = _first_usable_lyrics(getattr(song, "prompt", None))
        if lyrics:
            return lyrics

    lyrics = _first_usable_lyrics(
        candidate.get("lyrics"),
        candidate.get("text"),
        request_payload.get("lyrics"),
        authoritative=True,
    )
    if lyrics:
        return lyrics

    # SunoAPI liefert Custom-Mode-Lyrics häufig als prompt statt lyrics/text.
    lyrics = _first_usable_lyrics(
        candidate.get("prompt"),
        request_payload.get("prompt"),
        metadata.get("prompt"),
    )
    if lyrics:
        return lyrics

    if asset.suno_task_id:
        task = db.query(SunoTask).filter(SunoTask.task_id == asset.suno_task_id, SunoTask.is_deleted.is_(False)).order_by(SunoTask.id.desc()).first()
        if task:
            task_request = task.request_payload if isinstance(task.request_payload, dict) else {}
            lyrics = _first_usable_lyrics(task_request.get("lyrics"), authoritative=True)
            if lyrics:
                return lyrics

            lyrics = _first_usable_lyrics(task_request.get("prompt"))
            if lyrics:
                return lyrics

            for payload in (task.result_payload, task.response_payload):
                lyrics = _first_usable_lyrics(*_nested_values(payload, {"lyrics"}), authoritative=True)
                if lyrics:
                    return lyrics
                lyrics = _first_usable_lyrics(*_nested_values(payload, {"text"}), authoritative=True)
                if lyrics:
                    return lyrics
                lyrics = _first_usable_lyrics(*_nested_values(payload, {"prompt"}))
                if lyrics:
                    return lyrics

    if allow_missing:
        return ""
    raise HTTPException(status_code=422, detail="Für diesen Song wurde kein verwertbarer Songtext gefunden.")


def has_visible_lyrics_for_alignment(lyrics: str) -> bool:
    """True nur wenn der Text sichtbare Lyrics-Zeilen fuer das Standard-Alignment enthaelt."""
    return bool(_script_parse_lyrics_text(lyrics, skip_prefixes=("#", "/", ";"), skip_parens=False))

def load_transcription_admin_settings(db: Session) -> dict[str, Any]:
    settings = get_settings()
    row = db.query(AppSetting).filter(AppSetting.key == TRANSCRIPTION_SETTINGS_KEY).first()
    value = row.value if row and isinstance(row.value, dict) else {}

    backend = str(value.get("transcription_backend") or settings.transcript_backend_default or "voxtral").strip().lower()
    if backend not in SUPPORTED_BACKENDS:
        backend = "voxtral"

    language = str(value.get("transcription_language") or settings.transcript_language_default or "de").strip().lower()
    if language not in SUPPORTED_LANGUAGES:
        language = "auto"

    template_mode = str(value.get("lyrics_template_mode") or TRANSCRIPTION_MODE).strip().lower()
    if template_mode != TRANSCRIPTION_MODE:
        template_mode = TRANSCRIPTION_MODE

    match_mode = str(value.get("lyrics_match_mode") or TRANSCRIPTION_MATCH_MODE).strip().lower()
    if match_mode != TRANSCRIPTION_MATCH_MODE:
        match_mode = TRANSCRIPTION_MATCH_MODE

    return {
        "default_provider": str(value.get("default_provider") or settings.ai_default_provider).strip().lower(),
        "default_model": str(value.get("default_model") or settings.ai_default_model).strip(),
        "transcription_backend": backend,
        "transcription_language": language,
        "lyrics_template_mode": template_mode,
        "lyrics_match_mode": match_mode,
        "srt_output_enabled": bool(value.get("srt_output_enabled", True)),
        "srt_auto_regenerate": bool(value.get("srt_auto_regenerate", False)),
        "srt_generate_vocal_stems_before_transcription": bool(value.get("srt_generate_vocal_stems_before_transcription", False)),
        "srt_ai_cleanup_enabled": bool(value.get("srt_ai_cleanup_enabled", True)),
    }


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _path_candidates_from_audio_value(value: Any, audio_root: Path, public_route: str) -> list[Path]:
    if not value:
        return []
    text = str(value).strip().split("?", 1)[0]
    if not text:
        return []
    candidates: list[Path] = []
    parsed = urlparse(text)
    path_text = unquote(parsed.path if parsed.scheme in {"http", "https"} else text)
    raw = Path(path_text)
    candidates.append(raw)

    if raw.name:
        candidates.append(audio_root / raw.name)

    route = str(public_route or "").rstrip("/")
    if route and path_text.startswith(route + "/"):
        rel = path_text[len(route):].lstrip("/")
        if rel and ".." not in Path(rel).parts:
            candidates.append(audio_root / rel)

    marker = "/storage/audio/"
    normalized_path = path_text.replace("\\", "/")
    if marker in normalized_path:
        rel = normalized_path.rsplit(marker, 1)[-1].lstrip("/")
        if rel and ".." not in Path(rel).parts:
            candidates.append(audio_root / rel)

    return candidates


def _existing_audio_path_from_candidates(candidates: list[Path], audio_root: Path) -> Path | None:
    root = audio_root.expanduser().resolve()
    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve() if candidate.is_absolute() else (root / candidate).expanduser().resolve()
        except Exception:
            continue
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        if not _is_relative_to(resolved, root):
            continue
        if resolved.exists() and resolved.is_file() and resolved.stat().st_size > 0:
            return resolved
    return None


def _stem_storage_path() -> Path:
    return Path("storage/stems").resolve()


def _resolve_file_inside_roots(value: Any, roots: list[Path]) -> Path | None:
    if not value:
        return None
    raw = str(value).split("?", 1)[0].strip()
    if not raw:
        return None

    candidates: list[Path] = []
    direct = Path(raw)
    candidates.append(direct)
    for root in roots:
        root_resolved = root.expanduser().resolve()
        candidates.append(root_resolved / direct.name)
        marker = f"/{root_resolved.name}/"
        normalized = raw.replace("\\", "/")
        if marker in normalized:
            rel = normalized.rsplit(marker, 1)[-1].lstrip("/")
            if rel and ".." not in Path(rel).parts:
                candidates.append(root_resolved / rel)

    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
        except Exception:
            continue
        if not resolved.exists() or not resolved.is_file() or resolved.stat().st_size <= 0:
            continue
        if any(_is_relative_to(resolved, root.expanduser().resolve()) for root in roots):
            return resolved
    return None


def _existing_vocal_stem_path(asset: AudioAsset) -> Path | None:
    metadata = asset.metadata_json if isinstance(asset.metadata_json, dict) else {}
    stems = metadata.get("stems") if isinstance(metadata.get("stems"), dict) else {}
    files = stems.get("files") if isinstance(stems.get("files"), dict) else {}
    vocals = files.get("vocals") if isinstance(files.get("vocals"), dict) else {}
    if not vocals:
        return None

    roots = [_stem_storage_path()]
    for key in ("local_path", "filename", "public_url", "path"):
        path = _resolve_file_inside_roots(vocals.get(key), roots)
        if path:
            return path
    return None


def select_audio_path_for_transcription(asset: AudioAsset, original_audio_path: Path, prefer_existing_vocal_stem: bool = True) -> tuple[Path, dict[str, Any]]:
    if prefer_existing_vocal_stem:
        vocal_stem = _existing_vocal_stem_path(asset)
        if vocal_stem:
            return vocal_stem, {
                "source": "existing_vocal_stem",
                "stem_backend": "demucs",
                "stem_kind": "vocals",
                "path": str(vocal_stem),
            }

    metadata = asset.metadata_json if isinstance(asset.metadata_json, dict) else {}
    stems = metadata.get("stems") if isinstance(metadata.get("stems"), dict) else {}
    return original_audio_path, {
        "source": "original_audio",
        "stem_status": stems.get("status") or "missing",
        "path": str(original_audio_path),
    }


def _collect_audio_path_candidates(asset: AudioAsset) -> list[Path]:
    settings = get_settings()
    audio_root = settings.audio_storage_path.resolve()
    candidates: list[Path] = []
    for value in (asset.local_path, asset.filename, asset.public_url, asset.source_url):
        candidates.extend(_path_candidates_from_audio_value(value, audio_root, settings.suno_audio_public_route))

    metadata = asset.metadata_json if isinstance(asset.metadata_json, dict) else {}
    candidate = metadata.get("candidate") if isinstance(metadata.get("candidate"), dict) else {}
    request_payload = metadata.get("request_payload") if isinstance(metadata.get("request_payload"), dict) else {}
    for source in (metadata, candidate, request_payload):
        for key in (
            "sourceAudioUrl", "source_audio_url", "audioUrl", "audio_url",
            "sourceStreamAudioUrl", "source_stream_audio_url", "streamAudioUrl", "stream_audio_url",
            "downloadUrl", "download_url", "mp3Url", "mp3_url", "wavUrl", "wav_url",
        ):
            candidates.extend(_path_candidates_from_audio_value(source.get(key), audio_root, settings.suno_audio_public_route))

    if audio_root.exists():
        for extension in settings.audio_allowed_extensions_list:
            candidates.extend(sorted(audio_root.glob(f"audio_{asset.id}_*{extension}")))
        if asset.filename:
            candidates.extend(sorted(audio_root.rglob(Path(str(asset.filename)).name)))
    return candidates


def resolve_safe_audio_path(asset: AudioAsset) -> Path:
    settings = get_settings()
    audio_root = settings.audio_storage_path.resolve()

    if repair_local_file_metadata(asset):
        # Die Änderung wird im aufrufenden DB-Kontext committed.
        pass

    path = _existing_audio_path_from_candidates(_collect_audio_path_candidates(asset), audio_root)
    if path:
        return path

    if not any([asset.local_path, asset.filename, asset.public_url, asset.source_url]):
        raise HTTPException(status_code=422, detail="Für dieses AudioAsset ist kein lokaler oder nachladbarer Audiopfad gespeichert.")
    raise HTTPException(status_code=404, detail="Die lokale Audiodatei wurde nicht gefunden. Falls eine externe Quelle noch verfügbar ist, nutze zuerst 'Inhalte prüfen' oder erzeuge die SRT erneut, damit die Datei nachgeladen wird.")


def _metadata_audio_source_url(asset: AudioAsset) -> str | None:
    metadata = asset.metadata_json if isinstance(asset.metadata_json, dict) else {}
    candidate = metadata.get("candidate") if isinstance(metadata.get("candidate"), dict) else {}
    request_payload = metadata.get("request_payload") if isinstance(metadata.get("request_payload"), dict) else {}
    for source in (metadata, candidate, request_payload):
        for key in (
            "sourceAudioUrl", "source_audio_url", "audioUrl", "audio_url",
            "sourceStreamAudioUrl", "source_stream_audio_url", "streamAudioUrl", "stream_audio_url",
            "downloadUrl", "download_url", "mp3Url", "mp3_url", "wavUrl", "wav_url",
        ):
            value = source.get(key)
            if isinstance(value, str) and is_audio_url(value):
                return value
    if is_audio_url(asset.source_url):
        return str(asset.source_url)
    return None


async def ensure_safe_audio_path(db: Session, asset: AudioAsset) -> Path:
    try:
        path = resolve_safe_audio_path(asset)
        if repair_local_file_metadata(asset):
            db.add(asset)
            db.commit()
            db.refresh(asset)
        return path
    except HTTPException as initial_error:
        source_url = _metadata_audio_source_url(asset)
        if not source_url:
            raise initial_error
        metadata = asset.metadata_json if isinstance(asset.metadata_json, dict) else {}
        candidate_meta = metadata.get("candidate") if isinstance(metadata.get("candidate"), dict) else metadata
        candidate = AudioCandidate(
            source_url=source_url,
            audio_id=asset.audio_id,
            title=asset.display_title or asset.title,
            image_url=asset.image_url,
            duration_seconds=asset.duration_seconds,
            metadata=candidate_meta,
        )
        try:
            cached = await AudioCacheService(db).cache_candidate(candidate, task=None, song=db.query(Song).filter(Song.id == asset.song_id).first() if asset.song_id else None)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=f"Lokale Audiodatei fehlt und konnte nicht nachgeladen werden: {exc}") from exc
        if cached:
            db.refresh(asset)
        return resolve_safe_audio_path(asset)


def _slugify_filename(value: str, fallback: str = "transcript") -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", ascii_text).strip(".-_").lower()
    slug = re.sub(r"-+", "-", slug)
    return (slug or fallback)[:90]


def _visible_lyrics_lines(lyrics: str) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    for index, raw_line in enumerate(lyrics.replace("\r\n", "\n").replace("\r", "\n").split("\n"), start=1):
        line = _strip_control_markup_from_line(raw_line)
        if not line:
            continue
        lines.append({"source_line": index, "text": line})
    return lines


def _normalize_word(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = text.lower()
    text = re.sub(r"[^\wäöüß]+", "", text, flags=re.IGNORECASE)
    return text.strip("_")


def _word_count_for_line(line: str) -> int:
    words = [_normalize_word(item) for item in re.findall(r"[\wÄÖÜäöüß']+", line)]
    return max(1, len([item for item in words if item]))


def _seconds(value: Any, fallback: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    if number < 0:
        return fallback
    return number


def _extract_words(raw: Any) -> list[WordTiming]:
    words: list[WordTiming] = []

    def add_word(item: Any) -> None:
        if not isinstance(item, dict):
            return
        text = item.get("word") or item.get("text") or item.get("token")
        if not text:
            return
        start = item.get("start", item.get("start_time", item.get("startTime")))
        end = item.get("end", item.get("end_time", item.get("endTime")))
        start_f = _seconds(start, -1.0)
        end_f = _seconds(end, -1.0)
        if start_f < 0 or end_f < 0 or end_f <= start_f:
            return
        words.append(WordTiming(word=str(text).strip(), start=start_f, end=end_f))

    if isinstance(raw, dict):
        direct_words = raw.get("words")
        if isinstance(direct_words, list):
            for item in direct_words:
                add_word(item)
        for segment in raw.get("segments", []) if isinstance(raw.get("segments"), list) else []:
            if isinstance(segment, dict) and isinstance(segment.get("words"), list):
                for item in segment.get("words") or []:
                    add_word(item)
    return sorted(words, key=lambda item: (item.start, item.end))


def _extract_segments(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, dict):
        return []
    segments = raw.get("segments")
    if not isinstance(segments, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        start = _seconds(segment.get("start", segment.get("start_time", segment.get("startTime"))), -1.0)
        end = _seconds(segment.get("end", segment.get("end_time", segment.get("endTime"))), -1.0)
        if start < 0 or end <= start:
            continue
        cleaned.append({
            "start": start,
            "end": end,
            "text": str(segment.get("text") or "").strip(),
        })
    return cleaned


def _duration_from_words(words: list[WordTiming], fallback_duration: float) -> float:
    if words:
        return max(fallback_duration, words[-1].end)
    return max(1.0, fallback_duration)


def _normalize_match_word(value: str) -> str:
    text = str(value or "").lower()
    text = text.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    text = unicodedata.normalize("NFKD", text)
    text = re.sub(r"[^a-z0-9]+", "", text)
    return text.strip()


def _lyrics_tokens(text: str) -> list[str]:
    return [token for token in (_normalize_match_word(part) for part in re.findall(r"[\wÄÖÜäöüß']+", str(text or ""))) if token]


def _similarity_score(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    # Kleine, robuste Heuristik ohne zusätzliche Abhängigkeit.
    from difflib import SequenceMatcher
    return SequenceMatcher(None, a, b).ratio()


def _word_matches(asr_word: str, lyric_word: str, threshold: float = 0.45) -> bool:
    a = _normalize_match_word(asr_word)
    b = _normalize_match_word(lyric_word)
    if not a or not b:
        return False
    return a == b or _similarity_score(a, b) >= threshold


def _lookahead_match_score(words: list[WordTiming], start_idx: int, tokens: list[str], threshold: float = 0.45) -> float:
    if not tokens:
        return 0.0
    scan = start_idx
    matches = 0
    window_end = min(len(words), start_idx + max(12, len(tokens) * 3))
    for token in tokens[:10]:
        while scan < window_end:
            word = _normalize_match_word(words[scan].word)
            scan += 1
            if _word_matches(word, token, threshold):
                matches += 1
                break
    return matches / max(1, min(10, len(tokens)))


def _find_best_word_start(words: list[WordTiming], cursor: int, tokens: list[str], miss_streak: int = 0, threshold: float = 0.45) -> int | None:
    if cursor >= len(words) or not tokens:
        return None
    max_window = max(80, len(tokens) * 7 + miss_streak * 35)
    search_end = min(len(words), cursor + max_window)
    best_idx: int | None = None
    best_score = 0.0
    first = tokens[0]
    for idx in range(cursor, search_end):
        first_score = _similarity_score(_normalize_match_word(words[idx].word), first)
        if first_score < threshold:
            continue
        lookahead = _lookahead_match_score(words, idx, tokens, threshold)
        distance_penalty = max(0.0, (idx - cursor) / max(max_window, 1) - 0.12)
        score = ((first_score * 0.35) + (lookahead * 0.65)) / (1.0 + distance_penalty)
        if score > best_score:
            best_score = score
            best_idx = idx
    return best_idx if best_score >= threshold else None


def _has_token_match_ahead(words: list[WordTiming], scan_idx: int, target_token: str, threshold: float, max_slack: int = 5) -> bool:
    lookahead_end = min(len(words), scan_idx + max_slack + 1)
    for lookahead_idx in range(scan_idx + 1, lookahead_end):
        if _word_matches(words[lookahead_idx].word, target_token, threshold):
            return True
    return False


def _expected_line_duration(tokens: list[str]) -> float:
    # Rap-Zeilen sind selten unter 0,8s und sollten bei normaler Phrasierung
    # nicht über viele Takte wachsen. Das ist nur ein Safety-Cap für ASR-Fehler,
    # keine harte musikalische Vorgabe.
    return max(0.85, min(6.0, len(tokens) * 0.42))


def _adaptive_segment_duration_cap(segments: list[dict[str, Any]], tokens: list[str]) -> float:
    expected = _expected_line_duration(tokens)
    if not segments:
        return max(4.0, expected * 1.8)
    durations = [max(0.1, _seconds(item.get("end"), 0.0) - _seconds(item.get("start"), 0.0)) for item in segments[-8:]]
    avg_duration = sum(durations) / max(1, len(durations))
    # Verhindert Ausreißer wie 28s für eine einzelne Zeile, bleibt aber tolerant
    # für langsam gesungene Hooks oder längere gesprochene Lines.
    return max(3.2, min(8.0, max(expected * 1.8, avg_duration * 2.4)))


def _consume_words_for_line(
    words: list[WordTiming],
    start_idx: int,
    tokens: list[str],
    threshold: float = 0.45,
    max_segment_duration: float | None = None,
) -> tuple[list[WordTiming], int, float]:
    consumed: list[WordTiming] = []
    token_idx = 0
    scan = start_idx
    matched = 0
    max_scan = min(len(words), start_idx + max(len(tokens) * 4, len(tokens) + 8))
    duration_cap = float(max_segment_duration or _expected_line_duration(tokens) * 2.0)

    while scan < max_scan and token_idx < len(tokens):
        word = words[scan]
        if consumed and (word.end - consumed[0].start) > duration_cap:
            break

        if _word_matches(word.word, tokens[token_idx], threshold):
            consumed.append(word)
            matched += 1
            token_idx += 1
            scan += 1
            continue

        if not consumed:
            break

        # Füllwörter / ASR-Fehler nur dann übernehmen, wenn der nächste passende
        # Token unmittelbar in Reichweite liegt. Sonst frisst die alte Greedy-
        # Logik komplette Vocal-Pausen oder fremde Zeilen und reißt nach einigen
        # Segmenten ab.
        if _has_token_match_ahead(words, scan, tokens[token_idx], threshold, max_slack=5):
            consumed.append(word)
            scan += 1
            continue

        break

    if not consumed:
        # Fallback: zeilenlange Anzahl Wörter sequenziell belegen, aber mit echten Wortzeiten.
        end_idx = min(len(words), start_idx + max(1, len(tokens)))
        consumed = words[start_idx:end_idx]
        scan = end_idx

    # Nach dem Cap keine offensichtlichen Überlängen zurückgeben.
    if consumed and (consumed[-1].end - consumed[0].start) > duration_cap:
        trimmed: list[WordTiming] = []
        for item in consumed:
            if trimmed and (item.end - trimmed[0].start) > duration_cap:
                break
            trimmed.append(item)
        consumed = trimmed or consumed[:1]
        scan = min(len(words), words.index(consumed[-1]) + 1) if consumed else scan

    coverage = matched / max(1, len(tokens))
    return consumed, max(scan, start_idx + len(consumed)), coverage




def _line_chunk_similarity_for_partition(words: list[WordTiming], lyrics_text: str) -> float:
    """Bewertet, wie gut ein zusammenhängender ASR-Wortbereich zu einer Lyrics-Zeile passt."""
    chunk_norms = [_normalize_match_word(item.word) for item in words if _normalize_match_word(item.word)]
    line_norms = _lyrics_tokens(lyrics_text)
    if not chunk_norms and not line_norms:
        return 1.0
    if not chunk_norms or not line_norms:
        return 0.0

    from difflib import SequenceMatcher

    overlap = sum(1 for token in chunk_norms if token in set(line_norms))
    precision = overlap / max(1, len(chunk_norms))
    recall = overlap / max(1, len(line_norms))
    f1 = (2 * precision * recall / (precision + recall)) if precision + recall else 0.0
    word_order = SequenceMatcher(None, chunk_norms, line_norms).ratio()
    char_order = SequenceMatcher(None, " ".join(chunk_norms), " ".join(line_norms)).ratio()
    length_penalty = abs(len(chunk_norms) - len(line_norms)) / max(len(chunk_norms), len(line_norms), 1)
    return max(0.0, (0.48 * f1) + (0.37 * word_order) + (0.15 * char_order) - (0.12 * length_penalty))


def _partition_words_by_lyrics_lines_dtw(words: list[WordTiming], lines: list[dict[str, Any]]) -> list[tuple[int, int]] | None:
    """Globale, monotone Zeilen-Partitionierung der ASR-Worttimeline.

    Jede Lyrics-Zeile bekommt genau einen zusammenhängenden Wortbereich. Dadurch
    kann eine einzelne schwache Zeile den Cursor nicht mehr gierig bis in einen
    späteren Songteil ziehen. Große Vocal-Pausen bleiben als Zeitlücken erhalten,
    weil Segmentzeiten aus dem jeweils zugeordneten Wortbereich kommen.
    """
    line_count = len(lines)
    word_count = len(words)
    if line_count <= 0:
        return []
    if word_count < line_count:
        return None

    line_token_counts = [max(1, len(_lyrics_tokens(line.get("text") or ""))) for line in lines]
    avg_words_per_line = max(1, round(word_count / max(1, line_count)))
    max_chunk_for_line = [max(10, min(32, count * 2 + 8, avg_words_per_line * 3 + 8)) for count in line_token_counts]

    neg_inf = float("-inf")
    # Leichte Strafe für übersprungene ASR-Wörter zwischen zwei Zeilen. Pausen sind
    # weiterhin erlaubt; es werden nur unnötige, textlich schwache Sprünge reduziert.
    skip_penalty = 0.06
    dp = [[neg_inf] * (word_count + 1) for _ in range(line_count + 1)]
    back: list[list[tuple[int, int] | None]] = [[None] * (word_count + 1) for _ in range(line_count + 1)]
    dp[0][0] = 0.0
    sim_cache: dict[tuple[int, int, int], float] = {}

    for line_idx in range(1, line_count + 1):
        remaining_lines = line_count - line_idx
        min_end = line_idx
        max_end = word_count - remaining_lines
        max_chunk = max_chunk_for_line[line_idx - 1]

        prev_best_scores = [neg_inf] * (word_count + 1)
        prev_best_ends: list[int | None] = [None] * (word_count + 1)
        best_prefix_score = neg_inf
        best_prefix_end: int | None = None
        for prev_end in range(word_count + 1):
            previous_score = dp[line_idx - 1][prev_end]
            if previous_score != neg_inf:
                candidate_score = previous_score + (skip_penalty * prev_end)
                if candidate_score > best_prefix_score:
                    best_prefix_score = candidate_score
                    best_prefix_end = prev_end
            prev_best_scores[prev_end] = best_prefix_score
            prev_best_ends[prev_end] = best_prefix_end

        for end in range(min_end, max_end + 1):
            min_start = line_idx - 1
            max_start = end - 1
            start_floor = max(min_start, end - max_chunk)
            best_score = neg_inf
            best_back: tuple[int, int] | None = None
            for start in range(start_floor, max_start + 1):
                prev_end = prev_best_ends[start]
                if prev_end is None:
                    continue
                previous_score = prev_best_scores[start] - (skip_penalty * start)
                key = (line_idx - 1, start, end)
                score = sim_cache.get(key)
                if score is None:
                    score = _line_chunk_similarity_for_partition(words[start:end], str(lines[line_idx - 1].get("text") or ""))
                    sim_cache[key] = score
                candidate_score = previous_score + score
                if candidate_score > best_score:
                    best_score = candidate_score
                    best_back = (prev_end, start)
            dp[line_idx][end] = best_score
            back[line_idx][end] = best_back

    best_final = neg_inf
    best_end: int | None = None
    for end in range(line_count, word_count + 1):
        score = dp[line_count][end]
        if score == neg_inf:
            continue
        score -= skip_penalty * (word_count - end)
        if score > best_final:
            best_final = score
            best_end = end

    if best_end is None or back[line_count][best_end] is None:
        return None

    ranges: list[tuple[int, int]] = []
    end = best_end
    for line_idx in range(line_count, 0, -1):
        entry = back[line_idx][end]
        if entry is None:
            return None
        prev_end, start = entry
        ranges.append((start, end))
        end = prev_end
    ranges.reverse()
    return ranges


def _split_words_by_internal_gaps(words: list[WordTiming], gap_threshold_seconds: float = 2.75) -> list[list[WordTiming]]:
    if not words:
        return []
    chunks: list[list[WordTiming]] = [[words[0]]]
    for word in words[1:]:
        gap = word.start - chunks[-1][-1].end
        if gap > gap_threshold_seconds:
            chunks.append([word])
        else:
            chunks[-1].append(word)
    return chunks


def _select_best_timing_chunk_for_line(words: list[WordTiming], line_text: str) -> tuple[list[WordTiming], float]:
    """Wählt bei internen ASR-Pausen den passendsten Vocal-Teilbereich einer Zeile.

    Das verhindert SRTs wie 00:01:26 → 00:01:54 für eine einzelne Lyrics-Zeile,
    wenn die letzte Zeile nur wegen eines zufälligen Wortmatches in den nächsten
    Vocal-Block gezogen wurde.
    """
    if not words:
        return [], 0.0

    chunks = _split_words_by_internal_gaps(words)
    if len(chunks) <= 1:
        return words, _line_chunk_similarity_for_partition(words, line_text)

    best_chunk = chunks[0]
    best_score = _line_chunk_similarity_for_partition(best_chunk, line_text)
    for chunk in chunks[1:]:
        score = _line_chunk_similarity_for_partition(chunk, line_text)
        # Nur klar bessere spätere Chunks übernehmen; bei ähnlicher Qualität gewinnt
        # der frühere Chunk, damit Vocal-Pausen nicht unnötig übersprungen werden.
        if score > best_score + 0.08:
            best_score = score
            best_chunk = chunk
    return best_chunk, best_score


def _retokenize_words_to_lyrics(words: list[WordTiming], lyrics_text: str) -> list[dict[str, Any]]:
    tokens = str(lyrics_text or "").replace("\n", " ").split()
    if not words or not tokens:
        return []
    if len(tokens) == len(words):
        return [
            {"word": token, "start": round(src.start, 3), "end": round(src.end, 3)}
            for src, token in zip(words, tokens)
        ]

    start = words[0].start
    end = max(words[-1].end, start + 0.25)
    duration = max(0.25, end - start)
    total_chars = max(sum(len(token) for token in tokens), 1)
    cursor = start
    mapped: list[dict[str, Any]] = []
    for idx, token in enumerate(tokens):
        if idx == len(tokens) - 1:
            token_end = end
        else:
            token_end = cursor + duration * (len(token) / total_chars)
        mapped.append({"word": token, "start": round(cursor, 3), "end": round(max(token_end, cursor + 0.02), 3)})
        cursor = token_end
    return mapped


def _align_lyrics_to_word_timeline_dtw(lines: list[dict[str, Any]], asr_words: list[WordTiming], duration_seconds: float) -> list[dict[str, Any]]:
    words = sorted([w for w in asr_words if w.end > w.start >= 0], key=lambda item: (item.start, item.end))
    if not words or not lines:
        return []
    ranges = _partition_words_by_lyrics_lines_dtw(words, lines)
    if not ranges:
        return []

    segments: list[dict[str, Any]] = []
    fallback_cursor = words[0].start
    for line, (start_idx, end_idx) in zip(lines, ranges):
        assigned = words[start_idx:end_idx]
        line_text = str(line.get("text") or "")
        selected, confidence = _select_best_timing_chunk_for_line(assigned, line_text)
        if selected:
            start = selected[0].start
            end = max(selected[-1].end, start + 0.30)
        else:
            start = fallback_cursor
            end = start + _expected_line_duration(_lyrics_tokens(line_text))
        # Harte Ausreißerbremse: Eine einzelne Lyrics-Zeile darf nicht über eine
        # komplette Hook-/Verse-Pause gezogen werden. Der Text bleibt editierbar;
        # Timing wird lieber konservativ kurz gehalten als massiv falsch gestreckt.
        duration_cap = max(4.0, min(8.0, _expected_line_duration(_lyrics_tokens(line_text)) * 2.2))
        if end - start > duration_cap:
            end = start + duration_cap
        segments.append({
            "index": len(segments) + 1,
            "source_line": line.get("source_line"),
            "start": round(max(0.0, start), 3),
            "end": round(max(end, start + 0.30), 3),
            "text": line_text,
            "alignment_confidence": round(float(confidence), 3),
            "words": _retokenize_words_to_lyrics(selected, line_text),
            "alignment_method": "dtw_line_partition",
        })
        fallback_cursor = end + 0.05

    return _normalize_segment_timing(segments, _duration_from_words(words, duration_seconds))
def _align_lyrics_to_word_timeline(lines: list[dict[str, Any]], asr_words: list[WordTiming], duration_seconds: float) -> list[dict[str, Any]]:
    # Primärpfad: globale DTW-/Line-Partition. Die alte Greedy-Logik bleibt nur
    # als Fallback erhalten. Der Primärpfad verhindert den beobachteten Fehler,
    # bei dem nach Segment 12 eine einzelne schwache Zeile bis in einen späteren
    # Vocal-Block gezogen wurde.
    partitioned = _align_lyrics_to_word_timeline_dtw(lines, asr_words, duration_seconds)
    if partitioned:
        return partitioned

    words = sorted([w for w in asr_words if w.end > w.start >= 0], key=lambda item: (item.start, item.end))
    if not words:
        return []
    segments: list[dict[str, Any]] = []
    cursor = 0
    miss_streak = 0
    for line in lines:
        tokens = _lyrics_tokens(line["text"])
        if not tokens:
            continue
        start_idx = _find_best_word_start(words, cursor, tokens, miss_streak)
        if start_idx is None:
            # Kein sicherer Textmatch: nutze die nächste echte Wortposition als Anker,
            # aber erzeugt keinen durchlaufenden Untertitel über Vocal-Pausen hinweg.
            if cursor >= len(words):
                previous_end = segments[-1]["end"] if segments else 0.0
                start = previous_end + 0.08
                end = min(max(duration_seconds, start + 0.8), start + max(0.8, min(4.0, len(tokens) * 0.33)))
                confidence = 0.0
                next_cursor = cursor
            else:
                chunk_end = min(len(words), cursor + max(1, len(tokens)))
                chunk = words[cursor:chunk_end]
                start = chunk[0].start
                end = max(chunk[-1].end, start + 0.3)
                confidence = 0.15
                next_cursor = chunk_end
            miss_streak += 1
        else:
            duration_cap = _adaptive_segment_duration_cap(segments, tokens)
            chunk, next_cursor, confidence = _consume_words_for_line(words, start_idx, tokens, max_segment_duration=duration_cap)
            start = chunk[0].start
            end = max(chunk[-1].end, start + 0.3)
            # Wenn der Match sehr schwach ist, aber die nächste Zeile in der Nähe
            # besser passt, bleibt der Cursor streng chronologisch. Dadurch werden
            # wiederholte Hooks/Verses nicht in spätere Songteile gezogen.
            miss_streak = 0 if confidence >= 0.25 else miss_streak + 1
        segments.append({
            "index": len(segments) + 1,
            "source_line": line["source_line"],
            "start": round(max(0.0, start), 3),
            "end": round(max(end, start + 0.3), 3),
            "text": line["text"],
            "alignment_confidence": round(float(confidence), 3),
        })
        cursor = max(cursor, next_cursor)
    return _normalize_segment_timing(segments, _duration_from_words(words, duration_seconds))


def _segment_text_weight(text: str) -> int:
    words = [_normalize_word(item) for item in re.findall(r"[\wÄÖÜäöüß']+", str(text or ""))]
    return len([item for item in words if item])


def _group_asr_segments_into_vocal_blocks(segments: list[dict[str, Any]], *, gap_threshold_seconds: float = 2.25) -> list[dict[str, Any]]:
    cleaned = sorted(
        [
            item
            for item in segments
            if _seconds(item.get("end"), -1.0) > _seconds(item.get("start"), -1.0) >= 0
        ],
        key=lambda item: (_seconds(item.get("start"), 0.0), _seconds(item.get("end"), 0.0)),
    )
    if not cleaned:
        return []

    blocks: list[dict[str, Any]] = []
    current: dict[str, Any] = {
        "start": _seconds(cleaned[0].get("start"), 0.0),
        "end": _seconds(cleaned[0].get("end"), 0.0),
        "text_parts": [str(cleaned[0].get("text") or "").strip()],
        "segment_count": 1,
    }

    for item in cleaned[1:]:
        start = _seconds(item.get("start"), 0.0)
        end = _seconds(item.get("end"), start + 0.35)
        gap = start - _seconds(current.get("end"), start)
        if gap > gap_threshold_seconds:
            text = " ".join(part for part in current.get("text_parts", []) if part).strip()
            blocks.append({
                "start": round(_seconds(current.get("start"), 0.0), 3),
                "end": round(_seconds(current.get("end"), 0.0), 3),
                "text": text,
                "segment_count": int(current.get("segment_count") or 1),
            })
            current = {"start": start, "end": end, "text_parts": [str(item.get("text") or "").strip()], "segment_count": 1}
        else:
            current["end"] = max(_seconds(current.get("end"), end), end)
            current.setdefault("text_parts", []).append(str(item.get("text") or "").strip())
            current["segment_count"] = int(current.get("segment_count") or 0) + 1

    text = " ".join(part for part in current.get("text_parts", []) if part).strip()
    blocks.append({
        "start": round(_seconds(current.get("start"), 0.0), 3),
        "end": round(_seconds(current.get("end"), 0.0), 3),
        "text": text,
        "segment_count": int(current.get("segment_count") or 1),
    })
    return blocks



def _token_counter(tokens: list[str]) -> Counter:
    return Counter(token for token in tokens if token)


def _counter_f1(left: Counter, right: Counter) -> float:
    if not left or not right:
        return 0.0
    overlap = sum((left & right).values())
    precision = overlap / max(1, sum(left.values()))
    recall = overlap / max(1, sum(right.values()))
    return (2 * precision * recall / (precision + recall)) if precision + recall else 0.0


def _line_slice_text(lines: list[dict[str, Any]]) -> str:
    return " ".join(str(line.get("text") or "").strip() for line in lines if str(line.get("text") or "").strip())


def _block_line_slice_score(block: dict[str, Any], line_slice: list[dict[str, Any]]) -> float:
    """Bewertet, wie plausibel ein Lyrics-Zeilenbereich zu einem ASR-Vocal-Block passt.

    Wichtig für Songs mit Hook-/Verse-Pausen: Erst wird grob auf Vocal-Blöcke
    gemappt, danach erfolgt Word-Alignment nur innerhalb dieses Blocks. Dadurch
    kann ein schlechter Wortmatch ab ca. 50s nicht mehr den Rest des Songs in
    0,8s-Segmente zusammendrücken.
    """
    if not line_slice:
        return -999.0

    from difflib import SequenceMatcher

    block_text = str(block.get("text") or "")
    line_text = _line_slice_text(line_slice)
    block_tokens = _lyrics_tokens(block_text)
    line_tokens = _lyrics_tokens(line_text)
    if not block_tokens:
        # Ohne ASR-Text wird später duration/weight-basiert verteilt.
        return 0.0
    if not line_tokens:
        return -999.0

    f1 = _counter_f1(_token_counter(block_tokens), _token_counter(line_tokens))
    token_order = SequenceMatcher(None, block_tokens, line_tokens).ratio()
    char_order = SequenceMatcher(None, " ".join(block_tokens), " ".join(line_tokens)).ratio()

    block_duration = max(0.35, _seconds(block.get("end"), 0.0) - _seconds(block.get("start"), 0.0))
    expected_duration = max(0.85, sum(_word_count_for_line(str(line.get("text") or "")) for line in line_slice) * 0.34)
    duration_penalty = min(0.22, abs(block_duration - expected_duration) / max(block_duration, expected_duration, 1.0) * 0.16)

    length_penalty = min(0.20, abs(len(block_tokens) - len(line_tokens)) / max(len(block_tokens), len(line_tokens), 1) * 0.16)
    return max(0.0, (0.52 * f1) + (0.30 * token_order) + (0.18 * char_order) - duration_penalty - length_penalty)


def _allocate_line_counts_by_block_text(lines: list[dict[str, Any]], blocks: list[dict[str, Any]]) -> list[int] | None:
    line_count = len(lines)
    block_count = len(blocks)
    if line_count <= 0 or block_count <= 0 or line_count < block_count:
        return None
    if not any(_lyrics_tokens(str(block.get("text") or "")) for block in blocks):
        return None

    neg_inf = float("-inf")
    dp = [[neg_inf] * (line_count + 1) for _ in range(block_count + 1)]
    back: list[list[int | None]] = [[None] * (line_count + 1) for _ in range(block_count + 1)]
    dp[0][0] = 0.0

    for block_idx in range(1, block_count + 1):
        block = blocks[block_idx - 1]
        remaining_blocks = block_count - block_idx
        min_end = block_idx
        max_end = line_count - remaining_blocks
        block_token_count = max(1, len(_lyrics_tokens(str(block.get("text") or ""))))
        block_duration = max(0.35, _seconds(block.get("end"), 0.0) - _seconds(block.get("start"), 0.0))
        # Rap-Zeilen liegen oft bei 5-10 Wörtern; Dauergrenze bleibt großzügig.
        max_by_text = max(2, int(round(block_token_count / 3.2)) + 3)
        max_by_duration = max(2, int(block_duration / 0.65) + 2)
        max_lines_for_block = min(max_end, max(2, min(24, max(max_by_text, max_by_duration))))

        for end in range(min_end, max_end + 1):
            min_start = block_idx - 1
            start_floor = max(min_start, end - max_lines_for_block)
            for start in range(start_floor, end):
                previous = dp[block_idx - 1][start]
                if previous == neg_inf:
                    continue
                score = _block_line_slice_score(block, lines[start:end])
                # Leichte Strafe für extrem viele Zeilen in einem Block.
                count = end - start
                count_penalty = max(0.0, count - max_by_text) * 0.025
                candidate = previous + score - count_penalty
                if candidate > dp[block_idx][end]:
                    dp[block_idx][end] = candidate
                    back[block_idx][end] = start

    if back[block_count][line_count] is None:
        return None

    counts: list[int] = []
    end = line_count
    for block_idx in range(block_count, 0, -1):
        start = back[block_idx][end]
        if start is None:
            return None
        counts.append(end - start)
        end = start
    counts.reverse()
    if sum(counts) != line_count or any(count <= 0 for count in counts):
        return None
    return counts


def _allocate_line_counts_to_blocks(lines: list[dict[str, Any]], weights: list[int], blocks: list[dict[str, Any]]) -> list[int]:
    line_count = len(lines)
    block_count = len(blocks)
    if line_count <= 0 or block_count <= 0:
        return []
    if block_count == 1:
        return [line_count]

    # Primär: ASR-Text pro Vocal-Block gegen Lyrics-Zeilenbereiche matchen.
    # Das ist wesentlich robuster als reine Dauerverteilung, besonders bei
    # Wiederholungen und langen Instrumentalpausen.
    text_counts = _allocate_line_counts_by_block_text(lines, blocks)
    if text_counts:
        return text_counts

    block_weights: list[float] = []
    for block in blocks:
        text_weight = _segment_text_weight(str(block.get("text") or ""))
        duration_weight = max(0.35, _seconds(block.get("end"), 0.0) - _seconds(block.get("start"), 0.0))
        # ASR-Text ist oft ungenau, aber als Gewicht besser als reine Dauer.
        # Dauer bleibt Fallback und verhindert 0-Gewichtung bei leerem ASR-Text.
        block_weights.append(float(text_weight) if text_weight > 0 else duration_weight)

    total_block_weight = sum(block_weights) or float(block_count)
    raw_counts = [(weight / total_block_weight) * line_count for weight in block_weights]

    counts = [int(value) for value in raw_counts]
    if line_count >= block_count:
        counts = [max(1, count) for count in counts]
    else:
        ranked = sorted(range(block_count), key=lambda idx: block_weights[idx], reverse=True)
        counts = [0 for _ in blocks]
        for idx in ranked[:line_count]:
            counts[idx] = 1

    current_total = sum(counts)
    remainders = sorted(
        range(block_count),
        key=lambda idx: (raw_counts[idx] - int(raw_counts[idx]), block_weights[idx]),
        reverse=True,
    )

    while current_total < line_count:
        for idx in remainders:
            counts[idx] += 1
            current_total += 1
            if current_total >= line_count:
                break

    while current_total > line_count:
        removable = sorted(
            range(block_count),
            key=lambda idx: (counts[idx], raw_counts[idx] - int(raw_counts[idx])),
            reverse=True,
        )
        changed = False
        for idx in removable:
            minimum = 1 if line_count >= block_count else 0
            if counts[idx] > minimum:
                counts[idx] -= 1
                current_total -= 1
                changed = True
                break
        if not changed:
            break

    return counts


def _words_inside_block(words: list[WordTiming], block: dict[str, Any], tolerance: float = 0.35) -> list[WordTiming]:
    start = _seconds(block.get("start"), 0.0) - tolerance
    end = _seconds(block.get("end"), 0.0) + tolerance
    return [word for word in words if word.end >= start and word.start <= end]


def _segments_have_tail_compression(segments: list[dict[str, Any]], *, min_run: int = 8) -> bool:
    """Erkennt den typischen Fehlerfall: Ab einer Stelle laufen viele Zeilen mit
    fast identischen Mini-Dauern direkt hintereinander durch.
    """
    if len(segments) < min_run + 4:
        return False
    tail = segments[-min_run:]
    durations = [_seconds(item.get("end"), 0.0) - _seconds(item.get("start"), 0.0) for item in tail]
    gaps = [_seconds(tail[idx].get("start"), 0.0) - _seconds(tail[idx - 1].get("end"), 0.0) for idx in range(1, len(tail))]
    avg_duration = sum(durations) / len(durations)
    max_gap = max(gaps or [0.0])
    nearly_equal = max(durations) - min(durations) < 0.18
    return avg_duration <= 0.95 and max_gap <= 0.12 and nearly_equal


def _align_lyrics_to_vocal_blocks_hybrid(lines: list[dict[str, Any]], weights: list[int], asr_words: list[WordTiming], asr_segments: list[dict[str, Any]], duration_seconds: float) -> list[dict[str, Any]]:
    """Robustes Song-Alignment über Vocal-Blöcke.

    1. ASR-Segmente werden zu Vocal-Blöcken gruppiert.
    2. Lyrics-Zeilen werden per ASR-Text/Dauer auf diese Blöcke verteilt.
    3. Innerhalb eines Blocks wird, wenn möglich, Word-Timeline-DTW verwendet.
    4. Wenn das blockinterne Word-Alignment unsicher ist, wird innerhalb des
       Block-Zeitfensters gewichtet verteilt.

    Damit bleiben Beat-/Instrumentalpausen erhalten und spätere Lyrics werden
    nicht mehr in 0,8s-Ketten ans Ende gepresst.
    """
    blocks = _group_asr_segments_into_vocal_blocks(asr_segments)
    if not blocks:
        return []

    line_counts = _allocate_line_counts_to_blocks(lines, weights, blocks)
    if not line_counts or sum(line_counts) != len(lines):
        return []

    result: list[dict[str, Any]] = []
    line_cursor = 0
    for block_index, block in enumerate(blocks):
        count = line_counts[block_index] if block_index < len(line_counts) else 0
        if count <= 0:
            continue
        block_lines = lines[line_cursor: line_cursor + count]
        block_weights = weights[line_cursor: line_cursor + count]
        line_cursor += count

        block_start = _seconds(block.get("start"), 0.0)
        block_end = _seconds(block.get("end"), block_start + 0.35)
        block_words = _words_inside_block(asr_words, block)

        block_segments: list[dict[str, Any]] = []
        if len(block_words) >= len(block_lines):
            candidate = _align_lyrics_to_word_timeline_dtw(block_lines, block_words, duration_seconds)
            if candidate:
                # Nur übernehmen, wenn wirklich alle Segmente im Vocal-Block bleiben
                # und keine künstliche Mini-Kette erzeugt wurde.
                valid = True
                for seg in candidate:
                    seg_start = _seconds(seg.get("start"), 0.0)
                    seg_end = _seconds(seg.get("end"), seg_start + 0.35)
                    line_tokens = _lyrics_tokens(str(seg.get("text") or ""))
                    cap = max(4.0, min(8.0, _expected_line_duration(line_tokens) * 2.2))
                    if seg_start < block_start - 0.5 or seg_end > block_end + 0.75 or (seg_end - seg_start) > cap:
                        valid = False
                        break
                if valid and not _segments_have_tail_compression(candidate, min_run=min(8, max(3, len(candidate)))):
                    block_segments = candidate

        if not block_segments:
            block_segments = _spread_lines_inside_time_window(
                block_lines,
                block_weights,
                block_start,
                block_end,
                start_index=len(result) + 1,
            )

        for seg in block_segments:
            result.append({**seg, "index": len(result) + 1, "alignment_method": seg.get("alignment_method") or "vocal_block_hybrid"})

    if line_cursor < len(lines):
        # Rest niemals künstlich hinter der letzten Wortzeit in 0,8s-Schritten
        # erzeugen. Lieber kontrolliert im letzten Vocal-Block verteilen.
        last_block = blocks[-1]
        result.extend(_spread_lines_inside_time_window(
            lines[line_cursor:],
            weights[line_cursor:],
            _seconds(last_block.get("start"), 0.0),
            _seconds(last_block.get("end"), 0.0),
            start_index=len(result) + 1,
        ))

    speech_end = max(_seconds(item.get("end"), 0.0) for item in blocks)
    return _normalize_segment_timing(result, max(duration_seconds, speech_end))

def _spread_lines_inside_time_window(assigned_lines: list[dict[str, Any]], assigned_weights: list[int], start: float, end: float, *, start_index: int = 1) -> list[dict[str, Any]]:
    if not assigned_lines:
        return []
    start = max(0.0, float(start))
    end = max(start + 0.35, float(end))
    duration = max(0.35, end - start)
    total_weight = max(1, sum(assigned_weights))
    cursor = start
    result: list[dict[str, Any]] = []
    for idx, line in enumerate(assigned_lines):
        part = assigned_weights[idx] / total_weight
        line_end = end if idx == len(assigned_lines) - 1 else cursor + max(0.35, duration * part)
        line_end = min(end, max(cursor + 0.35, line_end))
        result.append({
            "index": start_index + len(result),
            "source_line": line["source_line"],
            "start": round(cursor, 3),
            "end": round(line_end, 3),
            "text": line["text"],
        })
        cursor = line_end
    return result


def align_lyrics_to_timeline_bundle(lyrics: str, asr: AsrResult, duration_seconds: float) -> dict[str, Any]:
    """Exaktes Lyrics-Alignment nach dem funktionierenden Referenzskript.

    Liefert zusätzlich eine `*.half.srt`-Variante für mobile Geräte.
    Die normale SRT nutzt Lyrics-Zeilen als Source of Truth; die Half-SRT splittet
    dieselben Zeilen wortbasiert mit Zeitinterpolation wie im CLI-Skript.
    """
    lines = _script_parse_lyrics_text(lyrics, skip_prefixes=("#", "/", ";"), skip_parens=False)
    if not lines:
        raise HTTPException(status_code=422, detail="Der Songtext enthält keine sichtbaren Zeilen.")

    hyp = [
        HypWord(
            norm=_script_tokenize_match(word.word)[0] if _script_tokenize_match(word.word) else str(word.word or "").strip().lower(),
            start=word.start,
            end=word.end,
        )
        for word in asr.words
        if word.end >= word.start
    ]
    hyp = [word for word in hyp if word.norm]
    if not hyp:
        raise HTTPException(status_code=422, detail="ASR lieferte keine verwertbaren Wort-Timestamps.")

    report = _script_align_lines(lines, hyp, warn_factor=0.6)
    _script_enforce_monotonic(lines, min_dur=0.6, gap=0.04)
    _script_compute_word_times(lines)

    segments: list[dict[str, Any]] = []
    for idx, line in enumerate(lines, start=1):
        start_value = round(float(line.start or 0.0), 3)
        end_value = round(float(line.end or start_value + 0.6), 3)
        segments.append({
            "index": idx,
            "source_line": line.index + 1,
            "start": start_value,
            "end": max(end_value, start_value + 0.05),
            "text": line.display,
            "alignment_confidence": 1.0 if line.matched else 0.0,
            "matched": bool(line.matched),
            "alignment_method": "lyrics_align_srt_reference",
        })

    if report:
        for segment in segments:
            segment.setdefault("alignment_report", report)

    normalized_segments = validate_and_normalize_srt_segments(segments)
    half_srt_text = _script_to_portrait_srt(lines, max_chars=22, min_dur=0.6)
    return {
        "segments": normalized_segments,
        "half_srt_text": half_srt_text,
        "alignment_report": report,
        "half_max_chars": 22,
    }


def align_lyrics_to_timeline(lyrics: str, asr: AsrResult, duration_seconds: float) -> list[dict[str, Any]]:
    return align_lyrics_to_timeline_bundle(lyrics, asr, duration_seconds)["segments"]


def _transcription_only_segments_from_asr_segments(asr_segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    for item in asr_segments or []:
        text = str(item.get("text") or "").strip()
        start = _seconds(item.get("start"), -1.0)
        end = _seconds(item.get("end"), -1.0)
        if not text or start < 0 or end <= start:
            continue
        segments.append({
            "index": len(segments) + 1,
            "start": round(start, 3),
            "end": round(end, 3),
            "text": text,
            "alignment_confidence": 1.0,
            "matched": True,
            "alignment_method": "transcription_only_asr_segment",
        })
    return segments


def _transcription_only_segments_from_words(words: list[WordTiming]) -> list[dict[str, Any]]:
    valid_words = [
        word
        for word in sorted(words or [], key=lambda item: (item.start, item.end))
        if str(word.word or "").strip() and word.end > word.start >= 0
    ]
    if not valid_words:
        return []

    max_chars = 76
    max_duration = 5.5
    gap_threshold = 0.85
    current_words: list[WordTiming] = []
    segments: list[dict[str, Any]] = []

    def flush() -> None:
        if not current_words:
            return
        text = " ".join(str(item.word or "").strip() for item in current_words if str(item.word or "").strip()).strip()
        if text:
            start = float(current_words[0].start)
            end = max(float(current_words[-1].end), start + 0.3)
            segments.append({
                "index": len(segments) + 1,
                "start": round(start, 3),
                "end": round(end, 3),
                "text": text,
                "alignment_confidence": 1.0,
                "matched": True,
                "alignment_method": "transcription_only_word_group",
            })
        current_words.clear()

    for word in valid_words:
        word_text = str(word.word or "").strip()
        if not word_text:
            continue
        if current_words:
            previous = current_words[-1]
            candidate_text = " ".join([*(str(item.word or "").strip() for item in current_words), word_text]).strip()
            candidate_duration = float(word.end) - float(current_words[0].start)
            gap = float(word.start) - float(previous.end)
            if gap > gap_threshold or len(candidate_text) > max_chars or candidate_duration > max_duration:
                flush()
        current_words.append(word)
    flush()
    return segments


def build_transcription_only_srt_bundle(asr: AsrResult, duration_seconds: float) -> dict[str, Any]:
    """Fallback fuer Audios ohne sichtbare Lyrics; Standard bleibt Lyrics-Alignment."""
    segments = _transcription_only_segments_from_asr_segments(asr.segments or [])
    source = "asr_segments"
    if not segments:
        segments = _transcription_only_segments_from_words(asr.words or [])
        source = "word_timestamps"
    if not segments and str(asr.text or "").strip():
        end = max(float(duration_seconds or 0.0), 0.6)
        segments = [{
            "index": 1,
            "start": 0.0,
            "end": round(end, 3),
            "text": str(asr.text or "").strip(),
            "alignment_confidence": 0.35,
            "matched": False,
            "alignment_method": "transcription_only_full_text",
        }]
        source = "full_text"

    normalized_segments = validate_and_normalize_srt_segments(segments)
    if not normalized_segments:
        raise HTTPException(status_code=422, detail="Transkription lieferte keinen verwertbaren Text fuer SRT.")
    return {
        "segments": normalized_segments,
        "half_srt_text": segments_to_half_srt(normalized_segments, max_chars=22, min_dur=0.6),
        "alignment_report": [],
        "half_max_chars": 22,
        "mode": "transcription_only_no_lyrics",
        "source": source,
    }


def _normalize_segment_timing(segments: list[dict[str, Any]], duration_seconds: float) -> list[dict[str, Any]]:
    previous_end = 0.0
    max_duration = max(duration_seconds, 1.0)
    normalized: list[dict[str, Any]] = []
    for idx, segment in enumerate(segments, start=1):
        start = max(previous_end, _seconds(segment.get("start"), previous_end))
        end = max(start + 0.35, _seconds(segment.get("end"), start + 0.35))
        if idx == len(segments):
            end = min(max(end, start + 0.35), max(max_duration, end))
        normalized.append({**segment, "index": idx, "start": round(start, 3), "end": round(end, 3)})
        previous_end = end
    return normalized


def _srt_timestamp(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def segments_to_srt(segments: list[dict[str, Any]]) -> str:
    return export_srt_text(segments)




def _parse_srt_timestamp(value: str) -> float:
    text = str(value or "").strip().replace(".", ",")
    match = re.fullmatch(r"(\d{1,2}):(\d{2}):(\d{2}),(\d{1,3})", text)
    if not match:
        raise ValueError(f"Ungültiger SRT-Zeitstempel: {value}")
    hours, minutes, seconds, millis = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(millis.ljust(3, "0")[:3]) / 1000.0


def srt_to_segments(srt_text: str) -> list[dict[str, Any]]:
    return parse_srt_text(srt_text)


def _coerce_editor_segments(segments: list[dict[str, Any]] | None, srt_text: str | None = None) -> list[dict[str, Any]]:
    if segments is None:
        segments = parse_srt_text(srt_text or "")
    return validate_and_normalize_srt_segments(list(segments or []))


def _write_transcript_text_file(asset: AudioAsset, audio_asset_id: int, text: str, *, suffix: str = ".srt") -> Path:
    settings = get_settings()
    transcript_root = settings.transcript_storage_path.resolve()
    target_dir = (transcript_root / str(audio_asset_id)).resolve()
    if not _is_relative_to(target_dir, transcript_root):
        raise HTTPException(status_code=500, detail="Ungültiger Transcript-Zielpfad.")
    target_dir.mkdir(parents=True, exist_ok=True)
    base_name = _slugify_filename(asset.display_title or asset.title or asset.filename or f"audio-{audio_asset_id}", fallback=f"audio-{audio_asset_id}")
    safe_suffix = suffix if str(suffix).startswith(".") else f".{suffix}"
    target_path = (target_dir / f"{base_name}{safe_suffix}").resolve()
    if not _is_relative_to(target_path, transcript_root):
        raise HTTPException(status_code=500, detail="Ungültiger Transcript-Dateipfad.")
    target_path.write_text(text, encoding="utf-8")
    return target_path


def _write_transcript_file(asset: AudioAsset, audio_asset_id: int, srt_text: str) -> Path:
    return _write_transcript_text_file(asset, audio_asset_id, srt_text, suffix=".srt")


def _half_transcript_path_from_srt_path(srt_path: str | None) -> Path | None:
    if not srt_path:
        return None
    path = Path(srt_path).resolve()
    return path.with_name(f"{path.stem}.half.srt")

def _transcribe_openai_sync(audio_path: Path, language: str) -> AsrResult:
    settings = get_settings()
    if not settings.openai_api_key:
        raise TranscriptionBackendError("OPENAI_API_KEY ist nicht gesetzt.")
    if audio_path.stat().st_size > 24 * 1024 * 1024:
        raise TranscriptionBackendError("OpenAI Whisper API unterstützt in dieser Implementierung nur Audiodateien bis ca. 24 MB.")

    url = f"{settings.openai_base_url.rstrip('/')}/audio/transcriptions"
    # Wichtiger httpx-Multipart-Hinweis:
    # Wiederholte Formularfelder dürfen hier nicht über `data={...list...}` laufen,
    # weil Provider/Parser daraus je nach Kombination einen einzigen Wert wie
    # "wordsegment" machen können. Deshalb werden ALLE Felder als Multipart-Parts
    # in `files=[...]` übergeben. Textfelder nutzen `(None, value)`.
    headers = {"Authorization": f"Bearer {settings.openai_api_key}"}
    try:
        with httpx.Client(timeout=settings.transcript_request_timeout_seconds) as client:
            with audio_path.open("rb") as file_handle:
                files: list[tuple[str, Any]] = [
                    ("file", (audio_path.name, file_handle, "application/octet-stream")),
                    ("model", (None, settings.transcript_openai_model)),
                    ("response_format", (None, "verbose_json")),
                    ("timestamp_granularities[]", (None, "word")),
                    ("timestamp_granularities[]", (None, "segment")),
                ]
                if language and language != "auto":
                    files.append(("language", (None, language)))
                response = client.post(url, headers=headers, files=files)
    except httpx.RequestError as exc:
        raise TranscriptionBackendError(f"OpenAI Whisper API ist nicht erreichbar: {exc}") from exc

    if response.status_code >= 400:
        raise TranscriptionBackendError(f"OpenAI Whisper API Fehler {response.status_code}: {response.text[:500]}")
    raw = response.json()
    return AsrResult(text=str(raw.get("text") or ""), words=_extract_words(raw), segments=_extract_segments(raw), raw=raw)


async def _transcribe_openai(audio_path: Path, language: str) -> AsrResult:
    return await asyncio.to_thread(_transcribe_openai_sync, audio_path, language)


def _transcribe_voxtral_sync(audio_path: Path, language: str) -> AsrResult:
    settings = get_settings()
    api_key = settings.voxtral_api_key or settings.mistral_api_key
    if not api_key:
        raise TranscriptionBackendError("VOXTRAL_API_KEY oder MISTRAL_API_KEY ist nicht gesetzt.")

    url = f"{settings.voxtral_base_url.rstrip('/')}/audio/transcriptions"
    # Voxtral/Mistral akzeptiert für timestamp_granularities praktisch nur eine
    # Granularität pro Request. Für Lyrics-SRT brauchen wir Wortzeiten, deshalb:
    # word only, diarize=false, language nicht mitsenden. Das vermeidet den
    # früheren 422-Fehler mit zusammengezogenen Werten wie "wordsegment".
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        with httpx.Client(timeout=settings.transcript_request_timeout_seconds) as client:
            with audio_path.open("rb") as file_handle:
                files: list[tuple[str, Any]] = [
                    ("file", (audio_path.name, file_handle, "application/octet-stream")),
                    ("model", (None, settings.transcript_voxtral_model)),
                    ("timestamp_granularities", (None, "word")),
                    ("diarize", (None, "false")),
                    ("temperature", (None, "0")),
                ]
                response = client.post(url, headers=headers, files=files)
    except httpx.RequestError as exc:
        raise TranscriptionBackendError(f"Voxtral API ist nicht erreichbar: {exc}") from exc

    if response.status_code >= 400:
        raise TranscriptionBackendError(f"Voxtral API Fehler {response.status_code}: {response.text[:700]}")
    raw = response.json()
    return AsrResult(text=str(raw.get("text") or ""), words=_extract_words(raw), segments=_extract_segments(raw), raw=raw)


async def _transcribe_voxtral(audio_path: Path, language: str) -> AsrResult:
    return await asyncio.to_thread(_transcribe_voxtral_sync, audio_path, language)


GroqProgressCallback = Callable[[str, dict[str, Any]], None]


def _groq_preprocess_audio_enabled(settings: Any) -> bool:
    return bool(getattr(settings, "transcript_groq_preprocess_audio", True))


def _prepare_groq_upload_audio_path(
    audio_path: Path,
    temp_dir: Path,
    settings: Any,
    emit: Callable[..., None],
) -> Path:
    if not _groq_preprocess_audio_enabled(settings):
        return audio_path

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        emit("groq_audio_preprocess_skipped", reason="ffmpeg_not_found")
        return audio_path

    try:
        sample_rate = int(getattr(settings, "transcript_groq_preprocess_sample_rate", 16000) or 16000)
    except (TypeError, ValueError):
        sample_rate = 16000
    sample_rate = max(8000, min(sample_rate, 48000))
    bitrate = str(getattr(settings, "transcript_groq_preprocess_bitrate", "64k") or "64k").strip() or "64k"

    target = temp_dir / f"{audio_path.stem}.groq_transcript.mp3"
    source_size = audio_path.stat().st_size if audio_path.exists() else None
    emit(
        "groq_audio_preprocess_started",
        source_filename=audio_path.name,
        source_size_bytes=source_size,
        target_filename=target.name,
        sample_rate=sample_rate,
        bitrate=bitrate,
    )
    command = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(audio_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-b:a",
        bitrate,
        "-map_metadata",
        "-1",
        str(target),
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        emit("groq_audio_preprocess_failed", reason="timeout", timeout_seconds=300)
        return audio_path
    except Exception as exc:
        emit("groq_audio_preprocess_failed", reason=exc.__class__.__name__, error=str(exc)[:500])
        return audio_path

    if completed.returncode != 0:
        emit(
            "groq_audio_preprocess_failed",
            reason="ffmpeg_failed",
            exit_code=completed.returncode,
            stderr=(completed.stderr or completed.stdout or "")[-700:],
        )
        return audio_path
    if not target.exists() or target.stat().st_size <= 0:
        emit("groq_audio_preprocess_failed", reason="empty_output")
        return audio_path

    emit(
        "groq_audio_preprocess_completed",
        source_filename=audio_path.name,
        source_size_bytes=source_size,
        upload_filename=target.name,
        upload_size_bytes=target.stat().st_size,
        sample_rate=sample_rate,
        bitrate=bitrate,
    )
    return target


def _transcribe_groq_sync(audio_path: Path, language: str, progress_callback: GroqProgressCallback | None = None) -> AsrResult:
    """Groq-Backend nach Referenzskript: OpenAI-kompatible API mit Wort-Timestamps."""
    settings = get_settings()
    api_key = str(getattr(settings, "groq_api_key", "") or os.environ.get("GROQ_API_KEY", "")).strip()
    if not api_key:
        raise TranscriptionBackendError("GROQ_API_KEY ist nicht gesetzt.")

    model_name = str(getattr(settings, "transcript_groq_model", "whisper-large-v3") or "whisper-large-v3").strip()
    url = "https://api.groq.com/openai/v1/audio/transcriptions"
    data: dict[str, Any] = {
        "model": model_name,
        "response_format": "verbose_json",
        "timestamp_granularities[]": ["word", "segment"],
        "temperature": "0",
    }
    if language and language != "auto":
        data["language"] = language

    try:
        import requests  # type: ignore
    except Exception as exc:
        raise TranscriptionBackendError("Python-Paket 'requests' fehlt. Installiere es mit: pip install requests") from exc

    def emit(event: str, **extra: Any) -> None:
        if progress_callback is None:
            return
        payload = {
            "provider_event": event,
            "backend": "groq",
            "model": model_name,
            **extra,
        }
        try:
            progress_callback(event, payload)
        except Exception:
            pass

    response = None
    max_retries = _groq_max_retries()
    request_timeout = _groq_request_timeout_seconds()
    retry_statuses = {429, 500, 502, 503}
    last_error = ""
    temp_upload_dir: tempfile.TemporaryDirectory[str] | None = None
    upload_audio_path = audio_path
    try:
        if _groq_preprocess_audio_enabled(settings):
            temp_upload_dir = tempfile.TemporaryDirectory(prefix="groq_transcript_")
            upload_audio_path = _prepare_groq_upload_audio_path(audio_path, Path(temp_upload_dir.name), settings, emit)

        original_size = audio_path.stat().st_size if audio_path.exists() else None
        upload_size = upload_audio_path.stat().st_size if upload_audio_path.exists() else None
        emit(
            "groq_request_configured",
            audio_filename=upload_audio_path.name,
            audio_size_bytes=upload_size,
            original_audio_filename=audio_path.name,
            original_audio_size_bytes=original_size,
            preprocessed_audio=upload_audio_path != audio_path,
            request_timeout_seconds=request_timeout,
            max_retries=max_retries,
            attempts_total=max_retries + 1,
            language=language,
        )
        for attempt in range(max_retries + 1):
            attempt_number = attempt + 1
            started_at = time.monotonic()
            emit(
                "groq_attempt_started",
                attempt=attempt_number,
                attempts_total=max_retries + 1,
                request_timeout_seconds=request_timeout,
                audio_filename=upload_audio_path.name,
                audio_size_bytes=upload_size,
            )
            try:
                with upload_audio_path.open("rb") as file_handle:
                    response = requests.post(
                        url,
                        headers={"Authorization": f"Bearer {api_key}"},
                        data=data,
                        files={"file": (upload_audio_path.name, file_handle)},
                        timeout=request_timeout,
                    )
            except requests.RequestException as exc:  # type: ignore[attr-defined]
                elapsed = time.monotonic() - started_at
                last_error = str(exc)
                emit(
                    "groq_attempt_failed",
                    attempt=attempt_number,
                    attempts_total=max_retries + 1,
                    elapsed_seconds=round(elapsed, 3),
                    exception_type=exc.__class__.__name__,
                    error=str(exc)[:500],
                )
                if attempt < max_retries:
                    retry_delay = min(60.0, 2.0 * (2 ** attempt))
                    emit(
                        "groq_attempt_retry_scheduled",
                        attempt=attempt_number,
                        attempts_total=max_retries + 1,
                        retry_delay_seconds=retry_delay,
                    )
                    time.sleep(retry_delay)
                    continue
                raise TranscriptionBackendError(
                    f"Groq API ist nicht erreichbar oder hat nach {request_timeout:.0f}s nicht geantwortet: {exc}"
                ) from exc

            elapsed = time.monotonic() - started_at
            emit(
                "groq_attempt_completed",
                attempt=attempt_number,
                attempts_total=max_retries + 1,
                elapsed_seconds=round(elapsed, 3),
                status_code=response.status_code,
                response_chars=len(response.text or ""),
            )
            if response.status_code == 200:
                break
            last_error = f"Groq API Fehler {response.status_code}: {response.text[:700]}"
            if response.status_code in retry_statuses and attempt < max_retries:
                retry_after = response.headers.get("retry-after") or response.headers.get("x-ratelimit-reset-requests")
                try:
                    delay = float(str(retry_after).rstrip("s"))
                except (TypeError, ValueError):
                    delay = 2.0 * (2 ** attempt)
                retry_delay = max(1.0, min(delay, 60.0))
                emit(
                    "groq_attempt_retry_scheduled",
                    attempt=attempt_number,
                    attempts_total=max_retries + 1,
                    retry_delay_seconds=retry_delay,
                    status_code=response.status_code,
                )
                time.sleep(retry_delay)
                continue
            break
    finally:
        if temp_upload_dir is not None:
            temp_upload_dir.cleanup()

    if response is None or response.status_code != 200:
        raise TranscriptionBackendError(last_error or "Groq API lieferte keine gültige Antwort.")

    raw = response.json()
    hyp = _script_flatten_words_from_payload(raw)
    raw["backend"] = "groq"
    raw["model"] = model_name
    raw["text"] = str(raw.get("text") or "")
    return AsrResult(text=str(raw.get("text") or ""), words=_script_hyp_to_word_timings(hyp), segments=_extract_segments(raw), raw=raw)


async def _transcribe_groq(audio_path: Path, language: str, progress_callback: GroqProgressCallback | None = None) -> AsrResult:
    return await asyncio.to_thread(_transcribe_groq_sync, audio_path, language, progress_callback)


def _resolve_whisperx_device(settings: Any) -> str:
    configured = str(getattr(settings, "transcript_whisperx_device", "auto") or "auto").strip().lower()
    if configured in {"cpu", "cuda", "mps"}:
        return configured
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


def _apply_whisperx_thread_limits(settings: Any, device: str) -> int:
    if device != "cpu":
        return 0
    configured = int(getattr(settings, "transcript_whisperx_cpu_threads", 0) or 0)
    env_value = str(os.environ.get("WHISPERX_THREADS", "")).strip()
    if env_value.isdigit() and int(env_value) > 0:
        threads = int(env_value)
    elif configured > 0:
        threads = configured
    else:
        cores = os.cpu_count() or 4
        threads = max(2, min(cores // 2, 6))

    for var in (
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "CT2_INTER_THREADS",
        "CT2_INTRA_THREADS",
    ):
        os.environ[var] = str(threads)

    try:
        import torch

        torch.set_num_threads(threads)
        try:
            torch.set_num_interop_threads(max(1, threads // 2))
        except RuntimeError:
            pass
    except Exception:
        pass
    return threads


def _interpolate_whisperx_words(raw: dict[str, Any]) -> dict[str, Any]:
    """WhisperX kann einzelne Wörter ohne Timestamp liefern.

    Für unser Lyrics-Alignment brauchen wir eine möglichst vollständige
    Wort-Timeline. Fehlende Wortzeiten werden deshalb innerhalb des jeweiligen
    Segments linear interpoliert, ohne vorhandene WhisperX-Zeiten zu verändern.
    """
    if not isinstance(raw, dict):
        return raw
    segments = raw.get("segments")
    if not isinstance(segments, list):
        return raw

    for segment in segments:
        if not isinstance(segment, dict):
            continue
        words = segment.get("words")
        if not isinstance(words, list) or not words:
            continue
        seg_start = _seconds(segment.get("start"), -1.0)
        seg_end = _seconds(segment.get("end"), -1.0)
        if seg_start < 0 or seg_end <= seg_start:
            continue

        timed_count = 0
        for word in words:
            if not isinstance(word, dict):
                continue
            start = _seconds(word.get("start"), -1.0)
            end = _seconds(word.get("end"), -1.0)
            if start >= 0 and end > start:
                timed_count += 1
        if timed_count == len([w for w in words if isinstance(w, dict)]):
            continue

        step = max(0.05, (seg_end - seg_start) / max(1, len(words)))
        for idx, word in enumerate(words):
            if not isinstance(word, dict):
                continue
            start = _seconds(word.get("start"), -1.0)
            end = _seconds(word.get("end"), -1.0)
            if start >= 0 and end > start:
                continue
            interpolated_start = seg_start + (idx * step)
            interpolated_end = min(seg_end, interpolated_start + max(0.05, step * 0.85))
            if interpolated_end <= interpolated_start:
                interpolated_end = min(seg_end, interpolated_start + 0.05)
            word["start"] = round(interpolated_start, 3)
            word["end"] = round(interpolated_end, 3)
            word["interpolated"] = True
    return raw


def _run_whisperx_sync(audio_path: Path, language: str) -> AsrResult:
    """Lokales WhisperX-Backend nach dem funktionierenden Referenzskript."""
    settings = get_settings()
    try:
        import whisperx
    except Exception as exc:
        raise TranscriptionBackendError(
            "whisperx ist im Python-Environment des FastAPI-Services nicht installiert. "
            "Installiere es im aktiven venv mit: pip install -r requirements-whisperx.txt"
        ) from exc

    device = _resolve_whisperx_device(settings)
    threads = _apply_whisperx_thread_limits(settings, device)
    model_name = str(settings.transcript_whisperx_model or "small").strip() or "small"
    compute_type = str(settings.transcript_whisperx_compute_type or "int8").strip() or "int8"
    if device == "cpu":
        compute_type = "int8"
    batch_size = max(1, int(settings.transcript_whisperx_batch_size or 8))
    if device == "cpu":
        batch_size = min(batch_size, 8)
    language_value = None if not language or language == "auto" else language
    align_language = str(getattr(settings, "transcript_whisperx_align_language", "") or "").strip() or None

    try:
        asr_options = {"suppress_numerals": False}
        load_kwargs: dict[str, Any] = {
            "compute_type": compute_type,
            "language": language_value,
            "asr_options": asr_options,
        }
        if threads > 0:
            load_kwargs["threads"] = threads
        try:
            model = whisperx.load_model(model_name, device, **load_kwargs)
        except TypeError:
            load_kwargs.pop("threads", None)
            try:
                model = whisperx.load_model(model_name, device, **load_kwargs)
            except TypeError:
                load_kwargs.pop("asr_options", None)
                model = whisperx.load_model(model_name, device, **load_kwargs)

        audio = whisperx.load_audio(str(audio_path))
        raw = model.transcribe(audio, batch_size=batch_size)
        detected_language = str(raw.get("language") or language_value or "en").strip() or "en"
        align_lang = align_language or detected_language

        try:
            model_a, metadata = whisperx.load_align_model(language_code=align_lang, device=device)
        except Exception:
            model_a, metadata = whisperx.load_align_model(language_code="en", device=device)
            align_lang = "en"

        aligned = whisperx.align(
            raw.get("segments", []),
            model_a,
            metadata,
            audio,
            device,
            return_char_alignments=False,
        )
        if isinstance(aligned, dict) and aligned.get("segments"):
            raw = aligned
        raw["language"] = detected_language
        raw["align_language"] = align_lang
        raw["backend"] = "whisperx"
        raw["device"] = device
        raw["model"] = model_name
        raw["compute_type"] = compute_type
        raw["batch_size"] = batch_size
        raw["text"] = str(raw.get("text") or "\n".join(str(seg.get("text") or "").strip() for seg in raw.get("segments", []) if isinstance(seg, dict))).strip()
    except Exception as exc:
        if isinstance(exc, TranscriptionBackendError):
            raise
        raise TranscriptionBackendError(f"WhisperX-Transkription fehlgeschlagen: {str(exc)[:700]}") from exc

    hyp = _script_flatten_words_from_segments(raw.get("segments", []) if isinstance(raw.get("segments"), list) else [])
    if not hyp:
        hyp = _script_flatten_words_from_payload(raw)
    return AsrResult(text=str(raw.get("text") or ""), words=_script_hyp_to_word_timings(hyp), segments=_extract_segments(raw), raw=raw)


async def _transcribe_whisperx(audio_path: Path, language: str) -> AsrResult:
    return await asyncio.to_thread(_run_whisperx_sync, audio_path, language)


async def transcribe_audio(
    audio_path: Path,
    backend: str,
    language: str,
    progress_callback: GroqProgressCallback | None = None,
) -> AsrResult:
    backend_key = str(backend or "").strip().lower()
    if backend_key == "openai_whisper_api":
        return await _transcribe_openai(audio_path, language)
    if backend_key == "voxtral":
        return await _transcribe_voxtral(audio_path, language)
    if backend_key == "whisperx":
        return await _transcribe_whisperx(audio_path, language)
    if backend_key == "groq":
        return await _transcribe_groq(audio_path, language, progress_callback)
    raise TranscriptionBackendError("Unbekanntes Transkriptionsbackend.")


def _safe_words_json(words: list[WordTiming]) -> list[dict[str, Any]]:
    return [{"word": item.word, "start": round(item.start, 3), "end": round(item.end, 3)} for item in words]


def _latest_transcript(db: Session, audio_asset_id: int) -> AudioTranscript | None:
    return (
        db.query(AudioTranscript)
        .filter(AudioTranscript.audio_asset_id == audio_asset_id)
        .order_by(AudioTranscript.generated_at.desc().nullslast(), AudioTranscript.updated_at.desc(), AudioTranscript.id.desc())
        .first()
    )


def transcript_to_response(transcript: AudioTranscript | None, audio_asset_id: int) -> dict[str, Any]:
    half_path = _half_transcript_path_from_srt_path(transcript.srt_path if transcript else None)
    half_text = ""
    half_exists = False
    if half_path and half_path.exists() and half_path.is_file():
        settings = get_settings()
        transcript_root = settings.transcript_storage_path.resolve()
        if _is_relative_to(half_path.resolve(), transcript_root):
            half_text = half_path.read_text(encoding="utf-8")
            half_exists = bool(half_text.strip())
    if not half_exists and transcript and transcript.status == "completed":
        fallback_segments = transcript.segments_json or srt_to_segments(transcript.srt_text or "")
        if fallback_segments:
            half_text = segments_to_half_srt(fallback_segments, max_chars=22, min_dur=0.6)
            half_exists = bool(half_text.strip())

    if not transcript or transcript.status != "completed" or not transcript.srt_text:
        return {
            "audio_asset_id": audio_asset_id,
            "exists": False,
            "status": transcript.status if transcript else "missing",
            "error_message": transcript.error_message if transcript else None,
            "srt_text": "",
            "srt_url": None,
            "srt_filename": None,
            "half_srt_exists": False,
            "half_srt_text": "",
            "half_srt_url": None,
            "half_srt_filename": None,
            "segments": transcript.segments_json if transcript else [],
            "generated_at": transcript.generated_at.isoformat() if transcript and transcript.generated_at else None,
            "updated_at": transcript.updated_at.isoformat() if transcript and transcript.updated_at else None,
        }
    return {
        "audio_asset_id": audio_asset_id,
        "exists": True,
        "status": transcript.status,
        "backend": transcript.backend,
        "language": transcript.language,
        "mode": transcript.mode,
        "match_mode": transcript.match_mode,
        "srt_text": transcript.srt_text,
        "srt_url": f"/api/audio-assets/{audio_asset_id}/srt/download",
        "srt_filename": Path(transcript.srt_path).name if transcript.srt_path else f"audio-{audio_asset_id}.srt",
        "half_srt_exists": half_exists,
        "half_srt_text": half_text,
        "half_srt_url": f"/api/audio-assets/{audio_asset_id}/srt/half/download" if half_exists else None,
        "half_srt_filename": half_path.name if half_path else f"audio-{audio_asset_id}.half.srt",
        "segments": transcript.segments_json or srt_to_segments(transcript.srt_text or ""),
        "generated_at": transcript.generated_at.isoformat() if transcript.generated_at else None,
        "updated_at": transcript.updated_at.isoformat() if transcript.updated_at else None,
    }


def get_saved_transcript(db: Session, audio_asset_id: int) -> dict[str, Any]:
    asset = db.query(AudioAsset).filter(AudioAsset.id == audio_asset_id, AudioAsset.is_deleted.is_(False)).first()
    if not asset:
        raise HTTPException(status_code=404, detail="AudioAsset wurde nicht gefunden.")
    return transcript_to_response(_latest_transcript(db, audio_asset_id), audio_asset_id)


def get_transcript_download_path(db: Session, audio_asset_id: int) -> tuple[Path, str]:
    transcript = _latest_transcript(db, audio_asset_id)
    if not transcript or transcript.status != "completed" or not transcript.srt_path:
        raise HTTPException(status_code=404, detail="Für diesen Song wurde noch keine SRT erzeugt.")

    settings = get_settings()
    transcript_root = settings.transcript_storage_path.resolve()
    path = Path(transcript.srt_path).resolve()
    if not _is_relative_to(path, transcript_root):
        raise HTTPException(status_code=500, detail="SRT-Pfad liegt außerhalb des erlaubten Transcript-Storage.")
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=500, detail="SRT-Datei ist nicht lesbar oder wurde gelöscht.")
    return path, path.name


def get_half_transcript_download_path(db: Session, audio_asset_id: int) -> tuple[Path, str]:
    transcript = _latest_transcript(db, audio_asset_id)
    if not transcript or transcript.status != "completed" or not transcript.srt_path:
        raise HTTPException(status_code=404, detail="Für diesen Song wurde noch keine SRT erzeugt.")

    settings = get_settings()
    transcript_root = settings.transcript_storage_path.resolve()
    path = _half_transcript_path_from_srt_path(transcript.srt_path)
    if not path:
        raise HTTPException(status_code=404, detail="Für diesen Song wurde noch keine Half-SRT erzeugt.")
    path = path.resolve()
    if not _is_relative_to(path, transcript_root):
        raise HTTPException(status_code=500, detail="Half-SRT-Pfad liegt außerhalb des erlaubten Transcript-Storage.")
    if not path.exists() or not path.is_file():
        fallback_segments = transcript.segments_json or srt_to_segments(transcript.srt_text or "")
        half_text = segments_to_half_srt(fallback_segments, max_chars=22, min_dur=0.6)
        if half_text.strip():
            path.write_text(half_text, encoding="utf-8")
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Half-SRT-Datei ist nicht vorhanden oder nicht lesbar.")
    return path, path.name



def _asset_title(asset: AudioAsset, fallback: str = "AudioAsset") -> str:
    return str(asset.display_title or asset.title or asset.filename or fallback).strip() or fallback


SRT_STATUS_PHASES: dict[str, tuple[int, str]] = {
    "initializing": (1, "SRT-Erzeugung initialisiert"),
    "lyrics_resolved": (2, "Songtext/Prompt geladen"),
    "lyrics_cleanup_started": (3, "Textaufbereitung gestartet"),
    "lyrics_cleanup_completed": (4, "Textaufbereitung abgeschlossen"),
    "language_resolved": (5, "Transkriptionssprache ermittelt"),
    "audio_resolving": (6, "Audiodatei wird geprüft"),
    "audio_ready": (7, "Audiodatei bereit"),
    "transcript_record_created": (8, "Transcript-Datensatz angelegt"),
    "transcription_started": (9, "Transkription gestartet"),
    "transcription_completed": (10, "Transkription abgeschlossen"),
    "alignment_started": (11, "Lyrics/SRT-Alignment gestartet"),
    "alignment_completed": (12, "Lyrics/SRT-Alignment abgeschlossen"),
    "files_written": (13, "SRT-Dateien gespeichert"),
    "structure_segments_stored": (14, "Waveform-Struktursegmente gespeichert"),
    "completed": (15, "SRT-Erzeugung abgeschlossen"),
    "failed": (15, "SRT-Erzeugung fehlgeschlagen"),
}
SRT_STATUS_TOTAL_STEPS = 15


def _json_safe_preview(value: Any, max_len: int = 240) -> Any:
    if value is None:
        return None
    if isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_json_safe_preview(item, max_len=max_len) for item in value[:12]]
    if isinstance(value, dict):
        return {str(key): _json_safe_preview(item, max_len=max_len) for key, item in list(value.items())[:18]}
    text = str(value)
    return text if len(text) <= max_len else f"{text[:max_len]}…"


def _transcription_timeout_seconds(backend: str) -> float:
    settings = get_settings()
    backend_key = str(backend or "").strip().lower()
    if backend_key == "whisperx":
        return float(getattr(settings, "transcript_whisperx_timeout_seconds", 1800) or 1800)
    return float(getattr(settings, "srt_transcription_timeout_seconds", 240.0) or 240.0)


def _groq_request_timeout_seconds() -> float:
    settings = get_settings()
    specific = float(getattr(settings, "transcript_groq_request_timeout_seconds", 90.0) or 90.0)
    legacy = float(getattr(settings, "transcript_request_timeout_seconds", specific) or specific)
    return max(10.0, min(specific, legacy))


def _groq_max_retries() -> int:
    settings = get_settings()
    try:
        value = int(getattr(settings, "transcript_groq_max_retries", 2) or 0)
    except (TypeError, ValueError):
        value = 2
    return max(0, min(value, 5))


def _update_srt_status_step(
    db: Session,
    task: SunoTask | None,
    asset: AudioAsset | None,
    phase: str,
    *,
    detail: str | None = None,
    extra: dict[str, Any] | None = None,
    status: str = "RUNNING",
    commit: bool = True,
) -> None:
    if task is None:
        return
    now = utc_now_naive()
    step, label = SRT_STATUS_PHASES.get(phase, (1, phase.replace("_", " ").strip().title() or "SRT"))
    progress: dict[str, Any] = {
        "current": step,
        "total": SRT_STATUS_TOTAL_STEPS,
        "phase": phase,
        "phase_label": label,
        "detail": detail or label,
    }
    if asset is not None:
        progress["audio_asset_id"] = asset.id
    if extra:
        progress.update({key: _json_safe_preview(value) for key, value in extra.items()})

    payload = dict(task.response_payload or {})
    steps_log = payload.get("steps_log") if isinstance(payload.get("steps_log"), list) else []
    steps_log.append({
        "at": now.isoformat(),
        "phase": phase,
        "phase_label": label,
        "detail": detail or label,
        **({key: _json_safe_preview(value) for key, value in (extra or {}).items()}),
    })
    payload.update({
        "background": True,
        "local_task": True,
        "status": status,
        "heartbeat_at": now.isoformat(),
        "progress": progress,
        "steps_log": steps_log[-40:],
    })
    if asset is not None:
        payload["audio_asset_id"] = asset.id
    task.status = status
    task.heartbeat_at = now
    if not task.started_at:
        task.started_at = now
    task.response_payload = payload
    db.add(task)

    running_notifications = (
        db.query(StatusNotification)
        .filter(
            StatusNotification.task_local_id == task.id,
            StatusNotification.event_type == "srt_generation_started",
            StatusNotification.status != "done",
            StatusNotification.is_deleted.is_(False),
        )
        .all()
    )
    for row in running_notifications:
        row.message = f"{label}: {detail or label}"
        row.updated_at = now
        db.add(row)

    if commit:
        db.commit()
        try:
            db.refresh(task)
        except Exception:
            pass


async def _transcribe_audio_with_timeout(
    audio_path: Path,
    backend: str,
    language: str,
    progress_callback: GroqProgressCallback | None = None,
) -> AsrResult:
    timeout_seconds = _transcription_timeout_seconds(backend)
    try:
        return await asyncio.wait_for(transcribe_audio(audio_path, backend, language, progress_callback), timeout=timeout_seconds)
    except asyncio.TimeoutError as exc:
        raise TranscriptionBackendError(
            f"{backend}-Transkription nach {timeout_seconds:.0f}s abgebrochen. "
            "Der Provider hat nicht rechtzeitig geantwortet; der lokale SRT-Task wurde sauber beendet."
        ) from exc


def _groq_progress_detail(event: str, payload: dict[str, Any]) -> str:
    attempt = payload.get("attempt")
    attempts_total = payload.get("attempts_total")
    attempt_text = f" Versuch {attempt}/{attempts_total}" if attempt and attempts_total else ""
    elapsed = payload.get("elapsed_seconds")
    elapsed_text = f" nach {elapsed}s" if elapsed is not None else ""
    if event == "groq_request_configured":
        size = payload.get("audio_size_bytes")
        size_mb = round(float(size) / 1024 / 1024, 2) if isinstance(size, (int, float)) else None
        return (
            "Groq-Transkription vorbereitet"
            f" ({size_mb} MB, Timeout {payload.get('request_timeout_seconds')}s, Retries {payload.get('max_retries')})."
        )
    if event == "groq_audio_preprocess_started":
        size = payload.get("source_size_bytes")
        size_mb = round(float(size) / 1024 / 1024, 2) if isinstance(size, (int, float)) else None
        return f"Groq-Audio wird fuer Transkription vorbereitet ({size_mb} MB -> {payload.get('bitrate')}, {payload.get('sample_rate')} Hz)."
    if event == "groq_audio_preprocess_completed":
        source_size = payload.get("source_size_bytes")
        upload_size = payload.get("upload_size_bytes")
        source_mb = round(float(source_size) / 1024 / 1024, 2) if isinstance(source_size, (int, float)) else None
        upload_mb = round(float(upload_size) / 1024 / 1024, 2) if isinstance(upload_size, (int, float)) else None
        return f"Groq-Audio vorbereitet ({source_mb} MB -> {upload_mb} MB)."
    if event == "groq_audio_preprocess_failed":
        return f"Groq-Audio-Vorbereitung fehlgeschlagen, Original wird verwendet: {payload.get('reason') or 'unbekannt'}."
    if event == "groq_audio_preprocess_skipped":
        return f"Groq-Audio-Vorbereitung uebersprungen: {payload.get('reason') or 'deaktiviert'}."
    if event == "groq_attempt_started":
        return f"Groq-Transkription{attempt_text} gestartet."
    if event == "groq_attempt_completed":
        return f"Groq-Transkription{attempt_text}{elapsed_text} mit HTTP {payload.get('status_code')} beendet."
    if event == "groq_attempt_failed":
        return f"Groq-Transkription{attempt_text}{elapsed_text} fehlgeschlagen: {payload.get('exception_type') or 'RequestException'}."
    if event == "groq_attempt_retry_scheduled":
        return f"Groq-Transkription{attempt_text}: neuer Versuch in {payload.get('retry_delay_seconds')}s."
    return f"Groq-Transkription: {event}."


async def _transcribe_audio_with_status_events(
    db: Session,
    srt_task: SunoTask | None,
    asset: AudioAsset | None,
    audio_path: Path,
    backend: str,
    language: str,
) -> AsrResult:
    if str(backend or "").strip().lower() != "groq" or srt_task is None or asset is None:
        return await _transcribe_audio_with_timeout(audio_path, backend, language)

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()

    def progress_callback(event: str, payload: dict[str, Any]) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, (event, payload))

    transcription_task = asyncio.create_task(
        _transcribe_audio_with_timeout(audio_path, backend, language, progress_callback)
    )
    queue_task: asyncio.Task[tuple[str, dict[str, Any]]] | None = asyncio.create_task(queue.get())

    async def flush_events() -> None:
        while True:
            try:
                event, payload = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            _update_srt_status_step(
                db,
                srt_task,
                asset,
                "transcription_started",
                detail=_groq_progress_detail(event, payload),
                extra=payload,
            )

    try:
        while True:
            wait_items: set[asyncio.Task[Any]] = {transcription_task}
            if queue_task is not None:
                wait_items.add(queue_task)
            done, _pending = await asyncio.wait(wait_items, return_when=asyncio.FIRST_COMPLETED)

            if queue_task is not None and queue_task in done:
                event, payload = queue_task.result()
                _update_srt_status_step(
                    db,
                    srt_task,
                    asset,
                    "transcription_started",
                    detail=_groq_progress_detail(event, payload),
                    extra=payload,
                )
                queue_task = asyncio.create_task(queue.get())

            if transcription_task in done:
                if queue_task is not None:
                    queue_task.cancel()
                await flush_events()
                return transcription_task.result()
    finally:
        if queue_task is not None and not queue_task.done():
            queue_task.cancel()


def _create_srt_status_task(
    db: Session,
    asset: AudioAsset,
    backend: str,
    language: str,
    language_info: dict[str, Any] | None = None,
    transcription_audio_source: dict[str, Any] | None = None,
    lyrics_cleanup_info: dict[str, Any] | None = None,
) -> SunoTask:
    now = utc_now_naive()
    request_payload = {
        "audio_asset_id": asset.id,
        "song_id": asset.song_id,
        "backend": backend,
        "language": language,
        "title": _asset_title(asset, f"AudioAsset {asset.id}"),
        "local_task": True,
    }
    if language_info:
        request_payload["language_detection"] = language_info
        request_payload["configured_language"] = language_info.get("configured_language")
        request_payload["detected_language"] = language_info.get("detected_language")
        request_payload["language_source"] = language_info.get("language_source")
    if transcription_audio_source:
        request_payload["transcription_audio_source"] = transcription_audio_source
    if lyrics_cleanup_info:
        request_payload["lyrics_cleanup"] = lyrics_cleanup_info

    task = SunoTask(
        task_id=None,
        task_type="generate_srt",
        status="RUNNING",
        request_payload=request_payload,
        response_payload=None,
        result_payload=None,
        error_message=None,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    notification = StatusNotification(
        event_type="srt_generation_started",
        title=f"SRT-Erzeugung läuft: {_asset_title(asset, f'AudioAsset {asset.id}')}",
        message=f"Backend: {backend} · Sprache: {language}",
        severity="info",
        status="unread",
        task_local_id=task.id,
        suno_task_id=None,
        content_type="audio",
        content_id=asset.id,
        target_tab="library",
        target_payload={
            "audio_asset_id": asset.id,
            "task_local_id": task.id,
            "task_type": "generate_srt",
            "status": "RUNNING",
        },
    )
    db.add(notification)
    db.commit()
    return task


def _finish_srt_status_task(db: Session, task: SunoTask | None, asset: AudioAsset, status: str, message: str, result_payload: dict[str, Any] | None = None) -> None:
    now = utc_now_naive()
    if task:
        task.status = status
        task.completed_at = now
        task.heartbeat_at = now
        task.error_message = None if status == "SUCCESS" else message
        task.result_payload = result_payload or {
            "audio_asset_id": asset.id,
            "status": status,
            "message": message,
        }
        existing_payload = dict(task.response_payload or {})
        existing_progress = dict(existing_payload.get("progress") or {})
        final_phase = "completed" if status == "SUCCESS" else "failed"
        final_step, final_label = SRT_STATUS_PHASES.get(final_phase, (SRT_STATUS_TOTAL_STEPS, status))
        existing_payload.update({
            "background": True,
            "local_task": True,
            "audio_asset_id": asset.id,
            "status": status,
            "message": message,
            "completed_at": now.isoformat(),
            "heartbeat_at": now.isoformat(),
            "progress": {
                **existing_progress,
                "current": final_step,
                "total": SRT_STATUS_TOTAL_STEPS,
                "audio_asset_id": asset.id,
                "phase": final_phase,
                "phase_label": final_label,
                "detail": message,
            },
        })
        steps_log = existing_payload.get("steps_log") if isinstance(existing_payload.get("steps_log"), list) else []
        steps_log.append({
            "at": now.isoformat(),
            "phase": final_phase,
            "phase_label": final_label,
            "detail": message,
        })
        existing_payload["steps_log"] = steps_log[-40:]
        task.response_payload = existing_payload
        db.add(task)
        running_rows = (
            db.query(StatusNotification)
            .filter(
                StatusNotification.task_local_id == task.id,
                StatusNotification.event_type == "srt_generation_started",
                StatusNotification.status != "done",
                StatusNotification.is_deleted.is_(False),
            )
            .all()
        )
        for row in running_rows:
            row.status = "done"
            row.completed_at = now
            row.message = f"Abgeschlossen: {message}"
            db.add(row)

    notification = StatusNotification(
        event_type="srt_generation_completed" if status == "SUCCESS" else "srt_generation_failed",
        title=f"SRT-Erzeugung {'fertig' if status == 'SUCCESS' else 'fehlgeschlagen'}: {_asset_title(asset, f'AudioAsset {asset.id}')}",
        message=message,
        severity="success" if status == "SUCCESS" else "error",
        status="unread",
        task_local_id=task.id if task else None,
        suno_task_id=None,
        content_type="audio",
        content_id=asset.id,
        target_tab="library" if status == "SUCCESS" else "status",
        target_payload={
            "audio_asset_id": asset.id,
            "task_local_id": task.id if task else None,
            "task_type": "generate_srt",
            "status": status,
        },
        completed_at=now,
    )
    db.add(notification)
    db.commit()


def save_manual_srt_for_audio_asset(db: Session, audio_asset_id: int, srt_text: str | None = None, segments: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    asset = db.query(AudioAsset).filter(AudioAsset.id == audio_asset_id, AudioAsset.is_deleted.is_(False)).first()
    if not asset:
        raise HTTPException(status_code=404, detail="AudioAsset wurde nicht gefunden.")

    normalized_segments = _coerce_editor_segments(segments, srt_text)
    normalized_srt = segments_to_srt(normalized_segments)
    if not normalized_srt.strip():
        raise HTTPException(status_code=422, detail="Die SRT konnte aus den Segmenten nicht erzeugt werden.")

    target_path = _write_transcript_file(asset, audio_asset_id, normalized_srt)
    half_srt_text = segments_to_half_srt(normalized_segments, max_chars=22, min_dur=0.6)
    if half_srt_text.strip():
        _write_transcript_text_file(asset, audio_asset_id, half_srt_text, suffix=".half.srt")
    now = utc_now_naive()
    transcript = _latest_transcript(db, audio_asset_id)
    if not transcript:
        transcript = AudioTranscript(
            audio_asset_id=audio_asset_id,
            backend="manual_editor",
            language="manual",
            mode=TRANSCRIPTION_MODE,
            match_mode=TRANSCRIPTION_MATCH_MODE,
            status="completed",
            generated_at=now,
        )
    transcript.backend = transcript.backend or "manual_editor"
    transcript.language = transcript.language or "manual"
    transcript.mode = TRANSCRIPTION_MODE
    transcript.match_mode = TRANSCRIPTION_MATCH_MODE
    transcript.srt_text = normalized_srt
    transcript.srt_path = str(target_path)
    transcript.segments_json = normalized_segments
    transcript.status = "completed"
    transcript.error_message = None
    transcript.generated_at = transcript.generated_at or now
    transcript.updated_at = now
    db.add(transcript)
    db.commit()
    db.refresh(transcript)

    db.add(StatusNotification(
        event_type="srt_editor_saved",
        title=f"SRT gespeichert: {_asset_title(asset, f'AudioAsset {asset.id}')}",
        message=f"{len(normalized_segments)} Segment(e) wurden gespeichert.",
        severity="success",
        status="unread",
        content_type="audio",
        content_id=asset.id,
        target_tab="library",
        target_payload={"audio_asset_id": asset.id, "status": "SUCCESS", "task_type": "srt_editor"},
        completed_at=now,
    ))
    db.commit()
    return transcript_to_response(transcript, audio_asset_id)


async def generate_srt_for_audio_asset(
    db: Session,
    audio_asset_id: int,
    manual_lyrics: str | None = None,
    force: bool = True,
    language_override: str | None = None,
    backend_override: str | None = None,
    prefer_existing_vocal_stem: bool = True,
    status_task: SunoTask | None = None,
) -> dict[str, Any]:
    asset = db.query(AudioAsset).filter(AudioAsset.id == audio_asset_id, AudioAsset.is_deleted.is_(False)).first()
    if not asset:
        raise HTTPException(status_code=404, detail="AudioAsset wurde nicht gefunden.")

    srt_task: SunoTask | None = status_task
    transcript: AudioTranscript | None = None

    try:
        _update_srt_status_step(db, srt_task, asset, "initializing", detail="AudioAsset geladen, Admin-Settings werden geprüft.")
        admin_settings = load_transcription_admin_settings(db)
        if not admin_settings.get("srt_output_enabled", True):
            raise HTTPException(status_code=422, detail="SRT-Ausgabe ist im Admin-Bereich deaktiviert.")

        if not force:
            existing = _latest_transcript(db, audio_asset_id)
            if existing and existing.status == "completed" and existing.srt_text:
                _update_srt_status_step(db, srt_task, asset, "completed", detail="Vorhandene SRT wurde wiederverwendet.", status="SUCCESS")
                return transcript_to_response(existing, audio_asset_id)

        backend = str(backend_override or admin_settings["transcription_backend"] or "").strip().lower()
        if backend not in SUPPORTED_BACKENDS:
            raise HTTPException(status_code=400, detail="Transkriptionsbackend ist nicht freigegeben.")

        configured_language = str(language_override or admin_settings["transcription_language"] or "auto").strip().lower()
        if configured_language not in SUPPORTED_LANGUAGES:
            raise HTTPException(status_code=400, detail="Transkriptionssprache ist nicht freigegeben.")

        _update_srt_status_step(
            db,
            srt_task,
            asset,
            "lyrics_resolved",
            detail="Lyrics/Prompt werden als Source of Truth aufgeloest.",
            extra={"backend": backend, "configured_language": configured_language},
        )
        source_lyrics = resolve_lyrics_for_audio_asset(db, audio_asset_id, manual_lyrics, allow_missing=True)
        has_alignment_lyrics = has_visible_lyrics_for_alignment(source_lyrics)

        if has_alignment_lyrics:
            _update_srt_status_step(
                db,
                srt_task,
                asset,
                "lyrics_cleanup_started",
                detail="Deterministische und optionale KI-Textaufbereitung laeuft.",
                extra={"source_chars": len(source_lyrics or "")},
            )
            lyrics, lyrics_cleanup_info = await prepare_lyrics_for_srt_alignment(db, asset, source_lyrics, admin_settings)
            has_alignment_lyrics = has_visible_lyrics_for_alignment(lyrics)
            _update_srt_status_step(
                db,
                srt_task,
                asset,
                "lyrics_cleanup_completed",
                detail="Textaufbereitung abgeschlossen.",
                extra={
                    "source_chars": lyrics_cleanup_info.get("source_chars") if isinstance(lyrics_cleanup_info, dict) else len(source_lyrics or ""),
                    "clean_chars": lyrics_cleanup_info.get("clean_chars") if isinstance(lyrics_cleanup_info, dict) else len(lyrics or ""),
                    "method": lyrics_cleanup_info.get("method") if isinstance(lyrics_cleanup_info, dict) else None,
                    "ai_used": bool((lyrics_cleanup_info.get("ai") or {}).get("used")) if isinstance(lyrics_cleanup_info, dict) and isinstance(lyrics_cleanup_info.get("ai"), dict) else False,
                    "alignment_lyrics": has_alignment_lyrics,
                },
            )
        else:
            lyrics = ""
            lyrics_cleanup_info = {
                "enabled": False,
                "used": False,
                "method": "skipped_no_lyrics",
                "source_chars": 0,
                "clean_chars": 0,
                "reason": "no_visible_lyrics_for_alignment",
            }
            _update_srt_status_step(
                db,
                srt_task,
                asset,
                "lyrics_cleanup_started",
                detail="Kein verwertbarer Songtext vorhanden; Textaufbereitung wird uebersprungen.",
                extra=lyrics_cleanup_info,
            )
            _update_srt_status_step(
                db,
                srt_task,
                asset,
                "lyrics_cleanup_completed",
                detail="Kein verwertbarer Songtext vorhanden; SRT wird aus Transkription erstellt.",
                extra=lyrics_cleanup_info,
            )

        language, language_info = resolve_transcription_language(configured_language, lyrics)
        _update_srt_status_step(
            db,
            srt_task,
            asset,
            "language_resolved",
            detail=f"Sprache fuer Transkription: {language}",
            extra=language_info,
        )

        _update_srt_status_step(db, srt_task, asset, "audio_resolving", detail="Lokale Audiodatei wird gesucht und geprueft.")
        audio_path = await ensure_safe_audio_path(db, asset)
        transcription_audio_path, transcription_audio_source = select_audio_path_for_transcription(
            asset,
            audio_path,
            prefer_existing_vocal_stem=prefer_existing_vocal_stem,
        )
        _update_srt_status_step(
            db,
            srt_task,
            asset,
            "audio_ready",
            detail="Audiodatei fuer Transkription ist bereit.",
            extra={
                "source": transcription_audio_source.get("source") if isinstance(transcription_audio_source, dict) else None,
                "path": str(transcription_audio_path),
            },
        )

        if srt_task is None:
            srt_task = _create_srt_status_task(db, asset, backend, language, language_info, transcription_audio_source, lyrics_cleanup_info)
        else:
            srt_task.request_payload = {
                **(srt_task.request_payload or {}),
                "backend": backend,
                "language": language,
                "language_detection": language_info,
                "transcription_audio_source": transcription_audio_source,
                "lyrics_cleanup": lyrics_cleanup_info,
            }
            srt_task.heartbeat_at = utc_now_naive()
            db.add(srt_task)
            db.commit()
        _update_srt_status_step(db, srt_task, asset, "audio_ready", detail="Task-Payload aktualisiert.")

        transcript = AudioTranscript(
            audio_asset_id=audio_asset_id,
            backend=backend,
            language=language,
            mode=TRANSCRIPTION_MODE,
            match_mode=TRANSCRIPTION_MATCH_MODE,
            status="running",
        )
        db.add(transcript)
        db.commit()
        db.refresh(transcript)
        _update_srt_status_step(
            db,
            srt_task,
            asset,
            "transcript_record_created",
            detail="Transcript-Datensatz wurde angelegt.",
            extra={"transcript_id": transcript.id},
        )

        duration = float(read_audio_duration_seconds(audio_path) or 0.0)
        _update_srt_status_step(
            db,
            srt_task,
            asset,
            "transcription_started",
            detail=f"{backend}-Transkription laeuft.",
            extra={
                "backend": backend,
                "language": language,
                "duration_seconds": round(duration, 3),
                "timeout_seconds": _transcription_timeout_seconds(backend),
                "groq_request_timeout_seconds": _groq_request_timeout_seconds() if backend == "groq" else None,
                "groq_max_retries": _groq_max_retries() if backend == "groq" else None,
            },
        )
        asr = await _transcribe_audio_with_status_events(db, srt_task, asset, transcription_audio_path, backend, language)
        _update_srt_status_step(
            db,
            srt_task,
            asset,
            "transcription_completed",
            detail="Transkription abgeschlossen, Wortzeiten werden fuer Alignment vorbereitet.",
            extra={"word_count": len(asr.words or []), "asr_segments": len(asr.segments or [])},
        )

        if isinstance(asr.raw, dict):
            asr.raw["songstudio_language_detection"] = language_info
            asr.raw["songstudio_transcription_audio_source"] = transcription_audio_source
            asr.raw["songstudio_lyrics_cleanup"] = lyrics_cleanup_info

        _update_srt_status_step(
            db,
            srt_task,
            asset,
            "alignment_started",
            detail="Lyrics werden auf die Transkriptionszeiten ausgerichtet." if has_alignment_lyrics else "Keine Lyrics vorhanden; ASR-Text wird direkt als SRT segmentiert.",
            extra={"mode": "lyrics_alignment" if has_alignment_lyrics else "transcription_only_no_lyrics"},
        )
        alignment_bundle = align_lyrics_to_timeline_bundle(lyrics, asr, duration) if has_alignment_lyrics else build_transcription_only_srt_bundle(asr, duration)
        segments = alignment_bundle["segments"]
        half_srt_text = str(alignment_bundle.get("half_srt_text") or "")
        srt_text = segments_to_srt(segments)
        _update_srt_status_step(
            db,
            srt_task,
            asset,
            "alignment_completed",
            detail="Alignment abgeschlossen.",
            extra={
                "segments": len(segments or []),
                "alignment_warnings": len(alignment_bundle.get("alignment_report") or []),
                "half_srt": bool(half_srt_text.strip()),
                "mode": alignment_bundle.get("mode") or "lyrics_alignment",
                "source": alignment_bundle.get("source"),
            },
        )
        if not srt_text.strip():
            raise HTTPException(status_code=422, detail="Alignment fehlgeschlagen: Es wurde keine SRT erzeugt.")

        target_path = _write_transcript_file(asset, audio_asset_id, srt_text)
        if half_srt_text.strip():
            _write_transcript_text_file(asset, audio_asset_id, half_srt_text, suffix=".half.srt")
        _update_srt_status_step(
            db,
            srt_task,
            asset,
            "files_written",
            detail="SRT- und optionale Half-SRT-Dateien wurden gespeichert.",
            extra={"srt_path": str(target_path), "half_srt": bool(half_srt_text.strip())},
        )

        transcript.srt_text = srt_text
        transcript.srt_path = str(target_path)
        transcript.segments_json = segments
        transcript.words_json = _safe_words_json(asr.words)
        transcript.status = "completed"
        transcript.error_message = None
        transcript.generated_at = utc_now_naive()
        transcript.updated_at = utc_now_naive()
        db.add(transcript)
        structure_segments = _store_structure_segments_from_srt_alignment(db, asset, source_lyrics, segments, duration) if has_alignment_lyrics else []
        _update_srt_status_step(
            db,
            srt_task,
            asset,
            "structure_segments_stored",
            detail="Waveform-Struktursegmente wurden aus SRT-Zeiten gespeichert." if has_alignment_lyrics else "Keine Lyrics-Struktur vorhanden; Waveform-Struktursegmente wurden nicht geaendert.",
            extra={"structure_segments": len(structure_segments or [])},
            commit=False,
        )
        db.commit()
        db.refresh(transcript)
        result = transcript_to_response(transcript, audio_asset_id)
        result["language_detection"] = language_info
        result["transcription_audio_source"] = transcription_audio_source
        result["lyrics_cleanup"] = lyrics_cleanup_info
        result["alignment_report"] = alignment_bundle.get("alignment_report") or []
        result["half_max_chars"] = alignment_bundle.get("half_max_chars", 22)
        result["srt_generation_mode"] = alignment_bundle.get("mode") or "lyrics_alignment"
        if alignment_bundle.get("source"):
            result["srt_generation_source"] = alignment_bundle.get("source")
        if structure_segments:
            result["structure_segments"] = structure_segments
        _finish_srt_status_task(db, srt_task, asset, "SUCCESS", "SRT wurde erzeugt und gespeichert.", result)
        return result
    except HTTPException as exc:
        if transcript:
            transcript.status = "error"
            transcript.error_message = str(exc.detail)
            transcript.updated_at = utc_now_naive()
            db.add(transcript)
            db.commit()
        _update_srt_status_step(db, srt_task, asset, "failed", detail=str(exc.detail), status="FAILED")
        _finish_srt_status_task(db, srt_task, asset, "FAILED", str(exc.detail))
        raise
    except TranscriptionBackendError as exc:
        if transcript:
            transcript.status = "error"
            transcript.error_message = str(exc)
            transcript.updated_at = utc_now_naive()
            db.add(transcript)
            db.commit()
        _update_srt_status_step(db, srt_task, asset, "failed", detail=str(exc), status="FAILED")
        _finish_srt_status_task(db, srt_task, asset, "FAILED", str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        if transcript:
            transcript.status = "error"
            transcript.error_message = str(exc)
            transcript.updated_at = utc_now_naive()
            db.add(transcript)
            db.commit()
        _update_srt_status_step(db, srt_task, asset, "failed", detail=str(exc), status="FAILED")
        _finish_srt_status_task(db, srt_task, asset, "FAILED", str(exc))
        raise HTTPException(status_code=500, detail=f"SRT-Erzeugung fehlgeschlagen: {exc}") from exc

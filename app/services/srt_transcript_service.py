from __future__ import annotations

# CORE CONTRACT
# Zweck: Erzeugt SRT/Half-SRT aus AudioAssets und Lyrics als Source of Truth.
# Audios ohne verwertbare Lyrics duerfen als Fallback ASR-only-SRT erzeugen;
# dieser Fallback darf den normalen Lyrics-Cleanup-/Alignment-Pfad nicht ersetzen.
# Kritische Logik: Lyrics-Cleanup, Transkriptionsprovider, Alignment, Task-Finalisierung.
# Tasks duerfen nie dauerhaft RUNNING bleiben; Providerfehler muessen FAILED setzen.
# SRT-Zeiten bauen structure_segments_json fuer Waveform-Abschnitte.
# Stand 2026-07-05: Wiederholte Suno-Abschnittsbloecke werden generisch per
# ASR-Wortzeiten verankert; unbelegte 0,3s-Wiederholungsquetschungen werden
# ausgelassen statt kuenstlich angezeigt. Diese Regeln sind nicht songspezifisch
# und duerfen nur mit Regressionstest gegen doppelte Hook/Bridge-Zeilen geaendert werden.
# Stand 2026-07-05: ASR-Zeilenkandidaten werden vor den Fallback-Heuristiken
# sequenziell und fuzzy gegen die Lyrics gemappt. Das schuetzt die Songtext-
# Reihenfolge bei ASR-Luecken/Fehlhoerungen und ersetzt wortspezifische Fixes
# durch generische Token-Aehnlichkeit plus monotone Skip-Kosten.
# Groq-Sonderfall: Der Groq-Upload nutzt bei Bedarf eine temporaere, klein
# kodierte Mono-Kopie der Audiodatei. Diese Kopie existiert nur fuer den
# Provider-POST und darf nicht die Originaldatei, Lyrics-Bereinigung, Alignment-
# Semantik, SRT-Ausgabe oder Waveform-/Abschnittslogik veraendern.
# Nicht aendern ohne Pruefung: audio_assets.py, MiniPlayer.jsx, LibraryPage.jsx, waveform_service.py.
# Siehe: docs/ARCHITECTURE_CONTRACT.md


import asyncio
import difflib
import json
import logging
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
SRT_DEBUG_LOG_LIMIT = 120

logger = logging.getLogger("songstudio.srt")

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
    section_label: str | None = None
    section_type: str | None = None
    starts_section: bool = False


@dataclass
class HypWord:
    norm: str
    start: float
    end: float


@dataclass
class _AsrLineCandidate:
    index: int
    tokens: list[str]
    start: float
    end: float
    text: str


@dataclass
class _AsrLyricsLineMatch:
    candidate_index: int
    line_index: int
    score: float
    start: float
    end: float
    text: str


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


_COLOGNE_TRANSLATE = str.maketrans({"ä": "a", "ö": "o", "ü": "u", "ß": "s"})


def _cologne_phonetics(word: str) -> str:
    """Kölner Phonetik für generische deutsche Lautgleichheit.

    Ersetzt songspezifische Schreibvarianten-Hardcodes (z. B. gehn/gehen) durch
    einen generischen phonetischen Vergleich. Reine Stdlib, deterministisch.
    """
    text = str(word or "").lower().translate(_COLOGNE_TRANSLATE)
    text = re.sub(r"[^a-z]", "", text)
    if not text:
        return ""
    codes: list[str] = []
    n = len(text)
    for i, ch in enumerate(text):
        prev = text[i - 1] if i > 0 else ""
        nxt = text[i + 1] if i + 1 < n else ""
        if ch in "aeijouy":
            codes.append("0")
        elif ch == "h":
            codes.append("-")
        elif ch == "b":
            codes.append("1")
        elif ch == "p":
            codes.append("3" if nxt == "h" else "1")
        elif ch in "dt":
            codes.append("8" if nxt in "csz" else "2")
        elif ch in "fvw":
            codes.append("3")
        elif ch in "gkq":
            codes.append("4")
        elif ch == "c":
            if i == 0:
                codes.append("4" if nxt in "ahkloqrux" else "8")
            elif prev in "sz":
                codes.append("8")
            else:
                codes.append("4" if nxt in "ahkoqux" else "8")
        elif ch == "x":
            codes.append("8" if prev in "ckq" else "48")
        elif ch == "l":
            codes.append("5")
        elif ch in "mn":
            codes.append("6")
        elif ch == "r":
            codes.append("7")
        elif ch in "sz":
            codes.append("8")
    raw = "".join(codes).replace("-", "")
    collapsed: list[str] = []
    for ch in raw:
        if collapsed and collapsed[-1] == ch:
            continue
        collapsed.append(ch)
    result = "".join(collapsed)
    if not result:
        return ""
    return result[0] + result[1:].replace("0", "")


def _script_word_similarity(a: str, b: str) -> float:
    """Generische Token-Ähnlichkeit für ASR-Fehlhörungen.

    Kombiniert String-Ratio, Präfix-Beziehung und Kölner Phonetik. Damit werden
    Fälle wie gehn/gehen, Flut/Blut oder leicht abweichende Endungen generisch
    behandelt, ohne wortspezifische Sonderfälle im Code zu pflegen.
    """
    left = str(a or "")
    right = str(b or "")
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    if min(len(left), len(right)) < 3:
        return 0.0
    ratio = difflib.SequenceMatcher(a=left, b=right, autojunk=False).ratio()
    if left.startswith(right) or right.startswith(left):
        ratio = max(ratio, min(len(left), len(right)) / max(len(left), len(right)) + 0.12)
    if len(left) >= 4 and len(right) >= 4 and _cologne_phonetics(left) == _cologne_phonetics(right):
        ratio = max(ratio, 0.86)
    return min(ratio, 1.0)


SCRIPT_FUZZY_WORD_THRESHOLD = 0.72


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


def _script_parse_lyrics_text(
    lyrics: str,
    skip_prefixes: tuple[str, ...] = ("#", "/", ";"),
    skip_parens: bool = False,
    source_lyrics: str | None = None,
) -> list[LyricLine]:
    """Parse sichtbare Lyrics-Zeilen für das Alignment.

    Wenn der originale Songtext mit Suno-Abschnittstags verfügbar ist, werden die
    Abschnittsinformationen zusätzlich an die bereinigten Zeilen gehängt. Die
    sichtbare SRT bleibt tagfrei, aber das Alignment kann frühe Intro-/Verse-
    Übergänge dadurch stabiler bewerten.
    """
    parsed: list[LyricLine] = []
    source_entries = _source_structure_lyrics_lines(source_lyrics or "") if source_lyrics else []
    previous_section_key: str | None = None

    def marker_for_line(line_index: int, visible_text: str) -> dict[str, str] | None:
        if not source_entries or line_index >= len(source_entries):
            return None
        entry = source_entries[line_index]
        marker = entry.get("marker") if isinstance(entry, dict) else None
        if not isinstance(marker, dict):
            return None
        # Defensive Prüfung: Die deterministische SRT-Bereinigung und der
        # Struktur-Parser sollten dieselbe Zeilenreihenfolge erzeugen. Falls die
        # KI später minimal anders normalisiert hat, akzeptieren wir den Marker
        # trotzdem nur, wenn die Textähnlichkeit noch plausibel ist.
        source_text = str(entry.get("text") or "")
        if source_text and visible_text:
            left = " ".join(_script_tokenize_match(source_text))
            right = " ".join(_script_tokenize_match(visible_text))
            if left and right and difflib.SequenceMatcher(a=left, b=right, autojunk=False).ratio() < 0.52:
                return None
        return {"label": str(marker.get("label") or ""), "type": str(marker.get("type") or "")}

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

        marker = marker_for_line(len(parsed), display)
        section_label = marker.get("label") if marker else None
        section_type = marker.get("type") if marker else None
        section_key = f"{section_type}:{section_label}" if section_type or section_label else None
        starts_section = bool(section_key and section_key != previous_section_key)
        if section_key:
            previous_section_key = section_key

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
                section_label=section_label,
                section_type=section_type,
                starts_section=starts_section,
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


@dataclass
class _EffectiveLyricsEntry:
    text: str
    marker: dict[str, str] | None = None
    derived: bool = False
    reason: str | None = None
    confidence: float = 1.0
    time_hint: float | None = None
    original_index: int | None = None


def _effective_line_tokens(text: str) -> list[str]:
    return _script_tokenize_match(_clean_srt_text_tags_from_line(str(text or "")))


def _effective_line_match_threshold(tokens: list[str]) -> float:
    if len(tokens) <= 1:
        return 0.96
    if len(tokens) <= 3:
        return 0.92
    if len(tokens) <= 6:
        return 0.86
    return 0.80


SRT_EFFECTIVE_TRAILING_ADLIB_TOKENS = {
    "ah", "aha", "ahaa", "ahaaa", "oh", "ohh", "ohhh", "ey", "hey",
    "yeah", "yeahh", "yeahhh", "yo", "uh", "uhh", "mhm", "hm", "hmm",
}


def _effective_line_token_variants(tokens: list[str]) -> list[list[str]]:
    """Liefert konservative Match-Varianten fuer wiederholte Suno-Zeilen.

    Suno und ASR behandeln Adlibs/gezogene Silben am Zeilenende nicht immer
    identisch. Eine Intro-Zeile wie "Es ist Zeit zu gehn ahaaa" kann im ASR
    beim zweiten Vorkommen z. B. ohne "ahaaa" oder mit "gehen" statt "gehn"
    auftauchen. Fuer die Erkennung von Zusatzzeilen duerfen wir deshalb eine
    gekuerzte Match-Variante verwenden, ohne den sichtbaren SRT-Text zu aendern.
    """
    base = [str(token or "").strip() for token in tokens if str(token or "").strip()]
    if not base:
        return []
    variants: list[list[str]] = [base]

    # Parenthetical echoes in the source lyrics, e.g.
    # "Es ist Zeit (es ist zeit), meine Wege neu zu gehen", are cleaned to
    # "es ist zeit es ist zeit meine ...". Suno/Groq often sings/transcribes
    # only one prefix before the rest of the line. Collapse that immediate
    # repeated prefix only for matching so repeated intro lines can still find
    # the following Verse/Hook anchor. The visible SRT text remains unchanged.
    max_repeat_len = min(5, len(base) // 2)
    for repeat_len in range(max_repeat_len, 1, -1):
        if base[:repeat_len] == base[repeat_len:repeat_len * 2]:
            variants.append([*base[:repeat_len], *base[repeat_len * 2:]])
            break

    last = base[-1]
    repeated_tail = bool(re.search(r"([aeiouyäöü])\1{2,}$", last, re.IGNORECASE))
    if len(base) >= 4 and (last in SRT_EFFECTIVE_TRAILING_ADLIB_TOKENS or repeated_tail):
        variants.append(base[:-1])

    # Echo-/Adlib-Zusätze am Zeilenende werden in Suno oft nur bei einer
    # Wiederholung wirklich gesungen oder von ASR nur einmal erkannt.
    # Für Timing-Matches darf ein unmittelbar wiederholter Suffix kollabieren;
    # der sichtbare SRT-Text bleibt unverändert.
    max_suffix_len = min(5, len(base) // 2)
    for repeat_len in range(max_suffix_len, 1, -1):
        if base[-repeat_len:] == base[-repeat_len * 2:-repeat_len]:
            variants.append(base[:-repeat_len])
            break

    # Schreibvarianten (gehn/gehen), Fehlhoerungen und von ASR zerhackte Silben
    # ("Flehn" -> "fl hen") werden nicht mehr ueber wortspezifische Hardcodes
    # behandelt, sondern generisch: _effective_ngram_score vergleicht Tokens
    # fuzzy (String-Ratio + Koelner Phonetik) und _effective_find_occurrences
    # prueft flexible Fenstergroessen (Split/Merge-tolerant). Dadurch bleiben
    # diese Faelle songunabhaengig abgedeckt.
    unique: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    for variant in variants:
        # Kurze Einwort-Adlibs bleiben zu schwach fuer robuste Wiederholungs-
        # erkennung. Markante Intro-Calls wie "Skalinooo" duerfen aber als
        # einzelne Anchor-Zeile erhalten bleiben; sonst kann ein kompletter
        # Suno-Intro-Block A-B-A-B nicht erkannt werden und wird zu A-B-B.
        if len(variant) < 2 and (not variant or len(variant[0]) < 5):
            continue
        key = tuple(variant)
        if key not in seen:
            unique.append(variant)
            seen.add(key)
    return unique


def _effective_ngram_score(tokens: list[str], candidate: list[str]) -> float:
    if not tokens or not candidate:
        return 0.0
    if tokens == candidate:
        return 1.0
    # Ein Kandidatenfenster darf nicht mitten in einer vorherigen Zeile beginnen.
    # Sonst kann z. B. "ahaaa Es ist Zeit ..." faelschlich als Verse-Zeile
    # "Es ist Zeit es ist zeit ..." gewertet werden und Wiederholungen blockieren.
    first_close = tokens[0] == candidate[0]
    if not first_close and len(tokens[0]) >= 4 and len(candidate[0]) >= 4:
        first_close = _script_word_similarity(tokens[0], candidate[0]) >= 0.78
    if (
        not first_close
        and min(len(tokens[0]), len(candidate[0])) >= 3
        and abs(len(tokens[0]) - len(candidate[0])) <= 2
        and (tokens[0].startswith(candidate[0]) or candidate[0].startswith(tokens[0]))
    ):
        first_close = True
    if not first_close:
        return 0.0
    # Frueher musste das zweite Token exakt stimmen; eine einzige Fehlhoerung
    # am Zeilenanfang blockierte damit die komplette Wiederholungserkennung.
    # Jetzt reicht generische Aehnlichkeit; komplett fremde Zweitworte sperren
    # weiterhin, damit Fenster nicht mitten in fremden Zeilen matchen.
    if len(tokens) >= 2 and len(candidate) >= 2:
        second_similarity = _script_word_similarity(tokens[1], candidate[1])
        if tokens[1] != candidate[1] and second_similarity < 0.55:
            return 0.0
    fuzzy_hits = sum(
        1
        for left, right in zip(tokens, candidate)
        if left == right or _script_word_similarity(left, right) >= 0.80
    )
    fuzzy_ratio = fuzzy_hits / max(len(tokens), len(candidate), 1)
    seq_ratio = difflib.SequenceMatcher(a=" ".join(candidate), b=" ".join(tokens), autojunk=False).ratio()
    return max(fuzzy_ratio, seq_ratio)


def _effective_find_occurrences(
    tokens: list[str],
    hyp: list[HypWord],
    *,
    start_index: int = 0,
    end_index: int | None = None,
    max_count: int | None = None,
) -> list[dict[str, Any]]:
    """Findet plausible ASR-Vorkommen einer Lyrics-Zeile.

    Die Funktion arbeitet bewusst lokal und konservativ. Sie dient nur dazu,
    zusätzliche von Suno gesungene Wiederholungen in eine abgeleitete SRT-Lyrics-
    Sicht zu übernehmen. Original-Lyrics, API, Tasks und DB-Schema bleiben
    unverändert.
    """
    if not tokens or not hyp:
        return []
    if len(tokens) == 1 and len(tokens[0]) < 5:
        return []
    threshold = _effective_line_match_threshold(tokens)
    hyp_tokens = [word.norm for word in hyp]
    size = len(tokens)
    # Split-/Merge-tolerante Fenster: Wenn ASR ein Wort in zwei Tokens zerhackt
    # ("flehn" -> "fl hen") oder zwei Woerter zusammenzieht, liegt das echte
    # Vorkommen in einem Fenster der Groesse size+1 bzw. size-1. Der Vergleich
    # auf zeichen-konkatenierter Ebene in _effective_ngram_score bewertet solche
    # Fenster korrekt hoch; das ersetzt die frueheren wortspezifischen Splits.
    minimum_window_size = 1 if size == 1 else 2
    window_sizes = sorted({candidate_size for candidate_size in (size - 1, size, size + 1) if candidate_size >= minimum_window_size})
    if not window_sizes:
        window_sizes = [size]
    end_limit = min(len(hyp_tokens), end_index if end_index is not None else len(hyp_tokens))
    pos = max(0, int(start_index or 0))
    occurrences: list[dict[str, Any]] = []
    while pos < end_limit:
        best_score = 0.0
        best_size = 0
        for candidate_size in window_sizes:
            if pos + candidate_size > end_limit:
                continue
            candidate = hyp_tokens[pos:pos + candidate_size]
            score = _effective_ngram_score(tokens, candidate)
            if score > best_score:
                best_score = score
                best_size = candidate_size
        if best_size and best_score >= threshold:
            occurrences.append({
                "start_index": pos,
                "end_index": pos + best_size,
                "start": float(hyp[pos].start),
                "end": float(hyp[pos + best_size - 1].end),
                "score": round(float(best_score), 3),
            })
            if max_count is not None and len(occurrences) >= max_count:
                break
            pos += max(1, best_size)
            continue
        pos += 1
    return occurrences


def _effective_find_occurrences_flexible(
    tokens: list[str],
    hyp: list[HypWord],
    *,
    start_index: int = 0,
    end_index: int | None = None,
    max_count: int | None = None,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    for variant in _effective_line_token_variants(tokens):
        for occurrence in _effective_find_occurrences(
            variant,
            hyp,
            start_index=start_index,
            end_index=end_index,
            max_count=None,
        ):
            key = (int(occurrence["start_index"]), int(occurrence["end_index"]))
            if key in seen:
                continue
            occurrence = dict(occurrence)
            occurrence["variant_len"] = len(variant)
            occurrence["variant_tokens"] = variant
            merged.append(occurrence)
            seen.add(key)
    merged.sort(key=lambda item: (int(item["start_index"]), -float(item.get("score") or 0.0), -int(item.get("variant_len") or 0)))
    if max_count is not None:
        return merged[:max_count]
    return merged


def _effective_first_occurrence(tokens: list[str], hyp: list[HypWord], start_index: int = 0) -> dict[str, Any] | None:
    found = _effective_find_occurrences_flexible(tokens, hyp, start_index=start_index, max_count=1)
    return found[0] if found else None


def _effective_next_anchor_occurrence(
    entries: list[_EffectiveLyricsEntry],
    current_index: int,
    hyp: list[HypWord],
    start_index: int,
) -> tuple[int, dict[str, Any]] | None:
    candidates: list[tuple[int, dict[str, Any]]] = []
    # Nur ein lokales Fenster betrachten. Das verhindert, dass spaetere identische
    # Hook-/Chorus-Wiederholungen einen fruehen Abschnitt falsch begrenzen.
    for probe_index in range(current_index + 1, min(len(entries), current_index + 9)):
        tokens = _effective_line_tokens(entries[probe_index].text)
        if not tokens:
            continue
        occurrence = _effective_first_occurrence(tokens, hyp, start_index=start_index)
        if occurrence:
            candidates.append((probe_index, occurrence))
    if not candidates:
        return None
    return min(candidates, key=lambda item: (item[1]["start_index"], item[0]))


def _effective_line_similarity(left: str, right: str) -> float:
    left_tokens = _effective_line_tokens(left)
    right_tokens = _effective_line_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    left_variants = _effective_line_token_variants(left_tokens) or [left_tokens]
    right_variants = _effective_line_token_variants(right_tokens) or [right_tokens]
    best = 0.0
    for left_variant in left_variants:
        left_text = " ".join(left_variant)
        for right_variant in right_variants:
            score = difflib.SequenceMatcher(a=left_text, b=" ".join(right_variant), autojunk=False).ratio()
            best = max(best, score)
    return best


def _script_find_line_occurrence_after(line: LyricLine, hyp: list[HypWord], cursor: int) -> dict[str, Any] | None:
    tokens = line.match_tokens or _effective_line_tokens(line.display)
    if not tokens:
        return None
    occurrences = _effective_find_occurrences_flexible(tokens, hyp, start_index=max(0, cursor), max_count=8)
    if not occurrences:
        return None
    return occurrences[0]


def _script_hyp_index_at_time(hyp: list[HypWord], time_value: float) -> int:
    target = max(0.0, float(time_value or 0.0))
    for index, word in enumerate(hyp):
        if float(word.end) >= target:
            return index
    return max(0, len(hyp) - 1)


def _script_anchor_repeated_section_blocks(lines: list[LyricLine], hyp: list[HypWord]) -> list[str]:
    """Verankert explizit wiederholte Abschnittsblöcke vor der Lückenverteilung.

    Wenn ein Hook/Bridge-Block im Songtext zweimal direkt hintereinander steht,
    kann SequenceMatcher die erste Zeile bis in die zweite Wiederholung ziehen,
    weil Wörter wie "trage die Glut" mehrfach vorkommen. Danach werden die
    übrigen Wiederholungszeilen kurz vor den nächsten Abschnitt gequetscht.
    Diese Korrektur greift nur bei klar erkannten Wiederholungsblöcken innerhalb
    desselben Abschnitts und nutzt weiterhin ausschließlich ASR-Wortzeiten.
    """
    report: list[str] = []
    if not lines or not hyp:
        return report

    run_start = 0
    while run_start < len(lines):
        section_key = (lines[run_start].section_type or "", lines[run_start].section_label or "")
        run_end = run_start + 1
        while run_end < len(lines) and (lines[run_end].section_type or "", lines[run_end].section_label or "") == section_key:
            run_end += 1

        run_len = run_end - run_start
        if run_len >= 4:
            max_block_len = min(6, run_len // 2)
            for block_len in range(max_block_len, 1, -1):
                first_start = run_start
                second_start = run_start + block_len
                second_end = second_start + block_len
                if second_end > run_end:
                    continue

                similarities = [
                    _effective_line_similarity(lines[first_start + offset].display, lines[second_start + offset].display)
                    for offset in range(block_len)
                ]
                if not similarities or sum(similarities) / len(similarities) < 0.78:
                    continue
                if min(similarities) < 0.66:
                    continue

                occurrences: list[dict[str, Any]] = []
                previous_time = None
                if first_start > 0 and lines[first_start - 1].end is not None:
                    previous_time = float(lines[first_start - 1].end or 0.0)
                elif lines[first_start].start is not None:
                    previous_time = max(0.0, float(lines[first_start].start or 0.0) - 1.5)
                cursor = _script_hyp_index_at_time(hyp, max(0.0, (previous_time or 0.0) - 0.35))
                failed = False
                for idx in range(first_start, second_end):
                    occurrence = _script_find_line_occurrence_after(lines[idx], hyp, cursor)
                    if not occurrence:
                        failed = True
                        break
                    occurrences.append(occurrence)
                    cursor = max(int(occurrence.get("end_index") or cursor), int(occurrence.get("start_index") or cursor) + 1)

                if failed or len(occurrences) != block_len * 2:
                    continue

                starts = [float(item.get("start") or 0.0) for item in occurrences]
                if any(right <= left for left, right in zip(starts, starts[1:])):
                    continue
                if starts[block_len] - starts[0] < 4.0:
                    continue

                changed = False
                for idx, occurrence in zip(range(first_start, second_end), occurrences):
                    start = round(float(occurrence.get("start") or 0.0), 3)
                    end = round(float(occurrence.get("end") or start), 3)
                    if end <= start:
                        continue
                    line = lines[idx]
                    if abs(float(line.start or -1.0) - start) > 0.12 or abs(float(line.end or -1.0) - end) > 0.12:
                        changed = True
                    line.start = start
                    line.end = end
                    line.matched = True
                    line.wstart = None
                    line.wend = None

                if changed:
                    report.append(
                        f"INFO: Wiederholter Abschnittsblock {lines[first_start].section_label or lines[first_start].section_type or 'Lyrics'} "
                        f"({first_start + 1}-{second_end}) vor Lueckenverteilung per ASR-Wortzeiten verankert."
                    )
                break

        run_start = run_end

    return report




def _entry_marker_key(entry: _EffectiveLyricsEntry) -> tuple[str, str]:
    marker = entry.marker if isinstance(entry.marker, dict) else {}
    return (str(marker.get("type") or "").lower(), str(marker.get("label") or ""))


def _entry_in_explicit_repeated_block(entries: list[_EffectiveLyricsEntry], index: int) -> bool:
    """Erkennt direkt ausgeschriebene Wiederholungsbloecke im Original-Songtext.

    Wichtig fuer Suno: Wenn der Songtext einen Hook/Chorus bereits als
    A-B-C-D / A-B-C-D enthaelt, duerfen spaetere ASR-Heuristiken keine
    zusaetzlichen A/B/C/D-Zeilen einfuegen oder vorhandene kurze Zeilen als
    kuenstliche Wiederholung entfernen. Die Performance darf variieren, aber die
    sichtbare Reihenfolge bleibt Source-of-Truth aus dem effektiven Songtext.
    """
    if index < 0 or index >= len(entries):
        return False
    key = _entry_marker_key(entries[index])
    if not any(key):
        return False
    run_start = index
    while run_start > 0 and _entry_marker_key(entries[run_start - 1]) == key:
        run_start -= 1
    run_end = index + 1
    while run_end < len(entries) and _entry_marker_key(entries[run_end]) == key:
        run_end += 1
    run_len = run_end - run_start
    if run_len < 4:
        return False
    max_block_len = min(8, run_len // 2)
    for block_len in range(2, max_block_len + 1):
        for start in range(run_start, run_end - (block_len * 2) + 1):
            sims = [
                _effective_line_similarity(entries[start + offset].text, entries[start + block_len + offset].text)
                for offset in range(block_len)
            ]
            if sims and min(sims) >= 0.66 and (sum(sims) / len(sims)) >= 0.82:
                if start <= index < start + block_len * 2:
                    return True
    return False


def _line_section_key(line: LyricLine) -> tuple[str, str]:
    return (str(line.section_type or "").lower(), str(line.section_label or ""))


def _line_in_explicit_repeated_block(lines: list[LyricLine], index: int) -> bool:
    if index < 0 or index >= len(lines):
        return False
    key = _line_section_key(lines[index])
    if not any(key):
        return False
    run_start = index
    while run_start > 0 and _line_section_key(lines[run_start - 1]) == key:
        run_start -= 1
    run_end = index + 1
    while run_end < len(lines) and _line_section_key(lines[run_end]) == key:
        run_end += 1
    run_len = run_end - run_start
    if run_len < 4:
        return False
    max_block_len = min(8, run_len // 2)
    for block_len in range(2, max_block_len + 1):
        for start in range(run_start, run_end - (block_len * 2) + 1):
            sims = [
                _effective_line_similarity(lines[start + offset].display, lines[start + block_len + offset].display)
                for offset in range(block_len)
            ]
            if sims and min(sims) >= 0.66 and (sum(sims) / len(sims)) >= 0.82:
                if start <= index < start + block_len * 2:
                    return True
    return False


def _script_explicit_repeated_block_ranges(lines: list[LyricLine]) -> list[tuple[int, int, int]]:
    """Liefert (start, block_len, repeat_count) fuer direkt notierte Refrain-Bloecke."""
    ranges: list[tuple[int, int, int]] = []
    run_start = 0
    while run_start < len(lines):
        key = _line_section_key(lines[run_start])
        run_end = run_start + 1
        while run_end < len(lines) and _line_section_key(lines[run_end]) == key:
            run_end += 1
        run_len = run_end - run_start
        if any(key) and run_len >= 4:
            chosen: tuple[int, int, int] | None = None
            max_block_len = min(8, run_len // 2)
            # Laengere Bloecke bevorzugen, damit A-B-C-D/A-B-C-D nicht als
            # kleinere A-B/A-B-Teilmenge behandelt wird.
            for block_len in range(max_block_len, 1, -1):
                for start in range(run_start, run_end - block_len * 2 + 1):
                    max_repeat = (run_end - start) // block_len
                    repeat_count = 1
                    for rep in range(1, max_repeat):
                        sims = [
                            _effective_line_similarity(lines[start + offset].display, lines[start + rep * block_len + offset].display)
                            for offset in range(block_len)
                        ]
                        if not sims or min(sims) < 0.66 or (sum(sims) / len(sims)) < 0.82:
                            break
                        repeat_count += 1
                    if repeat_count >= 2:
                        chosen = (start, block_len, repeat_count)
                        break
                if chosen:
                    break
            if chosen:
                ranges.append(chosen)
                run_start = max(run_end, chosen[0] + chosen[1] * chosen[2])
                continue
        run_start = run_end
    return ranges


def _script_repair_explicit_repeated_section_blocks(lines: list[LyricLine], hyp: list[HypWord]) -> list[str]:
    """Stabilisiert direkt notierte Chorus-/Hook-Wiederholungen als Block.

    Fehlerbild: Bei mehrfach gleichen Hook-Zeilen kann eine Einzelzeilen-Heuristik
    sichere spaetere Treffer vorziehen oder zusaetzliche Duplikate einfuegen.
    Dann stolpert die SRT innerhalb des Blocks, z. B. C-D-A-A-B-C-B-D statt
    A-B-C-D/A-B-C-D. Diese Funktion behandelt solche Abschnitte als komplette
    Bloecke und setzt vorhandene Zeilen wieder auf monotone ASR-Wortzeiten bzw.
    verteilt fehlende Treffer innerhalb des Blockfensters. Sichtbarer Text bleibt
    in Songtext-Reihenfolge.
    """
    report: list[str] = []
    if not lines:
        return report
    for block_start, block_len, repeat_count in _script_explicit_repeated_block_ranges(lines):
        block_end = block_start + block_len * repeat_count
        if block_end > len(lines):
            continue
        block_lines = lines[block_start:block_end]
        first_section_type = str(block_lines[0].section_type or "").lower() if block_lines else ""
        if first_section_type in {"intro", "instrumental_intro"}:
            # Intro-A-B-A-B hat eigene Speziallogik, weil kurze Artist-Calls
            # oft nur synthetisch aus der Luecke geschaetzt werden. Die allgemeine
            # Blockreparatur wuerde solche Luecken zu frueh verteilen.
            continue
        if len(block_lines) < 4:
            continue
        durations = [float(line.end or 0.0) - float(line.start or 0.0) for line in block_lines]
        starts = [float(line.start or 0.0) for line in block_lines]
        needs_repair = (
            any(duration < 0.55 for duration in durations)
            or any(right <= left + 0.03 for left, right in zip(starts, starts[1:]))
            or not all(line.matched for line in block_lines)
        )
        # Auch scheinbar plausible Bloecke kurz pruefen: Wenn die ASR-Treffer
        # deutlich andere monotone Starts liefern, war die alte Einzelankerung
        # wahrscheinlich auf spaetere Wiederholungen verrutscht.
        previous_time = float(lines[block_start - 1].end or 0.0) if block_start > 0 else max(0.0, starts[0] - 1.0)
        cursor = _script_hyp_index_at_time(hyp, max(0.0, previous_time - 0.6)) if hyp else 0
        occurrences: list[tuple[int, dict[str, Any]]] = []
        for local_index, line in enumerate(block_lines):
            occurrence = _script_find_line_occurrence_after(line, hyp, cursor) if hyp else None
            if occurrence:
                occurrences.append((local_index, occurrence))
                cursor = max(int(occurrence.get("end_index") or cursor), int(occurrence.get("start_index") or cursor) + 1)
        if len(occurrences) >= max(3, int(len(block_lines) * 0.58)):
            occurrence_starts = [float(item[1].get("start") or 0.0) for item in occurrences]
            if any(abs(starts[local_index] - float(occ.get("start") or 0.0)) > 1.25 for local_index, occ in occurrences):
                needs_repair = True
            if any(right <= left for left, right in zip(occurrence_starts, occurrence_starts[1:])):
                continue
        if not needs_repair:
            continue

        changed = False
        matched_local = {local_index: occ for local_index, occ in occurrences}
        for local_index, occurrence in matched_local.items():
            line = block_lines[local_index]
            start = round(float(occurrence.get("start") or 0.0), 3)
            end = round(max(float(occurrence.get("end") or start), start + 0.55), 3)
            if abs(float(line.start or -1.0) - start) > 0.12 or abs(float(line.end or -1.0) - end) > 0.12:
                changed = True
            line.start = start
            line.end = end
            line.matched = True
            line.wstart = None
            line.wend = None

        # Fehlende Treffer innerhalb des Blockes aus Nachbarankern verteilen.
        anchor_locals = sorted(matched_local)
        if anchor_locals:
            first_anchor = anchor_locals[0]
            if first_anchor > 0:
                start = previous_time
                end = float(block_lines[first_anchor].start or start)
                if end > start + 0.25:
                    _script_spread(block_lines, 0, first_anchor, start, end)
                    changed = True
            for left, right in zip(anchor_locals, anchor_locals[1:]):
                if right <= left + 1:
                    continue
                start = float(block_lines[left].end or block_lines[left].start or 0.0)
                end = float(block_lines[right].start or start)
                if end > start + 0.25:
                    _script_spread(block_lines, left + 1, right, start, end)
                    changed = True
            last_anchor = anchor_locals[-1]
            if last_anchor < len(block_lines) - 1:
                start = float(block_lines[last_anchor].end or block_lines[last_anchor].start or previous_time)
                next_time = float(lines[block_end].start or 0.0) if block_end < len(lines) else 0.0
                if next_time <= start:
                    next_time = start + _script_readable_window_seconds(block_lines, last_anchor + 1, len(block_lines))
                _script_spread(block_lines, last_anchor + 1, len(block_lines), start, next_time)
                changed = True
        else:
            # Ohne ASR-Treffer: Reihenfolge bleibt Songtext, Timing wird als
            # lesbares Fenster zwischen Nachbarsegmenten verteilt.
            start = previous_time
            end = float(lines[block_end].start or 0.0) if block_end < len(lines) else 0.0
            if end <= start:
                end = start + _script_readable_window_seconds(block_lines, 0, len(block_lines))
            _script_spread(block_lines, 0, len(block_lines), start, end)
            changed = True

        if changed:
            for local_index, repaired in enumerate(block_lines):
                lines[block_start + local_index] = repaired
            report.append(
                f"INFO: Wiederholter Abschnittsblock {block_lines[0].section_label or block_lines[0].section_type or 'Lyrics'} "
                f"als Block stabilisiert ({block_start + 1}-{block_end}, {repeat_count}x{block_len})."
            )
    return report

def _script_drop_squeezed_unmatched_repeats(lines: list[LyricLine], max_duration: float = 0.42) -> list[str]:
    """Entfernt künstlich gequetschte Wiederholungszeilen ohne ASR-Beleg.

    Lyrics bleiben grundsätzlich Source of Truth. Wenn eine wiederholte Zeile
    aber nicht gematcht wurde und nach der Timeline-Auflösung nur ein technisches
    Mini-Fenster bekommt, ist das für den Player schlechter als das Auslassen der
    unbelegten Wiederholung. Gesungene Wiederholungen sind davon nicht betroffen,
    weil sie als gematchte oder ausreichend lange Zeilen erhalten bleiben.
    """
    if not lines:
        return []

    drop_indexes: set[int] = set()
    for index, line in enumerate(lines):
        duration = float(line.end or 0.0) - float(line.start or 0.0)
        if _line_in_explicit_repeated_block(lines, index):
            # Explizit ausgeschriebene Hook-/Chorus-Wiederholungen nicht
            # entfernen; sie werden bei Bedarf als kompletter Block repariert.
            continue
        if line.matched or duration > max_duration:
            continue
        section_key = (line.section_type or "", line.section_label or "")
        if not any(section_key):
            continue

        has_repeat_anchor = False
        for probe in range(max(0, index - 8), min(len(lines), index + 9)):
            if probe == index:
                continue
            other = lines[probe]
            if (other.section_type or "", other.section_label or "") != section_key:
                continue
            other_duration = float(other.end or 0.0) - float(other.start or 0.0)
            if other_duration < 0.75:
                continue
            if _effective_line_similarity(line.display, other.display) >= 0.86:
                has_repeat_anchor = True
                break
        if has_repeat_anchor:
            drop_indexes.add(index)

    if not drop_indexes:
        return []

    removed = [lines[index].display for index in sorted(drop_indexes)]
    lines[:] = [line for index, line in enumerate(lines) if index not in drop_indexes]
    return [
        f"INFO: {len(removed)} gequetschte unbelegte Wiederholungszeile(n) ausgelassen: "
        + "; ".join(repr(item) for item in removed[:6])
    ]


def _effective_entries_from_lyrics(lyrics: str, source_lyrics: str | None) -> tuple[list[_EffectiveLyricsEntry], bool]:
    source_entries = _source_structure_lyrics_lines(source_lyrics or "") if source_lyrics else []
    if source_entries:
        entries: list[_EffectiveLyricsEntry] = []
        for index, entry in enumerate(source_entries):
            marker = entry.get("marker") if isinstance(entry.get("marker"), dict) else None
            entries.append(_EffectiveLyricsEntry(
                text=str(entry.get("text") or "").strip(),
                marker={"label": str(marker.get("label") or ""), "type": str(marker.get("type") or "")} if marker else None,
                original_index=index,
            ))
        return [entry for entry in entries if entry.text], True

    entries = []
    for index, raw in enumerate(str(lyrics or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")):
        cleaned = _clean_srt_text_tags_from_line(raw)
        if cleaned:
            entries.append(_EffectiveLyricsEntry(text=cleaned, original_index=index))
    return entries, False


def _render_effective_source_lyrics(entries: list[_EffectiveLyricsEntry]) -> str:
    lines: list[str] = []
    previous_key: str | None = None
    for entry in entries:
        marker = entry.marker if isinstance(entry.marker, dict) else None
        marker_label = str(marker.get("label") or "").strip() if marker else ""
        marker_type = str(marker.get("type") or "").strip() if marker else ""
        marker_key = f"{marker_type}:{marker_label}" if marker_label or marker_type else ""
        if marker_label and marker_key != previous_key:
            lines.append(f"[{marker_label}]")
            previous_key = marker_key
        lines.append(entry.text)
    return "\n".join(lines).strip()


def _build_effective_srt_lyrics_from_asr(
    lyrics: str,
    source_lyrics: str | None,
    hyp: list[HypWord],
) -> tuple[str, str | None, list[str], dict[str, Any]]:
    """Erzeugt eine abgeleitete SRT-Lyrics-Sicht fuer Suno-Abweichungen.

    Praxisfall: Suno wiederholt im Intro/Hook eine Zeile, die im offiziellen
    Songtext nur einmal steht. Ohne diese Zusatzzeile wird das Alignment auf den
    naechsten Abschnitt gezogen und Segmente springen. Diese Funktion fuegt nur
    dann abgeleitete Zeilen ein, wenn ASR dieselbe Lyrics-Zeile mehrfach vor dem
    naechsten plausiblen Abschnitts-/Zeilenanker erkennt.
    """
    entries, had_structure = _effective_entries_from_lyrics(lyrics, source_lyrics)
    if not entries or not hyp:
        return lyrics, source_lyrics, [], {"enabled": True, "derived_count": 0, "source": "no_effective_change"}

    effective: list[_EffectiveLyricsEntry] = []
    report: list[str] = []
    derived_records: list[dict[str, Any]] = []
    cursor = 0

    for index, entry in enumerate(entries):
        effective.append(entry)
        tokens = _effective_line_tokens(entry.text)
        if not tokens:
            continue

        first = _effective_first_occurrence(tokens, hyp, start_index=cursor)
        if not first:
            continue

        next_anchor = _effective_next_anchor_occurrence(entries, index, hyp, int(first["end_index"]))
        if not next_anchor:
            cursor = max(cursor, int(first["end_index"]))
            continue

        next_index, next_occurrence = next_anchor
        boundary = int(next_occurrence["start_index"])
        if boundary <= int(first["end_index"]):
            cursor = max(cursor, int(first["end_index"]))
            continue

        duplicates = _effective_find_occurrences_flexible(
            tokens,
            hyp,
            start_index=int(first["end_index"]),
            end_index=boundary,
            max_count=3,
        )
        accepted: list[dict[str, Any]] = []
        previous_start_time = float(first["start"])
        for occurrence in duplicates:
            start_time = float(occurrence["start"])
            end_time = float(occurrence["end"])
            if start_time - previous_start_time < 0.45:
                continue
            if end_time > float(next_occurrence["start"]) - 0.10:
                continue
            # Sehr grosse Luecken sind meist spaetere Hook-/Chorus-Wiederholungen,
            # keine lokale von Suno eingefuegte Zusatzzeile.
            if start_time - previous_start_time > 24.0:
                continue
            accepted.append(occurrence)
            previous_start_time = start_time

        if accepted and _entry_in_explicit_repeated_block(entries, index):
            # Direkt im Songtext ausgeschriebene Wiederholungsbloecke duerfen
            # nicht noch einmal aus ASR-Duplikaten erweitert werden. Sonst
            # entstehen in Hooks/Choruses zusaetzliche A/B-Zeilen und die
            # Reihenfolge stolpert.
            cursor = max(cursor, int(first["end_index"]))
            continue

        for occurrence in accepted:
            # Wenn Suno einen fruehen Intro-Block A-B als A-B-A-B performt,
            # ASR aber den kurzen A-Call beim zweiten Durchlauf verschluckt,
            # sieht die bisherige Logik nur B erneut und erzeugt A-B-B. In
            # diesem konservativen Spezialfall wird die vorherige Intro-Zeile
            # als Block-Prefix vor der erneut belegten aktuellen Zeile in die
            # effektive SRT-Lyrics-Sicht eingefuegt. Der gespeicherte Songtext
            # bleibt unveraendert; es betrifft nur das Alignment.
            if index > 0:
                previous_entry = entries[index - 1]
                current_marker = entry.marker if isinstance(entry.marker, dict) else {}
                previous_marker = previous_entry.marker if isinstance(previous_entry.marker, dict) else {}
                same_intro_marker = (
                    str(current_marker.get("type") or "").lower() in {"intro", "instrumental_intro"}
                    and str(previous_marker.get("type") or "").lower() == str(current_marker.get("type") or "").lower()
                    and str(previous_marker.get("label") or "") == str(current_marker.get("label") or "")
                )
                previous_tokens = _effective_line_tokens(previous_entry.text)
                current_tokens = _effective_line_tokens(entry.text)
                previous_is_short_call = 1 <= len(previous_tokens) <= 4 and previous_tokens != current_tokens
                repeat_start_index = int(occurrence.get("start_index") or 0)
                previous_between = _effective_find_occurrences_flexible(
                    previous_tokens,
                    hyp,
                    start_index=int(first["end_index"]),
                    end_index=repeat_start_index,
                    max_count=1,
                ) if previous_tokens and repeat_start_index > int(first["end_index"]) else []
                already_inserted_previous = bool(effective and _effective_line_similarity(effective[-1].text, previous_entry.text) >= 0.92)
                if same_intro_marker and previous_is_short_call and not already_inserted_previous:
                    prefix_occurrence = previous_between[0] if previous_between else None
                    prefix_confidence = float(prefix_occurrence.get("score") or 0.0) if prefix_occurrence else 0.62
                    prefix_time_hint = float(prefix_occurrence.get("start") or 0.0) if prefix_occurrence else max(0.0, float(occurrence.get("start") or 0.0) - 2.6)
                    prefix = _EffectiveLyricsEntry(
                        text=previous_entry.text,
                        marker=previous_entry.marker,
                        derived=True,
                        reason="asr_intro_block_prefix_repeat" if prefix_occurrence else "inferred_intro_block_prefix_repeat",
                        confidence=prefix_confidence,
                        time_hint=prefix_time_hint,
                        original_index=previous_entry.original_index,
                    )
                    effective.append(prefix)
                    derived_records.append({
                        "after_original_line": (previous_entry.original_index if previous_entry.original_index is not None else index - 1) + 1,
                        "text": previous_entry.text,
                        "section": (previous_entry.marker or {}).get("label") if isinstance(previous_entry.marker, dict) else None,
                        "reason": prefix.reason,
                        "confidence": round(prefix.confidence, 3),
                        "time_hint": round(float(prefix.time_hint or 0.0), 3),
                    })
                    report.append(
                        f"INFO: Effektive SRT-Lyrics: Intro-Block-Prefix vor wiederholter Zeile eingefuegt "
                        f"({previous_entry.text!r}, Hinweis bei {prefix_time_hint:.1f}s)."
                    )

            derived = _EffectiveLyricsEntry(
                text=entry.text,
                marker=entry.marker,
                derived=True,
                reason="asr_repeated_line_before_next_anchor",
                confidence=float(occurrence.get("score") or 0.0),
                time_hint=float(occurrence.get("start") or 0.0),
                original_index=entry.original_index,
            )
            effective.append(derived)
            derived_records.append({
                "after_original_line": (entry.original_index if entry.original_index is not None else index) + 1,
                "text": entry.text,
                "section": (entry.marker or {}).get("label") if isinstance(entry.marker, dict) else None,
                "reason": derived.reason,
                "confidence": round(derived.confidence, 3),
                "time_hint": round(float(derived.time_hint or 0.0), 3),
            })
            report.append(
                f"INFO: Effektive SRT-Lyrics: zusaetzliche Zeile nach Originalzeile "
                f"{(entry.original_index if entry.original_index is not None else index) + 1} eingefuegt "
                f"({entry.text!r}, ASR bei {float(occurrence.get('start') or 0.0):.1f}s)."
            )

        cursor = max(cursor, int((accepted[-1] if accepted else first)["end_index"]))

    if not derived_records:
        return lyrics, source_lyrics, [], {"enabled": True, "derived_count": 0, "source": "no_repeated_lines_detected"}

    effective_lyrics = "\n".join(entry.text for entry in effective if entry.text).strip()
    effective_source_lyrics = _render_effective_source_lyrics(effective) if had_structure else None
    info = {
        "enabled": True,
        "source": "asr_repeated_line_detection",
        "derived_count": len(derived_records),
        "derived_lines": derived_records[:80],
        "original_line_count": len(entries),
        "effective_line_count": len(effective),
    }
    return effective_lyrics or lyrics, effective_source_lyrics or source_lyrics, report, info


def _script_align_lines(lines: list[LyricLine], hyp: list[HypWord], warn_factor: float = 0.6) -> list[str]:
    target: list[str] = []
    tok_line: list[int] = []
    line_token_offsets: list[int] = []
    for line_index, line in enumerate(lines):
        line_token_offsets.append(len(target))
        for token in line.match_tokens:
            target.append(token)
            tok_line.append(line_index)

    hyp_tokens = [word.norm for word in hyp]
    n = len(target)
    token_starts: list[float | None] = [None] * n
    token_ends: list[float | None] = [None] * n

    matcher = difflib.SequenceMatcher(a=hyp_tokens, b=target, autojunk=False)
    fuzzy_rescued = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                token_starts[j1 + offset] = hyp[i1 + offset].start
                token_ends[j1 + offset] = hyp[i1 + offset].end
        elif tag == "replace":
            # Fuzzy-Rescue: SequenceMatcher verwirft Fehlhörungen komplett.
            # Innerhalb eines replace-Blocks ist die Reihenfolge aber gesichert,
            # deshalb dürfen positionsgleiche Paare (links- und rechtsbündig)
            # mit generischer Wortähnlichkeit als zusätzliche Anker dienen.
            # Das ersetzt die frühere Ankerarmut bei gehn/gehen, Flut/Blut usw.
            span = min(i2 - i1, j2 - j1)
            for offset in range(span):
                j = j1 + offset
                if token_starts[j] is not None:
                    continue
                candidate = hyp[i1 + offset]
                if _script_word_similarity(candidate.norm, target[j]) >= SCRIPT_FUZZY_WORD_THRESHOLD:
                    token_starts[j] = candidate.start
                    token_ends[j] = candidate.end
                    fuzzy_rescued += 1
            for offset in range(1, span + 1):
                j = j2 - offset
                if token_starts[j] is not None:
                    continue
                candidate = hyp[i2 - offset]
                if _script_word_similarity(candidate.norm, target[j]) >= SCRIPT_FUZZY_WORD_THRESHOLD:
                    token_starts[j] = candidate.start
                    token_ends[j] = candidate.end
                    fuzzy_rescued += 1

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
            # Exakte Token-Zeiten in Displaywort-Zeiten übernehmen statt sie zu
            # verwerfen. Lücken (None) werden später von _script_compute_word_times
            # zwischen den bekannten Ankern interpoliert. Heuristiken, die die
            # Zeile später verschieben, setzen wstart/wend weiterhin auf None und
            # erzwingen damit eine komplette Neuinterpolation.
            offset = line_token_offsets[line_index]
            word_starts: list[float | None] = []
            word_ends: list[float | None] = []
            cursor = offset
            for count in line.tok_counts:
                slice_starts = [token_starts[cursor + k] for k in range(count) if token_starts[cursor + k] is not None]
                slice_ends = [token_ends[cursor + k] for k in range(count) if token_ends[cursor + k] is not None]
                word_starts.append(min(slice_starts) if slice_starts else None)
                word_ends.append(max(slice_ends) if slice_ends else None)
                cursor += count
            if len(word_starts) == len(line.words) and any(value is not None for value in word_starts):
                line.wstart = word_starts  # type: ignore[assignment]
                line.wend = word_ends  # type: ignore[assignment]

    hyp_first_start = min((word.start for word in hyp), default=None)
    report: list[str] = []
    if fuzzy_rescued:
        report.append(f"INFO: Fuzzy-Rescue: {fuzzy_rescued} ASR-Fehlhoerung(en) als zusaetzliche Wort-Anker uebernommen.")
    report.extend(_script_apply_asr_line_review(lines, hyp))
    report.extend(_script_anchor_repeated_section_blocks(lines, hyp))
    report.extend(_script_reassign_sparse_section_jump_anchors(lines))
    report.extend(_script_resolve_timeline(lines, warn_factor, hyp_first_start=hyp_first_start, hyp=hyp))
    report.extend(_script_rebalance_ambiguous_intro_prefix(lines, hyp_first_start))
    return report


def _script_spread(lines: list[LyricLine], i0: int, i1: int, start: float, end: float) -> None:
    total_weight = sum(lines[i].weight for i in range(i0, i1)) or 1.0
    span = max(end - start, 0.0)
    t = start
    for i in range(i0, i1):
        duration = span * (lines[i].weight / total_weight)
        lines[i].start = t
        lines[i].end = t + duration
        t += duration



def _script_min_intro_gap_seconds(lines: list[LyricLine], i0: int, i1: int) -> float:
    """Mindestfenster fuer fruehe, vom ASR verschluckte Intro-Zeilen.

    Kurze Artist-Calls und gesprochene Einstiegszeilen werden von Whisper/Groq
    haeufig nicht als Wort-Anker geliefert. Wenn danach ein sicherer Anchor folgt,
    darf die fehlende Zeile nicht auf ein paar Zehntelsekunden gequetscht werden,
    weil der Player sonst scheinbar eine Zeile ueberspringt.
    Die Funktion ist bewusst nur fuer fruehe Gap-Protection gedacht und aendert
    keine API-/DB-Struktur.
    """
    total = 0.0
    for line in lines[i0:i1]:
        word_count = max(1, len(line.words or line.display.split()))
        # Untergrenze fuer Lesbarkeit; laengere Intro-Phrasen bekommen mehr Raum,
        # aber keine uebertrieben langen Luecken.
        by_words = 0.36 * word_count
        by_weight = 0.30 * max(float(line.weight or 1.0), 1.0)
        total += max(1.15, min(3.35, max(by_words, by_weight)))
    return total



def _script_readable_window_seconds(lines: list[LyricLine], i0: int, i1: int) -> float:
    """Plausibles Mindestfenster für mehrere sichtbare Lyrics-Zeilen.

    Wird nur für Korrekturen offensichtlich falscher Frühanker verwendet. Es ist
    bewusst konservativ und beeinflusst keine API-/DB-Struktur.
    """
    total = 0.0
    for line in lines[i0:i1]:
        words = line.words or line.display.split()
        word_count = max(1, len(words))
        by_words = 0.28 * word_count
        by_weight = 0.18 * max(float(line.weight or 1.0), 1.0)
        total += max(1.35, min(4.10, max(by_words, by_weight)))
    return total


def _script_demote_false_early_section_anchors(lines: list[LyricLine], seconds_per_weight: float) -> list[str]:
    """Ignoriert frühe doppelte Abschnitts-Anker aus Suno-Intro-Wiederholungen.

    Praxisfall: Suno hängt im Intro noch einmal Worte an, die im offiziellen
    Songtext erst mit ``[Verse 1]`` beginnen. Das ASR erkennt diese Worte früh,
    SequenceMatcher verankert dadurch die erste Verse-Zeile bei Sekunde 8, obwohl
    der eigentliche Verse erst deutlich später beginnt. Erkennbar ist das an:
      - erste Zeile eines neuen Abschnitts,
      - sehr frühe Startzeit direkt nach Intro-Zeilen,
      - danach langer Abstand bis zum nächsten stabilen Anker.
    In diesem Fall wird nur dieser frühe Anker demotet; die Zeile bleibt erhalten
    und wird im späteren Fenster vor dem nächsten Anker verteilt.
    """
    report: list[str] = []
    upper = min(len(lines) - 1, 10)
    for idx in range(1, upper):
        line = lines[idx]
        if not line.matched or not line.starts_section:
            continue
        if not line.section_type or line.section_type in {"intro", "instrumental_intro"}:
            continue
        if line.start is None or line.end is None:
            continue
        start = float(line.start)
        end = float(line.end)
        if start > 18.0:
            continue

        prev = lines[idx - 1]
        prev_end = float(prev.end or 0.0)
        prev_section = str(prev.section_type or "")
        if prev_end <= 0.0 or start > prev_end + 2.75:
            continue
        if prev_section and prev_section == str(line.section_type or ""):
            continue

        next_anchor = None
        for probe in range(idx + 2, min(len(lines), idx + 9)):
            candidate = lines[probe]
            if candidate.matched and candidate.start is not None:
                next_anchor = probe
                break
        if next_anchor is None:
            continue

        next_start = float(lines[next_anchor].start or 0.0)
        long_gap = next_start - end
        if long_gap < max(8.0, _script_readable_window_seconds(lines, idx, next_anchor) + 3.0):
            continue

        duration = max(0.0, end - start)
        # Sehr kurze Treffer oder Treffer direkt auf Worte des vorherigen Intros
        # sind besonders verdächtig. Normale frühe Verse-Anker ohne langen Gap
        # bleiben unangetastet.
        if duration <= 1.35 or long_gap >= 12.0:
            line.matched = False
            line.start = None
            line.end = None
            line.wstart = []
            line.wend = []
            report.append(
                f"INFO: Früher Abschnitts-Anker Zeile {idx + 1} ({line.section_label or line.section_type}) "
                f"bei {start:.1f}s als Intro-Wiederholung ignoriert; Zeile wird vor Anker {next_anchor + 1} neu verteilt."
            )
    return report


def _script_first_hyp_onset_in_window(hyp: list[HypWord] | None, window_start: float, window_end: float) -> float | None:
    """Erster ASR-Wortbeginn innerhalb eines Zeitfensters (Vokal-Onset)."""
    if not hyp:
        return None
    lower = window_start + 0.30
    upper = window_end - 0.20
    if upper <= lower:
        return None
    for word in hyp:
        start = float(word.start)
        if start < lower:
            continue
        if start > upper:
            return None
        return start
    return None


def _script_tail_spread_section_transition(
    lines: list[LyricLine],
    anchor_a: int,
    anchor_b: int,
    window_start: float,
    window_end: float,
    hyp: list[HypWord] | None = None,
) -> tuple[float | None, str | None]:
    """Legt einen neuen Abschnitt am Ende einer großen Intro-Lücke ab.

    Wenn nach dem Intro ein neuer Abschnitt beginnt und bis zum nächsten sicheren
    Anker ein sehr großes Fenster offen ist, ist eine gleichmäßige Verteilung ab
    dem Intro-Ende falsch: Dann würden Verse-Zeilen viel zu früh erscheinen.

    Ursachen-Fix: Existieren im Fenster echte ASR-Wörter (Vokal-Onset, auch wenn
    sie textlich nicht gematcht wurden), beginnt der Abschnitt an diesem Onset —
    dort setzt die Stimme hörbar ein. Nur ohne jeden ASR-Beleg wird wie bisher
    ein lesbares Fenster direkt vor den nächsten stabilen Anker gelegt; die
    reine Lesbarkeitsrechnung hat Verse-Starts sonst mehrere Sekunden zu spät
    platziert (z. B. 30s statt 25s).
    """
    if anchor_b <= anchor_a + 1:
        return None, None
    if anchor_a > 8 or window_end > 55.0:
        return None, None
    first = lines[anchor_a + 1]
    previous = lines[anchor_a]
    if not first.starts_section or not first.section_type:
        return None, None
    if first.section_type in {"intro", "instrumental_intro"}:
        return None, None
    if previous.section_type and previous.section_type == first.section_type:
        return None, None

    window = max(0.0, window_end - window_start)
    required = _script_readable_window_seconds(lines, anchor_a + 1, anchor_b)
    if window < max(9.0, required + 4.5):
        return None, None

    onset = _script_first_hyp_onset_in_window(hyp, window_start, window_end)
    if onset is not None and onset < window_end - 1.0:
        return onset, (
            f"INFO: Abschnitt {first.section_label or first.section_type} nach Intro-Lücke am "
            f"ASR-Vokal-Onset gestartet ({window_start:.1f}s-{window_end:.1f}s -> {onset:.1f}s-{window_end:.1f}s)."
        )

    tail_start = max(window_start, window_end - required)
    # Nicht an den ersten paar Sekunden kleben lassen; genau das erzeugt den
    # beobachteten Sprung von Intro direkt in Verse-Zeilen.
    if tail_start <= window_start + 2.5:
        return None, None
    return tail_start, (
        f"INFO: Abschnitt {first.section_label or first.section_type} nach Intro-Lücke spät verteilt "
        f"({window_start:.1f}s-{window_end:.1f}s -> {tail_start:.1f}s-{window_end:.1f}s)."
    )


def _script_protect_early_gap_before_anchor(
    lines: list[LyricLine],
    anchor_a: int,
    anchor_b: int,
    *,
    gap_seconds: float = 0.04,
) -> tuple[float, str | None]:
    """Reserviert Leseraum fuer fruehe ungematchte Zeilen zwischen Anchors.

    Fehlerbild: ``Skalino`` wird korrekt bei Sekunde 3 erkannt, der naechste
    echte Intro-Satz wurde vom ASR aber nicht erkannt. Wenn der erkannte
    ``Skalino``-Anchor zu lang endet, wird die ungematchte Zeile direkt vor den
    folgenden Verse-Anchor gequetscht und der Player springt visuell zwei Zeilen
    weiter. In den ersten Sekunden duerfen wir den fruehen Anchor daher am Ende
    kuerzen, damit die fehlende Intro-Zeile einen eigenen Zeitbereich bekommt.
    """
    if anchor_a < 0 or anchor_b <= anchor_a + 1:
        return float(lines[anchor_a].end or 0.0), None
    if anchor_a > 2 or anchor_b > 6:
        return float(lines[anchor_a].end or 0.0), None

    next_start = float(lines[anchor_b].start or 0.0)
    if next_start <= 0.0 or next_start > 24.0:
        return float(lines[anchor_a].end or 0.0), None

    required = _script_min_intro_gap_seconds(lines, anchor_a + 1, anchor_b)
    current_start = float(lines[anchor_a].end or 0.0)
    available = max(0.0, next_start - current_start)

    anchor_start = float(lines[anchor_a].start or 0.0)
    anchor_word_count = len(lines[anchor_a].words or lines[anchor_a].display.split())

    # Wichtig: Kurze Artist-Calls/Adlibs am Anfang werden von ASR-Anbietern
    # gelegentlich mit zu langer Endzeit geliefert (z. B. "Skalino" 3.0-7.1s).
    # Auch wenn rechnerisch ein kleines Gap uebrig bleibt, fuehlt sich das im
    # Live-Player wie ein Sprung ueber die naechste Intro-Zeile an. Deshalb darf
    # ein sehr frueher, kurzer Anchor nicht den ganzen Raum bis zum naechsten
    # Hauptzeilen-Anchor belegen.
    max_short_anchor_duration = 1.35 if anchor_word_count <= 2 else 2.15
    short_anchor_cap = anchor_start + max_short_anchor_duration
    candidate_end = current_start

    if anchor_a <= 1 and anchor_word_count <= 2 and current_start > short_anchor_cap + 0.20:
        # Den Anchor nur kuerzen, wenn dadurch fuer die fehlenden Zeilen ein
        # sinnvoller Leseraum entsteht. Der naechste sichere Anker bleibt fix.
        expanded_available = max(0.0, next_start - short_anchor_cap)
        if expanded_available >= max(1.35, required * 0.62):
            candidate_end = min(candidate_end, short_anchor_cap)

    if available < required * 0.82:
        min_anchor_duration = 0.75 if anchor_word_count <= 2 else 1.05
        # Frueherer Start wird bevorzugt, solange der Anchor selbst lesbar bleibt.
        gap_based_end = max(anchor_start + min_anchor_duration, next_start - required)
        candidate_end = min(candidate_end, gap_based_end)

    if candidate_end + gap_seconds < current_start:
        lines[anchor_a].end = round(candidate_end, 3)
        return float(lines[anchor_a].end or candidate_end), (
            f"INFO: Fruehe Intro-Zeile(n) {anchor_a + 2}-{anchor_b} vor Anker {anchor_b + 1} "
            f"entquetscht ({available:.1f}s -> {max(0.0, next_start - candidate_end):.1f}s)."
        )

    return current_start, None

def _script_early_hyp_resembles_intro(lines: list[LyricLine], first: int, hyp: list[HypWord] | None, *, before_time: float) -> bool:
    """True, wenn fruehe ASR-Tokens textlich zu den Intro-Zeilen passen."""
    if not hyp:
        return False
    intro_tokens = {token for index in range(first) for token in lines[index].match_tokens if len(token) >= 3}
    if not intro_tokens:
        return False
    for word in hyp:
        if float(word.start) >= before_time:
            break
        for token in intro_tokens:
            if _script_word_similarity(word.norm, token) >= 0.62:
                return True
    return False


def _script_onset_adjusted_window_start(
    hyp: list[HypWord] | None,
    window_start: float,
    window_end: float,
    required_seconds: float,
) -> float | None:
    """Verschiebt den Start eines Schaetz-Fensters auf den ASR-Vokal-Onset.

    Ursachen-Fix: Ungematchte Zeilen zwischen zwei Ankern wurden bisher direkt
    ab dem Ende der Vorgaengerzeile verteilt. Liegt im Fenster erst Stille oder
    Instrumental und die Stimme setzt spaeter wieder ein (ASR-Woerter vorhanden,
    nur textlich nicht gematcht), erschienen die Zeilen mehrere Sekunden zu
    frueh. Der Fensterstart folgt jetzt dem ersten ASR-Wort im Fenster; damit
    die Zeilen lesbar bleiben, wird nie weiter verschoben, als das Fenster
    Platz fuer `required_seconds` laesst.
    """
    onset = _script_first_hyp_onset_in_window(hyp, window_start, window_end)
    if onset is None:
        return None
    latest_start = window_end - max(0.6, required_seconds)
    adjusted = min(onset, max(window_start, latest_start))
    if adjusted <= window_start + 0.75:
        return None
    return adjusted


def _script_resolve_timeline(
    lines: list[LyricLine],
    warn_factor: float,
    hyp_first_start: float | None = None,
    hyp: list[HypWord] | None = None,
) -> list[str]:
    report: list[str] = []
    n = len(lines)
    rates = [
        (line.end - line.start) / line.weight
        for line in lines
        if line.matched and line.start is not None and line.end is not None and line.end > line.start and line.weight > 0
    ]
    seconds_per_weight = sorted(rates)[len(rates) // 2] if rates else 0.35
    report.extend(_script_demote_false_early_section_anchors(lines, seconds_per_weight))
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
        default_start = max(0.0, end - need)
        start = default_start

        # Schutz fuer fruehe Intro-/Adlib-Zeilen: ASR-Modelle verschlucken kurze
        # Einstiegsworte wie Kuenstlernamen oder gesprochene Intros haeufig.
        # Bisher wurden solche Zeilen direkt vor den ersten sicheren Anker gelegt;
        # dadurch erschien z. B. "Skalino" erst bei 7-8s und sprang sofort weiter.
        # Wenn der erste sichere Anker spaeter liegt, reservieren wir ein plausibles
        # Intro-Fenster vor dem Anker. Das veraendert keine API/Datenstruktur,
        # sondern nur die Schaetzung fuer nicht gematchte Zeilen vor dem ersten
        # Wort-Anker.
        if end >= 2.0:
            # Ursachen-Fix: Das Schutzfenster richtet sich nach dem tatsaechlichen
            # Textumfang der fehlenden Intro-Zeilen (Lesbarkeitsfenster), nicht
            # mehr pauschal nach 62% der Ankerzeit. Eine kurze Intro-Zeile wie
            # "Yeah. Absolute Dunkelheit." wurde sonst ~3s vor ihren echten
            # Einsatz gezogen.
            content_window = max(need, _script_min_intro_gap_seconds(lines, 0, first))
            protected_window = min(content_window, max(need, min(4.75, end * 0.62)))
            protected_start = max(0.0, end - protected_window)
            if hyp_first_start is not None and 0.75 <= hyp_first_start < end - 0.20:
                # Der erste ASR-Wortbeginn darf das Fenster nur nach vorne ziehen,
                # wenn die fruehen ASR-Tokens den Intro-Zeilen textlich aehneln;
                # Halluzinationen/fremde Adlibs am Songanfang pinnen die Zeile
                # sonst faelschlich auf den ersten ASR-Onset.
                if _script_early_hyp_resembles_intro(lines, first, hyp, before_time=end - 0.20):
                    protected_start = min(protected_start, max(0.0, float(hyp_first_start)))
            start = min(default_start, protected_start)

        _script_spread(lines, 0, first, start, end)
        if start < default_start - 0.25:
            report.append(
                f"INFO: Zeilen 1-{first} vor erstem Anker mit Intro-Fenster geschaetzt "
                f"({start:.1f}s-{end:.1f}s)."
            )
        else:
            report.append(f"INFO: Zeilen 1-{first} vor erstem Anker geschaetzt.")

    for anchor_a, anchor_b in zip(anchors, anchors[1:]):
        gap = anchor_b - anchor_a - 1
        if gap <= 0:
            continue
        window_start = lines[anchor_a].end or 0.0
        protection_report = None
        if anchor_a <= 2 and anchor_b <= 6:
            window_start, protection_report = _script_protect_early_gap_before_anchor(lines, anchor_a, anchor_b)
            if protection_report:
                report.append(protection_report)
        window_end = lines[anchor_b].start or window_start
        window = max(window_end - window_start, 0.0)
        expected = sum(lines[i].weight for i in range(anchor_a + 1, anchor_b)) * seconds_per_weight
        tail_start, tail_report = _script_tail_spread_section_transition(lines, anchor_a, anchor_b, window_start, window_end, hyp=hyp)
        if tail_start is not None:
            _script_spread(lines, anchor_a + 1, anchor_b, tail_start, window_end)
            if tail_report:
                report.append(tail_report)
        else:
            onset_start = _script_onset_adjusted_window_start(hyp, window_start, window_end, expected)
            if onset_start is not None:
                _script_spread(lines, anchor_a + 1, anchor_b, onset_start, window_end)
                report.append(
                    f"INFO: Zeilen {anchor_a + 2}-{anchor_b} am ASR-Vokal-Onset gestartet "
                    f"({window_start:.1f}s -> {onset_start:.1f}s, Fensterende {window_end:.1f}s)."
                )
            else:
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



def _script_insert_repeated_lines_from_timing(lines: list[LyricLine], hyp: list[HypWord]) -> list[str]:
    """Fuegt wiederholte kurze Zeilen anhand der finalen Zeitfenster ein.

    Diese zweite Sicherung greift, wenn der Effective-Lyrics-Layer eine Suno-
    Wiederholung nicht frueh genug erkannt hat, die ASR-Worte aber innerhalb des
    langen Zeitfensters einer kurzen Lyrics-Zeile zweimal auftauchen. Sie aendert
    nur die in-memory Alignment-Zeilen, keine API, keine DB, keine Tasklogik.
    """
    report: list[str] = []
    if not lines or not hyp:
        return report

    i = 0
    while i < len(lines):
        line = lines[i]
        start = float(line.start or 0.0)
        end = float(line.end or start)
        duration = end - start
        tokens = line.match_tokens or _effective_line_tokens(line.display)
        if _line_in_explicit_repeated_block(lines, i):
            i += 1
            continue
        if duration < 4.25 or len(tokens) < 3 or len(tokens) > 8:
            i += 1
            continue
        if i + 1 < len(lines):
            next_line = lines[i + 1]
            if _effective_line_tokens(next_line.display) == _effective_line_tokens(line.display):
                i += 1
                continue

        occurrences: list[dict[str, Any]] = []
        for occurrence in _effective_find_occurrences_flexible(tokens, hyp, start_index=0, max_count=None):
            occ_start = float(occurrence.get("start") or 0.0)
            occ_end = float(occurrence.get("end") or occ_start)
            if occ_start >= start - 0.35 and occ_end <= end + 0.35:
                occurrences.append(occurrence)
        occurrences.sort(key=lambda item: float(item.get("start") or 0.0))
        if len(occurrences) < 2:
            i += 1
            continue

        first = occurrences[0]
        second = occurrences[1]
        first_start = float(first.get("start") or start)
        first_end = float(first.get("end") or first_start)
        second_start = float(second.get("start") or start)
        second_end = float(second.get("end") or second_start)
        if second_start - first_start < 0.75:
            i += 1
            continue

        next_start = float(lines[i + 1].start) if i + 1 < len(lines) and lines[i + 1].start is not None else end
        first_new_end = min(end, max(start + 0.75, min(second_start - 0.04, first_end + 0.45)))
        second_new_start = max(first_new_end + 0.04, second_start)
        second_new_end = min(next_start - 0.04 if next_start > second_new_start else end, max(second_end + 0.45, second_new_start + 0.85))
        if second_new_end <= second_new_start + 0.35:
            midpoint = start + duration / 2
            first_new_end = max(start + 0.75, midpoint - 0.04)
            second_new_start = min(end - 0.75, midpoint + 0.04)
            second_new_end = end
        if second_new_end <= second_new_start + 0.35 or first_new_end <= start + 0.35:
            i += 1
            continue

        line.end = round(first_new_end, 3)
        line.wstart = None
        line.wend = None

        duplicate = LyricLine(
            index=line.index,
            display=line.display,
            words=list(line.words or []),
            tok_counts=list(line.tok_counts or []),
            match_tokens=list(line.match_tokens or []),
            weight=float(line.weight or 1.0),
            matched=True,
            start=round(second_new_start, 3),
            end=round(second_new_end, 3),
            wstart=None,
            wend=None,
            section_label=line.section_label,
            section_type=line.section_type,
            starts_section=False,
        )
        lines.insert(i + 1, duplicate)
        report.append(
            f"INFO: Wiederholte kurze Zeile aus ASR-Zeitfenster ergaenzt: {line.display!r} "
            f"bei {second_new_start:.1f}s."
        )
        i += 2
    return report


def _script_intro_lines_same(left: LyricLine, right: LyricLine) -> bool:
    left_tokens = _effective_line_tokens(left.display)
    right_tokens = _effective_line_tokens(right.display)
    if left_tokens and right_tokens and left_tokens == right_tokens:
        return True
    return _effective_line_similarity(left.display, right.display) >= 0.92


def _script_insert_missing_intro_block_prefix_repeats(lines: list[LyricLine]) -> list[str]:
    """Ergaenzt fehlende kurze Prefix-Zeilen bei Intro-Block-Wiederholungen.

    Praxisfall: Songtext enthaelt im Intro A-B, Suno performt A-B-A-B, aber
    ASR erkennt beim zweiten Durchlauf nur B sauber. Dann kann die vorherige
    Logik bereits B duplizieren, laesst A aber fehlen. Diese Funktion arbeitet
    nach dem ersten Timing-Alignment und fuegt die kurze vorherige Intro-Zeile
    direkt vor dem zweiten B ein. Dadurch entsteht die echte Performance-Sicht
    A-B-A-B, ohne den gespeicherten Songtext oder DB-Schema zu veraendern.
    """
    report: list[str] = []
    if len(lines) < 4:
        return report

    index = 0
    while index < min(len(lines) - 2, 12):
        first = lines[index]
        second = lines[index + 1]
        first_section = str(first.section_type or "").lower()
        second_section = str(second.section_type or "").lower()
        if first_section not in {"intro", "instrumental_intro"} or second_section != first_section:
            index += 1
            continue
        if _script_intro_lines_same(first, second):
            index += 1
            continue

        first_tokens = first.match_tokens or _effective_line_tokens(first.display)
        second_tokens = second.match_tokens or _effective_line_tokens(second.display)
        if not (1 <= len(first_tokens) <= 4 and 2 <= len(second_tokens) <= 10):
            index += 1
            continue

        # Nur bis zum ersten Nicht-Intro-Abschnitt pruefen. Spaetere Hooks oder
        # Bridges duerfen keine fruehen Intro-Duplikate erzeugen.
        intro_end = index + 2
        while intro_end < len(lines):
            section = str(lines[intro_end].section_type or "").lower()
            if section and section not in {"intro", "instrumental_intro"}:
                break
            intro_end += 1

        repeat_index: int | None = None
        for probe in range(index + 2, intro_end):
            if _script_intro_lines_same(lines[probe], second):
                repeat_index = probe
                break
        if repeat_index is None:
            index += 1
            continue

        # Wenn die Prefix-Zeile bereits vor dem zweiten B existiert, ist der
        # Block schon korrekt A-B-A-B und darf nicht erneut erweitert werden.
        if any(_script_intro_lines_same(lines[probe], first) for probe in range(index + 2, repeat_index)):
            index += 1
            continue

        repeated_second = lines[repeat_index]
        repeated_second_start = float(repeated_second.start or 0.0)
        previous_end = float(second.end or second.start or 0.0)
        if repeated_second_start <= previous_end + 0.45:
            index += 1
            continue

        estimated = _script_estimated_repeat_line_duration(first)
        duplicate_end = min(repeated_second_start - 0.04, max(previous_end + 0.55, repeated_second_start - 0.04))
        duplicate_start = max(previous_end + 0.08, duplicate_end - estimated)
        if duplicate_end <= duplicate_start + 0.45:
            index += 1
            continue

        duplicate = LyricLine(
            index=first.index,
            display=first.display,
            words=list(first.words or []),
            tok_counts=list(first.tok_counts or []),
            match_tokens=list(first.match_tokens or []),
            weight=float(first.weight or 1.0),
            matched=False,
            start=round(duplicate_start, 3),
            end=round(duplicate_end, 3),
            wstart=None,
            wend=None,
            section_label=first.section_label,
            section_type=first.section_type,
            starts_section=False,
        )
        lines.insert(repeat_index, duplicate)
        report.append(
            f"INFO: Fehlender Intro-Block-Prefix als Performance-Wiederholung ergaenzt: "
            f"{first.display!r} vor wiederholter Zeile {second.display!r} bei {duplicate_start:.1f}s."
        )
        index = repeat_index + 1

    return report


def _script_estimated_repeat_line_duration(line: LyricLine) -> float:
    words = line.words or line.display.split()
    word_count = max(1, len(words))
    weight = max(float(line.weight or 1.0), 1.0)
    return max(1.15, min(3.2, 0.34 * word_count + 0.12 * weight + 0.45))


def _script_observed_word_span_seconds(line: LyricLine) -> float | None:
    starts = [float(value) for value in (line.wstart or []) if value is not None]
    ends = [float(value) for value in (line.wend or []) if value is not None]
    if not starts or not ends:
        return None
    start = min(starts)
    end = max(ends)
    return max(0.0, end - start) if end > start else None


def _script_reflow_section_after_intro_repeat(lines: list[LyricLine], duplicate_index: int, gap: float = 0.04) -> str | None:
    """Zieht geschätzte erste Abschnittszeilen nach einer Intro-Wiederholung leicht vor.

    Die synthetische Intro-Wiederholung wird erst nach der initialen Timeline-
    Auflösung eingefügt. Der folgende Verse/Hook wurde zu diesem Zeitpunkt oft
    bereits konservativ direkt vor den nächsten sicheren ASR-Anker gelegt. Wenn
    zwischen Wiederholung und Anker noch ausreichend freies Fenster liegt, dürfen
    die ersten ungematchten Abschnittszeilen dieses Fenster nutzen, statt leicht
    verspätet zu starten.
    """
    start_idx = duplicate_index + 1
    if start_idx >= len(lines):
        return None
    first = lines[start_idx]
    if not first.starts_section or not first.section_type:
        return None
    if first.section_type in {"intro", "instrumental_intro"}:
        return None

    anchor_idx: int | None = None
    for probe in range(start_idx + 1, min(len(lines), start_idx + 8)):
        candidate = lines[probe]
        if candidate.matched and candidate.start is not None:
            anchor_idx = probe
            break
    if anchor_idx is None or anchor_idx <= start_idx:
        return None
    if any(lines[index].matched for index in range(start_idx, anchor_idx)):
        return None

    duplicate = lines[duplicate_index]
    duplicate_end = float(duplicate.end or duplicate.start or 0.0)
    anchor_start = float(lines[anchor_idx].start or 0.0)
    if duplicate_end <= 0.0 or anchor_start <= duplicate_end:
        return None

    required = _script_readable_window_seconds(lines, start_idx, anchor_idx)
    available = anchor_start - duplicate_end
    if available < required + 0.65:
        return None

    current_start = float(first.start or 0.0)
    line_count = anchor_idx - start_idx
    if line_count == 2:
        second = lines[start_idx + 1]
        second_current_start = float(second.start or 0.0)
        first_words = first.words or first.display.split()
        # Der erste echte Verse-Einsatz wurde vor dem Einfuegen der synthetischen
        # Intro-Wiederholung bereits plausibel gesetzt. In diesem Spezialfall
        # soll nicht der ganze Verse-Block nach vorne rutschen; nur die zweite
        # geschätzte Zeile beginnt zu spaet. Kurze Rap-Zeilen duerfen deshalb
        # frueher wechseln, waehrend der sichere Folgeanker fix bleibt.
        first_duration = max(1.35, min(1.85, 0.13 * max(1, len(first_words)) + 0.25))
        second_target_start = max(current_start + first_duration, duplicate_end + 0.35)
        second_target_start = min(second_target_start, anchor_start - 1.05)
        if second_target_start + 0.35 < second_current_start:
            first.end = round(second_target_start - gap, 3)
            first.wstart = None
            first.wend = None
            second.start = round(second_target_start, 3)
            second.end = round(max(second_target_start + 0.75, anchor_start - gap), 3)
            second.wstart = None
            second.wend = None
            return (
                f"INFO: Zweite Abschnittszeile nach Intro-Wiederholung frueher gesetzt "
                f"({second_current_start:.1f}s -> {second_target_start:.1f}s, erster Start bleibt {current_start:.1f}s)."
            )
        return None

    surplus = max(0.0, available - required - 0.35)
    lead_in = min(1.6, surplus)
    target_start = max(duplicate_end + 0.35, anchor_start - required - lead_in)
    target_end = max(target_start + 0.75, anchor_start - gap)
    if target_start >= current_start - 0.35 or target_end <= target_start:
        return None

    _script_spread(lines, start_idx, anchor_idx, target_start, target_end)
    return (
        f"INFO: Abschnitt {first.section_label or first.section_type} nach Intro-Wiederholung frueher verteilt "
        f"({current_start:.1f}s -> {target_start:.1f}s, Anker {anchor_idx + 1} bei {anchor_start:.1f}s)."
    )


def _script_find_time_occurrence(tokens: list[str], hyp: list[HypWord], start_time: float, end_time: float) -> dict[str, Any] | None:
    if not tokens or not hyp or end_time <= start_time:
        return None
    start_index = 0
    end_index = len(hyp)
    for idx, word in enumerate(hyp):
        if word.end >= start_time:
            start_index = idx
            break
    for idx, word in enumerate(hyp):
        if word.start > end_time:
            end_index = idx
            break
    matches = _effective_find_occurrences_flexible(tokens, hyp, start_index=start_index, end_index=end_index, max_count=1)
    if matches:
        return matches[0]

    # Fallback fuer schwache ASR-Ausgaben: Wenn wenigstens der Anfang der Zeile
    # erneut auftaucht, gilt das als Hinweis, die Wiederholung im Intro sichtbar
    # zu machen. Die sichtbare Textzeile stammt weiterhin aus dem Songtext.
    variants = _effective_line_token_variants(tokens) or [tokens]
    for variant in variants:
        prefix = variant[:min(3, len(variant))]
        if len(prefix) < 2 and (not prefix or len(prefix[0]) < 5):
            continue
        hyp_tokens = [word.norm for word in hyp]
        for pos in range(start_index, max(start_index, end_index - len(prefix) + 1)):
            candidate = hyp_tokens[pos:pos + len(prefix)]
            if candidate == prefix or (len(prefix) == 1 and candidate and _script_word_similarity(candidate[0], prefix[0]) >= 0.82):
                return {
                    "start_index": pos,
                    "end_index": pos + len(prefix),
                    "start": float(hyp[pos].start),
                    "end": float(hyp[pos + len(prefix) - 1].end),
                    "score": 0.74 if len(prefix) > 1 else 0.70,
                    "variant_len": len(prefix),
                    "variant_tokens": prefix,
                }
    return None


def _script_build_asr_line_candidates(hyp: list[HypWord]) -> list[_AsrLineCandidate]:
    """Baut robuste ASR-Zeilenkandidaten aus Wortzeiten.

    Whisper/Groq liefert fuer Musik selten perfekte Zeilen. Trotzdem sind
    Pausen, lange Wortabstaende und kompakte Wortgruppen gute Hinweise darauf,
    welche Lyrics-Zeile gerade gesungen wurde. Diese Kandidaten dienen nur als
    Timing-Reviewer; sichtbarer Text bleibt weiterhin aus den Songlyrics.
    """
    candidates: list[_AsrLineCandidate] = []
    current: list[HypWord] = []

    def flush() -> None:
        nonlocal current
        tokens = [word.norm for word in current if word.norm]
        if len(tokens) >= 2:
            candidates.append(_AsrLineCandidate(
                index=len(candidates),
                tokens=tokens,
                start=round(float(current[0].start), 3),
                end=round(float(current[-1].end), 3),
                text=" ".join(tokens),
            ))
        current = []

    previous: HypWord | None = None
    for word in hyp:
        if previous is not None:
            pause = float(word.start) - float(previous.end)
            duration = float(previous.end) - float(current[0].start) if current else 0.0
            previous_duration = float(previous.end) - float(previous.start)
            if (
                pause >= 0.82
                or (previous_duration >= 1.6 and pause >= 0.30)
                or len(current) >= 15
                or (len(current) >= 7 and duration >= 5.8)
            ):
                flush()
        current.append(word)
        previous = word
    flush()
    return candidates


def _script_candidate_line_score(candidate_tokens: list[str], line: LyricLine) -> float:
    line_tokens = line.match_tokens or _effective_line_tokens(line.display)
    if not candidate_tokens or not line_tokens:
        return 0.0

    candidate_text = " ".join(candidate_tokens)

    def fuzzy_sequence_score(variant: list[str]) -> float:
        if not variant:
            return 0.0

        candidate_cursor = 0
        matched = 0
        similarity_sum = 0.0
        first_match_at: int | None = None
        last_match_at: int | None = None

        for token in variant:
            best_index: int | None = None
            best_similarity = 0.0
            # Ein kleines Vorwaertsfenster reicht fuer normale ASR-Fehlhoerungen
            # und verhindert, dass spaete Hook-Treffer einen fruehen Abschnitt
            # nur wegen einzelner gleicher Woerter dominieren.
            for candidate_index in range(candidate_cursor, len(candidate_tokens)):
                similarity = _script_word_similarity(candidate_tokens[candidate_index], token)
                if similarity > best_similarity:
                    best_similarity = similarity
                    best_index = candidate_index
                if similarity >= 0.92:
                    break
            if best_index is None or best_similarity < SCRIPT_FUZZY_WORD_THRESHOLD:
                continue
            if first_match_at is None:
                first_match_at = best_index
            last_match_at = best_index
            matched += 1
            similarity_sum += best_similarity
            candidate_cursor = best_index + 1

        if matched <= 0:
            return 0.0

        line_coverage = matched / max(1, len(variant))
        candidate_coverage = matched / max(1, len(candidate_tokens))
        avg_similarity = similarity_sum / matched
        span_width = (last_match_at - first_match_at + 1) if first_match_at is not None and last_match_at is not None else matched
        compactness = matched / max(1, span_width)
        prefix_bonus = 0.0
        if variant and candidate_tokens:
            first_similarity = _script_word_similarity(candidate_tokens[0], variant[0])
            if first_similarity >= 0.86:
                prefix_bonus += 0.05
            if len(variant) > 1 and len(candidate_tokens) > 1 and _script_word_similarity(candidate_tokens[1], variant[1]) >= 0.82:
                prefix_bonus += 0.03

        length_penalty = 0.0
        if len(candidate_tokens) <= 3 and len(variant) >= 7 and line_coverage < 0.55:
            length_penalty = 0.10
        elif len(candidate_tokens) >= 7 and len(variant) <= 3 and candidate_coverage < 0.55:
            length_penalty = 0.12

        score = (
            line_coverage * 0.40
            + candidate_coverage * 0.32
            + avg_similarity * 0.18
            + compactness * 0.10
            + prefix_bonus
            - length_penalty
        )
        return max(0.0, min(1.0, score))

    best = 0.0
    for variant in _effective_line_token_variants(line_tokens) or [line_tokens]:
        variant_text = " ".join(variant)
        seq = difflib.SequenceMatcher(a=candidate_text, b=variant_text, autojunk=False).ratio()
        fuzzy = fuzzy_sequence_score(variant)
        best = max(best, min(1.0, max(seq, fuzzy)))
    return round(best, 3)


def _script_match_asr_candidates_to_lyrics(
    candidates: list[_AsrLineCandidate],
    lines: list[LyricLine],
    *,
    min_score: float = 0.78,
) -> list[_AsrLyricsLineMatch]:
    if not candidates or not lines:
        return []

    # Monotones ASR-Block-zu-Lyrics-Alignment:
    # Kandidaten duerfen nur vorwaerts auf Lyrics-Zeilen gemappt werden. Fehlende
    # ASR-Zeilen werden ueber Skip-Kosten modelliert, statt dass der beste globale
    # Einzelhit die komplette Reihenfolge ueberschreibt. Das ist die eigentliche
    # Korrektur gegen die fruehere Ankerarmut durch reine Exact-Matches.
    effective_min_score = min(min_score, 0.64)
    max_lookahead = 12
    states: dict[int, tuple[float, list[_AsrLyricsLineMatch]]] = {0: (0.0, [])}

    for candidate in candidates:
        next_states: dict[int, tuple[float, list[_AsrLyricsLineMatch]]] = {}

        def update(cursor: int, score: float, path: list[_AsrLyricsLineMatch]) -> None:
            current = next_states.get(cursor)
            if current is None or score > current[0]:
                next_states[cursor] = (score, path)

        for cursor, (state_score, path) in states.items():
            update(cursor, state_score - 0.05, path)
            line_limit = min(len(lines), cursor + max_lookahead)
            for line_index in range(cursor, line_limit):
                raw_score = _script_candidate_line_score(candidate.tokens, lines[line_index])
                if raw_score < effective_min_score:
                    continue
                skipped = line_index - cursor
                skip_penalty = skipped * 0.11
                if skipped >= 3:
                    skip_penalty += (skipped - 2) * 0.08
                if skipped > 0 and any(lines[probe].starts_section for probe in range(cursor + 1, line_index + 1)):
                    skip_penalty += 0.18
                transition_score = raw_score - skip_penalty
                if transition_score < 0.46:
                    continue
                match = _AsrLyricsLineMatch(
                    candidate_index=candidate.index,
                    line_index=line_index,
                    score=round(raw_score, 3),
                    start=candidate.start,
                    end=candidate.end,
                    text=candidate.text,
                )
                update(line_index + 1, state_score + transition_score, path + [match])

        states = next_states or states

    if not states:
        return []
    _, best_path = max(states.values(), key=lambda item: (item[0], len(item[1])))
    return best_path


def _script_has_ambiguous_skipped_prefix(lines: list[LyricLine], match: _AsrLyricsLineMatch) -> bool:
    """Schuetzt uebersprungene Lyrics-Zeilen mit gleichem Satzanfang.

    Suno zieht Verse-/Hook-Anfaenge gelegentlich in Intro-Luecken oder wiederholt
    nur einzelne Prefix-Worte. Der ASR-Zeilenreviewer darf dann einen spaeteren
    Songtext-Treffer nicht als Anker setzen, wenn direkt davor eine noch nicht
    sauber abgeschlossene Zeile mit demselben Anfang steht. Dadurch bleibt der
    Songtext die Quelle der Reihenfolge, waehrend ASR nur sichere Timing-Anker
    korrigiert.
    """
    if match.line_index <= 0:
        return False
    candidate_tokens = _script_tokenize_match(match.text)
    if len(candidate_tokens) < 2:
        return False
    candidate_prefix = candidate_tokens[:2]
    start_index = max(0, match.line_index - 4)
    for previous_index in range(start_index, match.line_index):
        previous = lines[previous_index]
        previous_tokens = previous.match_tokens or _effective_line_tokens(previous.display)
        if len(previous_tokens) < 2 or previous_tokens[:2] != candidate_prefix:
            continue
        previous_start = float(previous.start or 0.0)
        previous_end = float(previous.end or previous_start)
        previous_duration = previous_end - previous_start
        previous_is_clean_before = (
            bool(previous.matched)
            and previous_duration >= 0.45
            and previous_end <= match.start - 0.25
        )
        if not previous_is_clean_before:
            return True
    return False


def _script_refine_review_anchor(
    line: LyricLine,
    hyp: list[HypWord],
    block_start: float,
    block_end: float,
) -> tuple[float, float, list[float | None], list[float | None]] | None:
    """Verfeinert einen Review-Anker auf die Zeilenwoerter innerhalb des Blocks.

    Ursachen-Fix: ASR-Kandidatenbloecke folgen Gesangspausen, nicht
    Zeilengrenzen. Wird durchgesungen, enthaelt ein Block haeufig den Schluss
    der Vorgaengerzeile ("... in dein Fledermausland CHRONISCH GENIALER ...").
    Die bisherige Uebernahme der Blockgrenzen zog solche Zeilen sekundenweise
    nach vorn. Hier werden die Zeilen-Tokens gegen die Blockwoerter
    sub-aligned (exakt + Fuzzy wie im Hauptalignment); Start/Ende kommen dann
    von den tatsaechlich zur Zeile gehoerenden Woertern. Liefert None, wenn zu
    wenige Tokens sicher zuordenbar sind -- dann bleibt das bisherige
    Blockgrenzen-Verhalten als Fallback bestehen.
    """
    block_words = [
        word for word in hyp
        if float(word.start) >= block_start - 0.02 and float(word.end) <= block_end + 0.02
    ]
    if len(block_words) < 2:
        return None
    tokens = list(line.match_tokens)
    if not tokens:
        return None

    starts: list[float | None] = [None] * len(tokens)
    ends: list[float | None] = [None] * len(tokens)
    matcher = difflib.SequenceMatcher(a=[word.norm for word in block_words], b=tokens, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                starts[j1 + offset] = float(block_words[i1 + offset].start)
                ends[j1 + offset] = float(block_words[i1 + offset].end)
        elif tag == "replace":
            span = min(i2 - i1, j2 - j1)
            for offset in range(span):
                j = j1 + offset
                if starts[j] is None and _script_word_similarity(block_words[i1 + offset].norm, tokens[j]) >= SCRIPT_FUZZY_WORD_THRESHOLD:
                    starts[j] = float(block_words[i1 + offset].start)
                    ends[j] = float(block_words[i1 + offset].end)
            for offset in range(1, span + 1):
                j = j2 - offset
                if starts[j] is None and _script_word_similarity(block_words[i2 - offset].norm, tokens[j]) >= SCRIPT_FUZZY_WORD_THRESHOLD:
                    starts[j] = float(block_words[i2 - offset].start)
                    ends[j] = float(block_words[i2 - offset].end)

    matched_positions = [index for index, value in enumerate(starts) if value is not None and ends[index] is not None]
    if len(tokens) == 1:
        required = 1
    elif len(tokens) <= 5:
        required = 2
    else:
        required = max(2, int(round(len(tokens) * 0.34)))
    if len(matched_positions) < required:
        return None
    refined_start = min(starts[index] for index in matched_positions)
    refined_end = max(ends[index] for index in matched_positions)
    if refined_end - refined_start < 0.30:
        return None

    word_starts: list[float | None] = []
    word_ends: list[float | None] = []
    cursor = 0
    for count in line.tok_counts:
        slice_starts = [starts[cursor + k] for k in range(count) if cursor + k < len(tokens) and starts[cursor + k] is not None]
        slice_ends = [ends[cursor + k] for k in range(count) if cursor + k < len(tokens) and ends[cursor + k] is not None]
        word_starts.append(min(slice_starts) if slice_starts else None)
        word_ends.append(max(slice_ends) if slice_ends else None)
        cursor += count
    return refined_start, refined_end, word_starts, word_ends


def _script_apply_asr_line_review(lines: list[LyricLine], hyp: list[HypWord]) -> list[str]:
    candidates = _script_build_asr_line_candidates(hyp)
    matches = _script_match_asr_candidates_to_lyrics(candidates, lines)
    if not candidates:
        return []

    report = [
        f"INFO: ASR-Zeilenabgleich: {len(candidates)} Kandidaten, {len(matches)} sequenzielle Lyrics-Treffer "
        "per fuzzy Block-Alignment."
    ]
    changed = 0
    refined_count = 0
    for match in matches:
        if match.line_index < 0 or match.line_index >= len(lines):
            continue
        line = lines[match.line_index]
        current_start = float(line.start or 0.0)
        current_end = float(line.end or current_start)
        candidate_duration = max(0.0, match.end - match.start)
        if candidate_duration < 0.45:
            continue
        if _script_has_ambiguous_skipped_prefix(lines, match):
            report.append(
                f"INFO: ASR-Zeilenabgleich: Kandidat {match.candidate_index + 1} fuer Zeile "
                f"{match.line_index + 1} wegen voriger aehnlicher Lyrics-Zeile nicht als Anker uebernommen."
            )
            continue
        # Sichere ASR-Zeilen duerfen falsche oder fehlende globale
        # SequenceMatcher-Anker korrigieren. Bei bereits nahen Treffern bleibt
        # die bestehende feinere Wortzeit erhalten.
        should_apply = (
            not line.matched
            or line.start is None
            or abs(current_start - match.start) > 1.15
            or (current_end - current_start < 0.45 and candidate_duration >= 0.75)
        )
        if not should_apply:
            continue
        refined = _script_refine_review_anchor(line, hyp, match.start, match.end)
        if refined is not None:
            refined_start, refined_end, word_starts, word_ends = refined
            line.start = round(refined_start, 3)
            line.end = round(max(refined_end, refined_start + 0.6), 3)
            line.matched = True
            if len(word_starts) == len(line.words) and any(value is not None for value in word_starts):
                line.wstart = word_starts  # type: ignore[assignment]
                line.wend = word_ends  # type: ignore[assignment]
            else:
                line.wstart = None
                line.wend = None
            refined_count += 1
            changed += 1
            continue
        line.start = round(match.start, 3)
        line.end = round(max(match.end, match.start + 0.6), 3)
        line.matched = True
        line.wstart = None
        line.wend = None
        changed += 1
    if changed:
        report.append(f"INFO: ASR-Zeilenabgleich: {changed} Lyrics-Zeile(n) als Timing-Anker korrigiert ({refined_count} per Block-Subalignment verfeinert).")
    return report


def _script_reassign_sparse_section_jump_anchors(lines: list[LyricLine]) -> list[str]:
    """Korrigiert frühe ASR-Sprünge innerhalb eines neuen Abschnitts.

    Wenn Whisper/Groq nach einem Intro eine große Lücke hat, kann der erste
    Treffer im Verse/Hook inhaltlich wie eine spätere Lyrics-Zeile aussehen.
    Der sichtbare Songtext soll aber weiterhin strikt in Songtext-Reihenfolge
    laufen. Deshalb wird ein erster Anker, der mehrere erwartete Zeilen eines
    neuen Abschnitts überspringt, auf die nächste erwartete Zeile umgelegt. Das
    ist eine konservative Korrektur fuer lueckenhafte ASR-Starts, keine
    Sonderregel fuer konkrete Lyrics.
    """
    report: list[str] = []
    idx = 0
    while idx < len(lines):
        section_start = idx
        line = lines[section_start]
        section_type = str(line.section_type or "").lower()
        if not line.starts_section or not section_type or section_type in {"intro", "instrumental_intro"}:
            idx += 1
            continue

        section_end = section_start + 1
        while section_end < len(lines):
            probe = lines[section_end]
            if probe.starts_section and probe.section_type != line.section_type:
                break
            section_end += 1

        previous = lines[section_start - 1] if section_start > 0 else None
        previous_section = str(previous.section_type or "").lower() if previous else ""
        previous_end = float(previous.end or 0.0) if previous else 0.0
        if previous is None or previous_section not in {"intro", "instrumental_intro"} or previous_end <= 0.0:
            idx = section_end
            continue

        first_anchor: int | None = None
        for anchor_index in range(section_start, section_end):
            candidate = lines[anchor_index]
            if candidate.matched and candidate.start is not None and candidate.end is not None:
                first_anchor = anchor_index
                break
        if first_anchor is None:
            idx = section_end
            continue

        skipped = first_anchor - section_start
        first_anchor_start = float(lines[first_anchor].start or 0.0)
        if skipped < 2 or first_anchor_start <= previous_end + 8.0 or first_anchor_start > 62.0:
            idx = section_end
            continue

        shifted = 0
        for source_index in range(first_anchor, section_end):
            source = lines[source_index]
            if not source.matched or source.start is None or source.end is None:
                continue
            target_index = source_index - skipped
            if target_index < section_start or target_index >= source_index:
                continue
            target = lines[target_index]
            if target.matched and target.start is not None and target.end is not None:
                continue
            target.start = source.start
            target.end = source.end
            target.matched = True
            target.wstart = list(source.wstart or [])
            target.wend = list(source.wend or [])

            source.matched = False
            source.start = None
            source.end = None
            source.wstart = []
            source.wend = []
            shifted += 1

        if shifted:
            report.append(
                f"INFO: Lueckenhafter ASR-Abschnittsstart: {shifted} Anker im Abschnitt "
                f"{line.section_label or line.section_type} um {skipped} Lyrics-Zeile(n) nach vorne korrigiert."
            )

        idx = section_end
    return report


def _script_rebalance_ambiguous_intro_prefix(lines: list[LyricLine], hyp_first_start: float | None) -> list[str]:
    """Korrigiert einen ambigen ersten Intro-ASR-Block.

    Manche ASR-Ausgaben erkennen den ersten hörbaren Intro-Call als Anfang der
    nächsten Intro-Zeile. Wenn davor eine kurze ungematchte Intro-Zeile steht
    und der erste gematchte Intro-Block ungewöhnlich lang ist, darf diese kurze
    Zeile nicht vor den ersten hörbaren Einsatz geschätzt werden. Stattdessen
    beginnt sie am ersten ASR-Start; die folgende lange Intro-Zeile nutzt das
    freie Fenster bis vor den ersten Nicht-Intro-Abschnitt.
    """
    if len(lines) < 3 or hyp_first_start is None:
        return []
    first = lines[0]
    second = lines[1]
    first_section = str(first.section_type or "").lower()
    second_section = str(second.section_type or "").lower()
    if first_section not in {"intro", "instrumental_intro"} or second_section not in {"intro", "instrumental_intro"}:
        return []
    if first.matched or not second.matched or second.start is None or second.end is None:
        return []
    second_start = float(second.start)
    second_end = float(second.end)
    if abs(second_start - float(hyp_first_start)) > 0.35:
        return []
    if second_end - second_start < 4.0:
        return []

    next_section_index: int | None = None
    for idx in range(2, len(lines)):
        section = str(lines[idx].section_type or "").lower()
        if section and section not in {"intro", "instrumental_intro"}:
            next_section_index = idx
            break
    if next_section_index is None:
        return []
    next_start = float(lines[next_section_index].start or 0.0)
    if next_start <= second_end + 6.0:
        return []

    first_words = max(1, len(first.words or first.display.split()))
    first_duration = max(1.8, min(3.2, 0.75 + first_words * 0.95))
    first_start = float(hyp_first_start)
    first_end = min(next_start - 0.65, first_start + first_duration)
    second_start_new = first_end + 0.04
    second_end_new = max(second_end, min(next_start - 0.55, next_start - 8.0))
    if second_end_new <= second_start_new + 1.2:
        return []

    first.start = round(first_start, 3)
    first.end = round(first_end, 3)
    first.wstart = None
    first.wend = None
    second.start = round(second_start_new, 3)
    second.end = round(second_end_new, 3)
    second.wstart = None
    second.wend = None
    return [
        f"INFO: Ambiger Intro-Start korrigiert: erste Intro-Zeile auf {first_start:.1f}s gesetzt, "
        f"folgende Intro-Zeile bis {second_end_new:.1f}s verlaengert."
    ]


def _script_insert_plausible_intro_repeated_lines(lines: list[LyricLine], hyp: list[HypWord]) -> list[str]:
    """Fuegt plausibel wiederholte Intro-Zeilen ein, wenn Suno sie zusaetzlich singt.

    Diese Sicherung greift genau fuer den Praxisfall, in dem der offizielle
    Songtext eine Intro-Zeile nur einmal enthaelt, Suno sie vor dem Verse aber
    ein zweites Mal singt. Manche ASR-Modelle geben die Wiederholung nicht als
    sauberes zweites Volltreffer-Fenster aus; dann wuerde die SRT trotz
    Neugenerierung nur eine lange oder einzelne Intro-Zeile zeigen. Die Funktion
    arbeitet konservativ und nur im fruehen Intro vor dem ersten Nicht-Intro-
    Abschnitt. Es werden keine APIs, DB-Schemata oder Taskablaeufe geaendert.
    """
    report: list[str] = []
    if not lines:
        return report

    i = 0
    while i < min(len(lines) - 1, 8):
        line = lines[i]
        next_line = lines[i + 1]
        section_type = str(line.section_type or "").lower()
        next_section_type = str(next_line.section_type or "").lower()
        if section_type not in {"intro", "instrumental_intro"}:
            i += 1
            continue
        if not next_line.starts_section or next_section_type in {"intro", "instrumental_intro"}:
            i += 1
            continue
        if i > 0:
            prev_tokens = _effective_line_tokens(lines[i - 1].display)
            if prev_tokens == _effective_line_tokens(line.display):
                i += 1
                continue
            # Wenn dieselbe Intro-Zeile im aktuellen Intro-Block bereits frueher
            # vorkommt, wurde eine echte oder effektive Wiederholung schon
            # materialisiert. Dann darf diese Fallback-Heuristik nicht noch ein
            # weiteres synthetisches Duplikat am Ende der Intro-Luecke erzeugen.
            if any(
                str(lines[probe].section_type or "").lower() == section_type
                and _effective_line_similarity(lines[probe].display, line.display) >= 0.92
                for probe in range(0, i)
            ):
                i += 1
                continue
        tokens = line.match_tokens or _effective_line_tokens(line.display)
        if len(tokens) < 3 or len(tokens) > 9:
            i += 1
            continue
        if i + 1 < len(lines) and _effective_line_tokens(next_line.display) == _effective_line_tokens(line.display):
            i += 1
            continue

        start = float(line.start or 0.0)
        end = float(line.end or start)
        next_start = float(next_line.start or 0.0)
        if start <= 0.0 or next_start <= start:
            i += 1
            continue
        if start > 18.0 or next_start > 48.0:
            i += 1
            continue

        # Wenn direkt nach der Introzeile bereits Worte des kommenden Abschnitts
        # auftauchen, handelt es sich nicht um eine wiederholte Introzeile,
        # sondern um von Suno vorgezogenen Verse-/Hook-Text. Diesen Fall hat die
        # fruehere Abschnittsanker-Logik bereits speziell abgesichert.
        next_tokens = next_line.match_tokens or _effective_line_tokens(next_line.display)
        early_next_section = _script_find_time_occurrence(
            next_tokens,
            hyp,
            start_time=end + 0.01,
            end_time=min(next_start - 0.10, end + 5.0),
        )
        if early_next_section is not None:
            i += 1
            continue

        single_duration = _script_estimated_repeat_line_duration(line)
        duration = max(0.0, end - start)
        gap_after = max(0.0, next_start - end)
        intro_window = next_start - start
        # Ohne ausreichend großes Intro-Fenster soll keine synthetische
        # Wiederholung entstehen. Kurze normale Pausen vor dem Verse bleiben frei.
        if intro_window < max(6.2, single_duration * 2.25):
            i += 1
            continue

        occurrence = _script_find_time_occurrence(
            tokens,
            hyp,
            start_time=min(next_start - 0.2, max(end + 0.18, start + single_duration * 0.85)),
            end_time=max(start + single_duration, next_start - 0.15),
        )

        observed_word_span = _script_observed_word_span_seconds(line)
        observed_span = observed_word_span if observed_word_span is not None else duration
        compact_first_take = observed_span <= min(single_duration * 0.85, 2.35)
        has_large_gap = gap_after >= single_duration + 1.25
        has_repeat_hint = occurrence is not None
        synthetic_gap_repeat_allowed = (
            has_large_gap
            and intro_window >= single_duration * 3.1
            and compact_first_take
        )
        if not (has_repeat_hint or synthetic_gap_repeat_allowed):
            i += 1
            continue

        if occurrence:
            duplicate_start = float(occurrence.get("start") or 0.0)
            duplicate_end_hint = float(occurrence.get("end") or duplicate_start)
        else:
            # Wenn Groq/Whisper in einer langen Intro-Luecke keine verwertbaren
            # Worte fuer die Wiederholung liefert, darf die Wiederholung nicht
            # direkt nach dem ersten kurzen Treffer erscheinen. In diesem Fall
            # liegt Sunos zusaetzliche Intro-Zeile typischerweise kurz vor dem
            # eigentlichen Abschnittsstart. Kurze Luecken behalten das alte
            # direkte Verhalten.
            if gap_after >= max(5.5, single_duration * 2.0) and intro_window >= single_duration * 3.6:
                duplicate_start = max(end + 0.55, next_start - single_duration * 2.0)
            else:
                duplicate_start = min(next_start - single_duration - 0.08, end + 0.55)
            duplicate_end_hint = duplicate_start + single_duration

        if duplicate_start <= start + 0.65 or duplicate_start >= next_start - 0.65:
            i += 1
            continue

        first_end = min(end, max(start + 0.75, min(duplicate_start - 0.05, start + single_duration)))
        duplicate_start = max(first_end + 0.08, duplicate_start)
        duplicate_end = min(next_start - 0.05, max(duplicate_end_hint + 0.35, duplicate_start + min(single_duration, 2.8)))
        if duplicate_end <= duplicate_start + 0.45:
            i += 1
            continue

        line.end = round(first_end, 3)
        line.wstart = None
        line.wend = None
        duplicate = LyricLine(
            index=line.index,
            display=line.display,
            words=list(line.words or []),
            tok_counts=list(line.tok_counts or []),
            match_tokens=list(line.match_tokens or []),
            weight=float(line.weight or 1.0),
            matched=bool(has_repeat_hint),
            start=round(duplicate_start, 3),
            end=round(duplicate_end, 3),
            wstart=None,
            wend=None,
            section_label=line.section_label,
            section_type=line.section_type,
            starts_section=False,
        )
        lines.insert(i + 1, duplicate)
        reflow_report = _script_reflow_section_after_intro_repeat(lines, i + 1)
        report.append(
            f"INFO: Plausible Suno-Intro-Wiederholung als effektive SRT-Zeile ergaenzt: "
            f"{line.display!r} bei {duplicate_start:.1f}s vor Abschnitt {next_line.section_label or next_line.section_type}."
        )
        if reflow_report:
            report.append(reflow_report)
        i += 2
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
        if existing_start and existing_end and len(existing_start) == len(words) and len(existing_end) == len(words):
            # Exakte ASR-Wortanker uebernehmen; nur fehlende Woerter (None)
            # werden gewichtet zwischen den umliegenden Ankern interpoliert.
            weights = [_script_word_weight(word) for word in words]
            filled_start: list[float | None] = [
                float(value) if value is not None else None for value in existing_start
            ]
            filled_end: list[float | None] = [
                float(value) if value is not None else None for value in existing_end
            ]
            count = len(words)
            idx = 0
            while idx < count:
                if filled_start[idx] is not None and filled_end[idx] is not None:
                    idx += 1
                    continue
                gap_start = idx
                while idx < count and (filled_start[idx] is None or filled_end[idx] is None):
                    idx += 1
                gap_end = idx  # exklusiv
                left_time = float(filled_end[gap_start - 1]) if gap_start > 0 and filled_end[gap_start - 1] is not None else start
                right_time = float(filled_start[gap_end]) if gap_end < count and filled_start[gap_end] is not None else end
                right_time = max(right_time, left_time)
                gap_weights = weights[gap_start:gap_end]
                total_gap_weight = sum(gap_weights) or 1.0
                span = right_time - left_time
                cursor = left_time
                for pos, weight in zip(range(gap_start, gap_end), gap_weights):
                    part = span * (weight / total_gap_weight)
                    filled_start[pos] = cursor
                    filled_end[pos] = cursor + part
                    cursor += part

            clamped_start: list[float] = []
            clamped_end: list[float] = []
            previous = start
            for raw_start, raw_end in zip(filled_start, filled_end):
                ws = min(max(float(raw_start if raw_start is not None else previous), previous), end)
                we = min(max(float(raw_end if raw_end is not None else ws), ws), end)
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


def _extend_srt_segments_to_next_start(segments: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    rows = [dict(segment) for segment in segments or [] if isinstance(segment, dict)]
    rows.sort(key=lambda item: (_seconds(item.get("start"), 0.0), _seconds(item.get("end"), 0.0), int(item.get("index") or 0)))
    changed = 0
    for index, segment in enumerate(rows[:-1]):
        start = _seconds(segment.get("start"), 0.0)
        next_start = _seconds(rows[index + 1].get("start"), start)
        current_end = _seconds(segment.get("end"), start)
        if next_start <= start + 0.05:
            # Fast gleichzeitiger Folgestart: Verlaengern ist hier sinnlos, aber
            # eine bestehende Ueberlappung darf nicht stehen bleiben.
            if current_end > next_start:
                segment["end"] = round(next_start if next_start > start else start + 0.02, 3)
                changed += 1
            continue
        if abs(current_end - next_start) <= 0.001:
            continue
        segment["end"] = round(next_start, 3)
        changed += 1
    for index, segment in enumerate(rows, start=1):
        segment["index"] = index
    return rows, changed


def _gapless_srt_text(srt_text: str) -> str:
    segments = parse_srt_text(srt_text or "")
    if not segments:
        return srt_text
    gapless, _ = _extend_srt_segments_to_next_start(segments)
    return export_srt_text(gapless)


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
    return _gapless_srt_text(_script_to_portrait_srt(lines, max_chars=max_chars, min_dur=min_dur))


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
SRT_VISIBLE_WORD_TOKEN_RE = re.compile(r"(?<![\wÄÖÜäöüßẞ])([A-Za-zÄÖÜäöüßẞ]+(?:-[A-Za-zÄÖÜäöüßẞ]+)*)(?![\wÄÖÜäöüßẞ])")
SRT_VISIBLE_VOWEL_STRETCH_RE = re.compile(r"([aeiouyäöüAEIOUYÄÖÜ])\1{2,}")
SRT_VISIBLE_CONSONANT_LETTER_RE = re.compile(r"[bcdfghjklmnpqrstvwxyzßBCDFGHJKLMNPQRSTVWXYZẞ]")
SRT_VISIBLE_ADLIB_WORDS = {
    "ah", "aha", "ha", "hah", "oh", "ooh", "uh", "uhh", "eh", "ey", "eyy", "yeah",
    "yo", "ya", "yah", "mh", "mhm", "hmm", "mmm", "na", "la", "lalala",
}
SRT_VISIBLE_HYPHEN_SPACE_PREFIXES = {"zu"}


def _looks_like_srt_vocal_adlib_token(token: str) -> bool:
    compact = re.sub(r"[^A-Za-zÄÖÜäöüßẞ]", "", str(token or "")).lower()
    if not compact:
        return False
    simplified = re.sub(r"([a-zäöüß])\1+", r"\1", compact)
    return simplified in SRT_VISIBLE_ADLIB_WORDS


def _record_srt_stretch_normalization(original: str, replacement: str, normalized: list[str] | None) -> None:
    if normalized is not None and original != replacement:
        normalized.append(f"{original}->{replacement}")


def _normalize_srt_visible_hyphen_word(token: str) -> str:
    """Glättet offensichtliche Suno-Singhilfen in normalen Wörtern.

    ``zu-gehn`` ist für die SRT besser als zwei Wörter lesbar, während
    künstliche Trennungen innerhalb eines Wortes wie ``Fle-hen`` wieder
    zusammengeführt werden. Die Regel ist eng gehalten, damit echte
    Bindestrichbegriffe nicht pauschal zerstört werden.
    """
    if "-" not in token:
        return token
    parts = [part for part in token.split("-") if part]
    if len(parts) != 2:
        return token
    left, right = parts
    if left.lower() in SRT_VISIBLE_HYPHEN_SPACE_PREFIXES and len(right) >= 3:
        return f"{left} {right}"
    if len(left) >= 3 and len(right) >= 2:
        return f"{left}{right}"
    return token


def _normalize_srt_visible_word_stretches(text: str, normalized: list[str] | None = None) -> str:
    """Normalisiert offensichtliche SRT-Anzeige-Artefakte in normalen Wörtern.

    Die Funktion bleibt bewusst konservativ:
    - Konsonanten-Stretchings werden wie bisher gekürzt, z. B. ``Nachttt`` -> ``Nacht``.
    - Vokal-Stretchings werden nur in klaren normalen Wörtern mit mindestens
      zwei Konsonanten gekürzt, z. B. ``Skalinooo`` -> ``Skalino`` oder
      ``entlaaang`` -> ``entlang``.
    - Kurze Adlibs/Ausrufe wie ``ahaaa``, ``ohhh`` oder ``yeahhh`` bleiben
      erhalten, weil sie für den gesungenen Ausdruck relevant sein können.
    - Suno-Längungsbindestriche in normalen Wörtern werden geglättet, z. B.
      ``zu-gehn`` -> ``zu gehn`` und ``Fle-hen`` -> ``Flehen``.
    """
    value = str(text or "")
    if not value:
        return ""

    def normalize_token(match: re.Match[str]) -> str:
        token = match.group(1)
        original = token
        if _looks_like_srt_vocal_adlib_token(token):
            return token

        token = _normalize_srt_visible_hyphen_word(token)

        token = SRT_VISIBLE_CONSONANT_STRETCH_RE.sub(lambda consonant_match: consonant_match.group(1), token)

        compact_for_adlib = re.sub(r"[^A-Za-zÄÖÜäöüßẞ]", "", token).lower()
        consonant_count = len(SRT_VISIBLE_CONSONANT_LETTER_RE.findall(token))
        should_normalize_vowels = (
            len(compact_for_adlib) >= 5
            and consonant_count >= 2
            and not _looks_like_srt_vocal_adlib_token(token)
        )
        if should_normalize_vowels:
            token = SRT_VISIBLE_VOWEL_STRETCH_RE.sub(lambda vowel_match: vowel_match.group(1), token)

        _record_srt_stretch_normalization(original, token, normalized)
        return token

    return SRT_VISIBLE_WORD_TOKEN_RE.sub(normalize_token, value)

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
    # sollen niemals als Untertitelzeile erscheinen. Die zentrale
    # Abschnittserkennung aus waveform_service bleibt hier die führende Quelle,
    # damit SRT-Cleanup und Timeline-/Waveform-Segmente dieselben Tags verstehen.
    if extract_structure_marker(text):
        return True
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
    if extract_structure_marker(text):
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
        "Offensichtliche Wiederholungs-/Tipp-Artefakte und Suno-Längungsschreibweisen in normalen Wörtern darfst du konservativ normalisieren, "
        "z. B. 'Ein teil der Nachttt' -> 'Ein teil der Nacht', 'Skalinooo' -> 'Skalino', 'Weeeg entlaaang' -> 'Weg entlang' und 'Fle-hen' -> 'Flehen'. "
        "Lass künstlerische Vokal-Adlibs und bewusst gedehnte Ausrufe wie 'ahaaa', 'ohhh' oder 'yeahhh' unverändert, wenn sie nicht klar ein normales Wort beschädigen."
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
            "Offensichtliche beschädigte Wort-Stretchings und Suno-Längungsschreibweisen konservativ normalisieren: Nachttt -> Nacht, Skalinooo -> Skalino, Weeeg entlaaang -> Weg entlang, Fle-hen -> Flehen, zu-gehn -> zu gehn.",
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
        "srt_alignment_engine": (
            str(value.get("srt_alignment_engine") or "heuristic").strip().lower()
            if str(value.get("srt_alignment_engine") or "heuristic").strip().lower() in {"heuristic", "forced_alignment"}
            else "heuristic"
        ),
        "srt_quality_gate_enabled": bool(value.get("srt_quality_gate_enabled", False)),
        "srt_quality_gate_min_score": max(0.3, min(0.95, float(value.get("srt_quality_gate_min_score", 0.7) or 0.7))),
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


def align_lyrics_to_timeline_bundle(lyrics: str, asr: AsrResult, duration_seconds: float, source_lyrics: str | None = None) -> dict[str, Any]:
    """Exaktes Lyrics-Alignment nach dem funktionierenden Referenzskript.

    Liefert zusätzlich eine `*.half.srt`-Variante für mobile Geräte.
    Die normale SRT nutzt Lyrics-Zeilen als Source of Truth; die Half-SRT splittet
    dieselben Zeilen wortbasiert mit Zeitinterpolation wie im CLI-Skript.
    """
    # Einheitlicher Hyp-Aufbau für ALLE Backends: Groq/WhisperX liefern bereits
    # expandierte Einzel-Tokens, OpenAI/Voxtral rohe Wörter. Das frühere
    # `tokenize(word)[0]` hat bei rohen Mehrfach-Token-Wörtern (Bindestriche,
    # zusammengezogene Erkennungen) alle Folge-Tokens verworfen und damit Anker
    # verloren. `_script_expand_word` + `_script_finalize_hyp` sind für bereits
    # expandierte Tokens idempotent und verteilen bei rohen Wörtern die Zeit
    # korrekt auf alle Tokens.
    raw_hyp_tokens: list[tuple[str, float | None, float | None]] = []
    for word in asr.words:
        if word.end < word.start:
            continue
        raw_hyp_tokens += _script_expand_word(str(word.word or ""), word.start, word.end)
    hyp = _script_finalize_hyp(raw_hyp_tokens)
    if not hyp:
        raise HTTPException(status_code=422, detail="ASR lieferte keine verwertbaren Wort-Timestamps.")

    effective_lyrics, effective_source_lyrics, effective_report, effective_info = _build_effective_srt_lyrics_from_asr(lyrics, source_lyrics, hyp)
    lines = _script_parse_lyrics_text(effective_lyrics, skip_prefixes=("#", "/", ";"), skip_parens=False, source_lyrics=effective_source_lyrics or source_lyrics)
    if not lines:
        raise HTTPException(status_code=422, detail="Der Songtext enthält keine sichtbaren Zeilen.")

    report = list(effective_report)
    word_source = str(asr.raw.get("songstudio_word_source") or "") if isinstance(asr.raw, dict) else ""
    if word_source == "segment_text_distributed":
        report.append(
            "WARN: Provider lieferte KEINE Wort-Timestamps (Datenschema-Abweichung); "
            "Wortzeiten wurden gleichmaessig ueber Segmentfenster verteilt. "
            "Zeitstempel koennen dadurch mehrere Sekunden abweichen -> Backend/Modell mit "
            "Word-Timestamps verwenden (z. B. whisper-large-v3 statt Turbo-/Segment-only-Modell)."
        )
    elif word_source == "none":
        report.append("WARN: Provider-Antwort enthielt weder Wort- noch Segment-Timestamps.")
    report.extend(_script_align_lines(lines, hyp, warn_factor=0.6))
    _script_enforce_monotonic(lines, min_dur=0.6, gap=0.04)
    squeezed_repeat_report = _script_drop_squeezed_unmatched_repeats(lines)
    if squeezed_repeat_report:
        report.extend(squeezed_repeat_report)
        _script_enforce_monotonic(lines, min_dur=0.6, gap=0.04)
    timing_repeat_report = _script_insert_repeated_lines_from_timing(lines, hyp)
    if timing_repeat_report:
        report.extend(timing_repeat_report)
        _script_enforce_monotonic(lines, min_dur=0.6, gap=0.04)
    intro_repeat_report = _script_insert_plausible_intro_repeated_lines(lines, hyp)
    if intro_repeat_report:
        report.extend(intro_repeat_report)
        _script_enforce_monotonic(lines, min_dur=0.6, gap=0.04)
    intro_block_prefix_report = _script_insert_missing_intro_block_prefix_repeats(lines)
    if intro_block_prefix_report:
        report.extend(intro_block_prefix_report)
        _script_enforce_monotonic(lines, min_dur=0.6, gap=0.04)
    repeated_block_report = _script_repair_explicit_repeated_section_blocks(lines, hyp)
    if repeated_block_report:
        report.extend(repeated_block_report)
        _script_enforce_monotonic(lines, min_dur=0.6, gap=0.04)
    _script_compute_word_times(lines)
    return _finalize_alignment_bundle(lines, report, effective_info, alignment_method="lyrics_align_srt_reference")


def _finalize_alignment_bundle(
    lines: list[LyricLine],
    report: list[str],
    effective_info: dict[str, Any],
    *,
    alignment_method: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
            "alignment_method": alignment_method,
        })

    if report:
        for segment in segments:
            segment.setdefault("alignment_report", report)

    segments, gapless_changed = _extend_srt_segments_to_next_start(segments)
    if gapless_changed:
        report.append(f"INFO: Karaoke-SRT: {gapless_changed} Segment-Endzeiten bis zur naechsten Zeile verlaengert.")
    segments, _ = _extend_srt_segments_to_next_start(segments)
    # Quality VOR der Normalisierung berechnen: externe Normalizer duerfen
    # Zusatzfelder wie `matched` verwerfen, ohne den Score zu zerstoeren.
    alignment_quality = compute_alignment_quality({"segments": segments, "alignment_report": report})
    normalized_segments = validate_and_normalize_srt_segments(segments)
    half_srt_text = _gapless_srt_text(_script_to_portrait_srt(lines, max_chars=22, min_dur=0.6))
    bundle = {
        "segments": normalized_segments,
        "half_srt_text": half_srt_text,
        "alignment_report": report,
        "half_max_chars": 22,
        "effective_srt_lyrics": effective_info,
    }
    if extra:
        bundle.update(extra)
    bundle["alignment_quality"] = alignment_quality
    return bundle


def compute_alignment_quality(bundle: dict[str, Any]) -> dict[str, Any]:
    """Qualitaets-Score eines Alignment-Laufs fuer Golden-Set und Quality-Gate.

    Kombiniert Anker-Dichte (gematchte Zeilen), Schaetzanteil und WARN-Signale
    zu einem Score in [0, 1]. Deterministisch und rein aus dem Bundle ableitbar.
    """
    segments = bundle.get("segments") or []
    report = bundle.get("alignment_report") or []
    total = len(segments)
    matched = sum(1 for segment in segments if segment.get("matched"))
    matched_ratio = matched / total if total else 0.0
    estimated_lines = total - matched
    warn_lines = [line for line in report if str(line).startswith("WARN")]
    squeeze_warns = sum(1 for line in warn_lines if "gequetscht" in str(line))
    word_source_degraded = any("KEINE Wort-Timestamps" in str(line) for line in warn_lines)

    score = matched_ratio
    score -= 0.06 * min(len(warn_lines), 5)
    score -= 0.05 * min(squeeze_warns, 4)
    if word_source_degraded:
        score -= 0.25
    score = max(0.0, min(1.0, round(score, 3)))
    return {
        "score": score,
        "matched_ratio": round(matched_ratio, 3),
        "matched_lines": matched,
        "estimated_lines": estimated_lines,
        "total_lines": total,
        "warn_count": len(warn_lines),
        "squeeze_warn_count": squeeze_warns,
        "word_source_degraded": word_source_degraded,
    }


def align_lyrics_with_forced_alignment_bundle(
    lyrics: str,
    asr: AsrResult,
    audio_path: Path,
    duration_seconds: float,
    source_lyrics: str | None = None,
) -> dict[str, Any]:
    """Alternative Alignment-Engine: CTC-Forced-Alignment (MMS) statt Heuristik.

    Der Songtext ist bekannt; Forced Alignment richtet die bekannten Zeilen
    direkt auf das Audio aus (Wortgrenzen ~20-50ms), ohne dass Woerter vom ASR
    korrekt erkannt werden muessen. Das Groq/ASR-Transkript wird weiterhin fuer
    die Effective-Lyrics-Erkennung (Suno-Wiederholungen) genutzt. Der komplette
    Heuristik-Turm (tail_spread, gap_protection, Interpolation) entfaellt fuer
    gematchte Zeilen. Faellt bei fehlender torch/torchaudio-Installation oder
    Alignment-Fehlern kontrolliert auf die Heuristik-Engine zurueck (Aufrufer).
    """
    from app.services.forced_alignment_service import force_align_tokens

    raw_hyp_tokens: list[tuple[str, float | None, float | None]] = []
    for word in asr.words:
        if word.end < word.start:
            continue
        raw_hyp_tokens += _script_expand_word(str(word.word or ""), word.start, word.end)
    hyp = _script_finalize_hyp(raw_hyp_tokens)

    effective_lyrics, effective_source_lyrics, effective_report, effective_info = _build_effective_srt_lyrics_from_asr(lyrics, source_lyrics, hyp)
    lines = _script_parse_lyrics_text(effective_lyrics, skip_prefixes=("#", "/", ";"), skip_parens=False, source_lyrics=effective_source_lyrics or source_lyrics)
    if not lines:
        raise HTTPException(status_code=422, detail="Der Songtext enthält keine sichtbaren Zeilen.")

    report = list(effective_report)
    flat_tokens: list[str] = []
    token_line_index: list[int] = []
    for line_index, line in enumerate(lines):
        for token in line.match_tokens:
            flat_tokens.append(token)
            token_line_index.append(line_index)

    spans = force_align_tokens(audio_path, flat_tokens)
    if len(spans) != len(flat_tokens):
        raise RuntimeError(
            f"Forced Alignment lieferte {len(spans)} Spans fuer {len(flat_tokens)} Tokens."
        )

    aligned_tokens = 0
    low_confidence_tokens = 0
    for line_index, line in enumerate(lines):
        line_positions = [i for i in range(len(flat_tokens)) if token_line_index[i] == line_index]
        line_spans = [spans[i] for i in line_positions]
        usable = [span for span in line_spans if span is not None and span.end > span.start]
        if not usable:
            continue
        line.start = round(min(span.start for span in usable), 3)
        line.end = round(max(span.end for span in usable), 3)
        line.matched = True
        aligned_tokens += len(usable)
        low_confidence_tokens += sum(1 for span in usable if span.score < 0.20)
        word_starts: list[float | None] = []
        word_ends: list[float | None] = []
        cursor = 0
        for count in line.tok_counts:
            slice_spans = [line_spans[cursor + k] for k in range(count) if cursor + k < len(line_spans)]
            slice_usable = [span for span in slice_spans if span is not None and span.end > span.start]
            word_starts.append(min(span.start for span in slice_usable) if slice_usable else None)
            word_ends.append(max(span.end for span in slice_usable) if slice_usable else None)
            cursor += count
        if len(word_starts) == len(line.words) and any(value is not None for value in word_starts):
            line.wstart = word_starts  # type: ignore[assignment]
            line.wend = word_ends  # type: ignore[assignment]

    coverage = aligned_tokens / max(1, len(flat_tokens))
    report.append(
        f"INFO: Forced Alignment (MMS): {aligned_tokens}/{len(flat_tokens)} Tokens ausgerichtet "
        f"({coverage:.0%}), {low_confidence_tokens} mit niedriger Konfidenz."
    )
    if coverage < 0.55:
        raise RuntimeError(
            f"Forced Alignment deckte nur {coverage:.0%} der Tokens ab; Heuristik-Fallback wird verwendet."
        )

    _script_enforce_monotonic(lines, min_dur=0.6, gap=0.04)
    squeezed_repeat_report = _script_drop_squeezed_unmatched_repeats(lines)
    if squeezed_repeat_report:
        report.extend(squeezed_repeat_report)
        _script_enforce_monotonic(lines, min_dur=0.6, gap=0.04)
    _script_resolve_timeline(lines, warn_factor=0.6, hyp_first_start=None, hyp=hyp)
    _script_enforce_monotonic(lines, min_dur=0.6, gap=0.04)
    _script_compute_word_times(lines)
    return _finalize_alignment_bundle(
        lines,
        report,
        effective_info,
        alignment_method="forced_alignment_mms",
        extra={"engine": "forced_alignment"},
    )


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


def _sanitize_transcription_only_segments(
    segments: list[dict[str, Any]],
    *,
    min_duration: float = 0.6,
    merge_gap: float = 0.45,
    max_merged_duration: float = 9.0,
) -> list[dict[str, Any]]:
    """Bereinigt rohe ASR-Segmentgrenzen fuer den Transcription-only-Modus.

    Ursache der Editor-Faelle "Segment endet 7,02s / naechstes startet 7,00s"
    und "Segment nur 0,3s sichtbar": Whisper-Segmentgrenzen werden 1:1
    uebernommen; sie ueberlappen bei Musik regelmaessig um 10-50ms und liefern
    Mini-Segmente. Der Lyrics-Pfad normalisiert das ueber enforce_monotonic --
    dieser Pfad hatte keine entsprechende Stufe.
      1. Sortierung nach Startzeit
      2. Mini-Segmente werden mit dem zeitlich naechsten Nachbarn zusammengefuehrt
      3. Ueberlappungen werden geklemmt (Ende <= Folgestart), Reihenfolge monoton
      4. Zu kurze Segmente werden in vorhandene Luecken auf Mindestdauer gestreckt
    """
    rows = [dict(segment) for segment in segments or [] if str(segment.get("text") or "").strip()]
    rows.sort(key=lambda item: (_seconds(item.get("start"), 0.0), _seconds(item.get("end"), 0.0)))
    if not rows:
        return []

    merged: list[dict[str, Any]] = []
    index = 0
    while index < len(rows):
        segment = dict(rows[index])
        start = _seconds(segment.get("start"), 0.0)
        end = max(start, _seconds(segment.get("end"), start))
        duration = end - start
        if duration < min_duration:
            prev = merged[-1] if merged else None
            nxt = rows[index + 1] if index + 1 < len(rows) else None
            prev_gap = start - _seconds(prev.get("end"), start) if prev else None
            next_gap = (_seconds(nxt.get("start"), end) - end) if nxt else None
            prev_ok = (
                prev is not None
                and prev_gap is not None
                and prev_gap <= merge_gap
                and (end - _seconds(prev.get("start"), start)) <= max_merged_duration
            )
            next_ok = (
                nxt is not None
                and next_gap is not None
                and next_gap <= merge_gap
                and (_seconds(nxt.get("end"), end) - start) <= max_merged_duration
            )
            if prev_ok and (not next_ok or prev_gap <= next_gap):
                prev["text"] = f"{str(prev.get('text') or '').strip()} {str(segment.get('text') or '').strip()}".strip()
                prev["end"] = round(max(_seconds(prev.get("end"), end), end), 3)
                index += 1
                continue
            if next_ok:
                follower = dict(nxt)
                follower["text"] = f"{str(segment.get('text') or '').strip()} {str(follower.get('text') or '').strip()}".strip()
                follower["start"] = round(min(start, _seconds(follower.get("start"), start)), 3)
                rows[index + 1] = follower
                index += 1
                continue
        merged.append(segment)
        index += 1

    previous_end = 0.0
    for position, segment in enumerate(merged):
        start = max(previous_end, _seconds(segment.get("start"), previous_end))
        end = max(start + 0.05, _seconds(segment.get("end"), start))
        next_start = _seconds(merged[position + 1].get("start"), end) if position + 1 < len(merged) else None
        if next_start is not None and end > next_start:
            end = max(start + 0.05, next_start)
        if end - start < min_duration:
            limit = next_start if next_start is not None else start + min_duration
            end = min(max(end, start + min_duration), max(limit, start + 0.05))
        segment["start"] = round(start, 3)
        segment["end"] = round(end, 3)
        segment["index"] = position + 1
        previous_end = segment["end"]
    return merged


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

    segments = _sanitize_transcription_only_segments(segments)
    segments, _ = _extend_srt_segments_to_next_start(segments)
    alignment_quality = compute_alignment_quality({"segments": segments, "alignment_report": []})
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
        "alignment_quality": alignment_quality,
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
    raw["songstudio_word_source"] = _detect_asr_word_source(raw)
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
    raw["songstudio_word_source"] = _detect_asr_word_source(raw)
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


def _detect_asr_word_source(payload: Any) -> str:
    """Klassifiziert, woher die Wortzeiten der Provider-Antwort stammen.

    Ursachen-Fix fuer stille Degradation: Liefert die API keine echten
    Word-Timestamps (Datenschema-Abweichung, Modell ohne Wort-Support), werden
    Woerter bisher stillschweigend gleichmaessig ueber die Segmentfenster
    verteilt. Die SRT wirkt dann frueh im Song sekundenweise versetzt und erst
    bei dichten Segmenten synchron. Diese Klassifikation macht den Fallback
    im Debug-Log und Alignment-Report sichtbar.
    """
    if not isinstance(payload, dict):
        return "none"
    direct_words = payload.get("words")
    if isinstance(direct_words, list) and any(
        isinstance(word, dict) and word.get("start") is not None and word.get("end") is not None
        for word in direct_words
    ):
        return "word_timestamps"
    segments = payload.get("segments")
    if isinstance(segments, list):
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            words = segment.get("words")
            if isinstance(words, list) and any(
                isinstance(word, dict) and word.get("start") is not None and word.get("end") is not None
                for word in words
            ):
                return "segment_word_timestamps"
        if any(isinstance(segment, dict) and str(segment.get("text") or "").strip() for segment in segments):
            return "segment_text_distributed"
    return "none"


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
    raw["songstudio_word_source"] = _detect_asr_word_source(raw)
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
    raw["songstudio_word_source"] = _detect_asr_word_source(raw)
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


def _srt_debug_payload(data: dict[str, Any] | None = None) -> dict[str, Any]:
    return {str(key): _json_safe_preview(value, max_len=360) for key, value in (data or {}).items()}


def _append_srt_debug_event(
    db: Session | None,
    task: SunoTask | None,
    asset: AudioAsset | None,
    event: str,
    *,
    detail: str | None = None,
    data: dict[str, Any] | None = None,
    commit: bool = True,
) -> None:
    """Schreibt kompakte Debug-Entscheidungen zur SRT-Erzeugung.

    Der normale `steps_log` bleibt fuer UI-Fortschritt reserviert. `debug_log`
    dokumentiert die technischen Entscheidungen: KI-Cleanup, Provider/ASR,
    Alignment-Reports und SRT-Heuristiken. Keine kompletten Lyrics/Rohantworten
    speichern; dafuer existiert die separate AI_STORE_RAW_RESPONSES-Logik.
    """
    safe_data = _srt_debug_payload(data)
    asset_id = asset.id if asset is not None else None
    task_id = task.id if task is not None else None
    logger.info(
        "SRT debug event=%s asset_id=%s task_id=%s detail=%s data=%s",
        event,
        asset_id,
        task_id,
        detail or "",
        safe_data,
    )
    if task is None or db is None:
        return

    now = utc_now_naive()
    entry = {
        "at": now.isoformat(),
        "event": event,
        "detail": detail or event,
        **safe_data,
    }
    payload = dict(task.response_payload or {})
    debug_log = payload.get("debug_log") if isinstance(payload.get("debug_log"), list) else []
    debug_log.append(entry)
    payload["debug_log"] = debug_log[-SRT_DEBUG_LOG_LIMIT:]
    payload["last_debug_event"] = entry
    task.response_payload = payload
    task.heartbeat_at = now
    db.add(task)
    if commit:
        db.commit()
        try:
            db.refresh(task)
        except Exception:
            pass


def _alignment_report_debug_summary(report: list[str] | None) -> dict[str, Any]:
    rows = [str(item or "") for item in (report or []) if str(item or "").strip()]
    warn_rows = [item for item in rows if item.upper().startswith("WARN")]
    info_rows = [item for item in rows if item.upper().startswith("INFO")]
    repeat_rows = [
        item for item in rows
        if any(marker in item.lower() for marker in ("wiederholung", "repeated", "effektive srt-lyrics", "intro-wiederholung"))
    ]
    return {
        "total": len(rows),
        "info_count": len(info_rows),
        "warn_count": len(warn_rows),
        "repeat_decisions": repeat_rows[:8],
        "warnings": warn_rows[:8],
        "first_entries": rows[:8],
    }


def _segment_debug_preview(segments: list[dict[str, Any]] | None, limit: int = 8) -> list[dict[str, Any]]:
    preview: list[dict[str, Any]] = []
    for segment in (segments or [])[:limit]:
        preview.append({
            "index": segment.get("index"),
            "start": segment.get("start"),
            "end": segment.get("end"),
            "text": _json_safe_preview(segment.get("text"), max_len=90),
        })
    return preview


def _positive_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _last_asr_word_end(asr: AsrResult | None) -> float | None:
    if asr is None or not asr.words:
        return None
    ends = [_positive_float(getattr(word, "end", None)) for word in asr.words]
    valid = [end for end in ends if end is not None]
    return max(valid) if valid else None


def _resolve_srt_duration_seconds(asset: AudioAsset | None, file_duration_seconds: float | int | None, asr: AsrResult | None = None) -> dict[str, Any]:
    """Bestimmt eine robuste Dauer fuer SRT-Alignment und Struktursegmente.

    Mutagen kann bei einzelnen Suno-MP3s deutlich falsche Werte liefern. Fuer
    SRT ist die Provider-/DB-Dauer zusammen mit dem letzten ASR-Wort belastbarer
    als ein einzelner kaputter lokaler Header. Offensichtlich abweichende
    Dateidauern werden deshalb dokumentiert, aber nicht als harte Grenze genutzt.
    """
    file_duration = _positive_float(file_duration_seconds)
    asset_duration = _positive_float(getattr(asset, "duration_seconds", None))
    asr_end = _last_asr_word_end(asr)

    trusted = [value for value in (asset_duration, asr_end) if value is not None]
    if trusted:
        anchor = max(trusted)
        tolerance = max(12.0, anchor * 0.12)
        if file_duration is not None and abs(file_duration - anchor) <= tolerance:
            duration = max(anchor, file_duration)
            source = "file_asset_asr_consensus" if asr_end is not None and asset_duration is not None else "file_consensus"
            ignored_file_duration = False
        else:
            duration = anchor
            source = "asset_asr_consensus" if asr_end is not None and asset_duration is not None else ("asset_duration" if asset_duration is not None else "asr_last_word")
            ignored_file_duration = file_duration is not None
    elif file_duration is not None:
        duration = file_duration
        source = "file_duration"
        ignored_file_duration = False
    else:
        duration = 0.0
        source = "unknown"
        ignored_file_duration = False

    return {
        "duration_seconds": round(float(duration), 3),
        "source": source,
        "file_duration_seconds": round(float(file_duration), 3) if file_duration is not None else None,
        "asset_duration_seconds": round(float(asset_duration), 3) if asset_duration is not None else None,
        "asr_last_word_end_seconds": round(float(asr_end), 3) if asr_end is not None else None,
        "ignored_file_duration": ignored_file_duration,
    }


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
            _append_srt_debug_event(
                db,
                srt_task,
                asset,
                f"provider_{event}",
                detail=_groq_progress_detail(event, payload),
                data=payload,
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
                _append_srt_debug_event(
                    db,
                    srt_task,
                    asset,
                    f"provider_{event}",
                    detail=_groq_progress_detail(event, payload),
                    data=payload,
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
        existing_payload = dict(task.response_payload or {})
        debug_log = existing_payload.get("debug_log") if isinstance(existing_payload.get("debug_log"), list) else []
        final_result_payload = result_payload or {
            "audio_asset_id": asset.id,
            "status": status,
            "message": message,
        }
        if isinstance(final_result_payload, dict) and debug_log and "srt_debug_log" not in final_result_payload:
            final_result_payload = {**final_result_payload, "srt_debug_log": debug_log}
        task.status = status
        task.completed_at = now
        task.heartbeat_at = now
        task.error_message = None if status == "SUCCESS" else message
        task.result_payload = final_result_payload
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
    alignment_engine_override: str | None = None,
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
        _append_srt_debug_event(
            db,
            srt_task,
            asset,
            "srt_configuration_resolved",
            detail="SRT-Konfiguration, Lyrics-Quelle und Audioquelle wurden festgelegt.",
            data={
                "backend": backend,
                "configured_language": configured_language,
                "resolved_language": language,
                "has_alignment_lyrics": has_alignment_lyrics,
                "manual_lyrics": bool(manual_lyrics),
                "source_lyrics_chars": len(source_lyrics or ""),
                "clean_lyrics_chars": len(lyrics or ""),
                "srt_ai_cleanup_enabled": bool(admin_settings.get("srt_ai_cleanup_enabled", True)),
                "lyrics_cleanup_method": lyrics_cleanup_info.get("method") if isinstance(lyrics_cleanup_info, dict) else None,
                "lyrics_cleanup_ai_used": bool((lyrics_cleanup_info.get("ai") or {}).get("used")) if isinstance(lyrics_cleanup_info, dict) and isinstance(lyrics_cleanup_info.get("ai"), dict) else False,
                "language_detection": language_info,
                "audio_source": transcription_audio_source,
                "audio_path": str(transcription_audio_path),
            },
        )
        if isinstance(lyrics_cleanup_info, dict):
            deterministic = lyrics_cleanup_info.get("deterministic") if isinstance(lyrics_cleanup_info.get("deterministic"), dict) else {}
            ai_cleanup = lyrics_cleanup_info.get("ai") if isinstance(lyrics_cleanup_info.get("ai"), dict) else {}
            preservation = lyrics_cleanup_info.get("ai_content_preservation") if isinstance(lyrics_cleanup_info.get("ai_content_preservation"), dict) else {}
            _append_srt_debug_event(
                db,
                srt_task,
                asset,
                "lyrics_cleanup_decision",
                detail="Deterministische und optionale KI-Lyrics-Bereinigung ausgewertet.",
                data={
                    "method": lyrics_cleanup_info.get("method"),
                    "source_chars": lyrics_cleanup_info.get("source_chars"),
                    "clean_chars": lyrics_cleanup_info.get("clean_chars"),
                    "deterministic_changed": deterministic.get("changed"),
                    "deterministic_removed_count": deterministic.get("removed_count"),
                    "deterministic_unwrapped_count": deterministic.get("unwrapped_count"),
                    "ai_enabled": ai_cleanup.get("enabled"),
                    "ai_used": ai_cleanup.get("used"),
                    "ai_provider": ai_cleanup.get("provider"),
                    "ai_model": ai_cleanup.get("model"),
                    "ai_removed_count": len(ai_cleanup.get("removed_items") or []) if isinstance(ai_cleanup.get("removed_items"), list) else 0,
                    "ai_warning_count": len(ai_cleanup.get("warnings") or []) if isinstance(ai_cleanup.get("warnings"), list) else 0,
                    "ai_warnings": ai_cleanup.get("warnings") if isinstance(ai_cleanup.get("warnings"), list) else [],
                    "preservation_changed": preservation.get("changed"),
                    "preservation_restored_count": preservation.get("restored_count"),
                },
            )

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

        file_duration = float(read_audio_duration_seconds(audio_path) or 0.0)
        duration_resolution = _resolve_srt_duration_seconds(asset, file_duration, None)
        duration = float(duration_resolution.get("duration_seconds") or file_duration or 0.0)
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
                "duration_resolution": duration_resolution,
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
        first_word = asr.words[0] if asr.words else None
        last_word = asr.words[-1] if asr.words else None
        duration_resolution = _resolve_srt_duration_seconds(asset, file_duration, asr)
        duration = float(duration_resolution.get("duration_seconds") or duration or 0.0)
        _append_srt_debug_event(
            db,
            srt_task,
            asset,
            "asr_completed",
            detail="ASR-Ergebnis fuer SRT-Alignment vorbereitet.",
            data={
                "backend": backend,
                "language": language,
                "word_count": len(asr.words or []),
                "asr_segments": len(asr.segments or []),
                "first_word": {"word": first_word.word, "start": first_word.start, "end": first_word.end} if first_word else None,
                "last_word": {"word": last_word.word, "start": last_word.start, "end": last_word.end} if last_word else None,
                "duration_resolution": duration_resolution,
            },
        )
        if duration_resolution.get("ignored_file_duration"):
            _append_srt_debug_event(
                db,
                srt_task,
                asset,
                "duration_reconciled",
                detail="Lokale Dateidauer weicht deutlich von DB-/ASR-Dauer ab und wurde fuer das Alignment nicht als harte Grenze genutzt.",
                data=duration_resolution,
            )

        if isinstance(asr.raw, dict):
            asr.raw["songstudio_language_detection"] = language_info
            asr.raw["songstudio_transcription_audio_source"] = transcription_audio_source
            asr.raw["songstudio_lyrics_cleanup"] = lyrics_cleanup_info

        alignment_engine = str(alignment_engine_override or admin_settings.get("srt_alignment_engine") or "heuristic").strip().lower()
        if alignment_engine not in {"heuristic", "forced_alignment"}:
            alignment_engine = "heuristic"
        _update_srt_status_step(
            db,
            srt_task,
            asset,
            "alignment_started",
            detail="Lyrics werden auf die Transkriptionszeiten ausgerichtet." if has_alignment_lyrics else "Keine Lyrics vorhanden; ASR-Text wird direkt als SRT segmentiert.",
            extra={
                "mode": "lyrics_alignment" if has_alignment_lyrics else "transcription_only_no_lyrics",
                "engine": alignment_engine if has_alignment_lyrics else None,
            },
        )
        alignment_bundle: dict[str, Any] | None = None
        if has_alignment_lyrics and alignment_engine == "forced_alignment":
            try:
                alignment_bundle = align_lyrics_with_forced_alignment_bundle(
                    lyrics, asr, transcription_audio_path, duration, source_lyrics=source_lyrics,
                )
                _append_srt_debug_event(
                    db, srt_task, asset, "forced_alignment_completed",
                    detail="Forced Alignment (MMS) erfolgreich.",
                    data={"quality": alignment_bundle.get("alignment_quality")},
                )
            except Exception as forced_exc:  # noqa: BLE001
                alignment_bundle = None
                _append_srt_debug_event(
                    db, srt_task, asset, "forced_alignment_failed",
                    detail=f"Forced Alignment fehlgeschlagen; Heuristik-Fallback: {forced_exc}",
                    data={"error": str(forced_exc)[:400]},
                )
        if alignment_bundle is None:
            alignment_bundle = align_lyrics_to_timeline_bundle(lyrics, asr, duration, source_lyrics=source_lyrics) if has_alignment_lyrics else build_transcription_only_srt_bundle(asr, duration)
            if has_alignment_lyrics and alignment_engine == "forced_alignment":
                alignment_bundle.setdefault("alignment_report", []).append(
                    "WARN: Forced-Alignment-Engine nicht verfuegbar/fehlgeschlagen; Heuristik-Engine verwendet."
                )
                fallback_quality = alignment_bundle.get("alignment_quality") if isinstance(alignment_bundle.get("alignment_quality"), dict) else {}
                fallback_quality["warn_count"] = int(fallback_quality.get("warn_count") or 0) + 1
                fallback_quality["score"] = max(0.0, round(float(fallback_quality.get("score") or 0.0) - 0.06, 3))
                alignment_bundle["alignment_quality"] = fallback_quality
        if "alignment_quality" not in alignment_bundle:
            alignment_bundle["alignment_quality"] = compute_alignment_quality(alignment_bundle)
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
                "engine": alignment_bundle.get("engine") or "heuristic",
                "alignment_quality": alignment_bundle.get("alignment_quality"),
                "segments": len(segments or []),
                "alignment_warnings": len(alignment_bundle.get("alignment_report") or []),
                "half_srt": bool(half_srt_text.strip()),
                "mode": alignment_bundle.get("mode") or "lyrics_alignment",
                "source": alignment_bundle.get("source"),
            },
        )
        alignment_report = alignment_bundle.get("alignment_report") or []
        _append_srt_debug_event(
            db,
            srt_task,
            asset,
            "alignment_decisions",
            detail="SRT-Alignment und Heuristik-Entscheidungen ausgewertet.",
            data={
                "mode": alignment_bundle.get("mode") or "lyrics_alignment",
                "source": alignment_bundle.get("source"),
                "duration_seconds": round(duration, 3),
                "segments": len(segments or []),
                "half_srt": bool(half_srt_text.strip()),
                "effective_srt_lyrics": alignment_bundle.get("effective_srt_lyrics"),
                "alignment_report": _alignment_report_debug_summary(alignment_report),
                "segment_preview": _segment_debug_preview(segments),
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
        _append_srt_debug_event(
            db,
            srt_task,
            asset,
            "srt_files_written",
            detail="SRT-Dateien wurden lokal geschrieben.",
            data={
                "srt_path": str(target_path),
                "half_srt": bool(half_srt_text.strip()),
                "srt_chars": len(srt_text or ""),
                "half_srt_chars": len(half_srt_text or ""),
            },
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
        _append_srt_debug_event(
            db,
            srt_task,
            asset,
            "structure_segments_decision",
            detail="Waveform-/Abschnittssegmente aus SRT-Zeiten ausgewertet.",
            data={
                "has_alignment_lyrics": has_alignment_lyrics,
                "structure_segments": len(structure_segments or []),
                "structure_preview": structure_segments[:8] if structure_segments else [],
            },
            commit=False,
        )
        db.commit()
        db.refresh(transcript)
        result = transcript_to_response(transcript, audio_asset_id)
        result["language_detection"] = language_info
        result["transcription_audio_source"] = transcription_audio_source
        result["lyrics_cleanup"] = lyrics_cleanup_info
        result["alignment_report"] = alignment_bundle.get("alignment_report") or []
        result["alignment_quality"] = alignment_bundle.get("alignment_quality") or {}
        result["alignment_engine"] = alignment_bundle.get("engine") or "heuristic"
        result["half_max_chars"] = alignment_bundle.get("half_max_chars", 22)
        result["srt_generation_mode"] = alignment_bundle.get("mode") or "lyrics_alignment"
        if alignment_bundle.get("source"):
            result["srt_generation_source"] = alignment_bundle.get("source")
        if structure_segments:
            result["structure_segments"] = structure_segments
        result["srt_debug_log"] = (srt_task.response_payload or {}).get("debug_log") if srt_task is not None else []
        _finish_srt_status_task(db, srt_task, asset, "SUCCESS", "SRT wurde erzeugt und gespeichert.", result)
        return result
    except HTTPException as exc:
        if transcript:
            transcript.status = "error"
            transcript.error_message = str(exc.detail)
            transcript.updated_at = utc_now_naive()
            db.add(transcript)
            db.commit()
        _append_srt_debug_event(
            db,
            srt_task,
            asset,
            "srt_failed",
            detail=str(exc.detail),
            data={"exception_type": type(exc).__name__, "status_code": exc.status_code},
        )
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
        _append_srt_debug_event(
            db,
            srt_task,
            asset,
            "srt_failed",
            detail=str(exc),
            data={"exception_type": type(exc).__name__, "backend_error": True},
        )
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
        _append_srt_debug_event(
            db,
            srt_task,
            asset,
            "srt_failed",
            detail=str(exc),
            data={"exception_type": type(exc).__name__},
        )
        _update_srt_status_step(db, srt_task, asset, "failed", detail=str(exc), status="FAILED")
        _finish_srt_status_task(db, srt_task, asset, "FAILED", str(exc))
        raise HTTPException(status_code=500, detail=f"SRT-Erzeugung fehlgeschlagen: {exc}") from exc

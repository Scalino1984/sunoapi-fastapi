from __future__ import annotations

import mimetypes
from pathlib import Path

try:
    from mutagen import File as MutagenFile
except Exception:  # pragma: no cover
    MutagenFile = None


def normalize_audio_content_type(content_type: str | None, path: Path | None = None) -> str:
    value = (content_type or "").split(";", 1)[0].strip().lower()

    if value in {"audio/mp3", "audio/x-mp3"}:
        return "audio/mpeg"

    if value:
        return value

    extension = (path.suffix.lower() if path else "")
    by_extension = {
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".m4a": "audio/mp4",
        ".aac": "audio/aac",
        ".ogg": "audio/ogg",
        ".flac": "audio/flac",
    }

    if extension in by_extension:
        return by_extension[extension]

    guessed, _ = mimetypes.guess_type(str(path)) if path else (None, None)
    return guessed or "application/octet-stream"


def read_audio_duration_seconds(path: Path) -> int | None:
    if not path.exists() or not path.is_file() or path.stat().st_size <= 0:
        return None

    if MutagenFile is None:
        return None

    try:
        audio = MutagenFile(path)
    except Exception:
        return None

    if not audio or not getattr(audio, "info", None):
        return None

    length = getattr(audio.info, "length", None)
    if not length or length <= 0:
        return None

    return int(round(float(length)))

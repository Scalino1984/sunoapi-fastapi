from __future__ import annotations

from pathlib import Path
from typing import Iterable


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def _storage_relative_prefix(storage_root: str | Path | None) -> str | None:
    if storage_root is None:
        return None
    root = project_root().resolve()
    storage = Path(storage_root).expanduser()
    try:
        return storage.resolve().relative_to(root).as_posix()
    except Exception:
        pass
    parts = storage.as_posix().strip("/").split("/")
    if len(parts) >= 2 and parts[-2] == "storage":
        return f"storage/{parts[-1]}"
    if parts:
        return parts[-1]
    return None


def _portable_from_storage_marker(text: str, *, storage_root: str | Path | None) -> str | None:
    """Extrahiert portable Storage-Pfade aus alten absoluten Pfaden.

    Historische DB-Werte können von einem anderen Projektpfad stammen, z. B.
    ``/home/user/Projekte/app/storage/transcripts/293/song.srt``. Auf einem
    anderen Rechner existiert dieser absolute Pfad nicht, der eigentliche
    portable Teil ``storage/transcripts/293/song.srt`` ist aber eindeutig.
    """
    prefix = _storage_relative_prefix(storage_root)
    if not prefix:
        return None
    normalized = text.strip().replace("\\", "/")
    if not normalized:
        return None
    marker = f"/{prefix.strip('/')}/"
    variants = [marker, prefix.strip("/") + "/"]
    for variant in variants:
        if variant in normalized:
            rel = normalized.split(variant, 1)[-1].lstrip("/")
            if not rel or ".." in Path(rel).parts:
                return None
            return f"{prefix.rstrip('/')}/{rel}".lstrip("/")
    return None


def to_portable_path(value: str | Path | None, *, storage_root: str | Path | None = None) -> str | None:
    """Return a stable project-relative path for values stored in the DB.

    Absolute paths make backups non-portable. This helper stores paths as
    POSIX-style project-relative values, e.g. ``storage/audio/file.mp3``.
    Remote URLs and public media URLs are returned unchanged by callers only
    when they intentionally pass them; this helper is for filesystem paths.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if "://" in text or text.startswith("/media/") or text.startswith("/api/"):
        return text

    marker_path = _portable_from_storage_marker(text, storage_root=storage_root)
    if marker_path:
        return marker_path

    root = project_root().resolve()
    candidate = Path(text).expanduser()
    storage = Path(storage_root).expanduser().resolve() if storage_root else None

    if candidate.is_absolute():
        resolved = candidate.resolve()
        if _is_relative_to(resolved, root):
            return resolved.relative_to(root).as_posix()
        if storage and _is_relative_to(resolved, storage):
            try:
                return resolved.relative_to(root).as_posix()
            except Exception:
                storage_prefix = _storage_relative_prefix(storage_root)
                if storage_prefix:
                    return f"{storage_prefix.rstrip('/')}/{resolved.relative_to(storage).as_posix()}"
                return f"{storage.name}/{resolved.relative_to(storage).as_posix()}"
        return resolved.name

    normalized = Path(text.replace("\\", "/"))
    return normalized.as_posix().lstrip("/")


def resolve_portable_path(value: str | Path | None, roots: Iterable[str | Path]) -> Path | None:
    """Resolve a DB path value against project root and known storage roots."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or "://" in text or text.startswith("/api/"):
        return None
    if text.startswith("/media/"):
        text = Path(text.split("?", 1)[0]).name

    root = project_root().resolve()
    raw = Path(text.replace("\\", "/"))
    candidates: list[Path] = []
    if raw.is_absolute():
        candidates.append(raw)
        for item in roots:
            portable = _portable_from_storage_marker(str(raw), storage_root=item)
            if portable:
                candidates.append((root / portable).resolve())
                candidates.append(Path(portable).expanduser().resolve())
            if raw.name:
                candidates.append(Path(item).expanduser().resolve() / raw.name)
    else:
        candidates.append((root / raw).resolve())
        for item in roots:
            storage = Path(item).expanduser().resolve()
            candidates.append((storage / raw).resolve())
            if raw.name:
                candidates.append((storage / raw.name).resolve())

    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def public_url_for_file(path: str | Path, *, storage_root: str | Path, public_route: str) -> str:
    file_path = Path(path)
    storage = Path(storage_root).expanduser().resolve()
    route = str(public_route or "").rstrip("/") or "/media"
    try:
        rel = file_path.expanduser().resolve().relative_to(storage)
        return f"{route}/{rel.as_posix()}"
    except Exception:
        return f"{route}/{file_path.name}"

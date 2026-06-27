from __future__ import annotations

from datetime import UTC, datetime, timezone
from typing import Any


def utc_now() -> datetime:
    """Timezone-aware UTC-Zeitpunkt fuer neue nicht-DB-nahe Logik.

    Dieser Wert ist eindeutig UTC und eignet sich fuer Berechnungen,
    API-Normalisierung und neue externe/JSON-nahe Formate.
    """
    return datetime.now(UTC)


def utc_now_naive() -> datetime:
    """Legacy-kompatibler UTC-Zeitpunkt fuer vorhandene SQLite-DateTime-Spalten.

    Die bestehende Datenbank speichert Zeitwerte ohne Zeitzonen-Suffix,
    fachlich aber als UTC. Damit vorhandene Eintraege, Sortierungen und
    Watchdog-Vergleiche nicht gemischt aware/naive werden, bleiben DB-Werte
    vorerst naive UTC. Intern wird trotzdem nicht mehr das deprecated
    utc_now_naive() verwendet.
    """
    return utc_now().replace(tzinfo=None)


def utc_now_iso(*, timespec: str = "microseconds") -> str:
    """ISO-8601 UTC-Zeit mit expliziter Zeitzone fuer JSON/API-Metadaten."""
    return utc_now().isoformat(timespec=timespec)


def utc_filename_timestamp(fmt: str = "%Y%m%d_%H%M%S") -> str:
    """Stabiler UTC-Zeitstempel fuer Dateinamen und Export-Artefakte."""
    return utc_now().strftime(fmt)


def ensure_utc(value: Any) -> datetime | None:
    """Normalisiert alte naive DB-/ISO-Zeitwerte nach timezone-aware UTC.

    Naive Werte werden in diesem Projekt bewusst als UTC interpretiert, weil
    bestehende SQLite-Daten historisch mit utc_now_naive() gespeichert wurden.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    text = str(value).strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def ensure_utc_naive(value: Any) -> datetime | None:
    """Normalisiert beliebige Zeitwerte auf naive UTC fuer Legacy-DB-Vergleiche."""
    aware = ensure_utc(value)
    return aware.replace(tzinfo=None) if aware else None

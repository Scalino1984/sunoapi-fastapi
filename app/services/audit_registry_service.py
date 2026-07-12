from __future__ import annotations

from typing import Any


AUDIT_CHECKS: dict[str, dict[str, Any]] = {
    "database.integrity": {
        "id": "database.integrity",
        "category": "database",
        "title": "Datenbank- und Schemaintegrität",
        "description": "Prüft SQLite/PostgreSQL-Erreichbarkeit, Tabellen, Pflichtspalten und bekannte Performance-Indizes.",
        "priority": "critical",
        "risk": "none",
        "estimated_duration": "short",
        "supports_repair": False,
        "supports_dry_run": True,
        "default_selected": True,
    },
    "database.references": {
        "id": "database.references",
        "category": "database",
        "title": "Referenzen und Soft-Delete",
        "description": "Findet verwaiste Task-, Song-, Projekt-, Video-, Transcript-, Playlist- und Chat-Referenzen sowie widersprüchliche Papierkorbzustände.",
        "priority": "critical",
        "risk": "none",
        "estimated_duration": "short",
        "supports_repair": True,
        "supports_dry_run": True,
        "default_selected": True,
    },
    "imports.provenance": {
        "id": "imports.provenance",
        "category": "imports",
        "title": "SunoAPI.org-Import-Provenienz",
        "description": "Erkennt lokale Generierungen, die nachträglich fälschlich als manueller SunoAPI.org-Import markiert wurden.",
        "priority": "critical",
        "risk": "medium",
        "estimated_duration": "short",
        "supports_repair": True,
        "supports_dry_run": True,
        "default_selected": True,
    },
    "workflow.tasks": {
        "id": "workflow.tasks",
        "category": "workflow",
        "title": "Task- und Workflow-Konsistenz",
        "description": "Prüft hängende lokale Tasks, widersprüchliche Status-/Zeitfelder, doppelte aktive Jobs und offene Notifications terminaler Tasks.",
        "priority": "critical",
        "risk": "medium",
        "estimated_duration": "short",
        "supports_repair": True,
        "supports_dry_run": True,
        "default_selected": True,
    },
    "storage.references": {
        "id": "storage.references",
        "category": "storage",
        "title": "Datei- und Medienreferenzen",
        "description": "Prüft lokale Audio-, Video- und SRT-Referenzen gegen tatsächlich vorhandene Dateien, ohne Medien zu verändern.",
        "priority": "critical",
        "risk": "none",
        "estimated_duration": "medium",
        "supports_repair": False,
        "supports_dry_run": True,
        "default_selected": True,
    },
    "runtime.configuration": {
        "id": "runtime.configuration",
        "category": "configuration",
        "title": "Konfiguration und Laufzeitabhängigkeiten",
        "description": "Prüft Secrets, Storage-Verzeichnisse, Schreibrechte, ffmpeg/ffprobe, Provider-Grundkonfiguration und sicherheitsrelevante Einstellungen.",
        "priority": "high",
        "risk": "none",
        "estimated_duration": "short",
        "supports_repair": False,
        "supports_dry_run": True,
        "default_selected": True,
    },
}


def list_audit_checks() -> list[dict[str, Any]]:
    return [dict(item) for item in AUDIT_CHECKS.values()]


def normalize_check_ids(values: list[str] | None) -> list[str]:
    selected = values or [key for key, value in AUDIT_CHECKS.items() if value.get("default_selected")]
    result: list[str] = []
    for value in selected:
        key = str(value or "").strip()
        if key not in AUDIT_CHECKS:
            raise ValueError(f"Unbekannte Prüfung: {key}")
        if key not in result:
            result.append(key)
    if not result:
        raise ValueError("Mindestens eine Prüfung muss ausgewählt werden.")
    return result

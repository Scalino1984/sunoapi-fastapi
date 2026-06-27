#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

SUCCESS_STATUSES = {"SUCCESS", "COMPLETED", "COMPLETE", "DONE", "IMPORTED", "PARTIAL_SUCCESS", "FIRST_SUCCESS"}


def project_root() -> Path:
    script = Path(__file__).resolve()
    return script.parents[1] if script.parent.name == "scripts" else Path.cwd()


def resolve_db_path(value: str | None) -> Path:
    raw = value or os.environ.get("DATABASE_URL", "sqlite:///suno_fastapi_app.db")
    raw = raw.strip()
    if raw.startswith("sqlite:///"):
        return Path(raw.replace("sqlite:///", "", 1)).expanduser().resolve()
    if raw.startswith("sqlite://"):
        return Path(raw.replace("sqlite://", "", 1)).expanduser().resolve()
    return Path(raw).expanduser().resolve()


def table_exists(con: sqlite3.Connection, table: str) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def columns(con: sqlite3.Connection, table: str) -> set[str]:
    if not table_exists(con, table):
        return set()
    return {row[1] for row in con.execute(f"PRAGMA table_info({table})").fetchall()}


def scalar(con: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> int:
    row = con.execute(sql, params).fetchone()
    return int(row[0] or 0) if row else 0


def fail(message: str) -> tuple[bool, str]:
    return False, message


def ok(message: str) -> tuple[bool, str]:
    return True, message


def validate_sqlite(db_path: Path) -> list[tuple[bool, str]]:
    con = sqlite3.connect(str(db_path))
    try:
        checks: list[tuple[bool, str]] = []
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        checks.append(ok("SQLite integrity_check=ok") if str(integrity).lower() == "ok" else fail(f"SQLite integrity_check={integrity}"))

        required_tables = ["suno_tasks", "songs", "audio_assets", "audio_projects", "status_notifications"]
        for table in required_tables:
            checks.append(ok(f"Tabelle vorhanden: {table}") if table_exists(con, table) else fail(f"Tabelle fehlt: {table}"))

        if table_exists(con, "audio_assets"):
            cols = columns(con, "audio_assets")
            required_cols = ["source_url", "status", "song_id", "task_local_id", "suno_task_id", "audio_id", "project_id", "display_title", "is_deleted"]
            for col in required_cols:
                checks.append(ok(f"audio_assets.{col} vorhanden") if col in cols else fail(f"audio_assets.{col} fehlt"))
            active = "COALESCE(is_deleted, 0) = 0" if "is_deleted" in cols else "1=1"
            if "source_url" in cols:
                bad_source = scalar(con, f"SELECT COUNT(*) FROM audio_assets WHERE {active} AND (source_url IS NULL OR TRIM(source_url) = '')")
                checks.append(ok("Keine aktiven AudioAssets ohne source_url") if bad_source == 0 else fail(f"{bad_source} aktive AudioAssets ohne source_url"))
                duplicates = scalar(con, f"SELECT COUNT(*) FROM (SELECT source_url FROM audio_assets WHERE {active} AND source_url IS NOT NULL AND TRIM(source_url) <> '' GROUP BY source_url HAVING COUNT(*) > 1)")
                checks.append(ok("Keine aktiven doppelten source_url-Gruppen") if duplicates == 0 else fail(f"{duplicates} doppelte source_url-Gruppen"))
            if "status" in cols:
                invalid_status = scalar(con, f"SELECT COUNT(*) FROM audio_assets WHERE {active} AND LOWER(COALESCE(status, '')) NOT IN ('created','remote','cached','failed','imported','ready','success')")
                checks.append(ok("AudioAsset-Statuswerte plausibel") if invalid_status == 0 else fail(f"{invalid_status} AudioAssets mit unerwartetem Status"))

        if table_exists(con, "suno_tasks") and table_exists(con, "audio_assets"):
            task_cols = columns(con, "suno_tasks")
            asset_cols = columns(con, "audio_assets")
            if {"id", "task_id", "status", "is_deleted"}.issubset(task_cols) and {"task_local_id", "suno_task_id", "is_deleted"}.issubset(asset_cols):
                placeholders = ",".join("?" for _ in SUCCESS_STATUSES)
                active_tasks_with_assets = scalar(
                    con,
                    f"""
                    SELECT COUNT(*)
                    FROM suno_tasks t
                    WHERE COALESCE(t.is_deleted, 0) = 0
                      AND UPPER(COALESCE(t.status, '')) IN ({placeholders})
                      AND EXISTS (
                        SELECT 1 FROM audio_assets a
                        WHERE COALESCE(a.is_deleted, 0) = 0
                          AND (a.task_local_id = t.id OR (t.task_id IS NOT NULL AND a.suno_task_id = t.task_id))
                      )
                    """,
                    tuple(sorted(SUCCESS_STATUSES)),
                )
                checks.append(ok(f"{active_tasks_with_assets} erfolgreiche Tasks sind mit AudioAssets verknüpft"))

        return checks
    finally:
        con.close()


def validate_app_imports(database: str) -> list[tuple[bool, str]]:
    os.environ["DATABASE_URL"] = database
    checks: list[tuple[bool, str]] = []
    try:
        from app.database import init_db
        init_db()
        checks.append(ok("FastAPI DB-Init / leichte Migrationen erfolgreich"))
    except Exception as exc:  # pragma: no cover - CLI Diagnose
        checks.append(fail(f"FastAPI DB-Init fehlgeschlagen: {exc}"))
        return checks

    modules = [
        "app.services.audio_asset_materialization_service",
        "app.services.audio_cache_service",
        "app.services.music_service",
        "app.routers.archive",
        "app.routers.music",
    ]
    for module in modules:
        try:
            __import__(module)
            checks.append(ok(f"Import OK: {module}"))
        except Exception as exc:
            checks.append(fail(f"Import FEHLER: {module}: {exc}"))
    return checks


def run() -> int:
    parser = argparse.ArgumentParser(description="Validiert den lokalen Unified-Audio Zielstand nach Patch/Migration.")
    parser.add_argument("--database", "--db", dest="database", default="", help="Pfad zur SQLite-DB oder sqlite:/// URL. Standard: DATABASE_URL oder ./suno_fastapi_app.db")
    parser.add_argument("--skip-app-init", action="store_true", help="Nur rohe SQLite-Prüfung durchführen.")
    args = parser.parse_args()

    root = project_root()
    os.chdir(root)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    db_path = resolve_db_path(args.database)
    if not db_path.exists():
        print(f"ABBRUCH: Datenbank nicht gefunden: {db_path}", file=sys.stderr)
        return 2

    database_url = args.database if args.database and args.database.startswith("sqlite:") else f"sqlite:///{db_path}"
    checks = validate_sqlite(db_path)
    if not args.skip_app_init:
        checks.extend(validate_app_imports(database_url))

    print("Unified-Audio Local Master Validation")
    print(f"Datenbank: {db_path}\n")
    failed = 0
    for passed, message in checks:
        marker = "OK " if passed else "ERR"
        print(f"[{marker}] {message}")
        if not passed:
            failed += 1
    print()
    print(f"Ergebnis: {len(checks) - failed} OK, {failed} Fehler")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(run())

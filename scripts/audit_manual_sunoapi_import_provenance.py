#!/usr/bin/env python3
"""Audit und konservative Reparatur falscher SunoAPI.org-Importmarker.

Standardmäßig läuft das Skript ausschließlich im Dry-Run. Es erkennt nur
hochkonfidente Fälle, bei denen ``request_payload.source`` auf
``manual_sunoapi_import`` steht, die Task aber belastbare Merkmale einer lokalen
App-Generierung besitzt. Ohne ``--apply --confirm APPLY`` werden keinerlei
Daten verändert.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.import_provenance_service import (  # noqa: E402
    MANUAL_SUNOAPI_IMPORT_SOURCE,
    has_false_manual_sunoapi_import_marker,
    strip_manual_sunoapi_import_source,
)


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _json_dump(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _clean_metadata(metadata_value: Any) -> tuple[dict[str, Any], bool, dict[str, Any]]:
    metadata = _json_object(metadata_value)
    before = {
        "source": metadata.get("source"),
        "request_source": (
            metadata.get("request_payload", {}).get("source")
            if isinstance(metadata.get("request_payload"), dict)
            else None
        ),
    }
    changed = False

    if str(metadata.get("source") or "").strip().lower() == MANUAL_SUNOAPI_IMPORT_SOURCE:
        metadata.pop("source", None)
        changed = True

    request_payload = metadata.get("request_payload")
    if isinstance(request_payload, dict):
        cleaned_request = strip_manual_sunoapi_import_source(request_payload)
        if cleaned_request != request_payload:
            metadata["request_payload"] = cleaned_request
            changed = True

    after = {
        "source": metadata.get("source"),
        "request_source": (
            metadata.get("request_payload", {}).get("source")
            if isinstance(metadata.get("request_payload"), dict)
            else None
        ),
    }
    return metadata, changed, {"before": before, "after": after}


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table_name,),
    ).fetchone()
    return row is not None


def _active_filter(connection: sqlite3.Connection, table_name: str) -> str:
    columns = {
        row[1]
        for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    return " AND COALESCE(is_deleted, 0) = 0" if "is_deleted" in columns else ""


def _collect_candidates(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    if not _table_exists(connection, "suno_tasks"):
        raise RuntimeError("Tabelle suno_tasks fehlt.")

    rows = connection.execute(
        "SELECT id, task_id, task_type, status, request_payload, response_payload "
        "FROM suno_tasks WHERE COALESCE(is_deleted, 0) = 0 ORDER BY id ASC"
    ).fetchall()
    candidates: list[dict[str, Any]] = []
    for row in rows:
        request_payload = _json_object(row[4])
        response_payload = _json_object(row[5])
        if not has_false_manual_sunoapi_import_marker(
            task_type=row[2],
            request_payload=request_payload,
            response_payload=response_payload,
        ):
            continue
        candidates.append(
            {
                "task_local_id": int(row[0]),
                "task_id": row[1],
                "task_type": row[2],
                "status": row[3],
                "request_payload": request_payload,
                "response_payload": response_payload,
            }
        )
    return candidates


def _collect_related_changes(
    connection: sqlite3.Connection,
    candidates: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[tuple[str, int], dict[str, Any]]]:
    report_changes: list[dict[str, Any]] = []
    updates: dict[tuple[str, int], dict[str, Any]] = {}

    for candidate in candidates:
        task_id = candidate["task_id"]
        task_local_id = candidate["task_local_id"]
        cleaned_request = strip_manual_sunoapi_import_source(candidate["request_payload"])
        if cleaned_request != candidate["request_payload"]:
            key = ("suno_tasks", task_local_id)
            updates[key] = {"column": "request_payload", "value": cleaned_request}
            report_changes.append(
                {
                    "table": "suno_tasks",
                    "id": task_local_id,
                    "task_id": task_id,
                    "field": "request_payload.source",
                    "before": MANUAL_SUNOAPI_IMPORT_SOURCE,
                    "after": None,
                }
            )

        table_queries = {
            "songs": (
                "SELECT id, metadata_json FROM songs WHERE task_id = ?"
                + _active_filter(connection, "songs"),
                (task_id,),
            ),
            "audio_assets": (
                "SELECT id, metadata_json FROM audio_assets "
                "WHERE (task_local_id = ? OR suno_task_id = ?)"
                + _active_filter(connection, "audio_assets"),
                (task_local_id, task_id),
            ),
            "video_assets": (
                "SELECT id, metadata_json FROM video_assets "
                "WHERE (task_local_id = ? OR suno_task_id = ?)"
                + _active_filter(connection, "video_assets"),
                (task_local_id, task_id),
            ),
        }

        for table_name, (query, params) in table_queries.items():
            if not _table_exists(connection, table_name):
                continue
            for row_id, metadata_value in connection.execute(query, params).fetchall():
                metadata, changed, detail = _clean_metadata(metadata_value)
                if not changed:
                    continue
                key = (table_name, int(row_id))
                updates[key] = {"column": "metadata_json", "value": metadata}
                report_changes.append(
                    {
                        "table": table_name,
                        "id": int(row_id),
                        "task_id": task_id,
                        "field": "metadata provenance",
                        **detail,
                    }
                )

    return report_changes, updates


def _backup_database(source_path: Path, backup_path: Path) -> None:
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(str(source_path), timeout=60)
    target = sqlite3.connect(str(backup_path), timeout=60)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


def _integrity_check(connection: sqlite3.Connection) -> str:
    row = connection.execute("PRAGMA integrity_check").fetchone()
    return str(row[0] if row else "unknown")


def _apply_updates(
    connection: sqlite3.Connection,
    updates: dict[tuple[str, int], dict[str, Any]],
) -> None:
    connection.execute("BEGIN IMMEDIATE")
    try:
        for (table_name, row_id), update in updates.items():
            column = update["column"]
            if table_name not in {"suno_tasks", "songs", "audio_assets", "video_assets"}:
                raise RuntimeError(f"Nicht erlaubte Tabelle: {table_name}")
            if column not in {"request_payload", "metadata_json"}:
                raise RuntimeError(f"Nicht erlaubte Spalte: {column}")
            connection.execute(
                f"UPDATE {table_name} SET {column} = ? WHERE id = ?",
                (_json_dump(update["value"]), row_id),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prüft und repariert falsche manual_sunoapi_import-Herkunftsmarker.",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=PROJECT_ROOT / "suno_fastapi_app.db",
        help="Pfad zur SQLite-Datenbank.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Optionaler JSON-Reportpfad.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Änderungen anwenden. Ohne diesen Schalter bleibt der Lauf read-only.",
    )
    parser.add_argument(
        "--confirm",
        default="",
        help="Für --apply muss exakt APPLY angegeben werden.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    database_path = args.database.expanduser().resolve()
    if not database_path.is_file():
        print(f"FEHLER: Datenbank nicht gefunden: {database_path}", file=sys.stderr)
        return 2
    if args.apply and args.confirm != "APPLY":
        print("FEHLER: --apply benötigt zusätzlich --confirm APPLY.", file=sys.stderr)
        return 2

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = (
        args.report.expanduser().resolve()
        if args.report
        else PROJECT_ROOT / "reports" / f"manual_sunoapi_import_provenance_{timestamp}.json"
    )

    connection = sqlite3.connect(str(database_path), timeout=60)
    try:
        integrity_before = _integrity_check(connection)
        if integrity_before.lower() != "ok":
            raise RuntimeError(f"SQLite integrity_check vor Audit ist nicht ok: {integrity_before}")
        candidates = _collect_candidates(connection)
        changes, updates = _collect_related_changes(connection, candidates)
    finally:
        connection.close()

    backup_path: Path | None = None
    if args.apply and updates:
        backup_path = database_path.parent / "backups" / f"before_manual_import_provenance_repair_{timestamp}.db"
        _backup_database(database_path, backup_path)
        connection = sqlite3.connect(str(database_path), timeout=60)
        try:
            _apply_updates(connection, updates)
            integrity_after = _integrity_check(connection)
            if integrity_after.lower() != "ok":
                raise RuntimeError(f"SQLite integrity_check nach Reparatur ist nicht ok: {integrity_after}")
        finally:
            connection.close()
    else:
        integrity_after = integrity_before

    counts: dict[str, int] = {}
    for change in changes:
        table_name = change["table"]
        counts[table_name] = counts.get(table_name, 0) + 1

    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "apply" if args.apply else "dry-run",
        "database": str(database_path),
        "backup": str(backup_path) if backup_path else None,
        "integrity_before": integrity_before,
        "integrity_after": integrity_after,
        "candidate_task_count": len(candidates),
        "planned_or_applied_change_count": len(updates),
        "changes_by_table": counts,
        "candidate_tasks": [
            {
                "task_local_id": item["task_local_id"],
                "task_id": item["task_id"],
                "task_type": item["task_type"],
                "status": item["status"],
            }
            for item in candidates
        ],
        "changes": changes,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    mode_label = "ANWENDUNG" if args.apply else "DRY-RUN"
    print(f"{mode_label}: {len(candidates)} hochkonfidente Task-Kandidaten erkannt.")
    print(f"Geplante/angewendete Datensatzänderungen: {len(updates)}")
    for table_name in sorted(counts):
        print(f"  {table_name}: {counts[table_name]}")
    if backup_path:
        print(f"Backup: {backup_path}")
    print(f"Report: {report_path}")
    if not args.apply:
        print("Es wurden keine Daten verändert.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

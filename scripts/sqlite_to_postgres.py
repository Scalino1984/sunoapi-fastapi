#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import MetaData, Table, create_engine, func, select, text
from sqlalchemy.exc import NoSuchModuleError
from sqlalchemy.sql.sqltypes import Boolean, DateTime, JSON


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def _load_app_metadata():
    # Importing app.models registers all ORM tables on Base.metadata.
    from app.database import Base
    from app import models  # noqa: F401

    return Base.metadata


def _postgres_url_from_args(value: str | None) -> str:
    url = value or os.environ.get("POSTGRES_DATABASE_URL") or ""
    if not url:
        database_url = os.environ.get("DATABASE_URL") or ""
        if database_url.startswith(("postgresql://", "postgresql+")):
            url = database_url
    if not url:
        raise SystemExit(
            "PostgreSQL-Ziel fehlt. Nutze --postgres-url oder POSTGRES_DATABASE_URL.\n"
            "Beispiel: postgresql+psycopg://user:pass@localhost:5432/suno_fastapi_app"
        )
    if not url.startswith(("postgresql://", "postgresql+")):
        raise SystemExit("Das Ziel muss eine PostgreSQL-SQLAlchemy-URL sein.")
    return url


def _sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.expanduser().resolve()}"


def _is_json_column(table: Table, column_name: str) -> bool:
    return isinstance(table.c[column_name].type, JSON)


def _is_datetime_column(table: Table, column_name: str) -> bool:
    return isinstance(table.c[column_name].type, DateTime)


def _is_boolean_column(table: Table, column_name: str) -> bool:
    return isinstance(table.c[column_name].type, Boolean)


def _coerce_json(value: Any) -> Any:
    if value is None or isinstance(value, (dict, list, int, float, bool)):
        return value
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if isinstance(value, str):
        text_value = value.strip()
        if not text_value:
            return None
        try:
            return json.loads(text_value)
        except json.JSONDecodeError:
            return value
    return value


def _coerce_datetime(value: Any) -> Any:
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if isinstance(value, str):
        text_value = value.strip()
        if not text_value:
            return None
        normalized = text_value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized)
        except ValueError:
            for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    return datetime.strptime(text_value, fmt)
                except ValueError:
                    continue
    return value


def _coerce_boolean(value: Any) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "t", "yes", "y", "on"}
    return bool(value)


def _coerce_row(row: dict[str, Any], target_table: Table) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in row.items():
        if _is_json_column(target_table, key):
            result[key] = _coerce_json(value)
        elif _is_datetime_column(target_table, key):
            result[key] = _coerce_datetime(value)
        elif _is_boolean_column(target_table, key):
            result[key] = _coerce_boolean(value)
        else:
            result[key] = value
    return result


def _table_row_count(connection, table: Table) -> int:
    return int(connection.execute(select(func.count()).select_from(table)).scalar() or 0)


def _select_tables(metadata: MetaData, only: set[str], skip: set[str]) -> list[Table]:
    tables = list(metadata.sorted_tables)
    if only:
        tables = [table for table in tables if table.name in only]
    if skip:
        tables = [table for table in tables if table.name not in skip]
    return tables


def _clear_target(connection, tables: list[Table]) -> None:
    for table in reversed(tables):
        connection.execute(table.delete())


def _reset_sequence(connection, table: Table) -> None:
    pk_columns = list(table.primary_key.columns)
    if len(pk_columns) != 1:
        return
    pk_name = pk_columns[0].name
    sequence_name = connection.execute(
        text("SELECT pg_get_serial_sequence(:table_name, :pk_name)"),
        {"table_name": table.name, "pk_name": pk_name},
    ).scalar()
    if not sequence_name:
        return
    quoted_table = table.name.replace('"', '""')
    quoted_pk = pk_name.replace('"', '""')
    max_id = connection.execute(text(f'SELECT MAX("{quoted_pk}") FROM "{quoted_table}"')).scalar() or 0
    connection.execute(
        text("SELECT setval(:sequence_name, :next_value, :is_called)"),
        {"sequence_name": sequence_name, "next_value": max(int(max_id), 1), "is_called": int(max_id) > 0},
    )


def _copy_table(
    source_connection,
    target_connection,
    source_table: Table,
    target_table: Table,
    *,
    batch_size: int,
    dry_run: bool,
) -> int:
    common_columns = [column.name for column in target_table.columns if column.name in source_table.c]
    if not common_columns:
        return 0

    stmt = select(*[source_table.c[column_name] for column_name in common_columns])
    rows = source_connection.execute(stmt).mappings()
    copied = 0
    while True:
        batch = rows.fetchmany(batch_size)
        if not batch:
            break
        prepared = [_coerce_row(dict(row), target_table) for row in batch]
        copied += len(prepared)
        if not dry_run:
            target_connection.execute(target_table.insert(), prepared)
    return copied


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Kopiert die lokale SQLite-Datenbank der App in eine PostgreSQL-Datenbank.",
    )
    parser.add_argument("--sqlite", default="suno_fastapi_app.db", help="Pfad zur SQLite-Quelldatei.")
    parser.add_argument("--postgres-url", default=None, help="PostgreSQL-SQLAlchemy-URL. Alternativ POSTGRES_DATABASE_URL.")
    parser.add_argument("--batch-size", type=int, default=500, help="Insert-Batchgröße.")
    parser.add_argument("--only", default="", help="Kommagetrennte Tabellenliste, optional.")
    parser.add_argument("--skip", default="", help="Kommagetrennte Tabellenliste, optional.")
    parser.add_argument("--clear-target", action="store_true", help="Leert Zieltabellen vor dem Import.")
    parser.add_argument("--yes", action="store_true", help="Bestätigt destruktive Aktionen wie --clear-target.")
    parser.add_argument("--dry-run", action="store_true", help="Zählt und validiert, schreibt aber nichts in PostgreSQL.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    sqlite_path = Path(args.sqlite)
    if not sqlite_path.exists():
        raise SystemExit(f"SQLite-Datei nicht gefunden: {sqlite_path}")
    if args.batch_size < 1:
        raise SystemExit("--batch-size muss größer als 0 sein.")
    if args.clear_target and not args.yes:
        raise SystemExit("--clear-target ist destruktiv. Bitte zusätzlich --yes setzen.")

    postgres_url = _postgres_url_from_args(args.postgres_url)
    only = {item.strip() for item in args.only.split(",") if item.strip()}
    skip = {item.strip() for item in args.skip.split(",") if item.strip()}

    try:
        target_engine = create_engine(postgres_url, future=True)
    except NoSuchModuleError as exc:
        raise SystemExit(
            "PostgreSQL-Treiber fehlt. Installiere z. B.:\n"
            "  python3 -m pip install 'psycopg[binary]'\n"
            "oder nutze eine URL mit installiertem Treiber, z. B. postgresql+psycopg2://..."
        ) from exc

    source_engine = create_engine(_sqlite_url(sqlite_path), future=True)
    app_metadata = _load_app_metadata()
    tables = _select_tables(app_metadata, only, skip)
    if not tables:
        raise SystemExit("Keine Tabellen zum Kopieren ausgewählt.")

    source_metadata = MetaData()
    source_metadata.reflect(bind=source_engine)

    missing_in_source = [table.name for table in tables if table.name not in source_metadata.tables]
    if missing_in_source:
        print("WARNUNG: Nicht in SQLite vorhanden, wird übersprungen:", ", ".join(missing_in_source))

    copied_by_table: dict[str, int] = {}
    with source_engine.connect() as source_connection:
        with target_engine.begin() as target_connection:
            if args.dry_run:
                print("Dry-run: PostgreSQL wird nicht verändert.")
            else:
                app_metadata.create_all(bind=target_connection)

            if args.clear_target and not args.dry_run:
                _clear_target(target_connection, tables)

            if not args.clear_target and not args.dry_run:
                non_empty = [
                    table.name
                    for table in tables
                    if table.name in source_metadata.tables and _table_row_count(target_connection, table) > 0
                ]
                if non_empty:
                    raise SystemExit(
                        "Zieltabellen sind nicht leer: "
                        + ", ".join(non_empty)
                        + "\nNutze eine leere DB oder --clear-target --yes."
                    )

            for target_table in tables:
                source_table = source_metadata.tables.get(target_table.name)
                if source_table is None:
                    continue
                copied = _copy_table(
                    source_connection,
                    target_connection,
                    source_table,
                    target_table,
                    batch_size=args.batch_size,
                    dry_run=args.dry_run,
                )
                copied_by_table[target_table.name] = copied
                print(f"{target_table.name}: {copied} Zeile(n)")

            if not args.dry_run:
                for table in tables:
                    if table.name in copied_by_table:
                        _reset_sequence(target_connection, table)

    total = sum(copied_by_table.values())
    print(f"Fertig. Tabellen: {len(copied_by_table)}, Zeilen: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

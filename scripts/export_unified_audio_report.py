#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# Audit-Skript wird bewusst wiederverwendet, damit CLI und Report identische Befunde liefern.
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from audit_unified_audio_state import build_audit, resolve_db_path  # noqa: E402


def project_root() -> Path:
    script = Path(__file__).resolve()
    return script.parents[1] if script.parent.name == "scripts" else Path.cwd()


def table_exists(con: sqlite3.Connection, table: str) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def select_rows(con: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    con.row_factory = sqlite3.Row
    return con.execute(sql, params).fetchall()


def markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        return "_Keine Einträge._\n"
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        cells = []
        for value in row:
            text = "" if value is None else str(value)
            text = text.replace("|", "\\|").replace("\n", " ")
            if len(text) > 120:
                text = text[:117] + "..."
            cells.append(text)
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def build_report(db_path: Path, audit: dict[str, Any]) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines: list[str] = []
    lines.append("# Unified Audio Local Master Report")
    lines.append("")
    lines.append(f"Erstellt: `{now}`")
    lines.append(f"Datenbank: `{db_path}`")
    lines.append(f"SQLite integrity_check: `{audit['integrity_check']}`")
    lines.append("")
    lines.append("## Zielmodell")
    lines.append("")
    lines.append("```text")
    lines.append("suno_tasks   = Prozess / Status / externe Taskdaten")
    lines.append("songs        = Metadaten / Lyrics / Prompt")
    lines.append("audio_assets = zentrale Library-Wahrheit für alles Abspielbare")
    lines.append("```")
    lines.append("")
    lines.append("## Bestandszahlen")
    lines.append("")
    lines.append(markdown_table(["Bereich", "Anzahl"], [[k, v] for k, v in audit["counts"].items()]))
    lines.append("")
    lines.append(f"Tasks mit Audio-Kandidaten: **{audit['tasks_with_audio_candidates']}**")
    lines.append("")
    lines.append("## Befunde")
    lines.append("")
    findings = audit.get("findings", [])
    if not findings:
        lines.append("Keine kritischen Unified-Audio-Abweichungen gefunden.")
    else:
        lines.append(markdown_table(["Schwere", "Code", "Anzahl", "Beschreibung"], [[f["severity"], f["code"], f["count"], f["message"]] for f in findings]))
        for finding in findings:
            sample = finding.get("sample", [])
            if not sample:
                continue
            lines.append(f"### Beispiele: {finding['code']}")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(sample[:10], ensure_ascii=False, indent=2))
            lines.append("```")
            lines.append("")

    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    try:
        if table_exists(con, "audio_assets"):
            lines.append("## Letzte AudioAssets")
            lines.append("")
            rows = select_rows(con, """
                SELECT id, COALESCE(display_title, title) AS title, status, song_id, task_local_id, suno_task_id, audio_id, project_id
                FROM audio_assets
                WHERE COALESCE(is_deleted, 0) = 0
                ORDER BY id DESC
                LIMIT 20
            """)
            lines.append(markdown_table(["ID", "Titel", "Status", "Song", "Task lokal", "Suno Task", "Audio ID", "Projekt"], [[r["id"], r["title"], r["status"], r["song_id"], r["task_local_id"], r["suno_task_id"], r["audio_id"], r["project_id"]] for r in rows]))
            lines.append("")
            lines.append("## AudioAsset Statusverteilung")
            lines.append("")
            rows = select_rows(con, """
                SELECT COALESCE(status, '(leer)') AS status, COUNT(*) AS count
                FROM audio_assets
                WHERE COALESCE(is_deleted, 0) = 0
                GROUP BY COALESCE(status, '(leer)')
                ORDER BY count DESC
            """)
            lines.append(markdown_table(["Status", "Anzahl"], [[r["status"], r["count"]] for r in rows]))
        if table_exists(con, "suno_tasks"):
            lines.append("## SunoTask Statusverteilung")
            lines.append("")
            rows = select_rows(con, """
                SELECT COALESCE(status, '(leer)') AS status, COUNT(*) AS count
                FROM suno_tasks
                WHERE COALESCE(is_deleted, 0) = 0
                GROUP BY COALESCE(status, '(leer)')
                ORDER BY count DESC
            """)
            lines.append(markdown_table(["Status", "Anzahl"], [[r["status"], r["count"]] for r in rows]))
    finally:
        con.close()

    lines.append("## Empfohlener lokaler Ablauf")
    lines.append("")
    lines.append("```bash")
    lines.append("python3 scripts/audit_unified_audio_state.py")
    lines.append("python3 scripts/migrate_unified_audio_library.py --dry-run --backup")
    lines.append("python3 scripts/migrate_unified_audio_library.py --backup --yes")
    lines.append("python3 scripts/validate_unified_audio_workflow.py")
    lines.append("python3 scripts/export_unified_audio_report.py")
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def run() -> int:
    parser = argparse.ArgumentParser(description="Erzeugt einen Markdown-Report zum lokalen Unified-Audio DB-Zustand.")
    parser.add_argument("--database", "--db", dest="database", default="", help="Pfad zur SQLite-DB oder sqlite:/// URL. Standard: DATABASE_URL oder ./suno_fastapi_app.db")
    parser.add_argument("--output", "-o", default="", help="Zieldatei. Standard: storage/reports/unified_audio_report_<timestamp>.md")
    args = parser.parse_args()

    root = project_root()
    os.chdir(root)
    db_path = resolve_db_path(args.database)
    if not db_path.exists():
        print(f"ABBRUCH: Datenbank nicht gefunden: {db_path}", file=sys.stderr)
        return 2
    audit = build_audit(db_path)
    report = build_report(db_path, audit)
    if args.output:
        out_path = Path(args.output).expanduser().resolve()
    else:
        out_dir = root / "storage" / "reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"unified_audio_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    print(f"Report geschrieben: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

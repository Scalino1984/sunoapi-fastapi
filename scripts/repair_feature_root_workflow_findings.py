#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

ARCHIVED_TRANSCRIPT_STATUSES = {"archived_orphan", "orphaned", "deleted_asset_archived"}


@dataclass
class Action:
    category: str
    code: str
    message: str
    count: int = 0
    sample: list[dict[str, Any]] = field(default_factory=list)


def project_root() -> Path:
    script = Path(__file__).resolve()
    return script.parents[1] if script.parent.name == "scripts" else Path.cwd()


def resolve_db_path(value: str | None, root: Path) -> Path:
    raw = (value or os.environ.get("DATABASE_URL") or "sqlite:///suno_fastapi_app.db").strip()
    if raw.startswith("sqlite:///"):
        raw = raw.replace("sqlite:///", "", 1)
    elif raw.startswith("sqlite://"):
        raw = raw.replace("sqlite://", "", 1)
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def connect(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=OFF")
    con.execute("PRAGMA busy_timeout=60000")
    return con


def rowdict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def rows(con: sqlite3.Connection, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in con.execute(sql, tuple(params)).fetchall()]


def scalar(con: sqlite3.Connection, sql: str, params: Iterable[Any] = (), default: Any = None) -> Any:
    row = con.execute(sql, tuple(params)).fetchone()
    return row[0] if row is not None else default


def table_exists(con: sqlite3.Connection, table: str) -> bool:
    return bool(scalar(con, "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)))


def columns(con: sqlite3.Connection, table: str) -> set[str]:
    if not table_exists(con, table):
        return set()
    return {row[1] for row in con.execute(f"PRAGMA table_info({table})").fetchall()}


def has_columns(con: sqlite3.Connection, table: str, *cols: str) -> bool:
    existing = columns(con, table)
    return all(col in existing for col in cols)


def active_clause(alias: str | None = None) -> str:
    prefix = f"{alias}." if alias else ""
    return f"COALESCE({prefix}is_deleted, 0) = 0"


def parse_json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return None


def dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def backup_db(db_path: Path, root: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target_dir = root / "storage" / "backups"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{db_path.stem}.before-feature-root-repair-{stamp}{db_path.suffix}"
    shutil.copy2(db_path, target)
    return target


def add_action(actions: list[Action], category: str, code: str, message: str, count: int, sample: list[dict[str, Any]] | None = None) -> None:
    actions.append(Action(category=category, code=code, message=message, count=count, sample=(sample or [])[:10]))


def find_unambiguous_replacement_asset(con: sqlite3.Connection, old_asset: dict[str, Any] | None) -> dict[str, Any] | None:
    if not old_asset:
        return None
    old_id = old_asset.get("id")

    def single(candidates: list[dict[str, Any]], rule: str) -> dict[str, Any] | None:
        if len(candidates) == 1:
            item = dict(candidates[0])
            item["replacement_rule"] = rule
            return item
        return None

    source_url = str(old_asset.get("source_url") or "").strip()
    if source_url:
        candidates = rows(
            con,
            f"""
            SELECT id, display_title, song_id, project_id, source_url, audio_id
            FROM audio_assets
            WHERE {active_clause()} AND id != ? AND source_url = ?
            LIMIT 3
            """,
            (old_id, source_url),
        )
        found = single(candidates, "same_source_url")
        if found:
            return found

    audio_id = str(old_asset.get("audio_id") or "").strip()
    if audio_id:
        candidates = rows(
            con,
            f"""
            SELECT id, display_title, song_id, project_id, source_url, audio_id
            FROM audio_assets
            WHERE {active_clause()} AND id != ? AND audio_id = ?
            LIMIT 3
            """,
            (old_id, audio_id),
        )
        found = single(candidates, "same_audio_id")
        if found:
            return found

    song_id = old_asset.get("song_id")
    if song_id is not None:
        candidates = rows(
            con,
            f"""
            SELECT id, display_title, song_id, project_id, source_url, audio_id
            FROM audio_assets
            WHERE {active_clause()} AND id != ? AND song_id = ?
            ORDER BY is_final DESC, id DESC
            LIMIT 3
            """,
            (old_id, song_id),
        )
        found = single(candidates, "single_active_asset_same_song")
        if found:
            return found

    project_id = old_asset.get("project_id")
    if project_id is not None:
        candidates = rows(
            con,
            f"""
            SELECT id, display_title, song_id, project_id, source_url, audio_id
            FROM audio_assets
            WHERE {active_clause()} AND id != ? AND project_id = ?
            ORDER BY is_final DESC, id DESC
            LIMIT 3
            """,
            (old_id, project_id),
        )
        found = single(candidates, "single_active_asset_same_project")
        if found:
            return found

    return None


def repair_production_final_asset(con: sqlite3.Connection, dry_run: bool) -> Action:
    if not (table_exists(con, "audio_projects") and table_exists(con, "audio_assets") and has_columns(con, "audio_projects", "final_audio_asset_id", "is_deleted")):
        return Action("Production", "PRODUCTION_SKIPPED", "Benötigte Tabellen/Spalten fehlen; Production-Reparatur übersprungen.", 0)

    bad = rows(
        con,
        f"""
        SELECT p.id AS project_id, p.title, p.final_audio_asset_id
        FROM audio_projects p
        LEFT JOIN audio_assets a ON a.id = p.final_audio_asset_id AND {active_clause('a')}
        WHERE {active_clause('p')} AND p.final_audio_asset_id IS NOT NULL AND a.id IS NULL
        ORDER BY p.id
        """,
    )
    changes: list[dict[str, Any]] = []
    for item in bad:
        candidates = rows(
            con,
            f"""
            SELECT id, display_title, is_final, status
            FROM audio_assets
            WHERE {active_clause()} AND project_id = ?
            ORDER BY is_final DESC, id DESC
            LIMIT 2
            """,
            (item["project_id"],),
        )
        new_id = candidates[0]["id"] if candidates else None
        changes.append({**item, "new_final_audio_asset_id": new_id, "mode": "replace" if new_id else "clear"})
        if not dry_run:
            con.execute("UPDATE audio_projects SET final_audio_asset_id=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (new_id, item["project_id"]))
    return Action("Production", "PRODUCTION_FINAL_ASSET_REPAIRED", "final_audio_asset_id wurde auf aktiven Projekt-Asset gesetzt oder sicher geleert.", len(changes), changes)


def repair_favorites(con: sqlite3.Connection, dry_run: bool) -> list[Action]:
    actions: list[Action] = []
    if table_exists(con, "songs") and table_exists(con, "audio_assets") and has_columns(con, "songs", "is_favorite", "is_deleted") and has_columns(con, "audio_assets", "song_id", "is_favorite", "is_deleted"):
        mismatch_song = rows(
            con,
            f"""
            SELECT s.id AS song_id, s.title, COALESCE(s.is_favorite,0) AS old_is_favorite,
                   COALESCE(MAX(CASE WHEN a.is_favorite THEN 1 ELSE 0 END),0) AS new_is_favorite,
                   GROUP_CONCAT(CASE WHEN a.is_favorite THEN a.id END) AS favorite_asset_ids
            FROM songs s
            LEFT JOIN audio_assets a ON a.song_id = s.id AND {active_clause('a')}
            WHERE {active_clause('s')}
            GROUP BY s.id
            HAVING COALESCE(s.is_favorite,0) != COALESCE(MAX(CASE WHEN a.is_favorite THEN 1 ELSE 0 END),0)
            ORDER BY s.id
            """,
        )
        if not dry_run:
            for item in mismatch_song:
                con.execute("UPDATE songs SET is_favorite=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (int(item["new_is_favorite"]), item["song_id"]))
        add_action(actions, "Favoriten", "FAVORITE_SONG_SYNC_REPAIRED", "songs.is_favorite wurde aus aktiven AudioAsset-Favoriten synchronisiert.", len(mismatch_song), mismatch_song)

    if table_exists(con, "audio_projects") and table_exists(con, "audio_assets") and has_columns(con, "audio_projects", "is_favorite", "is_deleted") and has_columns(con, "audio_assets", "project_id", "is_favorite", "is_deleted"):
        mismatch_project = rows(
            con,
            f"""
            SELECT p.id AS project_id, p.title, COALESCE(p.is_favorite,0) AS old_is_favorite,
                   COALESCE(MAX(CASE WHEN a.is_favorite THEN 1 ELSE 0 END),0) AS new_is_favorite,
                   GROUP_CONCAT(CASE WHEN a.is_favorite THEN a.id END) AS favorite_asset_ids
            FROM audio_projects p
            LEFT JOIN audio_assets a ON a.project_id = p.id AND {active_clause('a')}
            WHERE {active_clause('p')}
            GROUP BY p.id
            HAVING COALESCE(p.is_favorite,0) != COALESCE(MAX(CASE WHEN a.is_favorite THEN 1 ELSE 0 END),0)
            ORDER BY p.id
            """,
        )
        if not dry_run:
            for item in mismatch_project:
                con.execute("UPDATE audio_projects SET is_favorite=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (int(item["new_is_favorite"]), item["project_id"]))
        add_action(actions, "Favoriten", "FAVORITE_PROJECT_SYNC_REPAIRED", "audio_projects.is_favorite wurde aus aktiven AudioAsset-Favoriten synchronisiert.", len(mismatch_project), mismatch_project)
    return actions


def repair_srt_orphans(con: sqlite3.Connection, dry_run: bool) -> list[Action]:
    actions: list[Action] = []
    if not (table_exists(con, "audio_transcripts") and table_exists(con, "audio_assets") and has_columns(con, "audio_transcripts", "audio_asset_id", "status", "error_message")):
        return [Action("SRT", "SRT_SKIPPED", "Benötigte Tabellen/Spalten fehlen; SRT-Orphan-Reparatur übersprungen.", 0)]

    orphan = rows(
        con,
        f"""
        SELECT t.id, t.audio_asset_id, t.status, t.backend, t.generated_at, t.error_message
        FROM audio_transcripts t
        LEFT JOIN audio_assets a ON a.id = t.audio_asset_id AND {active_clause('a')}
        WHERE a.id IS NULL AND LOWER(COALESCE(t.status,'')) NOT IN ({','.join('?' for _ in ARCHIVED_TRANSCRIPT_STATUSES)})
        ORDER BY t.id
        """,
        tuple(ARCHIVED_TRANSCRIPT_STATUSES),
    )

    reassigned: list[dict[str, Any]] = []
    archived: list[dict[str, Any]] = []
    for transcript in orphan:
        old_asset = rowdict(con.execute("SELECT * FROM audio_assets WHERE id=?", (transcript["audio_asset_id"],)).fetchone())
        replacement = find_unambiguous_replacement_asset(con, old_asset)
        if replacement:
            reassigned.append({**transcript, "new_audio_asset_id": replacement["id"], "replacement_rule": replacement.get("replacement_rule"), "replacement_title": replacement.get("display_title")})
            if not dry_run:
                con.execute("UPDATE audio_transcripts SET audio_asset_id=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (replacement["id"], transcript["id"]))
        else:
            reason = "Quell-AudioAsset fehlt" if old_asset is None else "Quell-AudioAsset ist gelöscht; kein eindeutiger aktiver Ersatz gefunden"
            new_status = "orphaned" if old_asset is None else "archived_orphan"
            new_error = (transcript.get("error_message") or "").strip()
            note = f"Archiviert durch Feature-Root-Reparatur: {reason} (alte audio_asset_id={transcript['audio_asset_id']})."
            if note not in new_error:
                new_error = f"{note}\n{new_error}".strip()
            archived.append({**transcript, "new_status": new_status, "reason": reason})
            if not dry_run:
                con.execute("UPDATE audio_transcripts SET status=?, error_message=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (new_status, new_error, transcript["id"]))

    add_action(actions, "SRT", "SRT_ORPHAN_TRANSCRIPTS_REASSIGNED", "Verwaiste Transcripts wurden nur bei eindeutiger Zuordnung auf aktive AudioAssets umgehängt.", len(reassigned), reassigned)
    add_action(actions, "SRT", "SRT_ORPHAN_TRANSCRIPTS_ARCHIVED", "Nicht eindeutig zuordenbare Transcripts wurden als archivierte Orphans markiert, aber nicht gelöscht.", len(archived), archived)
    return actions


def repair_bulk_notifications(con: sqlite3.Connection, dry_run: bool) -> Action:
    if not (table_exists(con, "status_notifications") and has_columns(con, "status_notifications", "target_payload", "target_tab", "is_deleted")):
        return Action("Status/Notifications", "NOTIFICATIONS_SKIPPED", "Benötigte Tabellen/Spalten fehlen; Notification-Reparatur übersprungen.", 0)

    rows_to_fix = rows(
        con,
        f"""
        SELECT id, event_type, title, target_tab, target_payload
        FROM status_notifications
        WHERE {active_clause()}
          AND target_payload IS NOT NULL
          AND LOWER(COALESCE(event_type,'')) LIKE 'bulk_%_completed'
          AND COALESCE(target_tab,'') != 'status'
        ORDER BY id
        """,
    )
    fixed: list[dict[str, Any]] = []
    for item in rows_to_fix:
        payload = parse_json(item.get("target_payload"))
        if not isinstance(payload, dict):
            continue
        has_asset = bool(payload.get("audio_asset_id") or payload.get("primary_audio_asset_id") or payload.get("audio_asset_ids"))
        if has_asset:
            continue
        payload = dict(payload)
        payload["notification_scope"] = payload.get("notification_scope") or "batch_summary"
        payload["click_target"] = payload.get("click_target") or "status_detail"
        fixed.append({"id": item["id"], "event_type": item["event_type"], "old_target_tab": item["target_tab"], "new_target_tab": "status", "target_payload": payload})
        if not dry_run:
            con.execute("UPDATE status_notifications SET target_tab='status', target_payload=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (dump_json(payload), item["id"]))
    return Action("Status/Notifications", "BULK_SUCCESS_NOTIFICATIONS_ROUTED_TO_STATUS", "Batch-Erfolgsnotifications ohne einzelnes AudioAsset-Ziel wurden auf Statusdetails statt Library-Ziel gesetzt.", len(fixed), fixed)


def render_report(root: Path, db_path: Path, actions: list[Action], dry_run: bool, backup_path: Path | None) -> str:
    lines: list[str] = []
    lines.append("# Feature Root Workflow Findings Repair")
    lines.append("")
    lines.append(f"Erstellt: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`")
    lines.append(f"Projektpfad: `{root}`")
    lines.append(f"Datenbank: `{db_path}`")
    lines.append(f"Modus: `{'DRY-RUN / ROLLBACK' if dry_run else 'COMMIT'}`")
    if backup_path:
        lines.append(f"Backup: `{backup_path}`")
    lines.append("")
    lines.append("## Aktionen")
    lines.append("")
    lines.append("| Bereich | Code | Anzahl | Beschreibung |")
    lines.append("| --- | --- | ---: | --- |")
    for action in actions:
        lines.append(f"| {action.category} | {action.code} | {action.count} | {action.message.replace('|', '\\|')} |")
    lines.append("")
    for action in actions:
        if action.sample:
            lines.append(f"### Beispiele: {action.category} / {action.code}")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(action.sample, ensure_ascii=False, indent=2, default=str))
            lines.append("```")
            lines.append("")
    lines.append("## Nachprüfung")
    lines.append("")
    lines.append("```bash")
    lines.append(f"python3 scripts/audit_feature_root_workflows.py --database {db_path} --write-report")
    lines.append("python3 scripts/validate_unified_audio_workflow.py --database " + str(db_path))
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def write_report(root: Path, markdown: str, explicit_path: str | None = None) -> Path:
    if explicit_path:
        target = Path(explicit_path).expanduser()
        if not target.is_absolute():
            target = root / target
    else:
        target = root / "storage" / "reports" / f"feature_root_workflow_repair_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(markdown, encoding="utf-8")
    return target


def run(root: Path, db_path: Path, dry_run: bool, create_backup: bool) -> tuple[list[Action], Path | None]:
    if not db_path.exists():
        raise FileNotFoundError(f"Datenbank nicht gefunden: {db_path}")
    backup_path = backup_db(db_path, root) if create_backup and not dry_run else None
    con = connect(db_path)
    try:
        integrity = scalar(con, "PRAGMA integrity_check", default="unknown")
        if integrity != "ok":
            raise RuntimeError(f"SQLite integrity_check ist nicht ok: {integrity}")
        con.execute("BEGIN IMMEDIATE")
        actions: list[Action] = []
        actions.append(repair_production_final_asset(con, dry_run=dry_run))
        actions.extend(repair_srt_orphans(con, dry_run=dry_run))
        actions.extend(repair_favorites(con, dry_run=dry_run))
        actions.append(repair_bulk_notifications(con, dry_run=dry_run))
        if dry_run:
            con.rollback()
        else:
            con.commit()
        return actions, backup_path
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def print_console(root: Path, db_path: Path, actions: list[Action], dry_run: bool, backup_path: Path | None) -> None:
    print("Feature Root Workflow Findings Repair")
    print(f"Projektpfad : {root}")
    print(f"Datenbank   : {db_path}")
    print(f"Modus       : {'DRY-RUN / ROLLBACK' if dry_run else 'COMMIT'}")
    if backup_path:
        print(f"Backup      : {backup_path}")
    print()
    print("Aktionen:")
    for action in actions:
        print(f"  {action.category:<22} {action.code:<46} {action.count:>4}  {action.message}")
        for item in action.sample[:3]:
            print(f"    Beispiel: {item}")
    print()
    print("Nachprüfung:")
    print(f"  python3 scripts/audit_feature_root_workflows.py --database {db_path} --write-report")
    print(f"  python3 scripts/validate_unified_audio_workflow.py --database {db_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Lokale, kontrollierte Reparatur der Feature-Root-Audit-Befunde. Startet keine Audio-/SRT-/Stem-/Cover-Jobs.")
    parser.add_argument("--database", "--db", dest="database", default=None, help="Pfad zur SQLite-Datenbank. Default: ./suno_fastapi_app.db oder DATABASE_URL.")
    parser.add_argument("--project-root", default=None, help="Projektwurzel. Default: automatisch anhand des Skriptpfads.")
    parser.add_argument("--dry-run", action="store_true", help="Nur prüfen, Änderungen zurückrollen. Empfohlen vor --yes.")
    parser.add_argument("--yes", action="store_true", help="Änderungen wirklich schreiben. Ohne --yes läuft das Skript nur als Dry-Run.")
    parser.add_argument("--backup", action="store_true", help="Vor echten Änderungen ein DB-Backup unter storage/backups erstellen.")
    parser.add_argument("--write-report", action="store_true", help="Markdown-Report nach storage/reports schreiben.")
    parser.add_argument("--report", default=None, help="Expliziter Report-Pfad. Aktiviert automatisch --write-report.")
    args = parser.parse_args()

    root = Path(args.project_root).expanduser().resolve() if args.project_root else project_root().resolve()
    db_path = resolve_db_path(args.database, root)
    dry_run = args.dry_run or not args.yes

    if not dry_run and not args.backup:
        print("ABBRUCH: Für echte Änderungen bitte --backup verwenden.", file=sys.stderr)
        return 2

    actions, backup_path = run(root, db_path, dry_run=dry_run, create_backup=args.backup)
    print_console(root, db_path, actions, dry_run=dry_run, backup_path=backup_path)
    if args.write_report or args.report:
        target = write_report(root, render_report(root, db_path, actions, dry_run, backup_path), args.report)
        print(f"Report geschrieben: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

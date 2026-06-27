#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1] if Path(__file__).resolve().parent.name == "scripts" else Path.cwd()


def _backup_sqlite_database(db_path: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = backup_dir / f"{db_path.stem}.before-source-date-normalize-{timestamp}{db_path.suffix}"
    source = sqlite3.connect(str(db_path))
    try:
        target = sqlite3.connect(str(backup_path))
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(db_path) + suffix)
        if sidecar.exists():
            shutil.copy2(sidecar, backup_dir / f"{backup_path.name}{suffix}")
    return backup_path


def _integrity(db_path: Path) -> str:
    con = sqlite3.connect(str(db_path))
    try:
        return str(con.execute("PRAGMA integrity_check").fetchone()[0])
    finally:
        con.close()


def _source_date_from_asset(asset: Any, task: Any | None = None) -> datetime | None:
    from app.services.audio_cache_service import collect_audio_candidates, extract_source_created_at, parse_source_datetime

    metadata = asset.metadata_json if isinstance(asset.metadata_json, dict) else {}
    for source in (
        metadata,
        metadata.get("candidate") if isinstance(metadata.get("candidate"), dict) else None,
        metadata.get("request_payload") if isinstance(metadata.get("request_payload"), dict) else None,
    ):
        parsed = extract_source_created_at(source)
        if parsed:
            return parsed
        if isinstance(source, dict):
            parsed = parse_source_datetime(source.get("source_created_at"))
            if parsed:
                return parsed

    if task is not None:
        candidates = collect_audio_candidates({"response_payload": task.response_payload, "result_payload": task.result_payload})
        for candidate in candidates:
            if asset.audio_id and candidate.audio_id and str(asset.audio_id) == str(candidate.audio_id) and candidate.created_at:
                return candidate.created_at
            if asset.source_url and candidate.source_url and str(asset.source_url) == str(candidate.source_url) and candidate.created_at:
                return candidate.created_at
        for candidate in candidates:
            if candidate.created_at:
                return candidate.created_at
    return None


def _set_source_date_metadata(asset: Any, source_dt: datetime) -> bool:
    metadata = asset.metadata_json if isinstance(asset.metadata_json, dict) else {}
    value = source_dt.isoformat()
    changed = False
    if metadata.get("source_created_at") != value:
        metadata["source_created_at"] = value
        changed = True
    candidate = metadata.get("candidate") if isinstance(metadata.get("candidate"), dict) else None
    if candidate is not None and not any(candidate.get(k) for k in ("created_at", "createdAt", "createTime")):
        candidate["created_at"] = value
        metadata["candidate"] = candidate
        changed = True
    if changed:
        asset.metadata_json = metadata
    return changed


def _normalize(db: Any, *, dry_run: bool) -> dict[str, Any]:
    from app.models import AudioAsset, AudioProject, Song, SunoTask

    stats: dict[str, Any] = {
        "assets_seen": 0,
        "assets_with_source_date": 0,
        "asset_dates_updated": 0,
        "asset_metadata_updated": 0,
        "song_dates_updated": 0,
        "project_dates_updated": 0,
        "task_dates_updated": 0,
        "examples": [],
    }

    assets = (
        db.query(AudioAsset)
        .filter(AudioAsset.is_deleted.is_(False))
        .order_by(AudioAsset.id.asc())
        .all()
    )

    task_cache: dict[int, Any] = {}
    song_min_dates: dict[int, datetime] = {}
    project_min_dates: dict[int, datetime] = {}
    task_min_dates: dict[int, datetime] = {}

    for asset in assets:
        stats["assets_seen"] += 1
        task = None
        if asset.task_local_id:
            task_id = int(asset.task_local_id)
            if task_id not in task_cache:
                task_cache[task_id] = db.query(SunoTask).filter(SunoTask.id == task_id).first()
            task = task_cache.get(task_id)
        source_dt = _source_date_from_asset(asset, task)
        if not source_dt:
            continue
        stats["assets_with_source_date"] += 1

        if asset.created_at and asset.created_at != source_dt:
            # Für Suno/SunoAPI-Importe soll die Library nach externem Erstelldatum laufen.
            if not dry_run:
                asset.created_at = source_dt
            stats["asset_dates_updated"] += 1
        if _set_source_date_metadata(asset, source_dt):
            stats["asset_metadata_updated"] += 1
        if asset.song_id:
            current = song_min_dates.get(int(asset.song_id))
            if current is None or source_dt < current:
                song_min_dates[int(asset.song_id)] = source_dt
        if asset.project_id:
            current = project_min_dates.get(int(asset.project_id))
            if current is None or source_dt < current:
                project_min_dates[int(asset.project_id)] = source_dt
        if asset.task_local_id:
            current = task_min_dates.get(int(asset.task_local_id))
            if current is None or source_dt < current:
                task_min_dates[int(asset.task_local_id)] = source_dt
        if len(stats["examples"]) < 5:
            stats["examples"].append({"audio_asset_id": asset.id, "title": asset.display_title or asset.title, "source_created_at": source_dt.isoformat()})
        db.add(asset)

    for song_id, source_dt in song_min_dates.items():
        song = db.query(Song).filter(Song.id == song_id, Song.is_deleted.is_(False)).first()
        if song and song.created_at and song.created_at != source_dt:
            if not dry_run:
                song.created_at = source_dt
            stats["song_dates_updated"] += 1
            db.add(song)

    for project_id, source_dt in project_min_dates.items():
        project = db.query(AudioProject).filter(AudioProject.id == project_id, AudioProject.is_deleted.is_(False)).first()
        if project and project.created_at and project.created_at != source_dt:
            if not dry_run:
                project.created_at = source_dt
            stats["project_dates_updated"] += 1
            db.add(project)

    for task_id, source_dt in task_min_dates.items():
        task = db.query(SunoTask).filter(SunoTask.id == task_id, SunoTask.is_deleted.is_(False)).first()
        if task and task.created_at and task.created_at != source_dt:
            if not dry_run:
                task.created_at = source_dt
            stats["task_dates_updated"] += 1
            db.add(task)

    if dry_run:
        db.rollback()
    else:
        db.commit()
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalisiert lokale Import-Daten auf Suno/SunoAPI.org-Erstelldatum.")
    parser.add_argument("--database", default="./suno_fastapi_app.db")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--backup", action="store_true")
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()

    root = _project_root()
    db_path = Path(args.database).expanduser().resolve()
    if not db_path.exists():
        print(f"Datenbank nicht gefunden: {db_path}", file=sys.stderr)
        return 2

    os.chdir(root)
    sys.path.insert(0, str(root))
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"

    print("Suno Source-Date Normalization")
    print(f"Projektpfad : {root}")
    print(f"Datenbank   : {db_path}")
    print(f"Modus       : {'DRY-RUN / ROLLBACK' if args.dry_run else 'COMMIT'}")
    print(f"Integrity   : {_integrity(db_path)}")

    backup = None
    if args.backup:
        backup = _backup_sqlite_database(db_path, root / "storage" / "backups")
        print(f"Backup      : {backup.relative_to(root) if backup.is_relative_to(root) else backup}")

    if not args.dry_run and not args.yes:
        print("Abbruch: Für echte Änderungen bitte --yes setzen.", file=sys.stderr)
        return 3

    from app.database import SessionLocal

    db = SessionLocal()
    try:
        stats = _normalize(db, dry_run=bool(args.dry_run))
    finally:
        db.close()

    print("\nZusammenfassung")
    for key, value in stats.items():
        if key == "examples":
            continue
        print(f"  {key:28s}: {value}")
    if stats["examples"]:
        print("\nBeispiele:")
        for example in stats["examples"]:
            print(f"  {example}")
    print("\nNachprüfung:")
    print(f"  python3 scripts/audit_unified_audio_state.py --database {db_path}")
    print(f"  python3 scripts/audit_feature_root_workflows.py --database {db_path} --write-report")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

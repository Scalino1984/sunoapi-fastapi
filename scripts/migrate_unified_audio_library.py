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


SUCCESS_STATUSES = {"SUCCESS", "COMPLETED", "COMPLETE", "DONE", "IMPORTED", "PARTIAL_SUCCESS", "FIRST_SUCCESS"}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1] if Path(__file__).resolve().parent.name == "scripts" else Path.cwd()


def _sqlite_path_from_url(database_url: str) -> Path | None:
    if not database_url.startswith("sqlite"):
        return None
    if database_url.startswith("sqlite:///"):
        raw = database_url.replace("sqlite:///", "", 1)
        return Path(raw).resolve()
    if database_url.startswith("sqlite://"):
        raw = database_url.replace("sqlite://", "", 1)
        return Path(raw).resolve()
    return None


def _backup_sqlite_database(db_path: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = backup_dir / f"{db_path.stem}.before-unified-audio-{timestamp}{db_path.suffix}"

    # SQLite Online-Backup ist sicherer als plain copy, falls aus Versehen noch ein Prozess liest.
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


def _sqlite_integrity_check(db_path: Path) -> str:
    con = sqlite3.connect(str(db_path))
    try:
        return str(con.execute("PRAGMA integrity_check").fetchone()[0])
    finally:
        con.close()


def _has_active_audio_asset(db: Any, AudioAsset: Any, *, source_url: str | None = None, audio_id: str | None = None, song_id: int | None = None) -> bool:
    query = db.query(AudioAsset).filter(AudioAsset.is_deleted.is_(False))
    if audio_id:
        if query.filter(AudioAsset.audio_id == str(audio_id)).first():
            return True
    if source_url:
        if db.query(AudioAsset).filter(AudioAsset.source_url == source_url, AudioAsset.is_deleted.is_(False)).first():
            return True
    if song_id:
        if db.query(AudioAsset).filter(AudioAsset.song_id == song_id, AudioAsset.is_deleted.is_(False)).first():
            return True
    return False


def _backfill_orphan_song_audio_assets(db: Any) -> tuple[int, int]:
    from app.models import AudioAsset, AudioProject, Song
    from app.services.audio_asset_repair_service import is_audio_url, repair_local_file_metadata

    created = 0
    skipped = 0
    songs = (
        db.query(Song)
        .filter(Song.is_deleted.is_(False), Song.audio_url.isnot(None))
        .order_by(Song.id.asc())
        .all()
    )

    for song in songs:
        source_url = (song.audio_url or "").strip()
        if not source_url or not is_audio_url(source_url):
            skipped += 1
            continue
        if _has_active_audio_asset(db, AudioAsset, source_url=source_url, song_id=song.id):
            skipped += 1
            continue

        project_id = song.project_id
        if not project_id:
            project = AudioProject(
                title=song.title or "Unbenannt",
                cover_image_url=song.cover_image_url,
                metadata_json={"created_by": "migrate_unified_audio_library", "source": "orphan_song"},
            )
            db.add(project)
            db.flush()
            project_id = project.id
            song.project_id = project_id
            db.add(song)

        asset = AudioAsset(
            task_local_id=None,
            song_id=song.id,
            suno_task_id=song.task_id,
            audio_id=None,
            title=song.title,
            display_title=song.title or "Unbenannt",
            image_url=song.cover_image_url,
            source_url=source_url,
            local_path=None,
            public_url=None,
            filename=None,
            status="remote",
            project_id=project_id,
            operation_label="Importiert",
            version_label=song.version_label,
            is_favorite=bool(song.is_favorite),
            is_final=bool(song.is_final),
            waveform_json=song.waveform_json,
            waveform_generated_at=song.waveform_generated_at,
            structure_segments_json=song.structure_segments_json,
            metadata_json={
                "created_by": "migrate_unified_audio_library",
                "source": "orphan_song",
                "song_metadata": song.metadata_json if isinstance(song.metadata_json, dict) else {},
            },
        )
        repair_local_file_metadata(asset)
        db.add(asset)
        db.flush()
        created += 1

    return created, skipped


def run() -> int:
    parser = argparse.ArgumentParser(
        description="Migriert bestehende Suno Song Studio SQLite-Daten in den vereinheitlichten audio_assets-Workflow."
    )
    parser.add_argument("--database", default="", help="Pfad zur SQLite-DB oder vollständige DATABASE_URL. Standard: .env/DATABASE_URL")
    parser.add_argument("--backup", action="store_true", help="Vor der Migration ein SQLite-Backup erstellen.")
    parser.add_argument("--backup-dir", default="storage/backups", help="Zielordner für Backups. Standard: storage/backups")
    parser.add_argument("--dry-run", action="store_true", help="Analyse ausführen, Änderungen aber zurückrollen.")
    parser.add_argument("--limit", type=int, default=0, help="Maximale Anzahl SunoTasks. 0 = alle passenden Tasks.")
    parser.add_argument("--force", action="store_true", help="Auch Tasks mit nicht-finalem Status materialisieren, wenn Audio-URLs vorhanden sind.")
    parser.add_argument("--skip-orphan-songs", action="store_true", help="Songs.audio_url ohne AudioAsset nicht nachziehen.")
    parser.add_argument("--yes", action="store_true", help="Keine interaktive Sicherheitsabfrage.")
    args = parser.parse_args()

    root = _project_root()
    os.chdir(root)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    if args.database:
        database = args.database.strip()
        if database.startswith("sqlite:"):
            os.environ["DATABASE_URL"] = database
        else:
            os.environ["DATABASE_URL"] = f"sqlite:///{Path(database).resolve()}"

    # Imports erst nach DATABASE_URL-Override.
    from app.database import SessionLocal, init_db, settings
    from app.models import AudioAsset, Song, SunoTask
    from app.services.audio_asset_materialization_service import AudioAssetMaterializationService
    from app.services.audio_cache_service import collect_audio_candidates

    db_path = _sqlite_path_from_url(settings.database_url)
    if db_path is None:
        print(f"ABBRUCH: Dieses Skript ist für SQLite gedacht. DATABASE_URL={settings.database_url}", file=sys.stderr)
        return 2
    if not db_path.exists():
        print(f"ABBRUCH: SQLite-Datenbank nicht gefunden: {db_path}", file=sys.stderr)
        return 2

    print("Unified-Audio-Migration")
    print(f"Projektpfad : {root}")
    print(f"Datenbank   : {db_path}")
    print(f"Dry-Run     : {args.dry_run}")

    integrity = _sqlite_integrity_check(db_path)
    print(f"Integrity   : {integrity}")
    if integrity.lower() != "ok":
        print("ABBRUCH: SQLite integrity_check ist nicht OK. Erst Backup prüfen/reparieren.", file=sys.stderr)
        return 3

    if args.backup:
        backup_path = _backup_sqlite_database(db_path, Path(args.backup_dir))
        print(f"Backup      : {backup_path}")
    elif not args.dry_run and not args.yes:
        print("ABBRUCH: Für echte Änderungen bitte --backup oder --yes verwenden.", file=sys.stderr)
        return 4

    if not args.yes and not args.dry_run:
        answer = input("Migration wirklich ausführen? Tippe JA: ").strip()
        if answer != "JA":
            print("Abgebrochen.")
            return 0

    init_db()
    db = SessionLocal()
    try:
        before_assets = db.query(AudioAsset).filter(AudioAsset.is_deleted.is_(False)).count()
        before_songs = db.query(Song).filter(Song.is_deleted.is_(False)).count()
        before_tasks = db.query(SunoTask).filter(SunoTask.is_deleted.is_(False)).count()

        task_query = db.query(SunoTask).filter(SunoTask.is_deleted.is_(False)).order_by(SunoTask.id.asc())
        if not args.force:
            task_query = task_query.filter(SunoTask.status.in_(sorted(SUCCESS_STATUSES)))
        if args.limit and args.limit > 0:
            task_query = task_query.limit(args.limit)
        tasks = task_query.all()

        materialized_created = 0
        materialized_updated = 0
        materialized_skipped_deleted = 0
        candidate_tasks = 0
        no_candidate_tasks = 0

        service = AudioAssetMaterializationService(db)
        for task in tasks:
            payload = {"response_payload": task.response_payload, "result_payload": task.result_payload}
            candidates = collect_audio_candidates(payload)
            if not candidates:
                no_candidate_tasks += 1
                continue
            candidate_tasks += 1
            result = service.materialize_task(task, force=args.force, commit=False)
            materialized_created += result.created
            materialized_updated += result.updated
            materialized_skipped_deleted += result.skipped_deleted

        orphan_created = 0
        orphan_skipped = 0
        if not args.skip_orphan_songs:
            orphan_created, orphan_skipped = _backfill_orphan_song_audio_assets(db)

        after_assets_pending = db.query(AudioAsset).filter(AudioAsset.is_deleted.is_(False)).count()

        if args.dry_run:
            db.rollback()
            action = "ROLLBACK / Dry-Run"
        else:
            db.commit()
            action = "COMMIT"

        print()
        print("Zusammenfassung")
        print(f"Aktion                         : {action}")
        print(f"SunoTasks aktiv vorher          : {before_tasks}")
        print(f"Songs aktiv vorher              : {before_songs}")
        print(f"AudioAssets aktiv vorher        : {before_assets}")
        print(f"Tasks mit Audio-Kandidaten      : {candidate_tasks}")
        print(f"Tasks ohne Audio-Kandidaten     : {no_candidate_tasks}")
        print(f"AudioAssets aus Tasks erstellt  : {materialized_created}")
        print(f"AudioAssets aus Tasks ergänzt   : {materialized_updated}")
        print(f"Gelöschte Treffer übersprungen  : {materialized_skipped_deleted}")
        print(f"Orphan-Song-Assets erstellt     : {orphan_created}")
        print(f"Orphan-Songs übersprungen       : {orphan_skipped}")
        print(f"AudioAssets aktiv danach        : {after_assets_pending if not args.dry_run else before_assets + materialized_created + orphan_created}")

        print()
        print("Nächster Prüfbefehl:")
        print("sqlite3 suno_fastapi_app.db \"SELECT COUNT(*) FROM audio_assets WHERE is_deleted=0;\"")
        return 0
    except Exception as exc:
        db.rollback()
        print(f"FEHLER: Migration wurde zurückgerollt: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(run())

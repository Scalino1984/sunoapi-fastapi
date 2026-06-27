import logging
from collections.abc import Generator
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import NullPool

from app.config import get_settings

logger = logging.getLogger("songstudio.database")


settings = get_settings()

IS_SQLITE = settings.database_url.startswith("sqlite")
connect_args = {"check_same_thread": False, "timeout": 60} if IS_SQLITE else {}
engine_kwargs = {"connect_args": connect_args, "pool_pre_ping": True}
if IS_SQLITE:
    # SQLite ist für lokale Single-Server-Setups okay, muss aber kurze
    # Transaktionen und einen hohen Busy-Timeout nutzen, damit Background-Jobs
    # Audio-Streaming/Statusabfragen nicht dauerhaft blockieren.
    engine_kwargs["poolclass"] = NullPool

engine = create_engine(settings.database_url, **engine_kwargs)


if IS_SQLITE:
    @event.listens_for(engine, "connect")
    def _configure_sqlite_connection(dbapi_connection, connection_record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA busy_timeout=60000")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA synchronous=NORMAL")
        finally:
            cursor.close()


def _enable_sqlite_wal_once() -> None:
    if not IS_SQLITE:
        return
    try:
        with engine.begin() as connection:
            connection.execute(text("PRAGMA journal_mode=WAL"))
            connection.execute(text("PRAGMA synchronous=NORMAL"))
            connection.execute(text("PRAGMA busy_timeout=60000"))
    except Exception:
        logger.exception("SQLite WAL konnte nicht initialisiert werden.")

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _sqlite_add_column_if_missing(table_name: str, column_name: str, column_sql: str) -> None:
    if not settings.database_url.startswith("sqlite"):
        return

    inspector = inspect(engine)
    if table_name not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
    if column_name in existing_columns:
        return

    with engine.begin() as connection:
        connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}"))


def _run_lightweight_sqlite_migrations() -> None:
    soft_delete_tables = [
        "suno_tasks",
        "songs",
        "audio_assets",
        "uploaded_files",
        "personas",
        "playlists",
        "lyric_drafts",
        "music_styles",
        "audio_projects",
        "production_profiles",
        "vocal_tags",
    ]
    for table_name in soft_delete_tables:
        _sqlite_add_column_if_missing(table_name, "is_deleted", "is_deleted BOOLEAN DEFAULT 0 NOT NULL")
        _sqlite_add_column_if_missing(table_name, "deleted_at", "deleted_at DATETIME")
        _sqlite_add_column_if_missing(table_name, "deleted_reason", "deleted_reason TEXT")

    _sqlite_add_column_if_missing("audio_assets", "image_url", "image_url TEXT")
    _sqlite_add_column_if_missing("audio_assets", "project_id", "project_id INTEGER")
    _sqlite_add_column_if_missing("audio_assets", "display_title", "display_title VARCHAR(255)")
    _sqlite_add_column_if_missing("audio_assets", "operation_label", "operation_label VARCHAR(120)")
    _sqlite_add_column_if_missing("audio_assets", "parent_audio_id", "parent_audio_id VARCHAR(255)")
    _sqlite_add_column_if_missing("audio_assets", "parent_task_id", "parent_task_id VARCHAR(255)")
    _sqlite_add_column_if_missing("audio_assets", "version_label", "version_label VARCHAR(120)")
    _sqlite_add_column_if_missing("audio_assets", "is_favorite", "is_favorite BOOLEAN DEFAULT 0 NOT NULL")
    _sqlite_add_column_if_missing("audio_assets", "is_final", "is_final BOOLEAN DEFAULT 0 NOT NULL")
    _sqlite_add_column_if_missing("audio_assets", "waveform_json", "waveform_json JSON")
    _sqlite_add_column_if_missing("audio_assets", "waveform_generated_at", "waveform_generated_at DATETIME")
    _sqlite_add_column_if_missing("audio_assets", "structure_segments_json", "structure_segments_json JSON")
    _sqlite_add_column_if_missing("songs", "cover_image_url", "cover_image_url TEXT")
    _sqlite_add_column_if_missing("songs", "project_id", "project_id INTEGER")
    _sqlite_add_column_if_missing("songs", "is_favorite", "is_favorite BOOLEAN DEFAULT 0 NOT NULL")
    _sqlite_add_column_if_missing("songs", "is_final", "is_final BOOLEAN DEFAULT 0 NOT NULL")
    _sqlite_add_column_if_missing("songs", "waveform_json", "waveform_json JSON")
    _sqlite_add_column_if_missing("songs", "waveform_generated_at", "waveform_generated_at DATETIME")
    _sqlite_add_column_if_missing("songs", "structure_segments_json", "structure_segments_json JSON")
    _sqlite_add_column_if_missing("songs", "version_label", "version_label VARCHAR(120)")
    _sqlite_add_column_if_missing("music_styles", "profile_json", "profile_json JSON")
    _sqlite_add_column_if_missing("music_styles", "is_profile", "is_profile BOOLEAN DEFAULT 0 NOT NULL")
    _sqlite_add_column_if_missing("users", "is_admin", "is_admin BOOLEAN DEFAULT 0 NOT NULL")
    _sqlite_add_column_if_missing("users", "nickname", "nickname VARCHAR(120)")
    _sqlite_add_column_if_missing("ai_chat_sessions", "assistant_profile_id", "assistant_profile_id INTEGER")

    # Lokale Background-Job-Steuerung/Watchdog. Die Spalten werden bewusst
    # leichtgewichtig ergänzt, damit bestehende SQLite-Installationen ohne
    # Alembic-Migration weiterlaufen.
    _sqlite_add_column_if_missing("suno_tasks", "started_at", "started_at DATETIME")
    _sqlite_add_column_if_missing("suno_tasks", "heartbeat_at", "heartbeat_at DATETIME")
    _sqlite_add_column_if_missing("suno_tasks", "completed_at", "completed_at DATETIME")
    _sqlite_add_column_if_missing("suno_tasks", "cancel_requested", "cancel_requested BOOLEAN DEFAULT 0 NOT NULL")



def _seed_default_vocal_tags_and_admin() -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    with engine.begin() as connection:
        # Wenn es Benutzer, aber noch keinen Admin gibt, wird der erste Benutzer Admin.
        try:
            users = connection.execute(text("SELECT id FROM users ORDER BY id ASC LIMIT 1")).fetchall()
            admins = connection.execute(text("SELECT id FROM users WHERE is_admin = 1 LIMIT 1")).fetchall()
            if users and not admins:
                connection.execute(text("UPDATE users SET is_admin = 1 WHERE id = :id"), {"id": users[0][0]})
        except Exception:
            pass

        try:
            count = connection.execute(text("SELECT COUNT(*) FROM vocal_tags")).scalar()
        except Exception:
            count = 0
        if count:
            return
        defaults = [
            ("German Male Rap", "[Verse 1 | German Male Rap | powerful / dramatic / emotional | Energy: High]", "Verse", 10),
            ("German Male Sung Hook", "[Chorus | German Male Sung | powerful / emotional | Energy: High]", "Hook", 20),
            ("Jamaican Patois Toasting", "[Verse 2 | Jamaican Patois Toasting | gritty / rhythmic / confident | Energy: High]", "Verse", 30),
            ("Low Spoken Intro", "[Intro | spoken male vocal | low energy | intimate / dark]", "Intro", 40),
            ("Bridge Atmospheric", "[Bridge | German Male Vocal | atmospheric / melancholic / rising tension | Energy: Medium]", "Bridge", 50),
            ("Adlibs", "[Adlibs | whispered doubles | background shouts | stereo delays]", "Adlibs", 60),
            ("Outro", "[Outro | spoken male vocal | fading / reflective | Energy: Low]", "Outro", 70),
            ("Female Hook", "[Chorus | Female Sung Vocal | soulful / wide / emotional | Energy: High]", "Hook", 80),
            ("Aggressive Drill Verse", "[Verse | German Male Rap | aggressive / precise / dark drill flow | Energy: High]", "Verse", 90),
            ("Reggae Toasting Hook", "[Hook | Jamaican Patois Toasting | melodic / bouncy / call and response | Energy: Medium]", "Hook", 100),
        ]
        for label, tag, category, sort_order in defaults:
            connection.execute(
                text("INSERT INTO vocal_tags (label, tag, category, sort_order, is_active, is_deleted, created_at, updated_at) VALUES (:label, :tag, :category, :sort_order, 1, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"),
                {"label": label, "tag": tag, "category": category, "sort_order": sort_order},
            )

_PERFORMANCE_INDEXES: list[tuple[str, str]] = [
    # Hot list path (active_usable_audio_assets ordert nach created_at desc, id desc)
    ("ix_audio_assets_deleted_created_id", "audio_assets (is_deleted, created_at, id)"),
    ("ix_audio_assets_deleted_updated_id", "audio_assets (is_deleted, updated_at, id)"),
    ("ix_audio_assets_project_deleted_created", "audio_assets (project_id, is_deleted, created_at)"),
    ("ix_audio_assets_song_deleted", "audio_assets (song_id, is_deleted)"),
    # Task-Listen + Watchdog/Recovery
    ("ix_suno_tasks_deleted_status_created", "suno_tasks (is_deleted, status, created_at)"),
    ("ix_suno_tasks_deleted_type_status", "suno_tasks (is_deleted, task_type, status)"),
    # Notifications
    ("ix_status_notifications_deleted_status_created", "status_notifications (is_deleted, status, created_at)"),
    ("ix_status_notifications_task_local", "status_notifications (task_local_id, is_deleted)"),
    # Transkripte
    ("ix_audio_transcripts_asset_status_updated", "audio_transcripts (audio_asset_id, status, updated_at, id)"),
    # Playlists / Activity
    ("ix_playlist_items_playlist_position", "playlist_items (playlist_id, position, id)"),
    ("ix_activity_log_content_created", "activity_log (content_type, content_id, created_at)"),
]


def ensure_performance_indexes() -> None:
    """Legt zusammengesetzte Indizes idempotent an (CREATE INDEX IF NOT EXISTS).

    SQLite nutzt bei Filter+Sortierung sonst nur Teil-Indizes; diese Compound-
    Indizes beschleunigen die heißen Listen-/Status-/Watchdog-Queries deutlich.
    """

    with engine.begin() as connection:
        for index_name, table_cols in _PERFORMANCE_INDEXES:
            try:
                connection.execute(text(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_cols}"))
            except Exception:
                logger.exception("Konnte Index %s nicht anlegen.", index_name)


def init_db() -> None:
    from app import models  # noqa: F401

    _enable_sqlite_wal_once()
    Base.metadata.create_all(bind=engine)
    _run_lightweight_sqlite_migrations()
    ensure_performance_indexes()
    _seed_default_vocal_tags_and_admin()

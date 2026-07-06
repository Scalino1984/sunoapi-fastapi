from datetime import datetime
from sqlalchemy import DateTime, Integer, String, Text, JSON, BigInteger, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from app.utils.time_utils import utc_now_naive

from app.database import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive, onupdate=utc_now_naive, nullable=False)


class SoftDeleteMixin:
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deleted_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    nickname: Mapped[str | None] = mapped_column(String(120), nullable=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ActivityLog(Base, TimestampMixin):
    __tablename__ = "activity_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    action: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    content_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    old_value: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    new_value: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)




class StatusNotification(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "status_notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    event_type: Mapped[str] = mapped_column(String(120), index=True, nullable=False, default="task_status")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str] = mapped_column(String(40), index=True, nullable=False, default="info")
    status: Mapped[str] = mapped_column(String(40), index=True, nullable=False, default="unread")
    task_local_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    suno_task_id: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(80), index=True, nullable=True)
    content_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    target_tab: Mapped[str | None] = mapped_column(String(80), nullable=True)
    target_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

class AppSetting(Base, TimestampMixin):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    key: Mapped[str] = mapped_column(String(160), unique=True, index=True, nullable=False)
    value: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class VocalTag(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "vocal_tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    label: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    tag: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(120), index=True, default="Tags", nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class SunoTask(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "suno_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    task_id: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    task_type: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(80), index=True, default="created", nullable=False)
    request_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    response_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    result_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Song(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "songs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    lyrics: Mapped[str | None] = mapped_column(Text, nullable=True)
    audio_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    video_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    midi_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    wav_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    task_id: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    project_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_final: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    waveform_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    waveform_generated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    structure_segments_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    version_label: Mapped[str | None] = mapped_column(String(120), nullable=True)

    @property
    def source_image_url(self) -> str | None:
        metadata = self.metadata_json or {}
        cover_cache = metadata.get("cover_cache") if isinstance(metadata, dict) else None
        if isinstance(cover_cache, dict) and cover_cache.get("source_url"):
            return cover_cache.get("source_url")
        if isinstance(metadata, dict) and metadata.get("source_image_url"):
            return metadata.get("source_image_url")
        return self.cover_image_url

    @property
    def cover_local_url(self) -> str | None:
        metadata = self.metadata_json or {}
        cover_cache = metadata.get("cover_cache") if isinstance(metadata, dict) else None
        if isinstance(cover_cache, dict) and cover_cache.get("public_url"):
            return cover_cache.get("public_url")
        image = self.cover_image_url or ""
        if image.startswith("/media/covers/"):
            return image
        return None

    @property
    def cover_cached(self) -> bool:
        return bool(self.cover_local_url)

    @property
    def capabilities(self) -> dict | None:
        metadata = self.metadata_json or {}
        value = metadata.get("capabilities") if isinstance(metadata, dict) else None
        return value if isinstance(value, dict) else None

    @property
    def import_source(self) -> str | None:
        metadata = self.metadata_json or {}
        return metadata.get("import_source") if isinstance(metadata, dict) else None

    @property
    def generation_source(self) -> str | None:
        metadata = self.metadata_json or {}
        return metadata.get("generation_source") if isinstance(metadata, dict) else None

    @property
    def is_suno_clip_import(self) -> bool:
        metadata = self.metadata_json or {}
        return bool(isinstance(metadata, dict) and metadata.get("is_suno_clip_import"))

    @property
    def is_opencli_generation(self) -> bool:
        metadata = self.metadata_json or {}
        return bool(isinstance(metadata, dict) and metadata.get("is_opencli_generation"))


class AudioAsset(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "audio_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    task_local_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    song_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    suno_task_id: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    audio_id: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    local_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    public_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    status: Mapped[str] = mapped_column(String(50), index=True, default="created", nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    project_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    display_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    operation_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    parent_audio_id: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    parent_task_id: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    version_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_final: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    waveform_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    waveform_generated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    structure_segments_json: Mapped[list | None] = mapped_column(JSON, nullable=True)

    @staticmethod
    def _is_local_audio_reference(value: str | None) -> bool:
        if not value:
            return False
        normalized = str(value).strip().replace("\\", "/")
        if not normalized:
            return False
        return (
            normalized.startswith("/media/audio/")
            or normalized.startswith("media/audio/")
            or normalized.startswith("storage/audio/")
            or "/storage/audio/" in normalized
            or "/media/audio/" in normalized
        )

    @property
    def audio_local(self) -> bool:
        """Read-only API flag: concrete playable audio is locally materialized.

        The Library UI must not infer local availability from missing schema
        values.  The database stores this state as operational metadata rather
        than a dedicated column: cached status plus known local/public media
        paths means the asset can be treated as locally available.  This
        intentionally avoids filesystem checks in read/list endpoints so that
        Library rendering stays fast and side-effect free.
        """
        status = str(self.status or "").strip().lower()
        if status != "cached":
            return False
        return any(
            self._is_local_audio_reference(value)
            for value in (self.local_path, self.public_url, self.source_url, self.filename)
        ) or bool(self.local_path or self.public_url or self.filename)

    @property
    def audio_availability_status(self) -> str:
        """Stable frontend status for local/remote/missing audio decisions."""
        status = str(self.status or "").strip().lower()
        if self.audio_local:
            return "cached"
        if status in {"failed", "error"}:
            return "failed"
        if status in {"deleted", "missing"}:
            return "missing"
        candidate = self._metadata_candidate()
        has_remote_reference = any(
            str(value or "").strip().lower().startswith(("http://", "https://"))
            for value in (
                self.source_url,
                self.public_url,
                candidate.get("audioUrl"),
                candidate.get("sourceAudioUrl"),
                candidate.get("streamAudioUrl"),
                candidate.get("sourceStreamAudioUrl"),
            )
        )
        if has_remote_reference or status == "remote":
            return "remote"
        if status in {"created", "queued", "running", "processing"}:
            return status
        return status or "missing"

    @property
    def audio_local_reason(self) -> str | None:
        """Machine-readable reason when `audio_local` is false."""
        if self.audio_local:
            return None
        availability = self.audio_availability_status
        if availability == "remote":
            return "remote_only"
        if availability == "failed":
            return self.error_message or "cache_failed"
        if availability == "missing":
            return "missing_audio"
        if availability in {"created", "queued", "running", "processing"}:
            return "not_cached_yet"
        return "not_cached"

    def _metadata_candidate(self) -> dict:
        metadata = self.metadata_json or {}
        candidate = metadata.get("candidate") if isinstance(metadata, dict) else None
        return candidate if isinstance(candidate, dict) else {}

    def _metadata_request_payload(self) -> dict:
        metadata = self.metadata_json or {}
        request_payload = metadata.get("request_payload") if isinstance(metadata, dict) else None
        return request_payload if isinstance(request_payload, dict) else {}

    @property
    def prompt(self) -> str | None:
        candidate = self._metadata_candidate()
        request_payload = self._metadata_request_payload()
        return candidate.get("prompt") or request_payload.get("prompt") or request_payload.get("lyrics")

    @property
    def lyrics(self) -> str | None:
        candidate = self._metadata_candidate()
        request_payload = self._metadata_request_payload()
        return candidate.get("lyrics") or candidate.get("text") or request_payload.get("lyrics")

    @property
    def style(self) -> str | None:
        candidate = self._metadata_candidate()
        request_payload = self._metadata_request_payload()
        return candidate.get("tags") or candidate.get("style") or request_payload.get("style") or request_payload.get("tags")

    @property
    def tags(self) -> str | None:
        return self.style

    @property
    def model_name(self) -> str | None:
        candidate = self._metadata_candidate()
        request_payload = self._metadata_request_payload()
        return candidate.get("modelName") or candidate.get("model") or request_payload.get("model")

    @property
    def source_audio_url(self) -> str | None:
        return self._metadata_candidate().get("sourceAudioUrl") or self._metadata_candidate().get("source_audio_url")

    @property
    def stream_audio_url(self) -> str | None:
        candidate = self._metadata_candidate()
        return candidate.get("streamAudioUrl") or candidate.get("sourceStreamAudioUrl")

    @property
    def source_image_url(self) -> str | None:
        metadata = self.metadata_json or {}
        cover_cache = metadata.get("cover_cache") if isinstance(metadata, dict) else None
        if isinstance(cover_cache, dict) and cover_cache.get("source_url"):
            return cover_cache.get("source_url")
        if isinstance(metadata, dict) and metadata.get("source_image_url"):
            return metadata.get("source_image_url")
        candidate = self._metadata_candidate()
        return candidate.get("sourceImageUrl") or candidate.get("imageUrl") or self.image_url

    @property
    def cover_local_url(self) -> str | None:
        metadata = self.metadata_json or {}
        cover_cache = metadata.get("cover_cache") if isinstance(metadata, dict) else None
        if isinstance(cover_cache, dict) and cover_cache.get("public_url"):
            return cover_cache.get("public_url")
        image = self.image_url or ""
        if image.startswith("/media/covers/"):
            return image
        return None

    @property
    def cover_cached(self) -> bool:
        return bool(self.cover_local_url)

    @property
    def operation_type(self) -> str | None:
        metadata = self.metadata_json or {}
        operation = metadata.get("operation") if isinstance(metadata, dict) else None
        return self.operation_label or operation

    @property
    def task_type(self) -> str | None:
        return self.operation_type

    @property
    def capabilities(self) -> dict | None:
        metadata = self.metadata_json or {}
        value = metadata.get("capabilities") if isinstance(metadata, dict) else None
        return value if isinstance(value, dict) else None

    @property
    def import_source(self) -> str | None:
        metadata = self.metadata_json or {}
        return metadata.get("import_source") if isinstance(metadata, dict) else None

    @property
    def generation_source(self) -> str | None:
        metadata = self.metadata_json or {}
        return metadata.get("generation_source") if isinstance(metadata, dict) else None

    @property
    def is_suno_clip_import(self) -> bool:
        metadata = self.metadata_json or {}
        return bool(isinstance(metadata, dict) and metadata.get("is_suno_clip_import"))

    @property
    def is_opencli_generation(self) -> bool:
        metadata = self.metadata_json or {}
        return bool(isinstance(metadata, dict) and metadata.get("is_opencli_generation"))


class UploadedFileRecord(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "uploaded_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    upload_method: Mapped[str] = mapped_column(String(50), nullable=False)
    original_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class Persona(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "personas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    persona_id: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    style: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_task_id: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    source_audio_id: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    vocal_start: Mapped[float | None] = mapped_column(nullable=True)
    vocal_end: Mapped[float | None] = mapped_column(nullable=True)
    response_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)



class VideoAsset(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "video_assets"

    # MP4 ist bewusst ein eigenes Modell. audio_assets bleibt die zentrale
    # Wahrheit fuer Audio; Video darf SRT, Stems, Waveform und Player-Logik
    # niemals als vermeintliches AudioAsset unterlaufen.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    audio_asset_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    song_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    task_local_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    suno_task_id: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    audio_id: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    local_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    public_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    status: Mapped[str] = mapped_column(String(50), index=True, default="created", nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    @property
    def video_local(self) -> bool:
        status = str(self.status or "").strip().lower()
        return status == "cached" and bool(self.local_path or self.public_url or self.filename)

    @property
    def stream_url(self) -> str | None:
        if not self.id or not self.audio_asset_id:
            return None
        return f"/api/audio-assets/{self.audio_asset_id}/videos/{self.id}/stream"

    @property
    def download_url(self) -> str | None:
        if not self.id or not self.audio_asset_id:
            return None
        return f"/api/audio-assets/{self.audio_asset_id}/videos/{self.id}/download"


class AudioTranscript(Base, TimestampMixin):
    __tablename__ = "audio_transcripts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    audio_asset_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    backend: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    language: Mapped[str | None] = mapped_column(String(20), nullable=True)
    mode: Mapped[str] = mapped_column(String(80), default="lyrics_source_of_truth", nullable=False)
    match_mode: Mapped[str] = mapped_column(String(80), default="lenient", nullable=False)
    srt_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    srt_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    segments_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    words_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(50), index=True, default="created", nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Playlist(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "playlists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class PlaylistItem(Base, TimestampMixin):
    __tablename__ = "playlist_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    playlist_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    audio_asset_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    song_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class LyricDraft(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "lyric_drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(80), default="draft", index=True, nullable=False)
    language: Mapped[str | None] = mapped_column(String(40), nullable=True)
    tags: Mapped[str | None] = mapped_column(Text, nullable=True)
    structure_template: Mapped[str | None] = mapped_column(String(120), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class MusicStyle(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "music_styles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    genre: Mapped[str | None] = mapped_column(String(120), index=True, nullable=True)
    bpm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    style_text: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    usage_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    profile_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_profile: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class AudioProject(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "audio_projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(80), default="active", index=True, nullable=False)
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    final_audio_asset_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class ProductionProfile(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "production_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    style: Mapped[str | None] = mapped_column(Text, nullable=True)
    vocal_gender: Mapped[str | None] = mapped_column(String(40), nullable=True)
    negative_tags: Mapped[str | None] = mapped_column(Text, nullable=True)
    persona_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    persona_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    style_weight: Mapped[float | None] = mapped_column(nullable=True)
    weirdness_constraint: Mapped[float | None] = mapped_column(nullable=True)
    audio_weight: Mapped[float | None] = mapped_column(nullable=True)
    instrumental: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    custom_mode: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)



class AiAssistantProfile(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "ai_assistant_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str] = mapped_column(String(80), index=True, nullable=False, default="openai")
    model: Mapped[str] = mapped_column(String(120), index=True, nullable=False, default="GPT-5.4-mini")
    system_instruction: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_format_instruction: Mapped[str | None] = mapped_column(Text, nullable=True)
    temperature: Mapped[float | None] = mapped_column(nullable=True)
    max_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class AiInstructionFile(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "ai_instruction_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class AiAssistantProfileFile(Base, TimestampMixin):
    __tablename__ = "ai_assistant_profile_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    profile_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    file_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class AiChatSession(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "ai_chat_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    lyric_draft_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    title: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    model: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    assistant_profile_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    canvas_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_history_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class AiChatMessage(Base, TimestampMixin):
    __tablename__ = "ai_chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str | None] = mapped_column(String(80), nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    canvas_before: Mapped[str | None] = mapped_column(Text, nullable=True)
    canvas_after: Mapped[str | None] = mapped_column(Text, nullable=True)
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class LyricCanvasHistory(Base, TimestampMixin):
    __tablename__ = "lyric_canvas_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    version_index: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(80), index=True, nullable=False, default="manual")
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

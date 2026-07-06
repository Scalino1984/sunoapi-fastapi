from __future__ import annotations

# CORE CONTRACT
# Zweck: Zentrale App-Konfiguration fuer Backend, Provider und lange Jobs.
# Kritische Logik: SRT-/Provider-Timeouts duerfen Tasks nicht endlos RUNNING lassen.
# Nicht aendern ohne Pruefung: srt_transcript_service.py, audio_assets.py, task_lifecycle_service.py.
# Neue Settings immer rueckwaertskompatibel mit Defaults einfuegen.
# Siehe: docs/ARCHITECTURE_CONTRACT.md


import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Suno FastAPI App"
    app_env: str = "local"
    debug: bool = False

    suno_api_key: str = Field(default="", repr=False)
    suno_base_url: str = "https://api.sunoapi.org"
    suno_file_upload_base_url: str = "https://sunoapiorg.redpandaai.co"

    # Öffentlicher Suno-Clip-Import: nutzt die Studio-Clip-API nur lesend und speichert die Inhalte
    # anschließend in die bestehenden App-Tabellen. Kann per Feature-Flag deaktiviert werden.
    suno_clip_import_enabled: bool = True
    suno_clip_api_url: str = "https://studio-api.prod.suno.com/api/clip/{id}"
    suno_clip_user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
    suno_clip_request_timeout_seconds: float = 30.0

    database_url: str = "sqlite:///./suno_fastapi_app.db"

    public_base_url: str = "http://localhost:8000"
    default_callback_path: str = "/api/webhooks/suno"

    request_timeout_seconds: float = 60.0
    polling_interval_seconds: int = 10
    polling_max_attempts: int = 60
    archive_page_size: int = 50

    suno_model_limits_json: str = (
        '{'
        '"V5_5":{"simple_prompt":500,"custom_prompt":5000,"style":1000,"title":100},'
        '"V5":{"simple_prompt":500,"custom_prompt":5000,"style":1000,"title":100},'
        '"V4_5ALL":{"simple_prompt":500,"custom_prompt":5000,"style":1000,"title":100},'
        '"V4_5":{"simple_prompt":500,"custom_prompt":5000,"style":1000,"title":100},'
        '"V4_5PLUS":{"simple_prompt":500,"custom_prompt":5000,"style":1000,"title":100},'
        '"V4":{"simple_prompt":500,"custom_prompt":5000,"style":1000,"title":100}'
        '}'
    )
    suno_lyrics_prompt_max_length: int = 200

    suno_audio_cache_mode: str = "on_success"  # off | on_success | on_first_success
    suno_audio_storage_dir: str = "storage/audio"
    suno_audio_public_route: str = "/media/audio"
    suno_audio_download_timeout_seconds: float = 120.0
    suno_audio_max_download_mb: int = 100
    suno_audio_allowed_extensions: str = ".mp3,.wav,.m4a,.aac,.ogg,.flac"
    suno_audio_allowed_content_types: str = "audio/mpeg,audio/mp3,audio/x-mp3,audio/wav,audio/wave,audio/x-wav,audio/mp4,audio/m4a,audio/aac,audio/ogg,audio/flac,audio/x-flac,application/octet-stream"
    suno_auto_download_only_music: bool = True
    suno_audio_download_retries: int = 2
    # Standard: lokal erzeugte Inhalte werden portabel gespeichert und in Backups aufgenommen.
    # Nur explizit deaktivieren, wenn bewusst remote-only gearbeitet werden soll.
    local_content_storage_enabled: bool = True

    # Optionaler OpenCLI-Provider: deaktiviert per Default, damit die bestehende SunoAPI-Generierung unverändert bleibt.
    suno_opencli_enabled: bool = False
    suno_opencli_binary: str = "opencli"
    suno_opencli_timeout_seconds: int = 900
    suno_opencli_wait_timeout_seconds: int = 360
    suno_opencli_formats: str = "mp3,metadata,cover"
    suno_opencli_confirm_paid: bool = False
    suno_opencli_max_imported_clips: int = 2
    suno_opencli_model_map_json: str = '{"V5_5":"chirp-fenix","V5":"chirp-fenix","V4_5ALL":"chirp-bluejay","V4_5PLUS":"chirp-bluejay","V4_5":"chirp-bluejay","V4":"chirp-v4"}'

    # Lokaler MP4-Cache: SunoAPI.org Video-URLs sind zeitlich begrenzt.
    # Videos werden deshalb als eigenes Modell gespeichert und niemals in audio_assets
    # einsortiert, damit Audio-, SRT-, Stem- und Waveform-Rootfunktionen stabil bleiben.
    suno_video_cache_enabled: bool = True
    suno_video_storage_dir: str = "storage/videos"
    suno_video_public_route: str = "/media/videos"
    suno_video_download_timeout_seconds: float = 180.0
    suno_video_max_download_mb: int = 250
    suno_video_allowed_extensions: str = ".mp4"
    suno_video_allowed_content_types: str = "video/mp4,application/mp4,application/octet-stream"

    # Lokaler Cover-Cache: Suno-Bild-URLs laufen extern nach einiger Zeit ab.
    # Covers werden deshalb separat und dauerhaft lokal unter /media/covers ausgeliefert.
    suno_cover_cache_enabled: bool = True
    suno_cover_storage_dir: str = "storage/covers"
    suno_cover_public_route: str = "/media/covers"
    suno_cover_download_timeout_seconds: float = 60.0
    suno_cover_max_download_mb: int = 20
    suno_cover_allowed_extensions: str = ".jpg,.jpeg,.png,.webp,.gif,.avif"
    suno_cover_allowed_content_types: str = "image/jpeg,image/png,image/webp,image/gif,image/avif,application/octet-stream"
    # Optionaler Mirror-Fallback fuer getrennte lokale/VServer-Instanzen:
    # Wenn die DB eine lokale /media/covers/... Referenz vom Server enthaelt,
    # die Datei lokal aber fehlt, kann "Inhalte pruefen" sie ueber diese Base-URLs
    # nachladen, z. B. https://songstudio-react.klangneural.de.
    library_content_remote_media_base_urls: str = ""

    # SRT-/Transkriptionsspeicher
    transcript_storage_dir: str = "storage/transcripts"
    transcript_backend_default: str = "groq"
    transcript_language_default: str = "de"
    transcript_openai_model: str = "whisper-1"
    transcript_voxtral_model: str = "voxtral-mini-latest"
    transcript_groq_model: str = "whisper-large-v3"
    transcript_whisperx_model: str = "small"
    transcript_whisperx_align_language: str = ""
    transcript_whisperx_device: str = "auto"
    transcript_whisperx_compute_type: str = "float16"
    transcript_whisperx_batch_size: int = 16
    transcript_whisperx_cpu_threads: int = 0
    transcript_whisperx_auto_cpu_downgrade: bool = True
    transcript_request_timeout_seconds: float = 600.0
    # SRT-Provider-Absicherung: Groq-Audio-Uploads duerfen lokale Tasks nicht minutenlang/endlos RUNNING halten.
    transcript_groq_request_timeout_seconds: float = 90.0
    transcript_groq_max_retries: int = 2
    # Groq-SRT-Schutz:
    # Lokale Netze/Edges koennen bei groesseren oder merkwuerdig getaggten MP3s
    # stabile HTTPS-Verbindungen haben, aber beim autorisierten Groq-Transkriptions-
    # POST in ReadTimeouts laufen. Deshalb wird NUR fuer den Groq-Upload eine
    # temporaere, kleine Mono-Transkriptionskopie erzeugt. Die Originaldatei,
    # Lyrics-Cleanup, Alignment und gespeicherte SRT-Dateien duerfen dadurch
    # fachlich nicht veraendert werden.
    transcript_groq_preprocess_audio: bool = True
    transcript_groq_preprocess_sample_rate: int = 16000
    transcript_groq_preprocess_bitrate: str = "64k"
    srt_transcription_timeout_seconds: float = 240.0
    transcript_whisperx_timeout_seconds: int = 1800
    voxtral_api_key: str = Field(default="", repr=False)
    mistral_api_key: str = Field(default="", repr=False)
    groq_api_key: str = Field(default="", repr=False)
    acoustid_api_key: str = Field(default="", repr=False)
    # Groq stellt neben der Audio-Transkription auch eine OpenAI-kompatible Chat-API bereit.
    # Wichtig: Die Basis muss /openai/v1 enthalten, sonst landet /chat/completions auf dem falschen Pfad.
    groq_base_url: str = "https://api.groq.com/openai/v1"
    voxtral_base_url: str = "https://api.mistral.ai/v1"

    # Replicate KI-Cover-Generator
    replicate_api_token: str = Field(default="", repr=False)
    replicate_cover_text_model: str = "ibm-granite/granite-3.3-8b-instruct"

    # Lokale Audio-KI-Analyse:
    # Speichert Reports isoliert unter storage/analysis und im AudioAsset.metadata_json.
    # Keine Suno-Payloads, Importlogik, SRT- oder Extend-Abläufe daran koppeln.
    audio_ai_analysis_enabled: bool = True
    audio_ai_analysis_storage_dir: str = "storage/analysis"
    audio_ai_analysis_max_seconds: int = 240
    audio_ai_analysis_ai_summary_enabled: bool = True
    audio_ai_model_analysis_enabled: bool = True
    audio_ai_model_cache_dir: str = "storage/models/huggingface"
    audio_ai_model_analysis_seconds: int = 30
    audio_ai_model_analysis_top_k: int = 8

    # Wiederherstellung offener Suno-Tasks nach FastAPI-Neustart
    suno_startup_recovery_enabled: bool = True
    suno_startup_recovery_initial_delay_seconds: int = 15
    suno_startup_recovery_interval_seconds: int = 30
    suno_startup_recovery_attempts: int = 10
    suno_startup_recovery_limit: int = 30

    # Lokale Task-/Worker-Architektur
    task_watchdog_enabled: bool = True
    task_watchdog_stale_minutes: int = 30
    task_watchdog_interval_seconds: int = 120
    background_worker_start_method: str = "thread"  # thread | spawn | fork | auto
    local_app_task_no_heartbeat_stale_minutes: int = 10
    startup_library_repair_enabled: bool = True
    local_task_default_timeout_seconds: int = 1800
    suno_task_import_item_timeout_seconds: int = 150

    # Enterprise / Betrieb
    enterprise_mode: bool = False
    trusted_hosts: str = "*"
    cors_allow_origins: str = ""
    security_headers_enabled: bool = True
    security_frame_options: str = "DENY"
    security_referrer_policy: str = "strict-origin-when-cross-origin"
    security_permissions_policy: str = "camera=(), microphone=(), geolocation=()"
    security_csp: str = ""
    audit_log_retention_days: int = 365
    backup_storage_dir: str = "storage/backups"
    export_include_deleted_default: bool = False
    max_request_body_mb: int = 100

    # Frontend / Benachrichtigungen
    frontend_badge_auto_close_enabled: bool = True
    frontend_badge_auto_close_seconds: int = 8
    frontend_badge_auto_mark_done: bool = False

    # Authentifizierung / Benutzerverwaltung
    allow_registration: str = "false"
    jwt_secret_key: str = Field(default="", repr=False)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 480
    auth_cookie_name: str = "access_token"
    auth_cookie_secure: bool = False
    auth_cookie_samesite: str = "lax"
    auth_rate_limit_login_requests: int = 10
    auth_rate_limit_register_requests: int = 5
    auth_rate_limit_window_seconds: int = 60
    # Optional nur für Erststart einer noch nicht vorhandenen SQLite-DB.
    # Wenn leer und die DB fehlt, fragt der Terminal-Start interaktiv nach den Daten.
    initial_admin_email: str = ""
    initial_admin_password: str = Field(default="", repr=False)
    initial_admin_nickname: str = ""

    # KI-Canvas / Multi-Provider Songtext-Assistent
    openai_api_key: str = Field(default="", repr=False)
    openai_base_url: str = "https://api.openai.com/v1"
    openrouter_api_key: str = Field(default="", repr=False)
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_site_url: str = "http://localhost:8000"
    openrouter_app_name: str = "Suno FastAPI App"
    gemini_api_key: str = Field(default="", repr=False)
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    ai_default_provider: str = "openai"
    ai_default_model: str = "GPT-5.4-mini"
    ai_request_timeout_seconds: float = 120.0
    ai_max_output_tokens: int = 6000
    ai_store_raw_responses: bool = False

    # KI-Style-Engine: feste Suno-Limits und adaptive Request-Bündelung.
    # Diese Werte werden von GlobalAssistantService.generate_style_suggestions()
    # direkt gelesen. Wenn sie nach einem Restore fehlen, bricht „Styles generieren"
    # mit AttributeError ab, obwohl Route und Frontend vorhanden sind.
    ai_style_lyrics_max_chars: int = 5000
    ai_style_music_style_max_chars: int = 1000
    ai_style_generation_batch_mode: str = "auto"  # auto | batch | chunked | single
    ai_style_generation_default_batch_size: int = 3
    ai_style_generation_low_token_batch_size: int = 1
    ai_style_generation_low_token_max_output_tokens: int = 4000
    ai_style_generation_low_token_models: str = "GPT-5.4-nano,Llama 3.1 8B Instant,GPT-OSS 20B"
    ai_style_generation_compact_reference_for_low_token: bool = True
    ai_style_generation_deferred_lyric_tagging_enabled: bool = True
    ai_allowed_models_json: str = '{"openai":["GPT-5.5","GPT-5.4-mini","GPT-5.4-nano"],"openrouter":["claude-4.6"],"gemini":["gemini-2.5-pro","gemini-flash-latest"],"groq":["Llama 3.3 70B Versatile","Llama 3.1 8B Instant","GPT-OSS 120B","GPT-OSS 20B"]}'
    ai_model_aliases_json: str = '{"openai":{"GPT-5.5":"gpt-5.5","GPT-5.4-mini":"gpt-5.4-mini","GPT-5.4-nano":"gpt-5.4-nano"},"openrouter":{"claude-4.6":"anthropic/claude-sonnet-4.6"},"gemini":{"gemini-2.5-pro":"gemini-2.5-pro","gemini-flash-latest":"gemini-2.5-flash"},"groq":{"Llama 3.3 70B Versatile":"llama-3.3-70b-versatile","Llama 3.1 8B Instant":"llama-3.1-8b-instant","GPT-OSS 120B":"openai/gpt-oss-120b","GPT-OSS 20B":"openai/gpt-oss-20b"}}'

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @field_validator("default_callback_path", "suno_audio_public_route", "suno_cover_public_route", "suno_video_public_route")
    @classmethod
    def normalize_route_path(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            return "/"
        if not cleaned.startswith("/"):
            cleaned = f"/{cleaned}"
        return cleaned.rstrip("/") if len(cleaned) > 1 else cleaned

    @field_validator("suno_audio_allowed_extensions")
    @classmethod
    def normalize_audio_extensions(cls, value: str) -> str:
        extensions = []
        for entry in str(value or "").split(","):
            extension = entry.strip().lower()
            if not extension:
                continue
            if not extension.startswith("."):
                extension = f".{extension}"
            if extension not in extensions:
                extensions.append(extension)
        return ",".join(extensions) or ".mp3,.wav,.m4a,.aac,.ogg,.flac"

    @property
    def callback_url(self) -> str:
        return f"{self.public_base_url.rstrip('/')}{self.default_callback_path}"

    @property
    def audio_storage_path(self) -> Path:
        return Path(self.suno_audio_storage_dir).resolve()

    @property
    def audio_allowed_extensions_list(self) -> list[str]:
        return [item.strip().lower() for item in self.suno_audio_allowed_extensions.split(",") if item.strip()]

    @property
    def audio_allowed_content_types_list(self) -> list[str]:
        return [item.strip().lower() for item in self.suno_audio_allowed_content_types.split(",") if item.strip()]

    @property
    def audio_max_download_bytes(self) -> int:
        return max(1, int(self.suno_audio_max_download_mb)) * 1024 * 1024

    @property
    def opencli_formats_list(self) -> list[str]:
        allowed = {"mp3", "m4a", "wav", "video", "cover", "metadata"}
        result: list[str] = []
        for item in str(self.suno_opencli_formats or "").split(","):
            value = item.strip().lower()
            if value and value in allowed and value not in result:
                result.append(value)
        return result or ["mp3", "metadata", "cover"]

    @property
    def opencli_model_map(self) -> dict[str, str]:
        try:
            parsed = json.loads(self.suno_opencli_model_map_json)
        except json.JSONDecodeError:
            parsed = {}
        if not isinstance(parsed, dict):
            parsed = {}
        return {str(key): str(value) for key, value in parsed.items() if str(key).strip() and str(value).strip()}

    def resolve_opencli_model(self, model_name: str | None) -> str | None:
        if not model_name:
            return None
        value = str(model_name).strip()
        allowed = {"chirp-fenix", "chirp-bluejay", "chirp-v4", "chirp-v3-5"}
        if value in allowed:
            return value
        return self.opencli_model_map.get(value)

    @property
    def video_storage_path(self) -> Path:
        return Path(self.suno_video_storage_dir).resolve()

    @property
    def video_allowed_extensions_list(self) -> list[str]:
        extensions: list[str] = []
        for item in self.suno_video_allowed_extensions.split(","):
            extension = item.strip().lower()
            if not extension:
                continue
            if not extension.startswith("."):
                extension = f".{extension}"
            if extension not in extensions:
                extensions.append(extension)
        return extensions or [".mp4"]

    @property
    def video_allowed_content_types_list(self) -> list[str]:
        return [item.strip().lower() for item in self.suno_video_allowed_content_types.split(",") if item.strip()]

    @property
    def video_max_download_bytes(self) -> int:
        return max(1, int(self.suno_video_max_download_mb)) * 1024 * 1024

    @property
    def cover_storage_path(self) -> Path:
        return Path(self.suno_cover_storage_dir).resolve()

    @property
    def cover_allowed_extensions_list(self) -> list[str]:
        extensions: list[str] = []
        for item in self.suno_cover_allowed_extensions.split(","):
            extension = item.strip().lower()
            if not extension:
                continue
            if not extension.startswith("."):
                extension = f".{extension}"
            if extension not in extensions:
                extensions.append(extension)
        return extensions or [".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"]

    @property
    def cover_allowed_content_types_list(self) -> list[str]:
        return [item.strip().lower() for item in self.suno_cover_allowed_content_types.split(",") if item.strip()]

    @property
    def cover_max_download_bytes(self) -> int:
        return max(1, int(self.suno_cover_max_download_mb)) * 1024 * 1024

    @property
    def transcript_storage_path(self) -> Path:
        return Path(self.transcript_storage_dir).resolve()

    @property
    def audio_ai_analysis_storage_path(self) -> Path:
        return Path(self.audio_ai_analysis_storage_dir).resolve()

    @property
    def audio_ai_model_cache_path(self) -> Path:
        return Path(self.audio_ai_model_cache_dir).resolve()

    @property
    def transcript_backends(self) -> list[str]:
        return ["groq", "whisperx", "openai_whisper_api", "voxtral"]

    def transcript_backend_has_runtime(self, backend: str) -> bool:
        backend_key = str(backend or "").strip().lower()
        if backend_key == "openai_whisper_api":
            return bool(self.openai_api_key)
        if backend_key == "voxtral":
            return bool(self.voxtral_api_key or self.mistral_api_key)
        if backend_key == "whisperx":
            try:
                import whisperx  # type: ignore
                return bool(whisperx)
            except Exception:
                return False
        if backend_key == "groq":
            return bool(self.groq_api_key)
        return False

    @property
    def model_limits(self) -> dict[str, dict[str, int]]:
        try:
            parsed = json.loads(self.suno_model_limits_json)
        except json.JSONDecodeError as exc:
            raise ValueError("SUNO_MODEL_LIMITS_JSON ist kein gültiges JSON.") from exc

        if not isinstance(parsed, dict):
            raise ValueError("SUNO_MODEL_LIMITS_JSON muss ein JSON-Objekt sein.")

        normalized: dict[str, dict[str, int]] = {}
        for model_name, limits in parsed.items():
            if not isinstance(limits, dict):
                continue
            normalized[str(model_name)] = {
                "simple_prompt": int(limits.get("simple_prompt", 0)),
                "custom_prompt": int(limits.get("custom_prompt", 0)),
                "style": int(limits.get("style", 0)),
                "title": int(limits.get("title", 0)),
            }
        return normalized

    def limits_for_model(self, model_name: str) -> dict[str, int]:
        limits = self.model_limits
        if model_name in limits:
            return limits[model_name]
        if limits:
            return next(iter(limits.values()))
        raise ValueError("Keine Suno-Modelllimits konfiguriert.")


    @property
    def trusted_hosts_list(self) -> list[str]:
        return [item.strip() for item in self.trusted_hosts.split(",") if item.strip()] or ["*"]

    @property
    def cors_allow_origins_list(self) -> list[str]:
        return [item.strip() for item in self.cors_allow_origins.split(",") if item.strip()]

    @property
    def backup_storage_path(self) -> Path:
        return Path(self.backup_storage_dir).resolve()

    @property
    def max_request_body_bytes(self) -> int:
        return max(1, int(self.max_request_body_mb)) * 1024 * 1024

    @property
    def registration_enabled(self) -> bool:
        return str(self.allow_registration or "").strip().lower() == "true"

    @property
    def ai_allowed_models(self) -> dict[str, list[str]]:
        try:
            parsed = json.loads(self.ai_allowed_models_json)
        except json.JSONDecodeError:
            parsed = {}
        result: dict[str, list[str]] = {}
        for provider, models in parsed.items() if isinstance(parsed, dict) else []:
            if isinstance(provider, str) and isinstance(models, list):
                result[provider] = [str(model) for model in models if str(model).strip()]
        return result

    @property
    def ai_model_aliases(self) -> dict[str, dict[str, str]]:
        try:
            parsed = json.loads(self.ai_model_aliases_json)
        except json.JSONDecodeError:
            parsed = {}
        result: dict[str, dict[str, str]] = {}
        for provider, mapping in parsed.items() if isinstance(parsed, dict) else []:
            if isinstance(provider, str) and isinstance(mapping, dict):
                result[provider] = {str(key): str(value) for key, value in mapping.items()}
        return result

    def resolve_ai_model(self, provider: str, model: str) -> str:
        provider_key = str(provider or "").strip().lower()
        model_key = str(model or "").strip()
        return self.ai_model_aliases.get(provider_key, {}).get(model_key, model_key)

    def ai_provider_has_key(self, provider: str) -> bool:
        provider_key = str(provider or "").strip().lower()
        if provider_key == "openai":
            return bool(self.openai_api_key)
        if provider_key == "openrouter":
            return bool(self.openrouter_api_key)
        if provider_key == "gemini":
            return bool(self.gemini_api_key)
        if provider_key == "groq":
            return bool(self.groq_api_key)
        return False

    @field_validator("auth_cookie_samesite")
    @classmethod
    def normalize_cookie_samesite(cls, value: str) -> str:
        cleaned = str(value or "lax").strip().lower()
        if cleaned not in {"lax", "strict", "none"}:
            return "lax"
        return cleaned

    def public_runtime_config(self) -> dict[str, Any]:
        return {
            "models": self.model_limits,
            "lyrics_prompt_max_length": self.suno_lyrics_prompt_max_length,
            "polling_interval_seconds": self.polling_interval_seconds,
            "archive_page_size": self.archive_page_size,
            "audio_cache_mode": self.suno_audio_cache_mode,
            "local_content_storage_enabled": self.local_content_storage_enabled,
            "audio_public_route": self.suno_audio_public_route,
            "audio_max_download_mb": self.suno_audio_max_download_mb,
            "opencli": {
                "enabled": self.suno_opencli_enabled,
                "binary": self.suno_opencli_binary,
                "installed": __import__("shutil").which(self.suno_opencli_binary) is not None,
                "formats": self.opencli_formats_list,
                "confirm_paid": self.suno_opencli_confirm_paid,
                "wait_timeout_seconds": self.suno_opencli_wait_timeout_seconds,
                "max_imported_clips": self.suno_opencli_max_imported_clips,
                "models": ["chirp-fenix", "chirp-bluejay", "chirp-v4", "chirp-v3-5"],
                "model_map": self.opencli_model_map,
            },
            "cover_cache_enabled": self.suno_cover_cache_enabled,
            "cover_public_route": self.suno_cover_public_route,
            "cover_max_download_mb": self.suno_cover_max_download_mb,
            "enterprise_mode": self.enterprise_mode,
            "security_headers_enabled": self.security_headers_enabled,
            "registration_enabled": self.registration_enabled,
            "notifications": {
                "badge_auto_close_enabled": self.frontend_badge_auto_close_enabled,
                "badge_auto_close_seconds": max(0, int(self.frontend_badge_auto_close_seconds)),
                "badge_auto_close_ms": max(0, int(self.frontend_badge_auto_close_seconds)) * 1000,
                "badge_auto_mark_done": self.frontend_badge_auto_mark_done,
            },
            "ai_chat": {
                "default_provider": self.ai_default_provider,
                "default_model": self.ai_default_model,
                "allowed_models": self.ai_allowed_models,
                "providers": {
                    "openai": {"configured": bool(self.openai_api_key)},
                    "openrouter": {"configured": bool(self.openrouter_api_key)},
                    "gemini": {"configured": bool(self.gemini_api_key)},
                    "groq": {"configured": bool(self.groq_api_key)},
                },
            },
            "transcription": {
                "backends": self.transcript_backends,
                "default_backend": self.transcript_backend_default,
                "default_language": self.transcript_language_default,
                "runtime": {
                    "groq": {"configured": self.transcript_backend_has_runtime("groq")},
                    "whisperx": {"configured": self.transcript_backend_has_runtime("whisperx")},
                    "openai_whisper_api": {"configured": self.transcript_backend_has_runtime("openai_whisper_api")},
                    "voxtral": {"configured": self.transcript_backend_has_runtime("voxtral")},
                },
            },
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()

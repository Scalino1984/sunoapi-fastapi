"""API-Schema-Vertrag fuer SunoAPI-Generate.

Die /music-Generierung muss die offiziellen SunoAPI-Namen negativeTags und
vocalGender akzeptieren und per Alias auch so serialisieren. Die alten internen
snake_case-Namen bleiben nur als kompatible Eingabe erlaubt. Diese Payload wird
in suno_tasks.request_payload gespeichert und spaeter fuer Library/Songdetails
und Offline-Anzeige aus audio_assets.metadata_json.request_payload gelesen.
"""

from enum import Enum
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

from app.config import get_settings


class UserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=12, max_length=256)
    nickname: str | None = Field(default=None, max_length=120)


class UserLogin(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=256)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    nickname: str | None = None
    is_active: bool
    is_admin: bool = False
    created_at: Any | None = None


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class TokenPayload(BaseModel):
    sub: str | None = None
    exp: int | None = None
    type: str | None = None


class UserProfileUpdate(BaseModel):
    nickname: str | None = Field(default=None, max_length=120)


class UserPasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


class SunoModel(str, Enum):
    V5_5 = "V5_5"
    V5 = "V5"
    V4_5ALL = "V4_5ALL"
    V4_5 = "V4_5"
    V4_5PLUS = "V4_5PLUS"
    V4 = "V4"


class GenericAPIResponse(BaseModel):
    ok: bool
    data: dict[str, Any] | list[Any] | None = None
    error: str | None = None


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: str | None
    task_type: str
    status: str
    request_payload: dict[str, Any] | None = None
    response_payload: dict[str, Any] | None = None
    result_payload: dict[str, Any] | None = None
    error_message: str | None = None
    progress: int | None = 0
    created_at: Any | None = None
    updated_at: Any | None = None
    started_at: Any | None = None
    heartbeat_at: Any | None = None
    completed_at: Any | None = None
    cancel_requested: bool | None = False
    already_imported: bool | None = None
    import_status: str | None = None
    import_message: str | None = None


class SongRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str | None = None
    model: str | None = None
    prompt: str | None = None
    lyrics: str | None = None
    audio_url: str | None = None
    cover_image_url: str | None = None
    video_url: str | None = None
    midi_url: str | None = None
    wav_url: str | None = None
    task_id: str | None = None
    metadata_json: dict[str, Any] | None = None
    capabilities: dict[str, Any] | None = None
    import_source: str | None = None
    generation_source: str | None = None
    is_suno_clip_import: bool | None = False
    is_opencli_generation: bool | None = False
    prompt: str | None = None
    lyrics: str | None = None
    style: str | None = None
    tags: str | None = None
    model_name: str | None = None
    source_audio_url: str | None = None
    stream_audio_url: str | None = None
    source_image_url: str | None = None
    cover_local_url: str | None = None
    cover_cached: bool | None = False
    operation_type: str | None = None
    task_type: str | None = None
    project_id: int | None = None
    is_favorite: bool | None = False
    is_final: bool | None = False
    version_label: str | None = None
    created_at: Any | None = None
    updated_at: Any | None = None


class AudioAssetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_local_id: int | None = None
    song_id: int | None = None
    suno_task_id: str | None = None
    audio_id: str | None = None
    title: str | None = None
    image_url: str | None = None
    source_url: str
    local_path: str | None = None
    public_url: str | None = None
    filename: str | None = None
    content_type: str | None = None
    file_size_bytes: int | None = None
    duration_seconds: int | None = None
    checksum_sha256: str | None = None
    status: str
    error_message: str | None = None
    metadata_json: dict[str, Any] | None = None
    capabilities: dict[str, Any] | None = None
    import_source: str | None = None
    generation_source: str | None = None
    is_suno_clip_import: bool | None = False
    is_opencli_generation: bool | None = False
    prompt: str | None = None
    lyrics: str | None = None
    style: str | None = None
    tags: str | None = None
    model_name: str | None = None
    source_audio_url: str | None = None
    stream_audio_url: str | None = None
    source_image_url: str | None = None
    cover_local_url: str | None = None
    cover_cached: bool | None = False
    audio_local: bool | None = False
    audio_availability_status: str | None = None
    audio_local_reason: str | None = None
    operation_type: str | None = None
    task_type: str | None = None
    project_id: int | None = None
    display_title: str | None = None
    operation_label: str | None = None
    parent_audio_id: str | None = None
    parent_task_id: str | None = None
    version_label: str | None = None
    is_favorite: bool | None = False
    is_final: bool | None = False
    waveform_json: dict[str, Any] | None = None
    waveform_generated_at: Any | None = None
    structure_segments_json: list[dict[str, Any]] | None = None
    srt_cached: bool | None = False
    half_srt_cached: bool | None = False
    latest_srt_status: str | None = None
    latest_srt_generated_at: Any | None = None
    # Externe/originale Sortierdaten aus Suno/SunoAPI.
    # Diese Felder sind bewusst read-only API-Kontext und brauchen keine DB-Migration.
    source_created_at: Any | None = None
    library_sort_at: Any | None = None
    task_created_at: Any | None = None
    created_at: Any | None = None
    updated_at: Any | None = None


class AudioWaveformRead(BaseModel):
    audio_asset_id: int
    audio_id: str | None = None
    duration_seconds: float | int | None = None
    points: int
    peaks: list[float]
    segments: list[dict[str, Any]] = []
    generated_at: str | None = None
    source: str | None = None

class PersonaRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    persona_id: str
    name: str
    description: str | None = None
    style: str | None = None
    source_task_id: str | None = None
    source_audio_id: str | None = None
    vocal_start: float | None = None
    vocal_end: float | None = None
    response_payload: dict[str, Any] | None = None
    created_at: Any | None = None
    updated_at: Any | None = None


class VoiceCreate(BaseModel):
    nickname: str = Field(min_length=1, max_length=255)
    voice_id: str = Field(min_length=1, max_length=255)
    task_id: str | None = Field(default=None, max_length=255)
    description: str | None = None
    style: str | None = Field(default=None, max_length=255)


class VoiceUpdate(BaseModel):
    nickname: str | None = Field(default=None, min_length=1, max_length=255)
    voice_id: str | None = Field(default=None, min_length=1, max_length=255)
    task_id: str | None = Field(default=None, max_length=255)
    description: str | None = None
    style: str | None = Field(default=None, max_length=255)


class VoiceRead(BaseModel):
    id: int
    voice_id: str
    nickname: str
    task_id: str | None = None
    description: str | None = None
    style: str | None = None
    source_type: str = "voice"
    response_payload: dict[str, Any] | None = None
    created_at: Any | None = None
    updated_at: Any | None = None




class ImportSunoTaskRequest(BaseModel):
    task_id: str = Field(min_length=1, max_length=255)
    task_type: str = Field(default="auto", max_length=100)
    title: str | None = Field(default=None, max_length=255)
    prompt: str | None = None
    style: str | None = None
    model: str | None = Field(default=None, max_length=80)
    cache_audio: bool = True
    generate_srt: bool = False
    generate_stems: bool = False

    @model_validator(mode="after")
    def validate_supported_import_type(self):
        supported = {
            "generate_music",
            "auto",
            "extend_music",
            "upload_and_cover",
            "upload_and_extend",
            "add_instrumental",
            "add_vocals",
            "generate_mashup",
            "generate_sounds",
            "create_cover",
            "generate_lyrics",
            "separate",
            "convert_to_wav",
            "generate_midi",
            "create_video",
            "create_custom_voice",
        }
        self.task_type = str(self.task_type or "auto").strip()
        if self.task_type not in supported:
            raise ValueError(f"Nicht unterstützter Import-Task-Typ: {self.task_type}")
        self.task_id = self.task_id.strip()
        return self




class ImportSunoSongRequest(BaseModel):
    song_id: str = Field(min_length=1, max_length=500)
    cache_audio: bool = True
    cache_cover: bool = True
    import_video_url: bool = True
    project_id: int | None = None
    playlist_id: int | None = None
    overwrite_existing: bool = False
    generate_srt: bool = False
    generate_stems: bool = False


class ImportSunoSongResponse(BaseModel):
    ok: bool
    song_id: int | None = None
    audio_asset_id: int | None = None
    task_local_id: int | None = None
    suno_song_id: str
    already_imported: bool = False
    audio_cached: bool = False
    cover_cached: bool = False
    message: str
    warnings: list[str] = []
    post_actions: list[dict[str, Any]] = []


class BatchImportSunoTaskRequest(BaseModel):
    task_ids: str = Field(min_length=1)
    task_type: str = Field(default="auto", max_length=100)
    cache_audio: bool = True
    title_prefix: str | None = Field(default=None, max_length=120)
    generate_srt: bool = False
    generate_stems: bool = False

    @property
    def parsed_task_ids(self) -> list[str]:
        normalized = str(self.task_ids or "").replace(",", "\n").replace(";", "\n")
        seen: set[str] = set()
        result: list[str] = []
        for raw in normalized.splitlines():
            item = raw.strip()
            if not item or item in seen:
                continue
            seen.add(item)
            result.append(item)
        return result




class BatchImportSunoSongRequest(BaseModel):
    song_ids: str = Field(min_length=1)
    cache_audio: bool = True
    cache_cover: bool = True
    import_video_url: bool = True
    overwrite_existing: bool = False
    generate_srt: bool = False
    generate_stems: bool = False

    @property
    def parsed_song_ids(self) -> list[str]:
        normalized = str(self.song_ids or "").replace(",", "\n").replace(";", "\n")
        seen: set[str] = set()
        result: list[str] = []
        for item in normalized.splitlines():
            value = item.strip()
            if not value or value in seen:
                continue
            result.append(value)
            seen.add(value)
        return result


class SunoSafeCheckRequest(BaseModel):
    title: str | None = None
    prompt: str | None = None
    style: str | None = None
    negative_tags: str | None = None
    customMode: bool = False
    instrumental: bool = False
    voice_id: str | None = None
    persona_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("persona_id", "personaId"),
        serialization_alias="personaId",
    )
    persona_model: str | None = Field(
        default=None,
        validation_alias=AliasChoices("persona_model", "personaModel"),
        serialization_alias="personaModel",
    )
    model: str | None = None

class GenerateMusicRequest(BaseModel):
    model: SunoModel = SunoModel.V5_5
    customMode: bool = False
    instrumental: bool = False
    prompt: str = Field(min_length=1)
    callback_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("callback_url", "callBackUrl"),
        serialization_alias="callBackUrl",
    )
    title: str | None = None
    style: str | None = None
    persona_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("persona_id", "personaId"),
        serialization_alias="personaId",
    )
    persona_model: str | None = Field(
        default=None,
        validation_alias=AliasChoices("persona_model", "personaModel"),
        serialization_alias="personaModel",
    )
    voice_id: str | None = None
    negative_tags: str | None = Field(
        default=None,
        validation_alias=AliasChoices("negative_tags", "negativeTags"),
        serialization_alias="negativeTags",
    )
    vocal_gender: str | None = Field(
        default=None,
        validation_alias=AliasChoices("vocal_gender", "vocalGender"),
        serialization_alias="vocalGender",
    )
    styleWeight: float | None = None
    weirdnessConstraint: float | None = None
    audioWeight: float | None = None

    @model_validator(mode="after")
    def validate_with_configured_model_limits(self):
        settings = get_settings()
        limits = settings.limits_for_model(self.model.value)

        prompt_limit = limits["custom_prompt"] if self.customMode else limits["simple_prompt"]
        if prompt_limit > 0 and len(self.prompt) > prompt_limit:
            raise ValueError(
                f"Prompt ist zu lang für Modell {self.model.value}. Erlaubt: {prompt_limit}, aktuell: {len(self.prompt)}."
            )

        if self.style and limits["style"] > 0 and len(self.style) > limits["style"]:
            raise ValueError(
                f"Style ist zu lang für Modell {self.model.value}. Erlaubt: {limits['style']}, aktuell: {len(self.style)}."
            )

        if self.title and limits["title"] > 0 and len(self.title) > limits["title"]:
            raise ValueError(
                f"Titel ist zu lang für Modell {self.model.value}. Erlaubt: {limits['title']}, aktuell: {len(self.title)}."
            )

        if self.customMode:
            if not self.instrumental and not self.prompt.strip():
                raise ValueError("Im Custom-Modus mit Gesang ist ein Prompt/Lyrics-Text erforderlich.")
            if not self.style or not self.style.strip():
                raise ValueError("Im Custom-Modus ist style erforderlich.")
            if not self.title or not self.title.strip():
                raise ValueError("Im Custom-Modus ist title erforderlich.")

        return self


class ExtendMusicRequest(BaseModel):
    defaultParamFlag: bool = False
    audio_id: str = Field(
        min_length=1,
        validation_alias=AliasChoices("audio_id", "audioId"),
        serialization_alias="audioId",
    )
    model: SunoModel = SunoModel.V5_5
    prompt: str | None = None
    style: str | None = None
    title: str | None = None
    continueAt: float | None = None
    autoContinueAt: bool = False
    persona_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("persona_id", "personaId"),
        serialization_alias="personaId",
    )
    persona_model: str | None = Field(
        default=None,
        validation_alias=AliasChoices("persona_model", "personaModel"),
        serialization_alias="personaModel",
    )
    voice_id: str | None = None
    negative_tags: str | None = Field(
        default=None,
        validation_alias=AliasChoices("negative_tags", "negativeTags"),
        serialization_alias="negativeTags",
    )
    vocal_gender: str | None = Field(
        default=None,
        validation_alias=AliasChoices("vocal_gender", "vocalGender"),
        serialization_alias="vocalGender",
    )
    styleWeight: float | None = None
    weirdnessConstraint: float | None = None
    audioWeight: float | None = None
    callback_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("callback_url", "callBackUrl"),
        serialization_alias="callBackUrl",
    )

    @model_validator(mode="after")
    def validate_extend_payload(self):
        settings = get_settings()
        limits = settings.limits_for_model(self.model.value)

        if self.defaultParamFlag:
            if not self.prompt or not self.prompt.strip():
                raise ValueError("Bei Custom-Extension ist prompt erforderlich.")
            if not self.style or not self.style.strip():
                raise ValueError("Bei Custom-Extension ist style erforderlich.")
            if not self.title or not self.title.strip():
                raise ValueError("Bei Custom-Extension ist title erforderlich.")
            if not self.autoContinueAt and (self.continueAt is None or self.continueAt <= 0):
                raise ValueError("Bei Custom-Extension ist continueAt > 0 erforderlich.")
            if limits["custom_prompt"] > 0 and len(self.prompt) > limits["custom_prompt"]:
                raise ValueError(f"Extend-Prompt ist zu lang. Erlaubt: {limits['custom_prompt']}, aktuell: {len(self.prompt)}.")
            if limits["style"] > 0 and len(self.style) > limits["style"]:
                raise ValueError(f"Extend-Style ist zu lang. Erlaubt: {limits['style']}, aktuell: {len(self.style)}.")
            if limits["title"] > 0 and len(self.title) > limits["title"]:
                raise ValueError(f"Extend-Titel ist zu lang. Erlaubt: {limits['title']}, aktuell: {len(self.title)}.")

        for field_name in ("styleWeight", "weirdnessConstraint", "audioWeight"):
            value = getattr(self, field_name)
            if value is not None and not 0 <= value <= 1:
                raise ValueError(f"{field_name} muss zwischen 0 und 1 liegen.")
        return self


class GenerateCoverRequest(BaseModel):
    task_id: str = Field(
        min_length=1,
        validation_alias=AliasChoices("task_id", "taskId"),
        serialization_alias="taskId",
    )
    callback_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("callback_url", "callBackUrl"),
        serialization_alias="callBackUrl",
    )


class GeneratePersonaRequest(BaseModel):
    task_id: str = Field(
        min_length=1,
        validation_alias=AliasChoices("task_id", "taskId"),
        serialization_alias="taskId",
    )
    audio_id: str = Field(
        min_length=1,
        validation_alias=AliasChoices("audio_id", "audioId"),
        serialization_alias="audioId",
    )
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    vocalStart: float | None = None
    vocalEnd: float | None = None
    style: str | None = None

    @model_validator(mode="after")
    def validate_persona_range(self):
        if self.vocalStart is not None and self.vocalEnd is not None:
            if self.vocalStart < 0 or self.vocalEnd <= self.vocalStart:
                raise ValueError("vocalStart/vocalEnd sind ungültig.")
            segment = self.vocalEnd - self.vocalStart
            if segment < 10 or segment > 30:
                raise ValueError("Persona-Analysebereich muss zwischen 10 und 30 Sekunden lang sein.")
        return self


class UploadAndCoverRequest(BaseModel):
    audio_url: str = Field(
        min_length=1,
        validation_alias=AliasChoices("audio_url", "uploadUrl"),
        serialization_alias="uploadUrl",
    )
    customMode: bool = False
    instrumental: bool = False
    model: SunoModel = SunoModel.V5_5
    prompt: str = Field(min_length=1)
    style: str | None = None
    title: str | None = None
    persona_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("persona_id", "personaId"),
        serialization_alias="personaId",
    )
    persona_model: str | None = Field(
        default=None,
        validation_alias=AliasChoices("persona_model", "personaModel"),
        serialization_alias="personaModel",
    )
    voice_id: str | None = None
    negative_tags: str | None = Field(
        default=None,
        validation_alias=AliasChoices("negative_tags", "negativeTags"),
        serialization_alias="negativeTags",
    )
    vocal_gender: str | None = Field(
        default=None,
        validation_alias=AliasChoices("vocal_gender", "vocalGender"),
        serialization_alias="vocalGender",
    )
    styleWeight: float | None = None
    weirdnessConstraint: float | None = None
    audioWeight: float | None = None
    callback_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("callback_url", "callBackUrl"),
        serialization_alias="callBackUrl",
    )

    @model_validator(mode="after")
    def validate_upload_cover_payload(self):
        settings = get_settings()
        limits = settings.limits_for_model(self.model.value)
        if self.customMode:
            if not self.style or not self.style.strip():
                raise ValueError("Im Custom-Cover-Modus ist style erforderlich.")
            if not self.title or not self.title.strip():
                raise ValueError("Im Custom-Cover-Modus ist title erforderlich.")
            if not self.instrumental and not self.prompt.strip():
                raise ValueError("Im Custom-Cover-Modus mit Gesang ist prompt/Lyrics erforderlich.")
            if limits["custom_prompt"] > 0 and len(self.prompt) > limits["custom_prompt"]:
                raise ValueError(f"Cover-Prompt ist zu lang. Erlaubt: {limits['custom_prompt']}, aktuell: {len(self.prompt)}.")
            if limits["style"] > 0 and self.style and len(self.style) > limits["style"]:
                raise ValueError(f"Cover-Style ist zu lang. Erlaubt: {limits['style']}, aktuell: {len(self.style)}.")
            if limits["title"] > 0 and self.title and len(self.title) > limits["title"]:
                raise ValueError(f"Cover-Titel ist zu lang. Erlaubt: {limits['title']}, aktuell: {len(self.title)}.")
        else:
            if limits["simple_prompt"] > 0 and len(self.prompt) > limits["simple_prompt"]:
                raise ValueError(f"Cover-Prompt ist zu lang. Erlaubt: {limits['simple_prompt']}, aktuell: {len(self.prompt)}.")
        return self


class UploadAndExtendRequest(BaseModel):
    audio_url: str = Field(
        min_length=1,
        validation_alias=AliasChoices("audio_url", "uploadUrl"),
        serialization_alias="uploadUrl",
    )
    defaultParamFlag: bool = False
    instrumental: bool = False
    model: SunoModel = SunoModel.V5_5
    prompt: str | None = None
    style: str | None = None
    title: str | None = None
    continueAt: float | None = None
    autoContinueAt: bool = False
    persona_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("persona_id", "personaId"),
        serialization_alias="personaId",
    )
    persona_model: str | None = Field(
        default=None,
        validation_alias=AliasChoices("persona_model", "personaModel"),
        serialization_alias="personaModel",
    )
    voice_id: str | None = None
    negative_tags: str | None = Field(
        default=None,
        validation_alias=AliasChoices("negative_tags", "negativeTags"),
        serialization_alias="negativeTags",
    )
    vocal_gender: str | None = Field(
        default=None,
        validation_alias=AliasChoices("vocal_gender", "vocalGender"),
        serialization_alias="vocalGender",
    )
    styleWeight: float | None = None
    weirdnessConstraint: float | None = None
    audioWeight: float | None = None
    callback_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("callback_url", "callBackUrl"),
        serialization_alias="callBackUrl",
    )

    @model_validator(mode="after")
    def validate_upload_extend_payload(self):
        settings = get_settings()
        limits = settings.limits_for_model(self.model.value)
        if self.defaultParamFlag:
            if not self.prompt or not self.prompt.strip():
                raise ValueError("Upload-Extend Custom benötigt prompt.")
            if not self.style or not self.style.strip():
                raise ValueError("Upload-Extend Custom benötigt style.")
            if not self.title or not self.title.strip():
                raise ValueError("Upload-Extend Custom benötigt title.")
            if not self.autoContinueAt and (self.continueAt is None or self.continueAt <= 0):
                raise ValueError("Upload-Extend Custom benötigt continueAt > 0.")
            if limits["custom_prompt"] > 0 and len(self.prompt) > limits["custom_prompt"]:
                raise ValueError(f"Upload-Extend-Prompt ist zu lang. Erlaubt: {limits['custom_prompt']}, aktuell: {len(self.prompt)}.")
            if limits["style"] > 0 and self.style and len(self.style) > limits["style"]:
                raise ValueError(f"Upload-Extend-Style ist zu lang. Erlaubt: {limits['style']}, aktuell: {len(self.style)}.")
            if limits["title"] > 0 and self.title and len(self.title) > limits["title"]:
                raise ValueError(f"Upload-Extend-Titel ist zu lang. Erlaubt: {limits['title']}, aktuell: {len(self.title)}.")
        return self


class ReplaceSectionRequest(BaseModel):
    task_id: str = Field(
        min_length=1,
        validation_alias=AliasChoices("task_id", "taskId"),
        serialization_alias="taskId",
    )
    audio_id: str = Field(
        min_length=1,
        validation_alias=AliasChoices("audio_id", "audioId"),
        serialization_alias="audioId",
    )
    prompt: str = Field(min_length=1)
    tags: str = Field(min_length=1)
    title: str = Field(min_length=1)
    infill_start_s: float = Field(
        ge=0,
        validation_alias=AliasChoices("infill_start_s", "infillStartS"),
        serialization_alias="infillStartS",
    )
    infill_end_s: float = Field(
        gt=0,
        validation_alias=AliasChoices("infill_end_s", "infillEndS"),
        serialization_alias="infillEndS",
    )
    full_lyrics: str = Field(
        min_length=1,
        validation_alias=AliasChoices("full_lyrics", "fullLyrics"),
        serialization_alias="fullLyrics",
    )
    negative_tags: str | None = Field(
        default=None,
        validation_alias=AliasChoices("negative_tags", "negativeTags"),
        serialization_alias="negativeTags",
    )
    callback_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("callback_url", "callBackUrl"),
        serialization_alias="callBackUrl",
    )

    @model_validator(mode="after")
    def validate_replace_range(self):
        if self.infill_start_s >= self.infill_end_s:
            raise ValueError("infill_start_s muss kleiner als infill_end_s sein.")
        duration = self.infill_end_s - self.infill_start_s
        if duration < 6 or duration > 60:
            raise ValueError("Der Replace-Bereich muss zwischen 6 und 60 Sekunden liegen.")
        return self


class GenerateMashupRequest(BaseModel):
    upload_url_list: list[str] = Field(
        min_length=2,
        max_length=2,
        validation_alias=AliasChoices("upload_url_list", "uploadUrlList"),
        serialization_alias="uploadUrlList",
    )
    customMode: bool = False
    instrumental: bool = False
    model: SunoModel = SunoModel.V5_5
    prompt: str | None = None
    style: str | None = None
    title: str | None = None
    vocal_gender: str | None = Field(
        default=None,
        validation_alias=AliasChoices("vocal_gender", "vocalGender"),
        serialization_alias="vocalGender",
    )
    styleWeight: float | None = None
    weirdnessConstraint: float | None = None
    audioWeight: float | None = None
    callback_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("callback_url", "callBackUrl"),
        serialization_alias="callBackUrl",
    )

    @model_validator(mode="after")
    def validate_mashup_payload(self):
        if len(self.upload_url_list) != 2:
            raise ValueError("Generate Mashup benötigt exakt zwei Audio-URLs.")
        if self.vocal_gender not in (None, "", "m", "f"):
            raise ValueError("vocal_gender muss leer, 'm' oder 'f' sein.")
        for field_name in ("styleWeight", "weirdnessConstraint", "audioWeight"):
            value = getattr(self, field_name)
            if value is not None and not 0 <= value <= 1:
                raise ValueError(f"{field_name} muss zwischen 0 und 1 liegen.")
        return self


class GenerateSoundsRequest(BaseModel):
    prompt: str = Field(min_length=1)
    model: SunoModel = SunoModel.V5
    sound_loop: bool = Field(
        default=False,
        validation_alias=AliasChoices("sound_loop", "soundLoop"),
        serialization_alias="soundLoop",
    )
    sound_tempo: int | None = Field(
        default=None,
        validation_alias=AliasChoices("sound_tempo", "soundTempo"),
        serialization_alias="soundTempo",
    )
    sound_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("sound_key", "soundKey"),
        serialization_alias="soundKey",
    )
    grab_lyrics: bool = Field(
        default=False,
        validation_alias=AliasChoices("grab_lyrics", "grabLyrics"),
        serialization_alias="grabLyrics",
    )
    callback_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("callback_url", "callBackUrl"),
        serialization_alias="callBackUrl",
    )
    task_id: str | None = None

    @model_validator(mode="after")
    def validate_sounds_payload(self):
        if self.model != SunoModel.V5:
            raise ValueError("Generate Sounds unterstützt laut SunoAPI nur Modell V5.")
        if self.sound_tempo is not None and not 1 <= self.sound_tempo <= 300:
            raise ValueError("sound_tempo muss zwischen 1 und 300 BPM liegen.")
        return self


class AddVocalsRequest(BaseModel):
    audio_url: str = Field(
        min_length=1,
        validation_alias=AliasChoices("audio_url", "uploadUrl"),
        serialization_alias="uploadUrl",
    )
    prompt: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=100)
    negative_tags: str = Field(
        min_length=1,
        validation_alias=AliasChoices("negative_tags", "negativeTags"),
        serialization_alias="negativeTags",
    )
    style: str = Field(min_length=1)
    vocal_gender: str | None = Field(
        default=None,
        validation_alias=AliasChoices("vocal_gender", "vocalGender"),
        serialization_alias="vocalGender",
    )
    styleWeight: float | None = None
    weirdnessConstraint: float | None = None
    audioWeight: float | None = None
    model: SunoModel = SunoModel.V4_5PLUS
    callback_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("callback_url", "callBackUrl"),
        serialization_alias="callBackUrl",
    )

    @model_validator(mode="after")
    def validate_add_vocals_payload(self):
        settings = get_settings()
        limits = settings.limits_for_model(self.model.value)
        if limits["custom_prompt"] > 0 and len(self.prompt) > limits["custom_prompt"]:
            raise ValueError(f"Prompt ist zu lang. Erlaubt: {limits['custom_prompt']}, aktuell: {len(self.prompt)}.")
        if limits["style"] > 0 and len(self.style) > limits["style"]:
            raise ValueError(f"Style ist zu lang. Erlaubt: {limits['style']}, aktuell: {len(self.style)}.")
        for field_name in ("styleWeight", "weirdnessConstraint", "audioWeight"):
            value = getattr(self, field_name)
            if value is not None and not 0 <= value <= 1:
                raise ValueError(f"{field_name} muss zwischen 0 und 1 liegen.")
        if self.vocal_gender not in (None, "", "m", "f"):
            raise ValueError("vocal_gender muss leer, 'm' oder 'f' sein.")
        return self


class AddInstrumentalRequest(BaseModel):
    audio_url: str = Field(
        min_length=1,
        validation_alias=AliasChoices("audio_url", "uploadUrl"),
        serialization_alias="uploadUrl",
    )
    title: str = Field(min_length=1, max_length=100)
    tags: str = Field(min_length=1)
    negative_tags: str = Field(
        min_length=1,
        validation_alias=AliasChoices("negative_tags", "negativeTags"),
        serialization_alias="negativeTags",
    )
    vocal_gender: str | None = Field(
        default=None,
        validation_alias=AliasChoices("vocal_gender", "vocalGender"),
        serialization_alias="vocalGender",
    )
    styleWeight: float | None = None
    weirdnessConstraint: float | None = None
    audioWeight: float | None = None
    model: SunoModel = SunoModel.V4_5PLUS
    callback_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("callback_url", "callBackUrl"),
        serialization_alias="callBackUrl",
    )

    @model_validator(mode="after")
    def validate_add_instrumental_payload(self):
        settings = get_settings()
        limits = settings.limits_for_model(self.model.value)
        if limits["style"] > 0 and len(self.tags) > limits["style"]:
            raise ValueError(f"Tags/Style sind zu lang. Erlaubt: {limits['style']}, aktuell: {len(self.tags)}.")
        for field_name in ("styleWeight", "weirdnessConstraint", "audioWeight"):
            value = getattr(self, field_name)
            if value is not None and not 0 <= value <= 1:
                raise ValueError(f"{field_name} muss zwischen 0 und 1 liegen.")
        if self.vocal_gender not in (None, "", "m", "f"):
            raise ValueError("vocal_gender muss leer, 'm' oder 'f' sein.")
        return self


class BoostMusicStyleRequest(BaseModel):
    content: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_boost_style_payload(self):
        limit = max((limits.get("style", 0) for limits in get_settings().model_limits.values()), default=0)
        if limit > 0 and len(self.content) > limit:
            raise ValueError(f"Style-Inhalt ist zu lang. Erlaubt: {limit}, aktuell: {len(self.content)}.")
        return self


class GenericAudioUrlRequest(BaseModel):
    audio_url: str = Field(
        min_length=1,
        validation_alias=AliasChoices("audio_url", "uploadUrl"),
        serialization_alias="uploadUrl",
    )
    callback_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("callback_url", "callBackUrl"),
        serialization_alias="callBackUrl",
    )


class SeparateAudioRequest(BaseModel):
    task_id: str = Field(
        min_length=1,
        validation_alias=AliasChoices("task_id", "taskId"),
        serialization_alias="taskId",
    )
    audio_id: str = Field(
        min_length=1,
        validation_alias=AliasChoices("audio_id", "audioId"),
        serialization_alias="audioId",
    )
    type: str = "separate_vocal"
    callback_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("callback_url", "callBackUrl"),
        serialization_alias="callBackUrl",
    )

    @model_validator(mode="after")
    def validate_separation_type(self):
        if self.type not in {"separate_vocal", "split_stem"}:
            raise ValueError("type muss 'separate_vocal' oder 'split_stem' sein.")
        return self


class ArchiveAudioExtendRequest(BaseModel):
    defaultParamFlag: bool = False
    model: SunoModel = SunoModel.V5_5
    prompt: str | None = None
    style: str | None = None
    title: str | None = None
    continueAt: float | None = None
    autoContinueAt: bool = False
    persona_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("persona_id", "personaId"),
        serialization_alias="personaId",
    )
    persona_model: str | None = Field(
        default=None,
        validation_alias=AliasChoices("persona_model", "personaModel"),
        serialization_alias="personaModel",
    )
    voice_id: str | None = None
    negative_tags: str | None = Field(
        default=None,
        validation_alias=AliasChoices("negative_tags", "negativeTags"),
        serialization_alias="negativeTags",
    )
    vocal_gender: str | None = Field(
        default=None,
        validation_alias=AliasChoices("vocal_gender", "vocalGender"),
        serialization_alias="vocalGender",
    )
    styleWeight: float | None = None
    weirdnessConstraint: float | None = None
    audioWeight: float | None = None
    callback_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("callback_url", "callBackUrl"),
        serialization_alias="callBackUrl",
    )

    @model_validator(mode="after")
    def validate_archive_extend_payload(self):
        settings = get_settings()
        limits = settings.limits_for_model(self.model.value)
        if self.defaultParamFlag:
            if not self.prompt or not self.prompt.strip():
                raise ValueError("Bei Custom-Extension ist prompt erforderlich.")
            if not self.style or not self.style.strip():
                raise ValueError("Bei Custom-Extension ist style erforderlich.")
            if not self.title or not self.title.strip():
                raise ValueError("Bei Custom-Extension ist title erforderlich.")
            if not self.autoContinueAt and (self.continueAt is None or self.continueAt <= 0):
                raise ValueError("Bei Custom-Extension ist continueAt > 0 erforderlich.")
            if limits["custom_prompt"] > 0 and len(self.prompt) > limits["custom_prompt"]:
                raise ValueError(f"Extend-Prompt ist zu lang. Erlaubt: {limits['custom_prompt']}, aktuell: {len(self.prompt)}.")
            if limits["style"] > 0 and len(self.style) > limits["style"]:
                raise ValueError(f"Extend-Style ist zu lang. Erlaubt: {limits['style']}, aktuell: {len(self.style)}.")
            if limits["title"] > 0 and len(self.title) > limits["title"]:
                raise ValueError(f"Extend-Titel ist zu lang. Erlaubt: {limits['title']}, aktuell: {len(self.title)}.")
        for field_name in ("styleWeight", "weirdnessConstraint", "audioWeight"):
            value = getattr(self, field_name)
            if value is not None and not 0 <= value <= 1:
                raise ValueError(f"{field_name} muss zwischen 0 und 1 liegen.")
        return self


class ArchiveAudioCoverSongRequest(BaseModel):
    customMode: bool = False
    instrumental: bool = False
    model: SunoModel = SunoModel.V5_5
    prompt: str = Field(min_length=1)
    style: str | None = None
    title: str | None = None
    persona_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("persona_id", "personaId"),
        serialization_alias="personaId",
    )
    persona_model: str | None = Field(
        default=None,
        validation_alias=AliasChoices("persona_model", "personaModel"),
        serialization_alias="personaModel",
    )
    voice_id: str | None = None
    negative_tags: str | None = Field(
        default=None,
        validation_alias=AliasChoices("negative_tags", "negativeTags"),
        serialization_alias="negativeTags",
    )
    vocal_gender: str | None = Field(
        default=None,
        validation_alias=AliasChoices("vocal_gender", "vocalGender"),
        serialization_alias="vocalGender",
    )
    styleWeight: float | None = None
    weirdnessConstraint: float | None = None
    audioWeight: float | None = None
    callback_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("callback_url", "callBackUrl"),
        serialization_alias="callBackUrl",
    )

    @model_validator(mode="after")
    def validate_archive_cover_song_payload(self):
        settings = get_settings()
        limits = settings.limits_for_model(self.model.value)
        if self.customMode:
            if not self.style or not self.style.strip():
                raise ValueError("Im Custom-Cover-Modus ist style erforderlich.")
            if not self.title or not self.title.strip():
                raise ValueError("Im Custom-Cover-Modus ist title erforderlich.")
            if not self.instrumental and not self.prompt.strip():
                raise ValueError("Im Custom-Cover-Modus mit Gesang ist prompt/Lyrics erforderlich.")
            if limits["custom_prompt"] > 0 and len(self.prompt) > limits["custom_prompt"]:
                raise ValueError(f"Cover-Prompt ist zu lang. Erlaubt: {limits['custom_prompt']}, aktuell: {len(self.prompt)}.")
            if self.style and limits["style"] > 0 and len(self.style) > limits["style"]:
                raise ValueError(f"Cover-Style ist zu lang. Erlaubt: {limits['style']}, aktuell: {len(self.style)}.")
            if self.title and limits["title"] > 0 and len(self.title) > limits["title"]:
                raise ValueError(f"Cover-Titel ist zu lang. Erlaubt: {limits['title']}, aktuell: {len(self.title)}.")
        else:
            if limits["simple_prompt"] > 0 and len(self.prompt) > limits["simple_prompt"]:
                raise ValueError(f"Cover-Prompt ist zu lang. Erlaubt: {limits['simple_prompt']}, aktuell: {len(self.prompt)}.")
        for field_name in ("styleWeight", "weirdnessConstraint", "audioWeight"):
            value = getattr(self, field_name)
            if value is not None and not 0 <= value <= 1:
                raise ValueError(f"{field_name} muss zwischen 0 und 1 liegen.")
        return self


class ArchiveAudioAddVocalsRequest(BaseModel):
    prompt: str = Field(min_length=1)
    title: str = Field(min_length=1)
    negative_tags: str = Field(
        min_length=1,
        validation_alias=AliasChoices("negative_tags", "negativeTags"),
        serialization_alias="negativeTags",
    )
    style: str = Field(min_length=1)
    vocal_gender: str | None = Field(
        default=None,
        validation_alias=AliasChoices("vocal_gender", "vocalGender"),
        serialization_alias="vocalGender",
    )
    styleWeight: float | None = None
    weirdnessConstraint: float | None = None
    audioWeight: float | None = None
    model: SunoModel = SunoModel.V4_5PLUS
    callback_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("callback_url", "callBackUrl"),
        serialization_alias="callBackUrl",
    )

    @model_validator(mode="after")
    def validate_archive_add_vocals_payload(self):
        settings = get_settings()
        limits = settings.limits_for_model(self.model.value)
        if limits["custom_prompt"] > 0 and len(self.prompt) > limits["custom_prompt"]:
            raise ValueError(f"Prompt ist zu lang. Erlaubt: {limits['custom_prompt']}, aktuell: {len(self.prompt)}.")
        if limits["style"] > 0 and len(self.style) > limits["style"]:
            raise ValueError(f"Style ist zu lang. Erlaubt: {limits['style']}, aktuell: {len(self.style)}.")
        if limits["title"] > 0 and len(self.title) > limits["title"]:
            raise ValueError(f"Titel ist zu lang. Erlaubt: {limits['title']}, aktuell: {len(self.title)}.")
        for field_name in ("styleWeight", "weirdnessConstraint", "audioWeight"):
            value = getattr(self, field_name)
            if value is not None and not 0 <= value <= 1:
                raise ValueError(f"{field_name} muss zwischen 0 und 1 liegen.")
        if self.vocal_gender not in (None, "", "m", "f"):
            raise ValueError("vocal_gender muss leer, 'm' oder 'f' sein.")
        return self


class ArchiveAudioAddInstrumentalRequest(BaseModel):
    title: str = Field(min_length=1)
    tags: str = Field(min_length=1)
    negative_tags: str = Field(
        min_length=1,
        validation_alias=AliasChoices("negative_tags", "negativeTags"),
        serialization_alias="negativeTags",
    )
    vocal_gender: str | None = Field(
        default=None,
        validation_alias=AliasChoices("vocal_gender", "vocalGender"),
        serialization_alias="vocalGender",
    )
    styleWeight: float | None = None
    weirdnessConstraint: float | None = None
    audioWeight: float | None = None
    model: SunoModel = SunoModel.V4_5PLUS
    callback_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("callback_url", "callBackUrl"),
        serialization_alias="callBackUrl",
    )

    @model_validator(mode="after")
    def validate_archive_add_instrumental_payload(self):
        settings = get_settings()
        limits = settings.limits_for_model(self.model.value)
        if limits["style"] > 0 and len(self.tags) > limits["style"]:
            raise ValueError(f"Tags/Style sind zu lang. Erlaubt: {limits['style']}, aktuell: {len(self.tags)}.")
        if limits["title"] > 0 and len(self.title) > limits["title"]:
            raise ValueError(f"Titel ist zu lang. Erlaubt: {limits['title']}, aktuell: {len(self.title)}.")
        for field_name in ("styleWeight", "weirdnessConstraint", "audioWeight"):
            value = getattr(self, field_name)
            if value is not None and not 0 <= value <= 1:
                raise ValueError(f"{field_name} muss zwischen 0 und 1 liegen.")
        if self.vocal_gender not in (None, "", "m", "f"):
            raise ValueError("vocal_gender muss leer, 'm' oder 'f' sein.")
        return self


class ArchiveAudioPersonaRequest(BaseModel):
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    vocalStart: float | None = None
    vocalEnd: float | None = None
    style: str | None = None

    @model_validator(mode="after")
    def validate_archive_persona_range(self):
        if self.vocalStart is not None and self.vocalEnd is not None:
            if self.vocalStart < 0 or self.vocalEnd <= self.vocalStart:
                raise ValueError("vocalStart/vocalEnd sind ungültig.")
            segment = self.vocalEnd - self.vocalStart
            if segment < 10 or segment > 30:
                raise ValueError("Persona-Analysebereich muss zwischen 10 und 30 Sekunden lang sein.")
        return self


class ArchiveAudioCoverImageRequest(BaseModel):
    callback_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("callback_url", "callBackUrl"),
        serialization_alias="callBackUrl",
    )


class GenerateLyricsRequest(BaseModel):
    prompt: str = Field(min_length=1)
    callback_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("callback_url", "callBackUrl"),
        serialization_alias="callBackUrl",
    )

    @model_validator(mode="after")
    def validate_with_configured_lyrics_limit(self):
        limit = get_settings().suno_lyrics_prompt_max_length
        if limit > 0 and len(self.prompt) > limit:
            raise ValueError(
                f"Lyrics-Prompt ist zu lang. Erlaubt: {limit}, aktuell: {len(self.prompt)}."
            )
        return self


class TimestampedLyricsRequest(BaseModel):
    audio_id: str = Field(
        min_length=1,
        validation_alias=AliasChoices("audio_id", "audioId"),
        serialization_alias="audioId",
    )
    task_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("task_id", "taskId"),
        serialization_alias="taskId",
    )
    callback_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("callback_url", "callBackUrl"),
        serialization_alias="callBackUrl",
    )


class ConvertToWavRequest(BaseModel):
    task_id: str = Field(
        min_length=1,
        validation_alias=AliasChoices("task_id", "taskId"),
        serialization_alias="taskId",
    )
    audio_id: str = Field(
        min_length=1,
        validation_alias=AliasChoices("audio_id", "audioId"),
        serialization_alias="audioId",
    )
    callback_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("callback_url", "callBackUrl"),
        serialization_alias="callBackUrl",
    )


class GenerateMidiRequest(BaseModel):
    task_id: str = Field(
        min_length=1,
        validation_alias=AliasChoices("task_id", "taskId"),
        serialization_alias="taskId",
    )
    audio_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("audio_id", "audioId"),
        serialization_alias="audioId",
    )
    callback_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("callback_url", "callBackUrl"),
        serialization_alias="callBackUrl",
    )


class CreateVideoRequest(BaseModel):
    task_id: str = Field(
        min_length=1,
        validation_alias=AliasChoices("task_id", "taskId"),
        serialization_alias="taskId",
    )
    audio_id: str = Field(
        min_length=1,
        validation_alias=AliasChoices("audio_id", "audioId"),
        serialization_alias="audioId",
    )
    author: str | None = None
    domain_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices("domain_name", "domainName"),
        serialization_alias="domainName",
    )
    callback_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("callback_url", "callBackUrl"),
        serialization_alias="callBackUrl",
    )


class VoiceValidateRequest(BaseModel):
    voice_url: str = Field(min_length=1)
    vocal_start_s: int = Field(ge=0)
    vocal_end_s: int = Field(gt=0)
    language: str = Field(default="de", min_length=2, max_length=8)
    callback_url: str | None = None

    @model_validator(mode="after")
    def validate_voice_segment(self):
        if self.vocal_end_s <= self.vocal_start_s:
            raise ValueError("vocal_end_s muss größer als vocal_start_s sein.")
        return self


class VoiceRegenerateRequest(BaseModel):
    task_id: str = Field(min_length=1)
    callback_url: str | None = None


class CustomVoiceRequest(BaseModel):
    task_id: str = Field(min_length=1)
    verify_url: str = Field(min_length=1)
    voice_name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    style: str | None = Field(default=None, max_length=255)
    singer_skill_level: str | None = "beginner"
    callback_url: str | None = None

    @model_validator(mode="after")
    def validate_skill_level(self):
        allowed = {None, "", "beginner", "intermediate", "advanced", "professional"}
        if self.singer_skill_level not in allowed:
            raise ValueError("singer_skill_level muss beginner, intermediate, advanced oder professional sein.")
        return self


class VoiceAvailabilityRequest(BaseModel):
    task_id: str = Field(min_length=1)


class UploadBase64Request(BaseModel):
    file: str = Field(min_length=1)
    original_name: str | None = None


class UploadUrlRequest(BaseModel):
    url: str = Field(min_length=1)


class WebhookPayload(BaseModel):
    id: str | None = None
    task_id: str | None = None
    status: str | None = None
    data: dict[str, Any] | list[Any] | None = None
    error: str | None = None
    model_config = ConfigDict(extra="allow")


class PlaylistCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    cover_image_url: str | None = None
    sort_order: int = 0


class PlaylistUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    cover_image_url: str | None = None
    sort_order: int | None = None


class PlaylistItemCreate(BaseModel):
    audio_asset_id: int | None = None
    song_id: int | None = None
    note: str | None = None

    @model_validator(mode="after")
    def validate_reference(self):
        if not self.audio_asset_id and not self.song_id:
            raise ValueError("playlist item benötigt audio_asset_id oder song_id.")
        return self


class PlaylistItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    playlist_id: int
    audio_asset_id: int | None = None
    song_id: int | None = None
    position: int
    note: str | None = None
    created_at: Any | None = None
    updated_at: Any | None = None
    audio_asset: dict[str, Any] | None = None
    song: dict[str, Any] | None = None


class PlaylistRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None = None
    cover_image_url: str | None = None
    sort_order: int = 0
    metadata_json: dict[str, Any] | None = None
    created_at: Any | None = None
    updated_at: Any | None = None
    items: list[PlaylistItemRead] = []


class LyricDraftCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(default="", max_length=50000)
    status: str = "draft"
    language: str | None = "de"
    tags: str | None = None
    structure_template: str | None = None


class LyricDraftUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    content: str | None = Field(default=None, max_length=50000)
    status: str | None = None
    language: str | None = None
    tags: str | None = None
    structure_template: str | None = None


class LyricDraftRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    content: str
    status: str
    language: str | None = None
    tags: str | None = None
    structure_template: str | None = None
    metadata_json: dict[str, Any] | None = None
    created_at: Any | None = None
    updated_at: Any | None = None


class MusicStyleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    genre: str | None = None
    bpm: int | None = None
    style_text: str = Field(min_length=1, max_length=5000)
    description: str | None = None
    tags: str | None = None
    is_favorite: bool = False
    is_profile: bool = False
    profile_json: dict[str, Any] | None = None


class MusicStyleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    genre: str | None = None
    bpm: int | None = None
    style_text: str | None = Field(default=None, min_length=1, max_length=5000)
    description: str | None = None
    tags: str | None = None
    is_favorite: bool | None = None
    is_profile: bool | None = None
    profile_json: dict[str, Any] | None = None


class MusicStyleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    genre: str | None = None
    bpm: int | None = None
    style_text: str
    description: str | None = None
    tags: str | None = None
    is_favorite: bool
    usage_count: int
    is_profile: bool | None = False
    profile_json: dict[str, Any] | None = None
    created_at: Any | None = None
    updated_at: Any | None = None


class AudioAssetUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    display_title: str | None = Field(default=None, max_length=255)
    project_id: int | None = None
    version_label: str | None = Field(default=None, max_length=120)
    is_favorite: bool | None = None
    is_final: bool | None = None


class AudioProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    cover_image_url: str | None = None


class AudioProjectUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    cover_image_url: str | None = None
    status: str | None = None
    is_favorite: bool | None = None
    final_audio_asset_id: int | None = None


class AudioProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str | None = None
    cover_image_url: str | None = None
    status: str
    is_favorite: bool
    final_audio_asset_id: int | None = None
    metadata_json: dict[str, Any] | None = None
    created_at: Any | None = None
    updated_at: Any | None = None
    audio_assets: list[dict[str, Any]] = []


class ProductionProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    model: str | None = None
    style: str | None = None
    vocal_gender: str | None = None
    negative_tags: str | None = None
    persona_id: str | None = None
    persona_model: str | None = None
    style_weight: float | None = None
    weirdness_constraint: float | None = None
    audio_weight: float | None = None
    instrumental: bool = False
    custom_mode: bool = True
    is_favorite: bool = False


class ProductionProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    model: str | None = None
    style: str | None = None
    vocal_gender: str | None = None
    negative_tags: str | None = None
    persona_id: str | None = None
    persona_model: str | None = None
    style_weight: float | None = None
    weirdness_constraint: float | None = None
    audio_weight: float | None = None
    instrumental: bool | None = None
    custom_mode: bool | None = None
    is_favorite: bool | None = None


class ProductionProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None = None
    model: str | None = None
    style: str | None = None
    vocal_gender: str | None = None
    negative_tags: str | None = None
    persona_id: str | None = None
    persona_model: str | None = None
    style_weight: float | None = None
    weirdness_constraint: float | None = None
    audio_weight: float | None = None
    instrumental: bool
    custom_mode: bool
    is_favorite: bool
    metadata_json: dict[str, Any] | None = None
    created_at: Any | None = None
    updated_at: Any | None = None


class ContentDeleteItem(BaseModel):
    type: str = Field(min_length=1)
    id: int


class BulkContentDeleteRequest(BaseModel):
    items: list[ContentDeleteItem] = Field(default_factory=list)
    delete_files: bool = True


class AiProviderConfig(BaseModel):
    default_provider: str
    default_model: str
    allowed_models: dict[str, list[str]]
    providers: dict[str, dict[str, bool]]


class AiChatSessionCreate(BaseModel):
    title: str = Field(default="Neue KI-Session", min_length=1, max_length=255)
    provider: str = Field(default="openai", min_length=1, max_length=80)
    model: str = Field(default="GPT-5.4-mini", min_length=1, max_length=120)
    lyric_draft_id: int | None = None
    assistant_profile_id: int | None = None
    canvas_content: str | None = Field(default="", max_length=50000)
    work_mode: str | None = Field(default="lyrics", max_length=80)


class AiChatSessionUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    provider: str | None = Field(default=None, min_length=1, max_length=80)
    model: str | None = Field(default=None, min_length=1, max_length=120)
    lyric_draft_id: int | None = None
    assistant_profile_id: int | None = None
    canvas_content: str | None = Field(default=None, max_length=50000)
    work_mode: str | None = Field(default=None, max_length=80)


class AiChatMessageCreate(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    canvas_content: str = Field(default="", max_length=50000)
    apply_to_canvas: bool = False
    work_mode: str | None = Field(default=None, max_length=80)


class AiCanvasSaveRequest(BaseModel):
    canvas_content: str = Field(default="", max_length=50000)
    source: str = Field(default="manual", max_length=80)
    change_summary: str | None = Field(default=None, max_length=1000)


class AiChatMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: int
    role: str
    content: str
    provider: str | None = None
    model: str | None = None
    canvas_before: str | None = None
    canvas_after: str | None = None
    change_summary: str | None = None
    raw_response: dict[str, Any] | None = None
    created_at: Any | None = None


class AiChatSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int | None = None
    lyric_draft_id: int | None = None
    title: str
    provider: str
    model: str
    assistant_profile_id: int | None = None
    canvas_content: str | None = None
    current_history_index: int = 0
    metadata_json: dict[str, Any] | None = None
    created_at: Any | None = None
    updated_at: Any | None = None
    messages: list[AiChatMessageRead] = []


class AiChatRunResponse(BaseModel):
    session: AiChatSessionRead
    assistant_message: AiChatMessageRead
    canvas_changed: bool
    canvas_content: str
    change_summary: str | None = None



class AiInstructionFileCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    content: str = Field(min_length=1, max_length=200000)
    filename: str | None = None
    content_type: str | None = None
    is_active: bool = True


class AiInstructionFileUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    content: str | None = Field(default=None, min_length=1, max_length=200000)
    is_active: bool | None = None


class AiInstructionFileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    filename: str | None = None
    content_type: str | None = None
    description: str | None = None
    content: str | None = None
    is_active: bool = True
    created_at: Any | None = None
    updated_at: Any | None = None


class AiAssistantProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    provider: str = Field(default="openai", min_length=1, max_length=80)
    model: str = Field(default="GPT-5.4-mini", min_length=1, max_length=120)
    system_instruction: str | None = Field(default=None, max_length=200000)
    response_format_instruction: str | None = Field(default=None, max_length=200000)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_output_tokens: int | None = Field(default=None, ge=1, le=64000)
    is_default: bool = False
    is_active: bool = True
    linked_file_ids: list[int] = Field(default_factory=list)


class AiAssistantProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    provider: str | None = Field(default=None, min_length=1, max_length=80)
    model: str | None = Field(default=None, min_length=1, max_length=120)
    system_instruction: str | None = Field(default=None, max_length=200000)
    response_format_instruction: str | None = Field(default=None, max_length=200000)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_output_tokens: int | None = Field(default=None, ge=1, le=64000)
    is_default: bool | None = None
    is_active: bool | None = None
    linked_file_ids: list[int] | None = None


class AiAssistantProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None = None
    provider: str
    model: str
    system_instruction: str | None = None
    response_format_instruction: str | None = None
    temperature: float | None = None
    max_output_tokens: int | None = None
    is_default: bool = False
    is_active: bool = True
    linked_file_ids: list[int] = Field(default_factory=list)
    linked_files: list[AiInstructionFileRead] = Field(default_factory=list)
    created_at: Any | None = None
    updated_at: Any | None = None


class AiProfileLinkFilesRequest(BaseModel):
    file_ids: list[int] = Field(default_factory=list)


class UserAdminUpdate(BaseModel):
    is_active: bool | None = None
    is_admin: bool | None = None
    nickname: str | None = Field(default=None, max_length=120)


class AiAdminSettingsRead(BaseModel):
    default_provider: str
    default_model: str
    default_assistant_profile_id: int | None = None
    system_instruction: str | None = None
    allowed_models: dict[str, list[str]] = Field(default_factory=dict)
    providers: dict[str, Any] = Field(default_factory=dict)
    transcription_backend: str = "voxtral"
    transcription_language: str = "de"
    lyrics_template_mode: str = "lyrics_source_of_truth"
    lyrics_match_mode: str = "lenient"
    srt_output_enabled: bool = True
    srt_auto_regenerate: bool = False
    srt_generate_vocal_stems_before_transcription: bool = False
    srt_ai_cleanup_enabled: bool = True
    srt_alignment_engine: str = "heuristic"
    srt_quality_gate_enabled: bool = False
    srt_quality_gate_min_score: float = Field(default=0.7, ge=0.3, le=0.95)
    library_content_polling_enabled: bool = False
    library_content_polling_interval_minutes: int = Field(default=15, ge=1, le=1440)
    library_content_polling_limit: int = Field(default=500, ge=10, le=5000)
    extend_auto_continue_at_enabled: bool = False
    extend_auto_continue_at_search_window_seconds: int = Field(default=15, ge=5, le=60)
    extend_auto_continue_at_vocal_threshold_ratio: float = Field(default=0.03, ge=0.005, le=0.25)
    extend_auto_continue_at_fallback_offset_seconds: float = Field(default=4.0, ge=1.0, le=30.0)
    extend_auto_continue_at_timeout_seconds: int = Field(default=180, ge=30, le=1200)
    audio_ai_analysis_enabled: bool = True
    audio_ai_analysis_ai_summary_enabled: bool = True
    audio_ai_model_analysis_enabled: bool = True
    audio_ai_analysis_max_seconds: int = Field(default=240, ge=30, le=1200)
    audio_ai_model_analysis_seconds: int = Field(default=30, ge=8, le=90)
    audio_ai_model_analysis_top_k: int = Field(default=8, ge=5, le=25)
    audio_ai_model_cache_dir: str = "storage/models/huggingface"
    audio_ai_acoustid_configured: bool = False
    library_ai_tagging_enabled: bool = False
    library_ai_tagging_profile_id: int | None = None
    library_ai_tagging_max_tags_per_asset: int = Field(default=5, ge=2, le=8)
    transcription_backends: list[str] = Field(default_factory=lambda: ["groq", "whisperx", "openai_whisper_api", "voxtral"])
    transcription_languages: list[str] = Field(default_factory=lambda: ["auto", "de", "en"])
    transcription_runtime: dict[str, Any] = Field(default_factory=dict)


class AiAdminSettingsUpdate(BaseModel):
    default_provider: str
    default_model: str
    default_assistant_profile_id: int | None = None
    system_instruction: str | None = None
    transcription_backend: str = "voxtral"
    transcription_language: str = "de"
    lyrics_template_mode: str = "lyrics_source_of_truth"
    lyrics_match_mode: str = "lenient"
    srt_output_enabled: bool = True
    srt_auto_regenerate: bool = False
    srt_generate_vocal_stems_before_transcription: bool = False
    srt_ai_cleanup_enabled: bool = True
    srt_alignment_engine: str = "heuristic"
    srt_quality_gate_enabled: bool = False
    srt_quality_gate_min_score: float = Field(default=0.7, ge=0.3, le=0.95)
    library_content_polling_enabled: bool = False
    library_content_polling_interval_minutes: int = Field(default=15, ge=1, le=1440)
    library_content_polling_limit: int = Field(default=500, ge=10, le=5000)
    extend_auto_continue_at_enabled: bool = False
    extend_auto_continue_at_search_window_seconds: int = Field(default=15, ge=5, le=60)
    extend_auto_continue_at_vocal_threshold_ratio: float = Field(default=0.03, ge=0.005, le=0.25)
    extend_auto_continue_at_fallback_offset_seconds: float = Field(default=4.0, ge=1.0, le=30.0)
    extend_auto_continue_at_timeout_seconds: int = Field(default=180, ge=30, le=1200)
    audio_ai_analysis_enabled: bool = True
    audio_ai_analysis_ai_summary_enabled: bool = True
    audio_ai_model_analysis_enabled: bool = True
    audio_ai_analysis_max_seconds: int = Field(default=240, ge=30, le=1200)
    audio_ai_model_analysis_seconds: int = Field(default=30, ge=8, le=90)
    audio_ai_model_analysis_top_k: int = Field(default=8, ge=5, le=25)
    library_ai_tagging_enabled: bool = False
    library_ai_tagging_profile_id: int | None = None
    library_ai_tagging_max_tags_per_asset: int = Field(default=5, ge=2, le=8)


class AiProviderTestRequest(BaseModel):
    provider: str
    model: str
    message: str | None = None


class VocalTagCreate(BaseModel):
    label: str = Field(min_length=1, max_length=255)
    tag: str = Field(min_length=1)
    category: str = Field(default="Tags", min_length=1, max_length=120)
    description: str | None = None
    sort_order: int = 0
    is_active: bool = True


class VocalTagUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=255)
    tag: str | None = Field(default=None, min_length=1)
    category: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    sort_order: int | None = None
    is_active: bool | None = None


class VocalTagRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    label: str
    tag: str
    category: str
    description: str | None = None
    sort_order: int = 0
    is_active: bool = True
    created_at: Any | None = None
    updated_at: Any | None = None


class ProductionWorkflowUpdate(BaseModel):
    production_status: str | None = Field(default=None, max_length=80)
    rating: int | None = Field(default=None, ge=0, le=5)
    energy: int | None = Field(default=None, ge=0, le=5)
    hook_strength: int | None = Field(default=None, ge=0, le=5)
    lyrics_quality: int | None = Field(default=None, ge=0, le=5)
    mix_quality: int | None = Field(default=None, ge=0, le=5)
    release_ready: bool | None = None
    youtube_ready: bool | None = None
    video_ready: bool | None = None
    notes: str | None = None
    youtube_title: str | None = Field(default=None, max_length=255)
    youtube_playlist: str | None = Field(default=None, max_length=255)
    youtube_description: str | None = None
    youtube_tags: list[str] | str | None = None
    genre: str | None = Field(default=None, max_length=120)
    mood: str | None = Field(default=None, max_length=120)
    todo: list[str] | str | None = None
    checkpoints: dict[str, Any] | None = None
    custom: dict[str, Any] | None = None


class DuplicateAssetVersionRequest(BaseModel):
    label: str | None = Field(default="Neue Version", max_length=120)
    notes: str | None = None

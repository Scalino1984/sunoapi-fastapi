import pytest
from pydantic import ValidationError

from app.schemas import (
    ArchiveAudioExtendRequest,
    ConvertToWavRequest,
    BatchImportSunoSongRequest,
    BatchImportSunoTaskRequest,
    ExtendMusicRequest,
    GenerateCoverRequest,
    GenerateMashupRequest,
    GenerateMusicRequest,
    GenerateSoundsRequest,
    ImportSunoTaskRequest,
    ProductionWorkflowUpdate,
    ReplaceSectionRequest,
)


def test_import_suno_task_request_accepts_known_task_types_and_rejects_unknown():
    request = ImportSunoTaskRequest(task_id=" task-123 ", task_type="extend_music")
    assert request.task_id == "task-123"
    assert request.task_type == "extend_music"

    with pytest.raises(ValidationError) as exc:
        ImportSunoTaskRequest(task_id="task-123", task_type="dangerous_unknown")
    assert "Nicht unterstützter Import-Task-Typ" in str(exc.value)


def test_batch_import_task_ids_are_split_trimmed_and_deduplicated():
    request = BatchImportSunoTaskRequest(
        task_ids="a, b\na; a\n\n c ",
        cache_video=False,
    )
    assert request.parsed_task_ids == ["a", "b", "c"]
    assert request.cache_video is False
    assert request.model_dump()["cache_video"] is False


def test_batch_import_song_ids_are_split_trimmed_and_deduplicated():
    request = BatchImportSunoSongRequest(song_ids="https://suno.com/song/1\nhttps://suno.com/song/1;clip-2")
    assert request.parsed_song_ids == ["https://suno.com/song/1", "clip-2"]


def test_generate_music_request_preserves_advanced_suno_parameters():
    request = GenerateMusicRequest(
        prompt="Text",
        style="Boom Bap",
        title="Titel",
        model="V5_5",
        styleWeight=0.7,
        weirdnessConstraint=0.4,
        audioWeight=0.3,
        negative_tags="no EDM",
        personaId="persona_123",
        personaModel="style_persona",
        callback_url="https://example.test/callback",
    )

    dumped = request.model_dump(by_alias=True, exclude_none=True)
    assert dumped["styleWeight"] == 0.7
    assert dumped["weirdnessConstraint"] == 0.4
    assert dumped["audioWeight"] == 0.3
    assert dumped["negativeTags"] == "no EDM"
    assert dumped["personaId"] == "persona_123"
    assert dumped["personaModel"] == "style_persona"
    assert dumped["callBackUrl"] == "https://example.test/callback"

    official_request = GenerateMusicRequest(
        prompt="Text",
        negativeTags="no Rock",
        vocalGender="f",
    )
    official_dumped = official_request.model_dump(by_alias=True, exclude_none=True)
    assert official_dumped["negativeTags"] == "no Rock"
    assert official_dumped["vocalGender"] == "f"


def test_followup_requests_dump_official_suno_payload_names():
    replace = ReplaceSectionRequest(
        task_id="task-1",
        audio_id="audio-1",
        prompt="new line",
        tags="Boom Bap",
        title="Replace",
        infill_start_s=10,
        infill_end_s=20,
        full_lyrics="full lyrics",
        negative_tags="no EDM",
    ).model_dump(by_alias=True, exclude_none=True)
    assert replace["taskId"] == "task-1"
    assert replace["audioId"] == "audio-1"
    assert replace["infillStartS"] == 10
    assert replace["infillEndS"] == 20
    assert replace["fullLyrics"] == "full lyrics"
    assert replace["negativeTags"] == "no EDM"

    sounds = GenerateSoundsRequest(
        prompt="vinyl hit",
        sound_loop=True,
        sound_tempo=100,
        sound_key="C minor",
        grab_lyrics=True,
    ).model_dump(by_alias=True, exclude_none=True)
    assert sounds["soundLoop"] is True
    assert sounds["soundTempo"] == 100
    assert sounds["soundKey"] == "C minor"
    assert sounds["grabLyrics"] is True

    mashup = GenerateMashupRequest(
        upload_url_list=["https://example.test/a.mp3", "https://example.test/b.mp3"],
        customMode=True,
        vocal_gender="m",
    ).model_dump(by_alias=True, exclude_none=True)
    assert mashup["uploadUrlList"] == ["https://example.test/a.mp3", "https://example.test/b.mp3"]
    assert mashup["vocalGender"] == "m"

    cover = GenerateCoverRequest(task_id="task-cover").model_dump(by_alias=True, exclude_none=True)
    assert cover["taskId"] == "task-cover"

    wav = ConvertToWavRequest(task_id="task-wav", audio_id="audio-wav").model_dump(by_alias=True, exclude_none=True)
    assert wav["taskId"] == "task-wav"
    assert wav["audioId"] == "audio-wav"


def test_extend_requests_accept_and_dump_official_suno_parameters():
    request = ExtendMusicRequest(
        audioId="audio-source-1",
        defaultParamFlag=True,
        model="V5_5",
        prompt="Extend text",
        style="Boom Bap",
        title="Extended",
        continueAt=60,
        negativeTags="no EDM",
        vocalGender="m",
        personaId="persona_123",
        personaModel="style_persona",
        callback_url="https://example.test/callback",
    )

    dumped = request.model_dump(by_alias=True, exclude_none=True)
    assert dumped["audioId"] == "audio-source-1"
    assert dumped["defaultParamFlag"] is True
    assert dumped["continueAt"] == 60
    assert dumped["negativeTags"] == "no EDM"
    assert dumped["vocalGender"] == "m"
    assert dumped["personaId"] == "persona_123"
    assert dumped["personaModel"] == "style_persona"
    assert dumped["callBackUrl"] == "https://example.test/callback"

    archive_request = ArchiveAudioExtendRequest(
        defaultParamFlag=True,
        model="V5_5",
        prompt="Extend text",
        style="Boom Bap",
        title="Extended",
        continueAt=60,
        negativeTags="no EDM",
        vocalGender="m",
    )
    archive_dumped = archive_request.model_dump(by_alias=True, exclude_none=True)
    assert archive_dumped["continueAt"] == 60
    assert archive_dumped["negativeTags"] == "no EDM"
    assert archive_dumped["vocalGender"] == "m"

    auto_request = ArchiveAudioExtendRequest(
        defaultParamFlag=True,
        model="V5_5",
        prompt="Extend text",
        style="Boom Bap",
        title="Extended",
        autoContinueAt=True,
    )
    assert auto_request.model_dump(exclude_none=True)["autoContinueAt"] is True


def test_production_workflow_update_accepts_string_or_list_payload_fields():
    as_list = ProductionWorkflowUpdate(youtube_tags=["rap", "boom bap"], todo=["SRT prüfen"], rating=5)
    as_string = ProductionWorkflowUpdate(youtube_tags="rap, boom bap", todo="SRT prüfen", release_ready=True)

    assert as_list.youtube_tags == ["rap", "boom bap"]
    assert as_string.youtube_tags == "rap, boom bap"
    assert as_string.release_ready is True

    with pytest.raises(ValidationError):
        ProductionWorkflowUpdate(rating=6)

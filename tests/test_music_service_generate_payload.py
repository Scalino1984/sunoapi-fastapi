from app.models import AudioAsset, Song, SunoTask
from app.services.music_service import MusicService
from app.suno_client import SunoAPIClient


class FakeSunoClient:
    def __init__(self):
        self.generate_payload = None

    async def generate_music(self, payload):
        self.generate_payload = dict(payload)
        return {"code": 200, "data": {"taskId": "task-advanced-generate"}}


class FakeImportSunoClient:
    async def get_details(self, task_id):
        return {
            "code": 200,
            "data": {
                "taskId": task_id,
                "status": "SUCCESS",
                "negativeTags": "no EDM",
                "vocalGender": "m",
                "styleWeight": 0.77,
                "weirdnessConstraint": 0.33,
                "audioWeight": 0.44,
                "customMode": True,
                "instrumental": False,
                "response": {
                    "id": "audio-import-options-1",
                    "title": "Imported Options",
                    "audioUrl": "https://cdn.sunoapi.test/audio-import-options-1.mp3",
                    "duration": 140,
                },
            },
        }


class FakeExtendSunoClient:
    def __init__(self):
        self.extend_payload = None

    async def extend_music(self, payload):
        self.extend_payload = dict(payload)
        return {"code": 200, "data": {"taskId": "task-advanced-extend"}}

    async def upload_and_cover(self, payload):  # pragma: no cover - required by method map
        raise AssertionError("unexpected upload_and_cover call")

    async def upload_and_extend(self, payload):  # pragma: no cover - required by method map
        raise AssertionError("unexpected upload_and_extend call")

    async def add_instrumental(self, payload):  # pragma: no cover - required by method map
        raise AssertionError("unexpected add_instrumental call")

    async def add_vocals(self, payload):  # pragma: no cover - required by method map
        raise AssertionError("unexpected add_vocals call")

    async def boost_music_style(self, payload):  # pragma: no cover - required by method map
        raise AssertionError("unexpected boost_music_style call")

    async def generate_mashup(self, payload):  # pragma: no cover - required by method map
        raise AssertionError("unexpected generate_mashup call")

    async def replace_section(self, payload):  # pragma: no cover - required by method map
        raise AssertionError("unexpected replace_section call")

    async def generate_persona(self, payload):  # pragma: no cover - required by method map
        raise AssertionError("unexpected generate_persona call")

    async def create_music_cover(self, payload):  # pragma: no cover - required by method map
        raise AssertionError("unexpected create_music_cover call")

    async def generate_sounds(self, payload):  # pragma: no cover - required by method map
        raise AssertionError("unexpected generate_sounds call")

    async def get_timestamped_lyrics(self, payload):  # pragma: no cover - required by method map
        raise AssertionError("unexpected get_timestamped_lyrics call")

    async def separate(self, payload):  # pragma: no cover - required by method map
        raise AssertionError("unexpected separate call")

    async def convert_to_wav(self, payload):  # pragma: no cover - required by method map
        raise AssertionError("unexpected convert_to_wav call")

    async def generate_midi(self, payload):  # pragma: no cover - required by method map
        raise AssertionError("unexpected generate_midi call")

    async def create_video(self, payload):  # pragma: no cover - required by method map
        raise AssertionError("unexpected create_video call")

    async def generate_voice_verification_phrase(self, payload):  # pragma: no cover - required by method map
        raise AssertionError("unexpected generate_voice_verification_phrase call")

    async def regenerate_voice_verification_phrase(self, payload):  # pragma: no cover - required by method map
        raise AssertionError("unexpected regenerate_voice_verification_phrase call")

    async def create_custom_voice(self, payload):  # pragma: no cover - required by method map
        raise AssertionError("unexpected create_custom_voice call")


class FakeFollowupSunoClient(FakeExtendSunoClient):
    def __init__(self):
        self.add_vocals_payload = None
        self.add_instrumental_payload = None

    async def add_vocals(self, payload):
        self.add_vocals_payload = dict(payload)
        return {"code": 200, "data": {"taskId": "task-add-vocals"}}

    async def add_instrumental(self, payload):
        self.add_instrumental_payload = dict(payload)
        return {"code": 200, "data": {"taskId": "task-add-instrumental"}}


async def test_generate_music_preserves_advanced_options_for_suno_and_db(isolated_db_session):
    client = FakeSunoClient()
    service = MusicService(isolated_db_session, client=client)

    await service.generate_music(
        {
            "model": "V5_5",
            "customMode": True,
            "instrumental": False,
            "title": "Advanced Options",
            "prompt": "Song text",
            "style": "Boom Bap",
            "negativeTags": "no EDM",
            "vocalGender": "m",
            "styleWeight": 0.77,
            "weirdnessConstraint": 0.33,
            "audioWeight": 0.44,
            "ui_only_field": "must not pass",
        }
    )

    assert client.generate_payload["negativeTags"] == "no EDM"
    assert client.generate_payload["vocalGender"] == "m"
    assert client.generate_payload["styleWeight"] == 0.77
    assert client.generate_payload["weirdnessConstraint"] == 0.33
    assert client.generate_payload["audioWeight"] == 0.44
    assert "ui_only_field" not in client.generate_payload

    task = isolated_db_session.query(SunoTask).one()
    assert task.request_payload["negativeTags"] == "no EDM"
    assert task.request_payload["vocalGender"] == "m"
    assert task.request_payload["styleWeight"] == 0.77
    assert task.request_payload["weirdnessConstraint"] == 0.33
    assert task.request_payload["audioWeight"] == 0.44
    assert "ui_only_field" not in task.request_payload

    song = isolated_db_session.query(Song).one()
    assert song.task_id == "task-advanced-generate"


def test_suno_client_normalizes_advanced_generate_option_names():
    payload = SunoAPIClient._normalize_payload(
        {
            "negative_tags": "no EDM",
            "vocal_gender": "m",
            "styleWeight": 0.77,
            "weirdnessConstraint": 0.33,
            "audioWeight": 0.44,
        }
    )

    assert payload["negativeTags"] == "no EDM"
    assert payload["vocalGender"] == "m"
    assert payload["styleWeight"] == 0.77
    assert payload["weirdnessConstraint"] == 0.33
    assert payload["audioWeight"] == 0.44


def test_suno_client_normalizes_extend_option_names():
    payload = SunoAPIClient._normalize_payload(
        {
            "audio_id": "audio-source-1",
            "continue_at": 60,
            "default_param_flag": True,
            "negative_tags": "no EDM",
            "vocal_gender": "m",
        }
    )

    assert payload["audioId"] == "audio-source-1"
    assert payload["continueAt"] == 60
    assert payload["defaultParamFlag"] is True
    assert payload["negativeTags"] == "no EDM"
    assert payload["vocalGender"] == "m"


async def test_extend_music_stores_official_suno_payload_names(isolated_db_session):
    client = FakeExtendSunoClient()
    service = MusicService(isolated_db_session, client=client)

    await service.call_task_endpoint(
        "extend_music",
        {
            "audio_id": "audio-source-1",
            "default_param_flag": True,
            "model": "V5_5",
            "title": "Extended Options",
            "prompt": "Extend text",
            "style": "Boom Bap",
            "continue_at": 60,
            "negative_tags": "no EDM",
            "vocal_gender": "m",
            "styleWeight": 0.77,
            "weirdnessConstraint": 0.33,
            "audioWeight": 0.44,
            "callBackUrl": "https://example.test/callback",
        },
    )

    assert client.extend_payload["audioId"] == "audio-source-1"
    assert client.extend_payload["continueAt"] == 60
    assert client.extend_payload["defaultParamFlag"] is True
    assert client.extend_payload["negativeTags"] == "no EDM"
    assert client.extend_payload["vocalGender"] == "m"
    assert client.extend_payload["callBackUrl"] == "https://example.test/callback"
    assert "audio_id" not in client.extend_payload
    assert "continue_at" not in client.extend_payload
    assert "negative_tags" not in client.extend_payload

    task = isolated_db_session.query(SunoTask).one()
    assert task.request_payload["audioId"] == "audio-source-1"
    assert task.request_payload["continueAt"] == 60
    assert task.request_payload["defaultParamFlag"] is True
    assert task.request_payload["negativeTags"] == "no EDM"
    assert task.request_payload["vocalGender"] == "m"
    assert task.request_payload["callBackUrl"] == "https://example.test/callback"
    assert "audio_id" not in task.request_payload
    assert "continue_at" not in task.request_payload


async def test_add_vocals_stores_official_suno_payload_names(isolated_db_session):
    client = FakeFollowupSunoClient()
    service = MusicService(isolated_db_session, client=client)

    await service.call_task_endpoint(
        "add_vocals",
        {
            "uploadUrl": "https://cdn.example.test/instrumental.mp3",
            "prompt": "A calm and relaxing piano track with soothing vocals",
            "title": "Relaxing Piano with Vocals",
            "negativeTags": "Heavy Metal, Aggressive Vocals",
            "style": "Jazz",
            "vocalGender": "m",
            "styleWeight": 0.61,
            "weirdnessConstraint": 0.72,
            "audioWeight": 0.65,
            "model": "V4_5PLUS",
            "callBackUrl": "https://example.test/callback",
        },
    )

    assert client.add_vocals_payload["uploadUrl"] == "https://cdn.example.test/instrumental.mp3"
    assert client.add_vocals_payload["negativeTags"] == "Heavy Metal, Aggressive Vocals"
    assert client.add_vocals_payload["vocalGender"] == "m"
    assert client.add_vocals_payload["styleWeight"] == 0.61
    assert client.add_vocals_payload["weirdnessConstraint"] == 0.72
    assert client.add_vocals_payload["audioWeight"] == 0.65
    assert "audio_url" not in client.add_vocals_payload
    assert "negative_tags" not in client.add_vocals_payload

    task = isolated_db_session.query(SunoTask).one()
    assert task.request_payload["uploadUrl"] == "https://cdn.example.test/instrumental.mp3"
    assert task.request_payload["negativeTags"] == "Heavy Metal, Aggressive Vocals"
    assert task.request_payload["vocalGender"] == "m"
    assert task.request_payload["callBackUrl"] == "https://example.test/callback"
    assert "audio_url" not in task.request_payload
    assert "negative_tags" not in task.request_payload


async def test_manual_sunoapi_task_import_preserves_advanced_options_in_db(isolated_db_session):
    service = MusicService(isolated_db_session, client=FakeImportSunoClient())

    task = await service.import_external_task(
        {
            "task_id": "task-import-options",
            "task_type": "generate_music",
            "cache_audio": False,
        }
    )

    assert task.request_payload["negativeTags"] == "no EDM"
    assert task.request_payload["vocalGender"] == "m"
    assert task.request_payload["styleWeight"] == 0.77
    assert task.request_payload["weirdnessConstraint"] == 0.33
    assert task.request_payload["audioWeight"] == 0.44
    assert task.request_payload["customMode"] is True
    assert task.request_payload["instrumental"] is False

    asset = isolated_db_session.query(AudioAsset).one()
    request_payload = asset.metadata_json["request_payload"]
    assert request_payload["negativeTags"] == "no EDM"
    assert request_payload["vocalGender"] == "m"
    assert request_payload["styleWeight"] == 0.77
    assert request_payload["weirdnessConstraint"] == 0.33
    assert request_payload["audioWeight"] == 0.44
    assert request_payload["customMode"] is True
    assert request_payload["instrumental"] is False

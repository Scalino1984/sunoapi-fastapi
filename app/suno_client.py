"""SunoAPI HTTP client.

Der Generate- und Extend-Pfad verwendet die offiziellen SunoAPI-Namen
negativeTags/vocalGender/audioId/continueAt/defaultParamFlag. Die
Normalisierung akzeptiert zusaetzlich alte interne snake_case-Namen, darf die
offiziellen Namen aber nicht veraendern oder entfernen. Die Routen speichern die
offiziellen Namen bereits in suno_tasks.request_payload.
"""

from __future__ import annotations

from typing import Any
import httpx

from app.config import get_settings


class SunoAPIError(RuntimeError):
    pass


class SunoAPIClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
        settings = get_settings()
        self.api_key = api_key if api_key is not None else settings.suno_api_key
        self.base_url = (base_url or settings.suno_base_url).rstrip("/")
        self.file_upload_base_url = settings.suno_file_upload_base_url.rstrip("/")
        self.timeout = settings.request_timeout_seconds

        if not self.api_key:
            raise SunoAPIError("SUNO_API_KEY fehlt. Bitte .env konfigurieren.")

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }

    @staticmethod
    def _normalize_payload(payload: dict[str, Any] | None) -> dict[str, Any] | None:
        if payload is None:
            return None

        key_map = {
            "callback_url": "callBackUrl",
            "call_back_url": "callBackUrl",
            "audio_url": "uploadUrl",
            "upload_url": "uploadUrl",
            "upload_url_list": "uploadUrlList",
            "audio_id": "audioId",
            "task_id": "taskId",
            "default_param_flag": "defaultParamFlag",
            "continue_at": "continueAt",
            "continue_at_seconds": "continueAt",
            "infill_start_s": "infillStartS",
            "infill_end_s": "infillEndS",
            "full_lyrics": "fullLyrics",
            "sound_loop": "soundLoop",
            "sound_tempo": "soundTempo",
            "sound_key": "soundKey",
            "grab_lyrics": "grabLyrics",
            "domain_name": "domainName",
            "style_weight": "styleWeight",
            "weirdness_constraint": "weirdnessConstraint",
            "audio_weight": "audioWeight",
            "style_prompt": "style",
            "style_parameters": "content",
            "voice_description": "description",
            "verification_phrase": "verificationPhrase",
            "voice_url": "voiceUrl",
            "voice_name": "voiceName",
            "verify_url": "verifyUrl",
            "vocal_start_s": "vocalStartS",
            "vocal_end_s": "vocalEndS",
            "singer_skill_level": "singerSkillLevel",
            "persona_name": "personaName",
            "persona_id": "personaId",
            "persona_model": "personaModel",
            "negative_tags": "negativeTags",
            "vocal_gender": "vocalGender",
            "visual_style": "visualStyle",
            "file": "base64Data",
            "original_name": "fileName",
            "url": "fileUrl",
        }

        normalized: dict[str, Any] = {}
        for key, value in payload.items():
            if value is None:
                continue

            if key in {"voice_id", "voiceId"}:
                voice_id = str(value).strip()
                if voice_id and not payload.get("persona_id") and not payload.get("personaId"):
                    normalized["personaId"] = voice_id
                if voice_id and not payload.get("persona_model") and not payload.get("personaModel"):
                    normalized["personaModel"] = "voice_persona"
                continue

            normalized[key_map.get(key, key)] = value
        return normalized

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        request_base_url = (base_url or self.base_url).rstrip("/")
        url = f"{request_base_url}{path}"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=self.headers,
                    json=self._normalize_payload(json_data),
                    params=self._normalize_payload(params),
                    files=files,
                    data=data,
                )
        except httpx.TimeoutException as exc:
            raise SunoAPIError(f"SunoAPI-Timeout bei {method.upper()} {path}.") from exc
        except httpx.HTTPError as exc:
            raise SunoAPIError(f"SunoAPI-Verbindungsfehler bei {method.upper()} {path}: {exc.__class__.__name__}") from exc

        try:
            payload = response.json()
        except ValueError:
            payload = {"raw": response.text}

        if response.status_code >= 400:
            raise SunoAPIError(
                f"SunoAPI HTTP-Fehler {response.status_code} bei {method.upper()} {path}: {payload}"
            )

        if isinstance(payload, dict):
            api_code = payload.get("code")
            if api_code is not None and api_code != 200:
                api_msg = payload.get("msg") or payload.get("message") or "Unbekannter SunoAPI-Fehler"
                raise SunoAPIError(
                    f"SunoAPI Fehler {api_code} bei {method.upper()} {path}: {api_msg}"
                )
            return payload

        return {"data": payload}

    async def generate_music(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/api/v1/generate", json_data=payload)

    async def extend_music(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/api/v1/generate/extend", json_data=payload)

    async def upload_and_cover(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/api/v1/generate/upload-cover", json_data=payload)

    async def upload_and_extend(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/api/v1/generate/upload-extend", json_data=payload)

    async def add_instrumental(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/api/v1/generate/add-instrumental", json_data=payload)

    async def add_vocals(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/api/v1/generate/add-vocals", json_data=payload)

    async def boost_music_style(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/api/v1/style/generate", json_data=payload)

    async def generate_mashup(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/api/v1/generate/mashup", json_data=payload)

    async def replace_section(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/api/v1/generate/replace-section", json_data=payload)

    async def generate_persona(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/api/v1/generate/generate-persona", json_data=payload)

    async def create_music_cover(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/api/v1/suno/cover/generate", json_data=payload)

    async def generate_lyrics(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/api/v1/lyrics", json_data=payload)

    async def get_lyrics_details(self, task_id: str) -> dict[str, Any]:
        return await self._request("GET", "/api/v1/lyrics/record-info", params={"taskId": task_id})

    async def get_timestamped_lyrics(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/api/v1/generate/get-timestamped-lyrics", json_data=payload)

    async def generate_sounds(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/api/v1/generate/sounds", json_data=payload)

    async def separate(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/api/v1/vocal-removal/generate", json_data=payload)

    async def convert_to_wav(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/api/v1/wav/generate", json_data=payload)

    async def generate_midi(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/api/v1/midi/generate", json_data=payload)

    async def create_video(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/api/v1/mp4/generate", json_data=payload)

    async def generate_voice_verification_phrase(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/api/v1/voice/validate", json_data=payload)

    async def get_voice_verification_phrase(self, task_id: str) -> dict[str, Any]:
        return await self._request("GET", "/api/v1/voice/validate-info", params={"taskId": task_id})

    async def create_custom_voice(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/api/v1/voice/generate", json_data=payload)

    async def get_custom_voice_record(self, task_id: str) -> dict[str, Any]:
        return await self._request("GET", "/api/v1/voice/record-info", params={"taskId": task_id})

    async def regenerate_voice_verification_phrase(self, payload: dict[str, Any]) -> dict[str, Any]:
        # SunoAPI documents this field as calBackUrl for this endpoint. The normalizer also accepts callback_url.
        return await self._request("POST", "/api/v1/voice/regenerate", json_data=payload)

    async def check_voice_availability(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/api/v1/voice/check-voice", json_data=payload)

    async def get_remaining_credits(self) -> dict[str, Any]:
        return await self._request("GET", "/api/v1/generate/credit")

    async def get_details(self, task_id: str) -> dict[str, Any]:
        return await self._request("GET", "/api/v1/generate/record-info", params={"taskId": task_id})

    async def get_cover_details(self, task_id: str) -> dict[str, Any]:
        return await self._request("GET", "/api/v1/suno/cover/record-info", params={"taskId": task_id})

    async def get_wav_details(self, task_id: str) -> dict[str, Any]:
        return await self._request("GET", "/api/v1/wav/record-info", params={"taskId": task_id})

    async def get_midi_details(self, task_id: str) -> dict[str, Any]:
        return await self._request("GET", "/api/v1/midi/record-info", params={"taskId": task_id})

    async def get_video_details(self, task_id: str) -> dict[str, Any]:
        return await self._request("GET", "/api/v1/mp4/record-info", params={"taskId": task_id})

    async def get_vocal_separation_details(self, task_id: str) -> dict[str, Any]:
        return await self._request("GET", "/api/v1/vocal-removal/record-info", params={"taskId": task_id})

    async def upload_base64(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/file-base64-upload",
            json_data=payload,
            base_url=self.file_upload_base_url,
        )

    async def upload_url(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/file-url-upload",
            json_data=payload,
            base_url=self.file_upload_base_url,
        )

    async def upload_stream(self, filename: str, content: bytes, content_type: str | None = None) -> dict[str, Any]:
        files = {"file": (filename, content, content_type or "application/octet-stream")}
        data = {"fileName": filename, "uploadPath": "audio/user-uploads"}
        return await self._request(
            "POST",
            "/api/file-stream-upload",
            files=files,
            data=data,
            base_url=self.file_upload_base_url,
        )

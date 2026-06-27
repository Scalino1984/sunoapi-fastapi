from __future__ import annotations

from typing import Any


SUNOAPI_FOLLOWUP_CAPABILITY_KEYS = {
    "extend": "sunoapi_extend",
    "extend_music": "sunoapi_extend",
    "cover_song": "sunoapi_cover_song",
    "upload_and_cover": "sunoapi_cover_song",
    "add_vocals": "sunoapi_add_vocals",
    "add_instrumental": "sunoapi_add_instrumental",
    "create_cover": "sunoapi_create_cover",
    "cover_image": "sunoapi_create_cover",
    "convert_to_wav": "sunoapi_wav",
    "generate_midi": "sunoapi_midi",
    "create_video": "sunoapi_video",
    "generate_persona": "sunoapi_persona",
    "persona": "sunoapi_persona",
}


def local_only_capabilities() -> dict[str, bool]:
    return {
        "local_playback": True,
        "local_download": True,
        "srt_generate": True,
        "lyrics_edit": True,
        "waveform": True,
        "local_bundle_download": True,
        "sunoapi_extend": False,
        "sunoapi_cover_song": False,
        "sunoapi_add_vocals": False,
        "sunoapi_add_instrumental": False,
        "sunoapi_create_cover": False,
        "sunoapi_wav": False,
        "sunoapi_midi": False,
        "sunoapi_video": False,
        "sunoapi_persona": False,
    }


def metadata_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def merge_capabilities(metadata: dict[str, Any] | None, capabilities: dict[str, bool] | None = None) -> dict[str, Any]:
    merged = dict(metadata or {})
    existing = merged.get("capabilities") if isinstance(merged.get("capabilities"), dict) else {}
    merged["capabilities"] = {**existing, **(capabilities or local_only_capabilities())}
    return merged


def mark_suno_public_clip(metadata: dict[str, Any] | None, *, suno_clip_id: str | None = None) -> dict[str, Any]:
    merged = merge_capabilities(metadata, local_only_capabilities())
    merged["import_source"] = "suno_public_clip"
    merged["is_suno_clip_import"] = True
    if suno_clip_id:
        merged["suno_clip_id"] = suno_clip_id
    return merged


def mark_opencli_generation(metadata: dict[str, Any] | None) -> dict[str, Any]:
    merged = merge_capabilities(metadata, local_only_capabilities())
    merged["generation_source"] = "opencli"
    merged["is_opencli_generation"] = True
    return merged


def is_local_only_asset_metadata(metadata: dict[str, Any] | None) -> bool:
    meta = metadata_dict(metadata)
    if meta.get("is_suno_clip_import") or meta.get("import_source") == "suno_public_clip":
        return True
    if meta.get("is_opencli_generation") or meta.get("generation_source") == "opencli" or meta.get("provider") == "opencli":
        return True
    caps = meta.get("capabilities") if isinstance(meta.get("capabilities"), dict) else {}
    sunoapi_keys = [key for key in caps if str(key).startswith("sunoapi_")]
    return bool(sunoapi_keys) and all(caps.get(key) is False for key in sunoapi_keys)


def can_use_sunoapi_capability(metadata: dict[str, Any] | None, capability_key: str) -> bool:
    meta = metadata_dict(metadata)
    caps = meta.get("capabilities") if isinstance(meta.get("capabilities"), dict) else {}
    if caps.get(capability_key) is False:
        return False
    if is_local_only_asset_metadata(meta) and capability_key.startswith("sunoapi_"):
        return False
    return True


def blocked_followup_reason(metadata: dict[str, Any] | None, action: str) -> str | None:
    capability = SUNOAPI_FOLLOWUP_CAPABILITY_KEYS.get(action, action if action.startswith("sunoapi_") else "")
    if capability and not can_use_sunoapi_capability(metadata, capability):
        meta = metadata_dict(metadata)
        if meta.get("is_suno_clip_import") or meta.get("import_source") == "suno_public_clip":
            return "Diese Aktion benötigt eine SunoAPI.org-kompatible Task-/Audio-ID. Öffentliche Suno-Clip-Imports unterstützen nur lokale Funktionen."
        if meta.get("is_opencli_generation") or meta.get("generation_source") == "opencli" or meta.get("provider") == "opencli":
            return "Diese Aktion benötigt eine SunoAPI.org-kompatible Task-/Audio-ID. OpenCLI-Assets unterstützen nur lokale Funktionen."
        return "Diese Aktion ist für dieses AudioAsset per Capability-Flag deaktiviert."
    return None

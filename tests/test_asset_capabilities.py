from app.services.asset_capabilities import (
    blocked_followup_reason,
    can_use_sunoapi_capability,
    is_local_only_asset_metadata,
    local_only_capabilities,
    mark_opencli_generation,
    mark_suno_public_clip,
    merge_capabilities,
)


def test_local_only_capabilities_block_costly_sunoapi_followups():
    caps = local_only_capabilities()

    assert caps["local_playback"] is True
    assert caps["srt_generate"] is True
    assert caps["sunoapi_extend"] is False
    assert caps["sunoapi_create_cover"] is False


def test_suno_public_clip_metadata_blocks_external_followups_but_keeps_local_actions():
    metadata = mark_suno_public_clip({"title": "Clip"}, suno_clip_id="abc123")

    assert is_local_only_asset_metadata(metadata) is True
    assert can_use_sunoapi_capability(metadata, "sunoapi_extend") is False
    assert "Öffentliche Suno-Clip-Imports" in blocked_followup_reason(metadata, "extend")
    assert blocked_followup_reason(metadata, "unknown_local_action") is None


def test_opencli_metadata_gets_specific_block_reason():
    metadata = mark_opencli_generation({"provider": "opencli"})

    assert is_local_only_asset_metadata(metadata) is True
    assert "OpenCLI-Assets" in blocked_followup_reason(metadata, "cover_song")


def test_explicit_capability_flag_blocks_only_requested_action():
    metadata = merge_capabilities({}, {"sunoapi_extend": False, "sunoapi_wav": True})

    assert blocked_followup_reason(metadata, "extend_music") == "Diese Aktion ist für dieses AudioAsset per Capability-Flag deaktiviert."
    assert blocked_followup_reason(metadata, "convert_to_wav") is None

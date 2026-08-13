from app.models import AudioAsset, Song
from app.services.srt_transcript_service import _persist_transcription_only_lyrics


def _segments() -> list[dict]:
    return [
        {"start": 0.0, "end": 3.0, "text": "Mi burst inna dis place with a song full a pure love,"},
        {"start": 3.0, "end": 6.0, "text": "every single word come from mi heart above."},
    ]


def test_asr_only_srt_persists_recovered_lyrics_in_song_and_asset_fields(isolated_db_session) -> None:
    song = Song(title="Import ohne Text", prompt="dark dancehall style")
    isolated_db_session.add(song)
    isolated_db_session.flush()
    asset = AudioAsset(
        song_id=song.id,
        source_url="https://example.test/import.mp3",
        status="cached",
        metadata_json={
            "source": "manual_import",
            "candidate": {"title": "Import ohne Text", "prompt": "dark dancehall style"},
            "request_payload": {"prompt": "dark dancehall style"},
        },
    )
    isolated_db_session.add(asset)
    isolated_db_session.flush()

    result = _persist_transcription_only_lyrics(
        isolated_db_session,
        asset,
        _segments(),
        backend="groq",
        language="en",
    )
    isolated_db_session.flush()
    isolated_db_session.refresh(song)
    isolated_db_session.refresh(asset)

    lyrics = "Mi burst inna dis place with a song full a pure love,\nevery single word come from mi heart above."
    metadata = asset.metadata_json or {}
    assert result == {"saved": True, "chars": len(lyrics), "segments": 2}
    assert song.lyrics == lyrics
    assert song.prompt == lyrics
    assert asset.lyrics == lyrics
    assert metadata["candidate"]["lyrics"] == lyrics
    assert metadata["candidate"]["text"] == lyrics
    assert metadata["candidate"]["prompt"] == lyrics
    assert metadata["request_payload"]["lyrics"] == lyrics
    assert metadata["request_payload"]["prompt"] == lyrics
    assert metadata["pre_asr_transcription_prompts"]["song"] == "dark dancehall style"
    assert metadata["lyrics_transcription"]["source"] == "srt_asr_transcription"


def test_asr_only_srt_never_replaces_existing_manual_lyrics(isolated_db_session) -> None:
    song = Song(title="Manuell gepflegt", prompt="Original prompt", lyrics="Mein eigener, manueller Songtext.")
    isolated_db_session.add(song)
    isolated_db_session.flush()
    asset = AudioAsset(
        song_id=song.id,
        source_url="https://example.test/manual.mp3",
        status="cached",
        metadata_json={
            "candidate": {"lyrics": "Mein eigener, manueller Songtext."},
            "lyrics_manual_override": {"enabled": True},
        },
    )
    isolated_db_session.add(asset)
    isolated_db_session.flush()

    result = _persist_transcription_only_lyrics(
        isolated_db_session,
        asset,
        _segments(),
        backend="groq",
        language="de",
    )
    isolated_db_session.flush()
    isolated_db_session.refresh(song)
    isolated_db_session.refresh(asset)

    assert result["saved"] is False
    assert result["reason"] == "lyrics_already_present"
    assert song.lyrics == "Mein eigener, manueller Songtext."
    assert asset.metadata_json["candidate"]["lyrics"] == "Mein eigener, manueller Songtext."


def test_asr_only_srt_creates_a_song_when_an_imported_asset_has_no_song(isolated_db_session) -> None:
    asset = AudioAsset(
        source_url="https://example.test/orphan-import.mp3",
        status="cached",
        title="Import ohne Song",
        metadata_json={"candidate": {"model": "manual_import"}},
    )
    isolated_db_session.add(asset)
    isolated_db_session.flush()

    result = _persist_transcription_only_lyrics(
        isolated_db_session,
        asset,
        _segments(),
        backend="whisperx",
        language="en",
    )
    isolated_db_session.flush()
    isolated_db_session.refresh(asset)
    song = isolated_db_session.query(Song).filter(Song.id == asset.song_id).first()

    assert result["saved"] is True
    assert song is not None
    assert song.lyrics == asset.lyrics

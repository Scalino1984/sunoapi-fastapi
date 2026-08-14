from app.models import AudioAsset, LyricDraft, MusicStyle, Playlist
from app.routers.library import search_library_content


def test_global_search_matches_normalized_tags_and_paginates(isolated_db_session):
    db = isolated_db_session
    db.add_all([
        AudioAsset(
            title="Nachtfahrt",
            source_url="https://cdn.example.test/nachtfahrt.mp3",
            status="remote",
            metadata_json={"ai_tags": {"tags": ["dark-orchestral"], "genres": ["hip-hop"]}},
        ),
        AudioAsset(
            title="Anderer Song",
            source_url="https://cdn.example.test/anderer.mp3",
            status="remote",
        ),
        LyricDraft(title="Nachttext", content="Ein dark Hip Hop Refrain", tags="demo"),
        MusicStyle(name="Nacht-Style", style_text="dark orchestral hip-hop", tags="cinematic"),
        Playlist(name="Nacht-Playlist", description="Dark hip hop Auswahl"),
    ])
    db.commit()

    result = search_library_content(q="dark hip hop", page=1, page_size=1, db=db)

    assert result["assets"]["total"] == 1
    assert result["assets"]["items"][0]["title"] == "Nachtfahrt"
    assert result["lyrics"]["total"] == 1
    assert result["styles"]["total"] == 1
    assert result["playlists"]["total"] == 1
    assert result["assets"]["page_size"] == 1


def test_global_search_matches_title_only_stored_in_original_candidate(isolated_db_session):
    db = isolated_db_session
    db.add(AudioAsset(
        # Materialisierte Altbestände können keinen direkten asset.title haben;
        # die sichtbare Library-Bezeichnung kommt dann aus candidate.title.
        title=None,
        source_url="https://cdn.example.test/di-clock-a-run.mp3",
        status="remote",
        metadata_json={"candidate": {"title": "Di Clock A Run"}},
    ))
    db.commit()

    result = search_library_content(q="Di Clock A Run", page=1, page_size=25, db=db)

    assert result["assets"]["total"] == 1
    assert result["assets"]["items"][0]["title"] == "Di Clock A Run"

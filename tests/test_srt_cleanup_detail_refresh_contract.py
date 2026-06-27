from pathlib import Path

from app.services.srt_transcript_service import deterministic_prepare_lyrics_for_srt


def test_srt_cleanup_normalizes_obvious_repeated_consonant_artifacts():
    raw = """Ein teil der Nachttt
...
Ein teil der Nachttt
...
Einnn teilll derrr Nachttt
(ein teil der nacht)"""

    cleaned, info = deterministic_prepare_lyrics_for_srt(raw)

    assert cleaned == """Ein teil der Nacht
...
Ein teil der Nacht
...
Ein teil der Nacht
ein teil der nacht"""
    assert info["normalized_stretch_count"] >= 6


def test_library_page_listens_for_external_srt_updates():
    library_page = Path("frontend-react/src/pages/LibraryPage.jsx").read_text(encoding="utf-8")

    assert "window.addEventListener('srt:updated', handleExternalSrtUpdated)" in library_page
    assert "window.removeEventListener('srt:updated', handleExternalSrtUpdated)" in library_page
    assert "Neu erzeugte SRTs ohne" not in library_page or "Browser-Refresh" in library_page

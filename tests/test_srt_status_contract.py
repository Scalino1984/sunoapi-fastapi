# CORE CONTRACT
# Zweck: Regressionstest fuer detaillierte SRT-Task-Phasen und Timeout-Settings.
# Kritische Logik: generate_srt Tasks muessen sichtbare Phasen und Timeouts besitzen.
# Nicht aendern ohne Pruefung: srt_transcript_service.py, config.py.
# Siehe: docs/ARCHITECTURE_CONTRACT.md

from app.config import get_settings
from app.services import srt_transcript_service as svc


def test_srt_status_phases_cover_full_pipeline():
    required = [
        "initializing",
        "lyrics_cleanup_started",
        "lyrics_cleanup_completed",
        "audio_ready",
        "transcription_started",
        "transcription_completed",
        "alignment_completed",
        "files_written",
        "structure_segments_stored",
        "completed",
        "failed",
    ]
    for phase in required:
        assert phase in svc.SRT_STATUS_PHASES
    assert svc.SRT_STATUS_TOTAL_STEPS >= len(required)


def test_srt_provider_timeout_settings_are_available():
    settings = get_settings()
    assert settings.transcript_groq_request_timeout_seconds > 0
    assert settings.transcript_groq_max_retries >= 0
    assert settings.srt_transcription_timeout_seconds > 0
    assert svc._groq_request_timeout_seconds() <= settings.transcript_request_timeout_seconds

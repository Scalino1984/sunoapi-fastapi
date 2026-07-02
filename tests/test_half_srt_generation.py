from app.services.srt_transcript_service import segments_to_half_srt


def test_half_srt_rebalances_single_word_tail_lines() -> None:
    srt_text = segments_to_half_srt(
        [
            {
                "index": 1,
                "start": 5.0,
                "end": 8.0,
                "text": "Do you remember standing on a broken field",
            }
        ],
        max_chars=22,
        min_dur=0.6,
    )

    assert "broken field" in srt_text
    assert "\nfield\n" not in srt_text

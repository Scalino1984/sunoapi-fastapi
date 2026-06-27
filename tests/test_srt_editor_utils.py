from app.services.srt_parser import renumber_segments
from app.services.srt_validation import validate_srt_segments


def extend_segment_and_ripple_following(segments, segment_index, delta):
    rows = renumber_segments(segments)
    result = []
    for idx, row in enumerate(rows):
        if idx == segment_index:
            row = {**row, "end": round(row["end"] + delta, 3)}
        elif idx > segment_index:
            row = {**row, "start": round(row["start"] + delta, 3), "end": round(row["end"] + delta, 3)}
        result.append(row)
    return renumber_segments(result, sort=False)


def delete_segment_keep_timing(segments, segment_index):
    return renumber_segments([row for idx, row in enumerate(renumber_segments(segments)) if idx != segment_index])


def delete_segment_close_gap(segments, segment_index):
    rows = renumber_segments(segments)
    removed = rows[segment_index]
    duration = removed["end"] - removed["start"]
    kept = []
    for idx, row in enumerate(rows):
        if idx == segment_index:
            continue
        if idx > segment_index:
            row = {**row, "start": round(row["start"] - duration, 3), "end": round(row["end"] - duration, 3)}
        kept.append(row)
    return renumber_segments(kept, sort=False)


def shift_segments_from_index(segments, start_index, delta, include_current=True):
    rows = renumber_segments(segments)
    start_at = start_index if include_current else start_index + 1
    result = []
    for idx, row in enumerate(rows):
        if idx >= start_at:
            row = {**row, "start": round(row["start"] + delta, 3), "end": round(row["end"] + delta, 3)}
        result.append(row)
    return renumber_segments(result, sort=False)


def simplified(rows):
    return [(row["index"], row["start"], row["end"]) for row in rows]


def test_segment_extend_with_ripple():
    rows = [{"start": 0, "end": 5, "text": "a"}, {"start": 5, "end": 10, "text": "b"}, {"start": 10, "end": 15, "text": "c"}]
    assert simplified(extend_segment_and_ripple_following(rows, 1, 5.0)) == [(1, 0.0, 5.0), (2, 5.0, 15.0), (3, 15.0, 20.0)]


def test_delete_keep_timing():
    rows = [{"start": 0, "end": 5, "text": "a"}, {"start": 5, "end": 10, "text": "b"}, {"start": 12, "end": 17, "text": "c"}]
    assert simplified(delete_segment_keep_timing(rows, 1)) == [(1, 0.0, 5.0), (2, 12.0, 17.0)]


def test_delete_close_gap():
    rows = [{"start": 0, "end": 5, "text": "a"}, {"start": 5, "end": 10, "text": "b"}, {"start": 10, "end": 15, "text": "c"}]
    assert simplified(delete_segment_close_gap(rows, 1)) == [(1, 0.0, 5.0), (2, 5.0, 10.0)]


def test_shift_from_index_include_current():
    rows = [{"start": 0, "end": 5, "text": "a"}, {"start": 5, "end": 10, "text": "b"}, {"start": 10, "end": 15, "text": "c"}]
    assert simplified(shift_segments_from_index(rows, 1, 3.0, True)) == [(1, 0.0, 5.0), (2, 8.0, 13.0), (3, 13.0, 18.0)]


def test_shift_from_index_following_only():
    rows = [{"start": 0, "end": 5, "text": "a"}, {"start": 5, "end": 10, "text": "b"}, {"start": 10, "end": 15, "text": "c"}]
    assert simplified(shift_segments_from_index(rows, 1, 3.0, False)) == [(1, 0.0, 5.0), (2, 5.0, 10.0), (3, 13.0, 18.0)]


def test_overlap_detection():
    result = validate_srt_segments([{"start": 0, "end": 5, "text": "a"}, {"start": 4.5, "end": 8, "text": "b"}])
    assert any(issue["type"] == "overlap" and "0.500" in issue["message"] for issue in result["issues"])


def test_gap_detection():
    result = validate_srt_segments([{"start": 0, "end": 5, "text": "a"}, {"start": 10, "end": 15, "text": "b"}])
    assert any(issue["type"] == "gap" and "5.000" in issue["message"] for issue in result["issues"])

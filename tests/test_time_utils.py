from datetime import UTC, datetime

from app.utils.time_utils import ensure_utc, ensure_utc_naive, utc_now, utc_now_iso, utc_now_naive


def test_utc_now_is_timezone_aware_utc():
    value = utc_now()

    assert value.tzinfo is not None
    assert value.utcoffset().total_seconds() == 0


def test_utc_now_naive_preserves_legacy_sqlite_contract():
    value = utc_now_naive()

    assert value.tzinfo is None


def test_ensure_utc_treats_legacy_naive_values_as_utc():
    value = ensure_utc(datetime(2026, 6, 24, 7, 46, 1))

    assert value == datetime(2026, 6, 24, 7, 46, 1, tzinfo=UTC)


def test_ensure_utc_parses_explicit_z_suffix():
    value = ensure_utc("2026-06-24T07:46:01Z")

    assert value == datetime(2026, 6, 24, 7, 46, 1, tzinfo=UTC)


def test_ensure_utc_naive_returns_db_compatible_utc_value():
    value = ensure_utc_naive("2026-06-24T07:46:01+00:00")

    assert value == datetime(2026, 6, 24, 7, 46, 1)
    assert value.tzinfo is None


def test_utc_now_iso_contains_explicit_utc_offset():
    value = utc_now_iso(timespec="seconds")

    assert value.endswith("+00:00")

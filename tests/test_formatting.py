from app.formatting import format_utc


def test_format_utc():
    assert format_utc("2026-10-28T14:05:09+00:00") == "2026-10-28 14:05 UTC"


def test_format_utc_handles_missing_and_garbage():
    assert format_utc(None) == "—"
    assert format_utc("") == "—"
    assert format_utc("not a date") == "not a date"

from video_extender.utils.duration import format_duration, parse_duration


class TestParseDuration:
    def test_bare_number_is_seconds(self) -> None:
        assert parse_duration("30") == 30.0
        assert parse_duration(45) == 45.0
        assert parse_duration(2.5) == 2.5

    def test_seconds_suffix(self) -> None:
        assert parse_duration("30s") == 30.0
        assert parse_duration("90s") == 90.0

    def test_minutes_suffix(self) -> None:
        assert parse_duration("30m") == 30 * 60
        assert parse_duration("1m") == 60.0

    def test_hours_suffix(self) -> None:
        assert parse_duration("1h") == 3600.0
        assert parse_duration("2h") == 7200.0

    def test_compound(self) -> None:
        assert parse_duration("1h30m") == 5400.0
        assert parse_duration("1h30m45s") == 5445.0
        assert parse_duration("90m30s") == 5430.0

    def test_invalid_raises(self) -> None:
        import pytest
        with pytest.raises(ValueError):
            parse_duration("abc")
        with pytest.raises(ValueError):
            parse_duration("")


class TestFormatDuration:
    def test_seconds_only(self) -> None:
        assert format_duration(0) == "0s"
        assert format_duration(45) == "45s"

    def test_minutes(self) -> None:
        assert format_duration(60) == "1m"
        assert format_duration(90) == "1m30s"

    def test_hours(self) -> None:
        assert format_duration(3600) == "1h"
        assert format_duration(3661) == "1h1m1s"

    def test_roundtrip(self) -> None:
        for s in [0, 1, 60, 90, 3600, 5445, 86400]:
            f = format_duration(s)
            # format_duration normalizes 0 to "0s"; parse it back
            if s > 0:
                assert parse_duration(f) == s, f"{s} → {f}"

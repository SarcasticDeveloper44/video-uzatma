"""Notify is best-effort; we test that it doesn't raise and respects platform."""
from __future__ import annotations

from unittest.mock import patch

from video_extender.utils.notify import notify


class TestNotify:
    def test_doesnt_raise_on_any_platform(self) -> None:
        # Even if no notification daemon present, must not raise.
        result = notify("test title", "test body")
        assert isinstance(result, bool)

    def test_unknown_platform_returns_false(self) -> None:
        with patch("video_extender.utils.notify.sys") as mock_sys:
            mock_sys.platform = "freebsd"
            assert notify("t", "b") is False

    def test_linux_uses_notify_send(self) -> None:
        with patch("video_extender.utils.notify.shutil.which", return_value=None), \
             patch("video_extender.utils.notify.sys") as mock_sys:
            mock_sys.platform = "linux"
            # No notify-send → returns False (graceful)
            assert notify("t", "b") is False

    def test_no_quote_injection(self) -> None:
        """Pathological strings shouldn't break the call (best-effort)."""
        result = notify('title "with quotes"', "body with 'apostrophes'")
        assert isinstance(result, bool)

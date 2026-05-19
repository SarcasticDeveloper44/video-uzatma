"""Notify behaviour — verified by mocking subprocess so NO real desktop
notifications are dispatched during the test run.

The conftest `_stub_desktop_notifications` autouse fixture replaces notify()
with a no-op for every other test; here we explicitly un-stub it for the
test module under test, then mock the underlying OS-dispatch subprocesses.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _restore_real_notify(monkeypatch):
    """Reload the real notify implementation for this module's tests, then
    mock the subprocess calls inside it so nothing reaches the desktop."""
    import importlib

    import video_extender.utils.notify as notify_module
    importlib.reload(notify_module)
    monkeypatch.setattr(
        "video_extender.utils.notify.subprocess.run",
        lambda *a, **k: None,
    )
    yield notify_module
    # Reload again to restore the conftest-injected stub for downstream tests.
    importlib.reload(notify_module)


class TestNotify:
    def test_doesnt_raise_on_any_platform(self, _restore_real_notify) -> None:
        result = _restore_real_notify.notify("test title", "test body")
        assert isinstance(result, bool)

    def test_unknown_platform_returns_false(self, _restore_real_notify) -> None:
        with patch("video_extender.utils.notify.sys") as mock_sys:
            mock_sys.platform = "freebsd"
            assert _restore_real_notify.notify("t", "b") is False

    def test_linux_no_notify_send_returns_false(self, _restore_real_notify) -> None:
        with patch("video_extender.utils.notify.shutil.which", return_value=None), \
             patch("video_extender.utils.notify.sys") as mock_sys:
            mock_sys.platform = "linux"
            assert _restore_real_notify.notify("t", "b") is False

    def test_no_quote_injection(self, _restore_real_notify) -> None:
        """Pathological strings shouldn't break the call (best-effort)."""
        result = _restore_real_notify.notify(
            'title "with quotes"', "body with 'apostrophes'",
        )
        assert isinstance(result, bool)

    def test_linux_invokes_notify_send_subprocess(self, _restore_real_notify) -> None:
        """When notify-send IS available, the subprocess.run is called with
        the expected argv (and our patched subprocess.run returns None →
        notify returns True via the success branch)."""
        calls = []

        def _capture(args, **kwargs):
            calls.append(list(args))
            return None

        with patch("video_extender.utils.notify.shutil.which",
                   return_value="/usr/bin/notify-send"), \
             patch("video_extender.utils.notify.sys") as mock_sys, \
             patch("video_extender.utils.notify.subprocess.run", _capture):
            mock_sys.platform = "linux"
            ok = _restore_real_notify.notify("Title", "Body", app_name="App")
            assert ok is True
            assert calls and calls[0][0] == "/usr/bin/notify-send"
            assert "Title" in calls[0]
            assert "Body" in calls[0]
            assert "App" in calls[0]

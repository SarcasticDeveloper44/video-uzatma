"""Cross-OS desktop notification: Linux notify-send, macOS osascript, Windows PowerShell toast."""
from __future__ import annotations

import shutil
import subprocess
import sys


def _escape_quotes(s: str) -> str:
    return s.replace('"', '`"').replace("'", "''")


def _notify_linux(title: str, body: str, app_name: str) -> bool:
    bin_ = shutil.which("notify-send")
    if not bin_:
        return False
    try:
        subprocess.run([bin_, "-a", app_name, title, body], timeout=5, check=False)
        return True
    except (subprocess.SubprocessError, OSError):
        return False


def _notify_macos(title: str, body: str, app_name: str) -> bool:
    try:
        # Escape double-quotes for osascript
        t = title.replace('"', '\\"')
        b = body.replace('"', '\\"')
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{b}" with title "{t}"'],
            timeout=5, check=False,
        )
        return True
    except (subprocess.SubprocessError, OSError, FileNotFoundError):
        return False


def _notify_windows(title: str, body: str, app_name: str) -> bool:
    """Windows native toast via PowerShell's BurntToast-free fallback.

    Uses the Windows.UI.Notifications WinRT API via PowerShell. Works on
    Windows 10+ without third-party modules.
    """
    ps = shutil.which("powershell") or shutil.which("pwsh")
    if not ps:
        return False
    script = (
        f"$ErrorActionPreference='SilentlyContinue';"
        f"[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime]>$null;"
        f"$template=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
        f"[Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
        f"$nodes=$template.GetElementsByTagName('text');"
        f"$nodes.Item(0).AppendChild($template.CreateTextNode('{_escape_quotes(title)}'))>$null;"
        f"$nodes.Item(1).AppendChild($template.CreateTextNode('{_escape_quotes(body)}'))>$null;"
        f"$toast=[Windows.UI.Notifications.ToastNotification]::new($template);"
        f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{_escape_quotes(app_name)}').Show($toast)"
    )
    try:
        subprocess.run(
            [ps, "-NoProfile", "-NonInteractive", "-Command", script],
            timeout=8, check=False,
        )
        return True
    except (subprocess.SubprocessError, OSError):
        return False


def notify(title: str, body: str, *, app_name: str = "Video Extender") -> bool:
    """Best-effort desktop notification. Returns True if dispatched."""
    if sys.platform == "linux":
        return _notify_linux(title, body, app_name)
    if sys.platform == "darwin":
        return _notify_macos(title, body, app_name)
    if sys.platform == "win32":
        return _notify_windows(title, body, app_name)
    return False

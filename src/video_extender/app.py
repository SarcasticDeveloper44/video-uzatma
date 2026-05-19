"""GUI entry point — `python -m video_extender` (no args)."""
from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication


def _apply_dark_palette_if_os_prefers(app: QApplication) -> None:
    """Detect OS color scheme; apply a dark Fusion palette when the user's
    system theme is Dark. No-op for Light/Unknown so Qt's default palette
    wins. Qt 6.5+ has QStyleHints.colorScheme().
    """
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QColor, QGuiApplication, QPalette
        from PySide6.QtWidgets import QApplication, QStyleFactory
        hints = QGuiApplication.styleHints()
        scheme = getattr(hints, "colorScheme", lambda: None)()
        if scheme != Qt.ColorScheme.Dark:
            return
        QApplication.setStyle(QStyleFactory.create("Fusion"))
        palette = QPalette()
        bg = QColor(35, 35, 38)
        bg2 = QColor(50, 50, 53)
        text = QColor(220, 220, 220)
        accent = QColor(64, 132, 220)
        disabled_text = QColor(127, 127, 127)
        palette.setColor(QPalette.ColorRole.Window, bg)
        palette.setColor(QPalette.ColorRole.WindowText, text)
        palette.setColor(QPalette.ColorRole.Base, bg2)
        palette.setColor(QPalette.ColorRole.AlternateBase, bg)
        palette.setColor(QPalette.ColorRole.Text, text)
        palette.setColor(QPalette.ColorRole.Button, bg2)
        palette.setColor(QPalette.ColorRole.ButtonText, text)
        palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 80, 80))
        palette.setColor(QPalette.ColorRole.Highlight, accent)
        palette.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.white)
        palette.setColor(QPalette.ColorRole.Link, accent)
        palette.setColor(QPalette.ColorRole.ToolTipBase, bg2)
        palette.setColor(QPalette.ColorRole.ToolTipText, text)
        palette.setColor(QPalette.ColorGroup.Disabled,
                         QPalette.ColorRole.Text, disabled_text)
        palette.setColor(QPalette.ColorGroup.Disabled,
                         QPalette.ColorRole.ButtonText, disabled_text)
        app.setPalette(palette)
    except Exception:  # noqa: BLE001
        # Theming is cosmetic; never let it block GUI start.
        pass


def main() -> int:
    import signal

    from PySide6.QtWidgets import QApplication
    from video_extender.gui.main_window import MainWindow
    from video_extender.utils import logging as _logging

    log = _logging.setup()
    log.info("GUI başlatılıyor…")

    # Restore the default SIGINT handler so a Ctrl+C in the parent terminal
    # actually quits the Qt event loop. Without this, Qt installs its own
    # handler and PySide6 spends seconds before propagating, which surfaces
    # as a noisy KeyboardInterrupt traceback in the launcher.
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    app = QApplication.instance() or QApplication(sys.argv)
    # QApplication.instance() returns QCoreApplication | None at the type
    # level; we know we just built (or have) a QApplication so the narrowing
    # is safe.
    assert isinstance(app, QApplication)
    app.setApplicationName("Video Extender")
    app.setOrganizationName("video-extender")
    _apply_dark_palette_if_os_prefers(app)

    win = MainWindow()
    win.resize(1100, 720)
    win.show()
    # Force the window to front + take focus — on tiled WMs and some
    # Wayland compositors a freshly-created window can land behind the
    # terminal that spawned it.
    win.raise_()
    win.activateWindow()
    log.info(
        "GUI hazır (pencere açıldı). Geometry: %dx%d at (%d,%d), visible=%s",
        win.width(), win.height(), win.x(), win.y(), win.isVisible(),
    )
    try:
        rc = app.exec()
    except KeyboardInterrupt:
        log.info("Ctrl+C alındı, kapatılıyor…")
        return 130
    log.info("Qt event loop exited (rc=%d).", rc)
    return rc


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130) from None

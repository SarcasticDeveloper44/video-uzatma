"""GUI entry point — `python -m video_extender` (no args)."""
from __future__ import annotations

import sys


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
    app.setApplicationName("Video Extender")
    app.setOrganizationName("video-extender")

    win = MainWindow()
    win.resize(1100, 720)
    win.show()
    # Force the window to front + take focus — on tiled WMs and some
    # Wayland compositors a freshly-created window can land behind the
    # terminal that spawned it.
    win.raise_()
    win.activateWindow()
    log.info("GUI hazır (pencere açıldı).")
    try:
        return app.exec()
    except KeyboardInterrupt:
        log.info("Ctrl+C alındı, kapatılıyor…")
        return 130


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130) from None

"""GUI entry point — `python -m video_extender` (no args)."""
from __future__ import annotations

import sys


def main() -> int:
    from PySide6.QtWidgets import QApplication
    from video_extender.gui.main_window import MainWindow
    from video_extender.utils import logging as _logging

    log = _logging.setup()
    log.info("GUI başlatılıyor…")

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
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

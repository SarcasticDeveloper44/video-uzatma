"""GUI entry point — `python -m video_extender` (no args)."""
from __future__ import annotations

import sys


def main() -> int:
    from PySide6.QtWidgets import QApplication
    from video_extender.gui.main_window import MainWindow
    from video_extender.utils import logging as _logging

    _logging.setup()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Video Extender")
    app.setOrganizationName("video-extender")

    win = MainWindow()
    win.resize(1100, 720)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

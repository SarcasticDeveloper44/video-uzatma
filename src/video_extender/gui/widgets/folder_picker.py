"""Source picker: a folder, a single video, or multiple videos.

Drag-drop accepts:
  - a folder       → all videos in it (recursive optional)
  - a single video → process just that one
  - multiple videos → process exactly that set

A single "Seç…" button shows a popup menu so the user picks the mode
(folder vs file) without us cluttering the layout with two buttons.
QFileDialog itself doesn't support mixed file+dir selection in native
mode, so this menu indirection is the clean compromise.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, Signal
from PySide6.QtGui import QAction, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QHBoxLayout, QLabel, QMenu, QPushButton,
    QVBoxLayout, QWidget,
)

from video_extender.utils.paths import is_video


class FolderPicker(QWidget):
    folder_changed = Signal(Path)
    files_chosen = Signal(list)         # list[Path] — explicit video files
    recursive_toggled = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._folder: Path | None = None

        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.path_label = QLabel(
            "<i>Klasör veya video dosyalarını buraya sürükle — ya da seç düğmelerini kullan.</i>"
        )
        self.path_label.setStyleSheet(
            "padding: 14px; border: 2px dashed #888; border-radius: 6px;"
        )
        self.path_label.setMinimumHeight(60)
        self.btn_select = QPushButton("Seç ▾")
        self.btn_select.setToolTip("Klasör veya video dosyaları seç")
        self.btn_select.clicked.connect(self._show_select_menu)
        row.addWidget(self.path_label, 1)
        row.addWidget(self.btn_select)
        layout.addLayout(row)

        self.recursive_cb = QCheckBox("Alt klasörleri de tara")
        self.recursive_cb.toggled.connect(self.recursive_toggled)
        layout.addWidget(self.recursive_cb)

        self.setAcceptDrops(True)

    @property
    def folder(self) -> Path | None:
        return self._folder

    @property
    def recursive(self) -> bool:
        return self.recursive_cb.isChecked()

    # --- pick handlers ---
    def _show_select_menu(self) -> None:
        """Popup beneath the Seç… button. Two actions: folder mode or file mode.
        Lets us keep a single button while exposing the two QFileDialog APIs
        Qt provides (no native dialog supports mixed file+dir selection)."""
        menu = QMenu(self)
        folder_action = QAction("Klasör seç…", menu)
        files_action = QAction("Video(lar) seç…", menu)
        menu.addAction(folder_action)
        menu.addAction(files_action)
        # Anchor the menu just below the button.
        anchor = self.btn_select.mapToGlobal(QPoint(0, self.btn_select.height()))
        chosen = menu.exec(anchor)
        if chosen is folder_action:
            self._pick_folder()
        elif chosen is files_action:
            self._pick_files()

    def _pick_folder(self) -> None:
        start = str(self._folder or Path.home())
        d = QFileDialog.getExistingDirectory(self, "Video klasörünü seç", start)
        if d:
            self._set_folder(Path(d))

    def _pick_files(self) -> None:
        start = str(self._folder or Path.home())
        files, _ = QFileDialog.getOpenFileNames(
            self, "Video(lar) seç", start,
            "Video (*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.flv *.wmv *.mpg "
            "*.mpeg *.ts *.m2ts *.3gp *.ogv *.mxf *.f4v)",
        )
        if files:
            self._set_files([Path(f) for f in files])

    # --- internal state setters (emit appropriate signal) ---
    def _set_folder(self, p: Path) -> None:
        self._folder = p
        self.path_label.setText(f"<b>{p}</b>")
        self.folder_changed.emit(p)

    def _set_files(self, files: list[Path]) -> None:
        if not files:
            return
        # The parent of the first file becomes the "source folder" for
        # output/state purposes. All explicit files are passed downstream.
        self._folder = files[0].parent
        if len(files) == 1:
            self.path_label.setText(
                f"<b>{files[0].name}</b><br>"
                f"<small style='color:#888;'>{files[0].parent}</small>"
            )
        else:
            preview = ", ".join(f.name for f in files[:3])
            suffix = "…" if len(files) > 3 else ""
            self.path_label.setText(
                f"<b>{len(files)} video</b><br>"
                f"<small style='color:#888;'>{preview}{suffix} — {files[0].parent}</small>"
            )
        self.files_chosen.emit(files)

    # --- drag & drop ---
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if not event.mimeData().hasUrls():
            event.ignore()
            return
        urls = event.mimeData().urls()
        # Accept if ANY url is a directory or a recognised video file.
        for u in urls:
            p = Path(u.toLocalFile())
            if p.is_dir() or is_video(p):
                event.acceptProposedAction()
                return
        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        urls = event.mimeData().urls()
        paths = [Path(u.toLocalFile()) for u in urls]
        # Prefer a directory drop over a mixed/files drop: if any path is a
        # dir, treat the whole drop as that single directory.
        for p in paths:
            if p.is_dir():
                self._set_folder(p)
                event.acceptProposedAction()
                return
        # Otherwise collect every video file in the drop.
        files = [p for p in paths if is_video(p)]
        if files:
            self._set_files(files)
            event.acceptProposedAction()
            return
        event.ignore()

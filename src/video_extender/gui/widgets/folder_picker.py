"""Folder picker with drag & drop support."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)


class FolderPicker(QWidget):
    folder_changed = Signal(Path)
    recursive_toggled = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._folder: Path | None = None

        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.path_label = QLabel("<i>Henüz klasör seçilmedi — klasörü buraya sürükleyebilirsin.</i>")
        self.path_label.setStyleSheet(
            "padding: 14px; border: 2px dashed #888; border-radius: 6px;"
        )
        self.path_label.setMinimumHeight(60)
        self.btn = QPushButton("Klasör Seç…")
        self.btn.clicked.connect(self._pick)
        row.addWidget(self.path_label, 1)
        row.addWidget(self.btn)
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

    def _pick(self) -> None:
        start = str(self._folder or Path.home())
        d = QFileDialog.getExistingDirectory(self, "Video klasörünü seç", start)
        if d:
            self._set_folder(Path(d))

    def _set_folder(self, p: Path) -> None:
        self._folder = p
        self.path_label.setText(f"<b>{p}</b>")
        self.folder_changed.emit(p)

    # Drag & drop
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if any(Path(u.toLocalFile()).is_dir() for u in urls):
                event.acceptProposedAction()
                return
        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        for u in event.mimeData().urls():
            p = Path(u.toLocalFile())
            if p.is_dir():
                self._set_folder(p)
                event.acceptProposedAction()
                return
        event.ignore()

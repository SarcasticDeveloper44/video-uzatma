"""Save/load JSON profiles for the current spec."""
from __future__ import annotations

from pathlib import Path
from collections.abc import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from video_extender.core import config as _config
from video_extender.core.job import JobSpec


class ProfilesPanel(QFrame):
    profile_loaded = Signal(object)  # emits JobSpec

    def __init__(
        self,
        gather_spec: Callable[[], JobSpec],
        apply_spec: Callable[[JobSpec], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._gather = gather_spec
        self._apply = apply_spec

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<b>Profiller</b>"))

        row = QHBoxLayout()
        save_btn = QPushButton("Profili Kaydet…")
        load_btn = QPushButton("Profil Yükle…")
        save_btn.clicked.connect(self._save)
        load_btn.clicked.connect(self._load)
        row.addWidget(save_btn)
        row.addWidget(load_btn)
        layout.addLayout(row)
        layout.addStretch(1)

    def _save(self) -> None:
        try:
            spec = self._gather()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Hata", str(exc))
            return
        f, _ = QFileDialog.getSaveFileName(self, "Profili kaydet", str(Path.home() / "profile.json"),
                                           "JSON (*.json)")
        if not f:
            return
        try:
            _config.save_profile(Path(f), spec)
        except OSError as exc:
            QMessageBox.warning(self, "Yazma hatası", str(exc))

    def _load(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Profil yükle", str(Path.home()), "JSON (*.json)")
        if not f:
            return
        try:
            spec, _ = _config.load_profile(Path(f))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Yükleme hatası", str(exc))
            return
        self._apply(spec)
        self.profile_loaded.emit(spec)

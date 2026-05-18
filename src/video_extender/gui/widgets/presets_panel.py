"""Platform preset selector."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QFormLayout, QFrame, QLabel, QVBoxLayout, QWidget

from video_extender.core.presets import PRESET_REGISTRY


class PresetsPanel(QFrame):
    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<b>Platform Preset</b>"))

        form = QFormLayout()
        self.combo = QComboBox()
        # Group: working presets first, then scaffolds.
        from video_extender.core.presets.base import PlatformPreset
        working: list[tuple[str, type[PlatformPreset]]] = []
        scaffold: list[tuple[str, type[PlatformPreset]]] = []
        for k, cls in PRESET_REGISTRY.items():
            (scaffold if "iskelet" in cls.label.lower() else working).append((k, cls))
        for k, cls in sorted(working, key=lambda kv: kv[1].label):
            self.combo.addItem(cls.label, k)
        if scaffold:
            self.combo.insertSeparator(self.combo.count())
            for k, cls in sorted(scaffold, key=lambda kv: kv[1].label):
                self.combo.addItem(cls.label, k)
        self.combo.setCurrentIndex(0)
        form.addRow("Hedef:", self.combo)

        self.desc = QLabel("")
        self.desc.setWordWrap(True)
        self.desc.setStyleSheet("color: #555; font-style: italic;")
        form.addRow(self.desc)
        layout.addLayout(form)
        layout.addStretch(1)

        self.combo.currentIndexChanged.connect(self._refresh_desc)
        self.combo.currentIndexChanged.connect(lambda *_: self.changed.emit())
        self._refresh_desc()

    def _refresh_desc(self) -> None:
        key = self.combo.currentData()
        cls = PRESET_REGISTRY.get(key)
        if cls is None:
            self.desc.setText("")
            return
        self.desc.setText(cls.description)

    @property
    def preset_key(self) -> str:
        return self.combo.currentData() or "tiktok"

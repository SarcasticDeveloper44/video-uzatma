"""Hardware info widget — shows detected CPU/GPU/encoders."""
from __future__ import annotations

from PySide6.QtWidgets import QFormLayout, QFrame, QLabel, QVBoxLayout, QWidget

from video_extender.core.hardware import detect


class HardwareInfoWidget(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(self)
        title = QLabel("<b>Tespit Edilen Donanım</b>")
        layout.addWidget(title)

        hw = detect()
        form = QFormLayout()
        form.addRow("CPU çekirdek:", QLabel(str(hw.cpu_count)))
        form.addRow("RAM:", QLabel(f"{hw.ram_total_mb} MB"))
        form.addRow("ffmpeg:", QLabel(hw.ffmpeg_path or "<bulunamadı>"))

        if hw.gpus:
            for g in hw.gpus:
                encoders = ", ".join(g.encoders) if g.encoders else "—"
                form.addRow(f"GPU ({g.vendor}):", QLabel(f"{g.name}\n  Encoders: {encoders}"))
        else:
            form.addRow("GPU:", QLabel("<bulunamadı; CPU kullanılacak>"))

        layout.addLayout(form)
        # The scheduler preview that used to live here was hard-coded to a
        # mid-grey color that vanished on dark themes. The same information
        # is available cleanly via the CLI: `video-extender --doctor`.
        layout.addStretch(1)

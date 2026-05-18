"""Hardware info widget — shows detected CPU/GPU/encoders."""
from __future__ import annotations

from PySide6.QtWidgets import QFormLayout, QFrame, QLabel, QVBoxLayout, QWidget

from video_extender.core.hardware import detect
from video_extender.core.scheduler import plan


class HardwareInfoWidget(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
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

        # Scheduler preview for 10 jobs
        layout.addWidget(QLabel("<b>10 video için planlanan paralel worker'lar:</b>"))
        p = plan(10, hw=hw)
        plan_text = "\n".join(f"  • {s.label}" for s in p.slots)
        plan_label = QLabel(plan_text)
        plan_label.setStyleSheet("font-family: monospace; color: #444;")
        layout.addWidget(plan_label)
        layout.addStretch(1)

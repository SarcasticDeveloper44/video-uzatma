"""Filter toggles: watermark, audio normalize, metadata strip, final fade-out,
aspect convert, subtitle burn, color grade."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)


class FiltersPanel(QFrame):
    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<b>Ek Filtreler</b>"))

        form = QFormLayout()

        # Audio normalize
        self.normalize_cb = QCheckBox("Sesi platform LUFS hedefine normalize et")
        self.normalize_cb.setChecked(True)
        form.addRow(self.normalize_cb)

        # Metadata strip
        self.strip_cb = QCheckBox("Metadata temizle (GPS, EXIF gibi)")
        self.strip_cb.setChecked(True)
        form.addRow(self.strip_cb)

        # Final fade-out
        self.final_fade_cb = QCheckBox("Final çıktıda ek ses fade-out uygula")
        self.final_fade_cb.setChecked(False)
        form.addRow(self.final_fade_cb)

        # Watermark
        self.wm_cb = QCheckBox("Watermark / Logo ekle")
        form.addRow(self.wm_cb)

        wm_row = QHBoxLayout()
        self.wm_path = QLineEdit()
        self.wm_path.setPlaceholderText("PNG/JPG yolu…")
        wm_browse = QPushButton("Seç…")
        wm_browse.clicked.connect(self._pick_wm)
        wm_row.addWidget(self.wm_path, 1)
        wm_row.addWidget(wm_browse)
        form.addRow("Resim:", wm_row)

        self.wm_position = QComboBox()
        self.wm_position.addItems(["bottom-right", "bottom-left", "top-right", "top-left", "center"])
        form.addRow("Konum:", self.wm_position)

        self.wm_opacity = QDoubleSpinBox()
        self.wm_opacity.setRange(0.1, 1.0)
        self.wm_opacity.setSingleStep(0.1)
        self.wm_opacity.setValue(0.8)
        form.addRow("Opaklık:", self.wm_opacity)

        # --- Subtitle burn ---
        self.subs_cb = QCheckBox("Altyazı yak (SRT/ASS)")
        form.addRow(self.subs_cb)
        subs_row = QHBoxLayout()
        self.subs_path = QLineEdit()
        self.subs_path.setPlaceholderText("subtitles.srt veya subtitles.ass")
        subs_btn = QPushButton("Seç…")
        subs_btn.clicked.connect(self._pick_subs)
        subs_row.addWidget(self.subs_path, 1)
        subs_row.addWidget(subs_btn)
        form.addRow("Altyazı dosyası:", subs_row)
        self.subs_font_size = QSpinBox()
        self.subs_font_size.setRange(8, 96)
        self.subs_font_size.setValue(24)
        form.addRow("Font boyutu:", self.subs_font_size)

        # --- Aspect convert ---
        self.aspect_cb = QCheckBox("En-boy oranını değiştir")
        form.addRow(self.aspect_cb)
        self.aspect_target = QComboBox()
        for ratio in ["9:16", "16:9", "1:1", "4:5", "4:3"]:
            self.aspect_target.addItem(ratio)
        form.addRow("Hedef oran:", self.aspect_target)
        self.aspect_mode = QComboBox()
        self.aspect_mode.addItems(["blur_pad", "crop"])
        form.addRow("Yöntem:", self.aspect_mode)

        # --- Color grade ---
        self.cg_cb = QCheckBox("Renk düzenle")
        form.addRow(self.cg_cb)
        self.cg_brightness = QDoubleSpinBox()
        self.cg_brightness.setRange(-1.0, 1.0); self.cg_brightness.setSingleStep(0.05)
        form.addRow("Brightness (-1..1):", self.cg_brightness)
        self.cg_contrast = QDoubleSpinBox()
        self.cg_contrast.setRange(0.0, 3.0); self.cg_contrast.setSingleStep(0.05); self.cg_contrast.setValue(1.0)
        form.addRow("Contrast (0..3):", self.cg_contrast)
        self.cg_saturation = QDoubleSpinBox()
        self.cg_saturation.setRange(0.0, 3.0); self.cg_saturation.setSingleStep(0.05); self.cg_saturation.setValue(1.0)
        form.addRow("Saturation (0..3):", self.cg_saturation)
        self.cg_gamma = QDoubleSpinBox()
        self.cg_gamma.setRange(0.1, 10.0); self.cg_gamma.setSingleStep(0.05); self.cg_gamma.setValue(1.0)
        form.addRow("Gamma (0.1..10):", self.cg_gamma)

        layout.addLayout(form)
        layout.addStretch(1)

        for w in (self.normalize_cb, self.strip_cb, self.final_fade_cb,
                  self.wm_cb, self.wm_path, self.wm_position, self.wm_opacity,
                  self.subs_cb, self.subs_path, self.subs_font_size,
                  self.aspect_cb, self.aspect_target, self.aspect_mode,
                  self.cg_cb, self.cg_brightness, self.cg_contrast,
                  self.cg_saturation, self.cg_gamma):
            try:
                w.toggled.connect(lambda *_: self.changed.emit())  # type: ignore[attr-defined]
            except AttributeError:
                pass
            try:
                w.textChanged.connect(lambda *_: self.changed.emit())  # type: ignore[attr-defined]
            except AttributeError:
                pass
            try:
                w.currentIndexChanged.connect(lambda *_: self.changed.emit())  # type: ignore[attr-defined]
            except AttributeError:
                pass
            try:
                w.valueChanged.connect(lambda *_: self.changed.emit())  # type: ignore[attr-defined]
            except AttributeError:
                pass

    def _pick_wm(self) -> None:
        f, _ = QFileDialog.getOpenFileName(
            self, "Watermark resmi seç", str(Path.home()),
            "Görseller (*.png *.jpg *.jpeg *.webp)",
        )
        if f:
            self.wm_path.setText(f)
            self.wm_cb.setChecked(True)

    def _pick_subs(self) -> None:
        f, _ = QFileDialog.getOpenFileName(
            self, "Altyazı dosyası seç", str(Path.home()),
            "Altyazı (*.srt *.ass *.ssa *.vtt)",
        )
        if f:
            self.subs_path.setText(f)
            self.subs_cb.setChecked(True)

    # ---- API ----
    def build_filter_chain(self) -> tuple[list[str], dict]:
        names: list[str] = []
        opts: dict = {}
        # Aspect convert must run FIRST so other filters see the converted resolution.
        if self.aspect_cb.isChecked():
            names.append("aspect_convert")
            opts["aspect_convert"] = {
                "target": self.aspect_target.currentText(),
                "mode": self.aspect_mode.currentText(),
            }
        if self.normalize_cb.isChecked():
            names.append("audio_normalize")
            opts["audio_normalize"] = {}  # target_lufs filled by main_window from preset
        if self.wm_cb.isChecked() and self.wm_path.text().strip():
            names.append("watermark")
            opts["watermark"] = {
                "image": self.wm_path.text().strip(),
                "position": self.wm_position.currentText(),
                "opacity": self.wm_opacity.value(),
            }
        if self.subs_cb.isChecked() and self.subs_path.text().strip():
            names.append("subtitle_burn")
            opts["subtitle_burn"] = {
                "file": self.subs_path.text().strip(),
                "font_size": self.subs_font_size.value(),
            }
        if self.cg_cb.isChecked() and (
            self.cg_brightness.value() != 0.0 or self.cg_contrast.value() != 1.0
            or self.cg_saturation.value() != 1.0 or self.cg_gamma.value() != 1.0
        ):
            names.append("color_grade")
            opts["color_grade"] = {
                "brightness": self.cg_brightness.value(),
                "contrast": self.cg_contrast.value(),
                "saturation": self.cg_saturation.value(),
                "gamma": self.cg_gamma.value(),
            }
        if self.final_fade_cb.isChecked():
            names.append("audio_fade_out")
            opts["audio_fade_out"] = {"duration": 1.5}  # total_duration filled by pipeline
        if self.strip_cb.isChecked():
            names.append("metadata_strip")
        return names, opts

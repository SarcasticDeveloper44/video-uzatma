"""Settings panel: duration, mode, extender method, quality, filename template."""
from __future__ import annotations

from PySide6.QtCore import Signal
from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QRadioButton, QSpinBox, QVBoxLayout, QWidget,
)

from video_extender.core.extenders import EXTENDER_REGISTRY
from video_extender.core.job import ExtendMode
from video_extender.utils.duration import format_duration


_UNIT_FACTORS = {"saniye": 1, "dakika": 60, "saat": 3600}


class SettingsPanel(QFrame):
    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<b>Uzatma Ayarları</b>"))

        form = QFormLayout()

        # Duration + unit
        dur_row = QHBoxLayout()
        self.duration_input = QSpinBox()
        self.duration_input.setRange(1, 99999)
        self.duration_input.setValue(30)
        self.unit_combo = QComboBox()
        self.unit_combo.addItems(["dakika", "saniye", "saat"])
        dur_row.addWidget(self.duration_input)
        dur_row.addWidget(self.unit_combo)
        form.addRow("Uzatma süresi:", dur_row)

        # Mode
        self.add_radio = QRadioButton("Sabit süre EKLE (orijinal + N)")
        self.add_radio.setChecked(True)
        self.fill_radio = QRadioButton("Toplam süreye TAMAMLA (toplam N)")
        mode_box = QVBoxLayout()
        mode_box.addWidget(self.add_radio)
        mode_box.addWidget(self.fill_radio)
        form.addRow("Mod:", mode_box)

        # Method
        self.method_combo = QComboBox()
        for k, cls in sorted(EXTENDER_REGISTRY.items(), key=lambda kv: kv[1].label):
            self.method_combo.addItem(cls.label, k)
        form.addRow("Yöntem:", self.method_combo)

        # Per-method extra inputs: intro/outro file paths + end card image
        io_row = QHBoxLayout()
        self.intro_path = QLineEdit()
        self.intro_path.setPlaceholderText("(opsiyonel) intro klibi")
        intro_btn = QPushButton("…")
        intro_btn.setFixedWidth(32)
        intro_btn.clicked.connect(self._pick_intro)
        io_row.addWidget(self.intro_path, 1)
        io_row.addWidget(intro_btn)
        form.addRow("Intro klip:", io_row)

        outro_row = QHBoxLayout()
        self.outro_path = QLineEdit()
        self.outro_path.setPlaceholderText("intro_outro için: outro klibi")
        outro_btn = QPushButton("…")
        outro_btn.setFixedWidth(32)
        outro_btn.clicked.connect(self._pick_outro)
        outro_row.addWidget(self.outro_path, 1)
        outro_row.addWidget(outro_btn)
        form.addRow("Outro klip:", outro_row)

        card_row = QHBoxLayout()
        self.endcard_path = QLineEdit()
        self.endcard_path.setPlaceholderText("image_card için: PNG/JPG bitiş kartı")
        card_btn = QPushButton("…")
        card_btn.setFixedWidth(32)
        card_btn.clicked.connect(self._pick_endcard)
        card_row.addWidget(self.endcard_path, 1)
        card_row.addWidget(card_btn)
        form.addRow("Bitiş kartı:", card_row)

        # Audio fade-out
        self.fade_spin = QDoubleSpinBox()
        self.fade_spin.setRange(0.0, 10.0)
        self.fade_spin.setSingleStep(0.5)
        self.fade_spin.setValue(1.5)
        self.fade_spin.setSuffix(" sn")
        form.addRow("Ses fade-out:", self.fade_spin)

        # Quality
        self.quality_combo = QComboBox()
        self.quality_combo.addItems(["low", "medium", "high"])
        self.quality_combo.setCurrentText("medium")
        form.addRow("Kalite:", self.quality_combo)

        # Codec
        self.codec_combo = QComboBox()
        self.codec_combo.addItem("H.264 (en uyumlu)", "h264")
        self.codec_combo.addItem("HEVC (~%30 daha küçük; bazı reklam platformlarında reddedilebilir)", "hevc")
        form.addRow("Codec:", self.codec_combo)

        # Encoder override
        self.encoder_combo = QComboBox()
        self.encoder_combo.addItem("Otomatik (sistemin en hızlısı)", None)
        self._populate_encoder_choices()
        form.addRow("Encoder (zorla):", self.encoder_combo)

        # Filename template
        self.filename_template = QLineEdit("{name}_extended.{ext}")
        self.filename_template.setToolTip("Token'lar: {name}, {ext}, {duration}, {preset}")
        form.addRow("Çıktı isim şablonu:", self.filename_template)

        layout.addLayout(form)
        layout.addStretch(1)

        for w in (self.duration_input, self.unit_combo, self.method_combo,
                  self.quality_combo, self.codec_combo, self.encoder_combo,
                  self.fade_spin, self.filename_template,
                  self.add_radio, self.fill_radio):
            try:
                w.valueChanged.connect(self._emit_changed)  # type: ignore[attr-defined]
            except AttributeError:
                pass
            try:
                w.currentIndexChanged.connect(self._emit_changed)  # type: ignore[attr-defined]
            except AttributeError:
                pass
            try:
                w.textChanged.connect(self._emit_changed)  # type: ignore[attr-defined]
            except AttributeError:
                pass
            try:
                w.toggled.connect(self._emit_changed)  # type: ignore[attr-defined]
            except AttributeError:
                pass

    def _emit_changed(self, *args: object) -> None:
        self.changed.emit()

    def _populate_encoder_choices(self) -> None:
        """Add to the encoder dropdown only encoders that are listed AND functional."""
        from video_extender.core.encoders import ENCODER_REGISTRY
        from video_extender.core.hardware import detect, probe_encoder
        hw = detect()
        # Group: working GPU encoders first, then CPU, then unavailable greyed-out.
        gpu_avail, cpu_avail, unavailable = [], [], []
        for name, cls in sorted(ENCODER_REGISTRY.items(), key=lambda kv: (kv[1].kind, kv[0])):
            listed = cls.ffmpeg_encoder in hw.available_encoders
            functional = listed and probe_encoder(cls.ffmpeg_encoder)
            label = cls.label + ("" if functional else " [çalışmıyor]")
            entry = (cls.ffmpeg_encoder, label, functional)
            if not listed:
                unavailable.append(entry)
            elif cls.kind == "gpu":
                gpu_avail.append(entry)
            else:
                cpu_avail.append(entry)
        for enc, label, functional in gpu_avail + cpu_avail:
            self.encoder_combo.addItem(label, enc)
            if not functional:
                idx = self.encoder_combo.count() - 1
                self.encoder_combo.model().item(idx).setEnabled(False)

    def _pick_intro(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Intro klip", str(Path.home()),
                                           "Video (*.mp4 *.mov *.mkv *.webm)")
        if f:
            self.intro_path.setText(f)

    def _pick_outro(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Outro klip", str(Path.home()),
                                           "Video (*.mp4 *.mov *.mkv *.webm)")
        if f:
            self.outro_path.setText(f)

    def _pick_endcard(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Bitiş kartı", str(Path.home()),
                                           "Görsel (*.png *.jpg *.jpeg *.webp)")
        if f:
            self.endcard_path.setText(f)

    def extender_options(self) -> dict:
        opts: dict = {}
        if self.intro_path.text().strip():
            opts["intro"] = self.intro_path.text().strip()
        if self.outro_path.text().strip():
            opts["outro"] = self.outro_path.text().strip()
        if self.endcard_path.text().strip():
            opts["image"] = self.endcard_path.text().strip()
        return opts

    # --- read API ---
    @property
    def extend_seconds(self) -> float:
        factor = _UNIT_FACTORS[self.unit_combo.currentText()]
        return float(self.duration_input.value() * factor)

    @property
    def extend_mode(self) -> ExtendMode:
        return ExtendMode.ADD if self.add_radio.isChecked() else ExtendMode.FILL

    @property
    def method(self) -> str:
        return self.method_combo.currentData()

    @property
    def quality(self) -> str:
        return self.quality_combo.currentText()

    @property
    def video_codec(self) -> str:
        return self.codec_combo.currentData() or "h264"

    @property
    def encoder_override(self) -> str | None:
        return self.encoder_combo.currentData()

    @property
    def audio_fade(self) -> float:
        return self.fade_spin.value()

    @property
    def filename_template_text(self) -> str:
        return self.filename_template.text() or "{name}_extended.{ext}"

    def summary(self) -> str:
        return f"{self.extend_mode.value} {format_duration(self.extend_seconds)} ({self.method}, {self.quality})"

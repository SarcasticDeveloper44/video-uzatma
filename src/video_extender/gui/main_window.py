"""Main window: ties widgets + worker threads + preflight + run lifecycle."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton, QSplitter,
    QStatusBar, QTabWidget, QVBoxLayout, QWidget,
)

from video_extender.core import preflight as _preflight
from video_extender.core.job import ExtendMode, Job, JobSpec, JobStatus
from video_extender.core.presets import PRESET_REGISTRY
from video_extender.gui.widgets.filters_panel import FiltersPanel
from video_extender.gui.widgets.folder_picker import FolderPicker
from video_extender.gui.widgets.hardware_info import HardwareInfoWidget
from video_extender.gui.widgets.presets_panel import PresetsPanel
from video_extender.gui.widgets.profiles_panel import ProfilesPanel
from video_extender.gui.widgets.settings_panel import SettingsPanel
from video_extender.gui.widgets.video_list import VideoListWidget
from video_extender.gui.workers import BatchSignals, BatchThread, ProbeThread
from video_extender.utils.notify import notify


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Video Extender — Reklam Toplu Uzatıcı")

        self.signals = BatchSignals()
        self._jobs: list[Job] = []
        self._probe_thread: ProbeThread | None = None
        self._batch_thread: BatchThread | None = None

        # --- Top: folder picker ---
        central = QWidget(self)
        root_layout = QVBoxLayout(central)

        self.folder_picker = FolderPicker()
        self.folder_picker.folder_changed.connect(self._on_folder_chosen)
        root_layout.addWidget(self.folder_picker)

        # --- Middle: splitter (left=tabs, right=video list) ---
        splitter = QSplitter(Qt.Horizontal)

        self.tabs = QTabWidget()
        self.settings_panel = SettingsPanel()
        self.presets_panel = PresetsPanel()
        self.filters_panel = FiltersPanel()
        self.profiles_panel = ProfilesPanel(self._gather_spec, self._apply_spec)
        self.hardware_widget = HardwareInfoWidget()

        self.tabs.addTab(self.settings_panel, "Uzatma")
        self.tabs.addTab(self.presets_panel, "Platform")
        self.tabs.addTab(self.filters_panel, "Filtreler")
        self.tabs.addTab(self.profiles_panel, "Profiller")
        self.tabs.addTab(self.hardware_widget, "Donanım")

        self.video_list = VideoListWidget()
        splitter.addWidget(self.tabs)
        splitter.addWidget(self.video_list)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([380, 720])
        root_layout.addWidget(splitter, 1)

        # --- Bottom: action bar ---
        action_row = QHBoxLayout()
        self.summary_label = QLabel("")
        self.start_btn = QPushButton("Başlat")
        self.start_btn.setMinimumWidth(140)
        self.start_btn.setEnabled(False)
        self.cancel_btn = QPushButton("İptal")
        self.cancel_btn.setEnabled(False)
        action_row.addWidget(self.summary_label, 1)
        action_row.addWidget(self.cancel_btn)
        action_row.addWidget(self.start_btn)
        root_layout.addLayout(action_row)

        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar(self))

        # Connections
        self.start_btn.clicked.connect(self._start_batch)
        self.cancel_btn.clicked.connect(self._cancel_batch)
        for panel in (self.settings_panel, self.presets_panel, self.filters_panel):
            panel.changed.connect(self._refresh_summary)
        self.profiles_panel.profile_loaded.connect(lambda _s: self._refresh_summary())

        self.signals.job_added.connect(self._on_job_added)
        self.signals.job_updated.connect(self._on_job_updated)
        self.signals.batch_started.connect(self._on_batch_started)
        self.signals.batch_finished.connect(self._on_batch_finished)
        self.signals.error.connect(self._on_error)

        self._refresh_summary()
        self._run_initial_preflight()

    # -----------------------------------------------------------------
    # Spec gathering / applying
    # -----------------------------------------------------------------
    def _gather_spec(self) -> JobSpec:
        filters, opts = self.filters_panel.build_filter_chain()
        preset_key = self.presets_panel.preset_key
        if "audio_normalize" in opts:
            params = PRESET_REGISTRY[preset_key].for_quality(self.settings_panel.quality)
            opts["audio_normalize"]["target_lufs"] = params.audio_lufs
        return JobSpec(
            extend_seconds=self.settings_panel.extend_seconds,
            extend_mode=self.settings_panel.extend_mode,
            extender_name=self.settings_panel.method,
            preset_name=preset_key,
            quality=self.settings_panel.quality,
            video_codec=self.settings_panel.video_codec,
            filters=tuple(filters),
            filter_options=opts,
            extender_options=self.settings_panel.extender_options(),
            filename_template=self.settings_panel.filename_template_text,
            audio_fade_out_seconds=self.settings_panel.audio_fade,
        )

    def _apply_spec(self, spec: JobSpec) -> None:
        # Settings
        self.settings_panel.duration_input.setValue(int(spec.extend_seconds))
        self.settings_panel.unit_combo.setCurrentText("saniye")
        if spec.extend_mode == ExtendMode.ADD:
            self.settings_panel.add_radio.setChecked(True)
        else:
            self.settings_panel.fill_radio.setChecked(True)
        idx = self.settings_panel.method_combo.findData(spec.extender_name)
        if idx >= 0:
            self.settings_panel.method_combo.setCurrentIndex(idx)
        self.settings_panel.quality_combo.setCurrentText(spec.quality)
        idx_codec = self.settings_panel.codec_combo.findData(spec.video_codec)
        if idx_codec >= 0:
            self.settings_panel.codec_combo.setCurrentIndex(idx_codec)
        self.settings_panel.fade_spin.setValue(spec.audio_fade_out_seconds)
        self.settings_panel.filename_template.setText(spec.filename_template)
        self.settings_panel.intro_path.setText(spec.extender_options.get("intro", ""))
        self.settings_panel.outro_path.setText(spec.extender_options.get("outro", ""))
        self.settings_panel.endcard_path.setText(spec.extender_options.get("image", ""))

        idx = self.presets_panel.combo.findData(spec.preset_name)
        if idx >= 0:
            self.presets_panel.combo.setCurrentIndex(idx)

        names = set(spec.filters or ())
        self.filters_panel.normalize_cb.setChecked("audio_normalize" in names)
        self.filters_panel.strip_cb.setChecked("metadata_strip" in names)
        self.filters_panel.final_fade_cb.setChecked("audio_fade_out" in names)
        self.filters_panel.wm_cb.setChecked("watermark" in names)
        wm = spec.filter_options.get("watermark", {})
        if wm.get("image"):
            self.filters_panel.wm_path.setText(wm["image"])
            self.filters_panel.wm_position.setCurrentText(wm.get("position", "bottom-right"))
            self.filters_panel.wm_opacity.setValue(float(wm.get("opacity", 0.8)))

    # -----------------------------------------------------------------
    # Folder change → probe
    # -----------------------------------------------------------------
    def _on_folder_chosen(self, folder: Path) -> None:
        self.video_list.clear_rows()
        self._jobs = []
        spec = self._gather_spec()
        if self._probe_thread and self._probe_thread.isRunning():
            self._probe_thread.requestInterruption()
            self._probe_thread.wait(1000)
        t = ProbeThread(folder, self.folder_picker.recursive, spec, self.signals)
        self._probe_thread = t
        t.finished.connect(lambda: self._on_probe_done(t))
        t.start()
        self.statusBar().showMessage(f"{folder} taranıyor…")

    def _on_probe_done(self, t: ProbeThread) -> None:
        self._jobs = t.jobs
        self.start_btn.setEnabled(bool(self._jobs))
        self.statusBar().showMessage(f"{len(self._jobs)} video hazır.")
        self._refresh_summary()

    # -----------------------------------------------------------------
    # Batch run
    # -----------------------------------------------------------------
    def _start_batch(self) -> None:
        if not self._jobs or self.folder_picker.folder is None:
            return
        try:
            spec = self._gather_spec()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Hata", str(exc))
            return
        # Preflight before start
        report = _preflight.run(source_folder=self.folder_picker.folder, output_subdir=spec.output_subdir)
        if not report.ok:
            QMessageBox.critical(self, "Preflight başarısız", "\n".join(report.errors))
            return
        if report.warnings:
            ok = QMessageBox.question(self, "Uyarılar", "\n".join(report.warnings) + "\n\nDevam edilsin mi?")
            if ok != QMessageBox.Yes:
                return

        # Reset progress / status on rows
        for j in self._jobs:
            if j.status not in (JobStatus.FAILED,):
                j.status = JobStatus.PENDING
                j.progress = 0.0
                self.video_list.update_job(j)

        self._batch_thread = BatchThread(self._jobs, spec, self.folder_picker.folder, self.signals)
        self._batch_thread.start()
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)

    def _cancel_batch(self) -> None:
        if self._batch_thread is not None:
            self._batch_thread.cancel()
            self.statusBar().showMessage("İptal isteniyor…")

    # -----------------------------------------------------------------
    # Signal handlers
    # -----------------------------------------------------------------
    def _on_job_added(self, job: Job) -> None:
        self.video_list.add_job(job)

    def _on_job_updated(self, job: Job) -> None:
        self.video_list.update_job(job)

    def _on_batch_started(self, count: int) -> None:
        self.statusBar().showMessage(f"{count} video işleniyor…")

    def _on_batch_finished(self, completed: int, failed: int, skipped: int) -> None:
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        msg = f"{completed} tamam · {failed} hata · {skipped} atlandı"
        self.statusBar().showMessage(msg)
        notify("Video Extender", msg)
        if failed:
            QMessageBox.information(
                self, "Batch tamamlandı",
                f"{msg}\n\nDetaylı log: output/logs/ klasöründe.",
            )

    def _on_error(self, msg: str) -> None:
        QMessageBox.warning(self, "Hata", msg)

    def _refresh_summary(self) -> None:
        try:
            spec = self._gather_spec()
            self.summary_label.setText(
                f"<b>{len(self._jobs)}</b> video · {self.settings_panel.summary()} · "
                f"{spec.preset_name} · filtreler: {len(spec.filters)}"
            )
        except Exception:  # noqa: BLE001
            self.summary_label.setText("")

    def _run_initial_preflight(self) -> None:
        report = _preflight.run()
        if not report.ok:
            QMessageBox.critical(
                self, "Preflight başarısız",
                "\n".join(report.errors) + "\n\nUygulamayı kullanamazsın.",
            )

"""Main window: ties widgets + worker threads + preflight + run lifecycle."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton, QSplitter,
    QStatusBar, QTabWidget, QVBoxLayout, QWidget,
)

from video_extender.core import config as _config
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

        central = QWidget(self)
        root_layout = QVBoxLayout(central)

        self.folder_picker = FolderPicker()
        root_layout.addWidget(self.folder_picker)
        root_layout.addWidget(self._build_main_splitter(), 1)
        root_layout.addLayout(self._build_action_bar())

        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar(self))

        self._wire_signals()
        self._refresh_summary()
        self._run_initial_preflight()
        # Restore last-used spec + window geometry AFTER preflight so any
        # error dialogs from preflight render first.
        self._restore_settings()

    # -----------------------------------------------------------------
    # UI construction
    # -----------------------------------------------------------------
    def _build_main_splitter(self) -> QSplitter:
        """Middle area: tab stack (left) + video list (right)."""
        splitter = QSplitter(Qt.Orientation.Horizontal)

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
        return splitter

    def _build_action_bar(self) -> QHBoxLayout:
        """Bottom row: summary label + Retry / Cancel / Start buttons."""
        action_row = QHBoxLayout()
        self.summary_label = QLabel("")
        self.retry_btn = QPushButton("Başarısızları Yeniden Dene")
        self.retry_btn.setEnabled(False)
        self.start_btn = QPushButton("Başlat")
        self.start_btn.setMinimumWidth(140)
        self.start_btn.setEnabled(False)
        self.cancel_btn = QPushButton("İptal")
        self.cancel_btn.setEnabled(False)
        action_row.addWidget(self.summary_label, 1)
        action_row.addWidget(self.retry_btn)
        action_row.addWidget(self.cancel_btn)
        action_row.addWidget(self.start_btn)
        return action_row

    def _wire_signals(self) -> None:
        """Connect every widget signal to its MainWindow handler."""
        self.folder_picker.folder_changed.connect(self._on_folder_chosen)

        self.start_btn.clicked.connect(self._start_batch)
        self.cancel_btn.clicked.connect(self._cancel_batch)
        self.retry_btn.clicked.connect(self._retry_failed)

        for panel in (self.settings_panel, self.presets_panel, self.filters_panel):
            panel.changed.connect(self._refresh_summary)
        self.profiles_panel.profile_loaded.connect(lambda _s: self._refresh_summary())

        self.signals.job_added.connect(self._on_job_added)
        self.signals.job_updated.connect(self._on_job_updated)
        self.signals.batch_started.connect(self._on_batch_started)
        self.signals.batch_finished.connect(self._on_batch_finished)
        self.signals.error.connect(self._on_error)

        # Video list row interactions
        self.video_list.cellDoubleClicked.connect(self._on_row_double_clicked)
        self.video_list.row_remove_requested.connect(self._on_remove_row)
        self.video_list.row_retry_requested.connect(self._on_retry_row)

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
            encoder_override=self.settings_panel.encoder_override,
            max_parallel=self.settings_panel.max_parallel,
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
        idx_enc = self.settings_panel.encoder_combo.findData(spec.encoder_override)
        if idx_enc >= 0:
            self.settings_panel.encoder_combo.setCurrentIndex(idx_enc)
        self.settings_panel.parallel_slider.setValue(spec.max_parallel or 0)
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
            if ok != QMessageBox.StandardButton.Yes:
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
        self.retry_btn.setEnabled(False)
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
        self._update_batch_eta()

    def _update_batch_eta(self) -> None:
        """Aggregate per-job ETA into an overall batch ETA shown in the status bar."""
        if not self._jobs:
            return
        running = [j for j in self._jobs if j.status == JobStatus.RUNNING]
        pending = [j for j in self._jobs if j.status in (JobStatus.PENDING, JobStatus.QUEUED)]
        if not running and not pending:
            return
        # Running jobs contribute their reported ETA.
        # Pending jobs estimate using mean speed of running jobs (or 1x fallback)
        # and their own source duration scaled by extender (we use target_duration if known
        # else fall back to source media duration).
        speeds = [j.speed for j in running if j.speed > 0]
        mean_speed = (sum(speeds) / len(speeds)) if speeds else 1.0
        running_eta = sum(j.eta_seconds for j in running) / max(1, len(running))
        pending_remaining = 0.0
        for j in pending:
            est_target = j.target_duration if j.target_duration > 0 else (
                j.media.duration if j.media else 0.0
            )
            pending_remaining += est_target / mean_speed
        # Pending work runs in parallel across available worker slots, but a rough
        # serial sum / num_workers is a decent estimate. We approximate with the
        # number of running jobs as proxy for active workers.
        n_workers = max(1, len(running))
        eta_total = running_eta + (pending_remaining / n_workers)
        from video_extender.gui.widgets.video_list import _format_eta
        completed = sum(1 for j in self._jobs if j.status in (
            JobStatus.COMPLETED, JobStatus.SKIPPED, JobStatus.FAILED, JobStatus.CANCELLED))
        total = len(self._jobs)
        self.statusBar().showMessage(
            f"{completed}/{total} bitti · "
            f"hız ~{mean_speed:.1f}x · toplam kalan ~{_format_eta(eta_total)}"
        )

    def _on_batch_started(self, count: int) -> None:
        self.statusBar().showMessage(f"{count} video işleniyor…")

    def _on_batch_finished(self, completed: int, failed: int, skipped: int) -> None:
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.retry_btn.setEnabled(failed > 0)
        msg = f"{completed} tamam · {failed} hata · {skipped} atlandı"
        self.statusBar().showMessage(msg)
        # Only surface a desktop notification when the batch actually did work.
        # No notify on pure-cancel (completed=failed=0) or zero-job runs — the
        # user already knows they cancelled and doesn't need a tray ping.
        if completed > 0 or failed > 0:
            notify("Video Extender", msg)
        if failed:
            QMessageBox.information(
                self, "Batch tamamlandı",
                f"{msg}\n\nBaşarısızları yeniden denemek için 'Başarısızları Yeniden Dene' "
                f"düğmesi aktif. Detaylı log: output/logs/ klasöründe.",
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

    # -----------------------------------------------------------------
    # Settings persistence (QSettings + last-used JobSpec)
    # -----------------------------------------------------------------
    def _restore_settings(self) -> None:
        s = QSettings("video-extender", "video-extender")
        geom = s.value("window/geometry")
        if geom is not None:
            self.restoreGeometry(geom)
        state = s.value("window/state")
        if state is not None:
            self.restoreState(state)
        spec_json = s.value("spec/last")
        if isinstance(spec_json, str) and spec_json:
            try:
                payload = json.loads(spec_json)
                spec = _config.jobspec_from_dict(payload)
                self._apply_spec(spec)
            except Exception:  # noqa: BLE001
                pass  # malformed prior settings → ignore, use defaults
        last_folder = s.value("folder/last")
        if isinstance(last_folder, str) and last_folder:
            p = Path(last_folder)
            if p.is_dir():
                self.folder_picker._set_folder(p)

    def _save_settings(self) -> None:
        s = QSettings("video-extender", "video-extender")
        s.setValue("window/geometry", self.saveGeometry())
        s.setValue("window/state", self.saveState())
        try:
            spec = self._gather_spec()
            s.setValue("spec/last", json.dumps(_config.jobspec_to_dict(spec), ensure_ascii=False))
        except Exception:  # noqa: BLE001
            pass
        if self.folder_picker.folder is not None:
            s.setValue("folder/last", str(self.folder_picker.folder))

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._batch_thread is not None and self._batch_thread.isRunning():
            running = sum(1 for j in self._jobs if j.status == JobStatus.RUNNING)
            pending = sum(1 for j in self._jobs if j.status in (
                JobStatus.PENDING, JobStatus.QUEUED))
            reply = QMessageBox.question(
                self, "İşlem devam ediyor",
                f"{running} video şu an işleniyor, {pending} tanesi sırada.\n"
                f"Pencereyi kapatırsan tamamlanmamış işler iptal edilecek.\n\n"
                f"Yine de kapat?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._batch_thread.cancel()
            self._batch_thread.wait(3000)
        self._save_settings()
        super().closeEvent(event)

    # -----------------------------------------------------------------
    # Inline ffmpeg log viewer (for failed jobs)
    # -----------------------------------------------------------------
    def _retry_failed(self) -> None:
        """Reset every FAILED job to PENDING and re-run the batch."""
        if self._batch_thread is not None and self._batch_thread.isRunning():
            return
        targets = [j for j in self._jobs if j.status == JobStatus.FAILED]
        if not targets:
            return
        for j in targets:
            self._reset_job_for_retry(j)
        self._start_batch()

    def _on_retry_row(self, source: Path) -> None:
        """Retry a single failed row."""
        if self._batch_thread is not None and self._batch_thread.isRunning():
            QMessageBox.information(
                self, "İşlem devam ediyor",
                "Batch çalışırken yeniden deneme başlatılamaz. Önce bitmesini bekle.",
            )
            return
        job = next((j for j in self._jobs if j.source == source), None)
        if job is None or job.status != JobStatus.FAILED:
            return
        self._reset_job_for_retry(job)
        self._start_batch()

    def _reset_job_for_retry(self, job: Job) -> None:
        job.status = JobStatus.PENDING
        job.progress = 0.0
        job.error = None
        job.speed = 0.0
        job.eta_seconds = 0.0
        job.worker_label = ""
        self.video_list.update_job(job)

    def _on_remove_row(self, source: Path) -> None:
        # Only allow removal when no batch is running.
        if self._batch_thread is not None and self._batch_thread.isRunning():
            QMessageBox.information(
                self, "İşlem devam ediyor",
                "Batch çalışırken video kaldırılamaz. Önce işlemi iptal et.",
            )
            return
        self._jobs = [j for j in self._jobs if j.source != source]
        self.video_list.remove_row_for(source)
        self.start_btn.setEnabled(bool(self._jobs))
        self._refresh_summary()

    def _on_row_double_clicked(self, row: int, _col: int) -> None:
        if row < 0:
            return
        source = next(
            (src for src, r in self.video_list._row_for_source.items() if r == row),
            None,
        )
        if source is None:
            return
        job = next((j for j in self._jobs if j.source == source), None)
        if job is not None:
            self._show_job_log(job)

    def _show_job_log(self, job: Job) -> None:
        # Compose details: status + error + ffmpeg log (if any)
        parts: list[str] = []
        parts.append(f"Dosya:    {job.source}")
        parts.append(f"Çıktı:    {job.output}")
        parts.append(f"Durum:    {job.status.value}")
        if job.error:
            parts.append(f"Hata:     {job.error}")
        parts.append("")
        if job.stderr_log and job.stderr_log.exists():
            try:
                parts.append("──── ffmpeg log ────")
                parts.append(job.stderr_log.read_text(encoding="utf-8", errors="replace"))
            except OSError as exc:
                parts.append(f"(log okunamadı: {exc})")
        else:
            parts.append("(ffmpeg log mevcut değil — job henüz çalışmadı ya da hızlı çıktı.)")

        dlg = QMessageBox(self)
        dlg.setWindowTitle(f"İş detayı — {job.source.name}")
        dlg.setIcon(QMessageBox.Icon.Information)
        dlg.setText(f"<b>{job.source.name}</b> — {job.status.value}")
        dlg.setDetailedText("\n".join(parts))
        # Make the detail box wider/taller
        dlg.setStyleSheet("QTextEdit { min-width: 900px; min-height: 480px; }")
        dlg.exec()

    def _run_initial_preflight(self) -> None:
        report = _preflight.run()
        if not report.ok:
            QMessageBox.critical(
                self, "Preflight başarısız",
                "\n".join(report.errors) + "\n\nUygulamayı kullanamazsın.",
            )

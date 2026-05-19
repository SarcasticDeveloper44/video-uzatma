"""Main window: ties widgets + worker threads + preflight + run lifecycle."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import (
    QAction, QCloseEvent, QGuiApplication, QIcon, QKeySequence, QShortcut,
)
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QMainWindow, QMenu, QMessageBox,
    QPushButton, QSplitter, QStatusBar, QStyle, QSystemTrayIcon, QTabWidget,
    QVBoxLayout, QWidget,
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
from video_extender.utils import logging as _logging
from video_extender.utils.notify import notify

log = _logging.get("gui.main")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Video Extender — Reklam Toplu Uzatıcı")

        self.signals = BatchSignals()
        self._jobs: list[Job] = []
        self._probe_thread: ProbeThread | None = None
        self._batch_thread: BatchThread | None = None
        # `True` once the user has explicitly clicked a preset choice — after
        # that we never override their selection via auto-detection.
        self._user_preset_chosen = False
        self._batch_paused = False

        central = QWidget(self)
        root_layout = QVBoxLayout(central)

        self.folder_picker = FolderPicker()
        root_layout.addWidget(self.folder_picker)
        root_layout.addWidget(self._build_main_splitter(), 1)
        root_layout.addLayout(self._build_action_bar())

        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar(self))

        self._wire_signals()
        self._wire_shortcuts()
        self._setup_tray_icon()
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
        # Status filter combobox above the list so the user can isolate
        # failures / completed / pending without scrolling huge batches.
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Göster:"))
        self.status_filter = QComboBox()
        self.status_filter.addItem("Tümü", None)
        self.status_filter.addItem("Bekleyen", JobStatus.PENDING)
        self.status_filter.addItem("Çalışan", JobStatus.RUNNING)
        self.status_filter.addItem("Tamamlanan", JobStatus.COMPLETED)
        self.status_filter.addItem("Hatalı", JobStatus.FAILED)
        self.status_filter.addItem("Atlanan", JobStatus.SKIPPED)
        self.status_filter.addItem("İptal", JobStatus.CANCELLED)
        self.status_filter.currentIndexChanged.connect(self._apply_status_filter)
        filter_row.addWidget(self.status_filter)
        filter_row.addStretch(1)
        right_layout.addLayout(filter_row)
        right_layout.addWidget(self.video_list, 1)

        splitter.addWidget(self.tabs)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([380, 720])
        return splitter

    def _build_action_bar(self) -> QHBoxLayout:
        """Bottom row: multi-line summary label + Retry / Cancel / Start buttons."""
        action_row = QHBoxLayout()
        self.summary_label = QLabel("")
        # Pre-batch summary spans 3 lines — give it room.
        self.summary_label.setWordWrap(True)
        self.summary_label.setTextFormat(Qt.TextFormat.RichText)
        self.summary_label.setMinimumHeight(60)
        self.retry_btn = QPushButton("Başarısızları Yeniden Dene")
        self.retry_btn.setEnabled(False)
        self.start_btn = QPushButton("Başlat")
        self.start_btn.setMinimumWidth(140)
        self.start_btn.setEnabled(False)
        self.pause_btn = QPushButton("Duraklat")
        self.pause_btn.setEnabled(False)
        self.cancel_btn = QPushButton("İptal")
        self.cancel_btn.setEnabled(False)
        action_row.addWidget(self.summary_label, 1)
        action_row.addWidget(self.retry_btn)
        action_row.addWidget(self.pause_btn)
        action_row.addWidget(self.cancel_btn)
        action_row.addWidget(self.start_btn)
        return action_row

    def _wire_signals(self) -> None:
        """Connect every widget signal to its MainWindow handler."""
        self.folder_picker.folder_changed.connect(self._on_folder_chosen)
        self.folder_picker.files_chosen.connect(self._on_files_chosen)

        self.start_btn.clicked.connect(self._start_batch)
        self.cancel_btn.clicked.connect(self._cancel_batch)
        self.pause_btn.clicked.connect(self._toggle_pause)
        self.retry_btn.clicked.connect(self._retry_failed)

        for panel in (self.settings_panel, self.presets_panel, self.filters_panel):
            panel.changed.connect(self._refresh_summary)
        self.profiles_panel.profile_loaded.connect(lambda _s: self._refresh_summary())
        self.profiles_panel.reset_requested.connect(self._reset_to_defaults)
        # `activated` fires only when the user picks an item, not when we
        # set the combo programmatically — perfect signal for "user override".
        self.presets_panel.combo.activated.connect(self._on_preset_user_picked)

        self.signals.job_added.connect(self._on_job_added)
        self.signals.job_updated.connect(self._on_job_updated)
        self.signals.batch_started.connect(self._on_batch_started)
        self.signals.batch_finished.connect(self._on_batch_finished)
        self.signals.error.connect(self._on_error)

        # Video list row interactions
        self.video_list.cellDoubleClicked.connect(self._on_row_double_clicked)
        self.video_list.row_remove_requested.connect(self._on_remove_row)
        self.video_list.row_retry_requested.connect(self._on_retry_row)
        self.video_list.row_reveal_requested.connect(self._on_reveal_row)
        self.video_list.row_show_log_requested.connect(self._on_show_log_row)
        self.video_list.rows_remove_requested.connect(self._on_remove_rows)
        self.video_list.rows_retry_requested.connect(self._on_retry_rows)
        self.video_list.rows_reveal_requested.connect(self._on_reveal_rows)

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
            meta_mode=self.settings_panel.meta_mode,
            filters=tuple(filters),
            filter_options=opts,
            extender_options=self.settings_panel.extender_options(),
            filename_template=self.settings_panel.filename_template_text,
            audio_fade_out_seconds=self.settings_panel.audio_fade,
            output_dir_override=self.settings_panel.output_dir_override,
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

    def _on_files_chosen(self, files: list[Path]) -> None:
        """User dropped (or picked) one or more video files directly. Skip
        the folder-wide scan; probe only the explicit set."""
        if not files:
            return
        self.video_list.clear_rows()
        self._jobs = []
        spec = self._gather_spec()
        if self._probe_thread and self._probe_thread.isRunning():
            self._probe_thread.requestInterruption()
            self._probe_thread.wait(1000)
        # Source folder for batch I/O is the parent of the first file.
        source_folder = files[0].parent
        t = ProbeThread(source_folder, False, spec, self.signals, explicit_files=files)
        self._probe_thread = t
        t.finished.connect(lambda: self._on_probe_done(t))
        t.start()
        self.statusBar().showMessage(f"{len(files)} video inceleniyor…")

    def _on_probe_done(self, t: ProbeThread) -> None:
        self._jobs = t.jobs
        self.start_btn.setEnabled(bool(self._jobs))
        self.statusBar().showMessage(f"{len(self._jobs)} video hazır.")
        self._auto_pick_preset()
        self._maybe_show_meta_warnings()
        self._refresh_summary()

    def _maybe_show_meta_warnings(self) -> None:
        """When Meta Mode is on, scan probed sources for issues that would
        survive into the output and surface them as a single status dialog.
        Skipped when Meta Mode is off or no jobs probed."""
        if not self.settings_panel.meta_mode or not self._jobs:
            return
        from video_extender.core import compliance as _compliance
        problem_lines: list[str] = []
        for j in self._jobs:
            if j.media is None:
                continue
            report = _compliance.check_source(j.media)
            if report.issues:
                bullets = "\n  ".join(i.message for i in report.issues)
                problem_lines.append(f"• {j.name}:\n  {bullets}")
        if not problem_lines:
            self.statusBar().showMessage(
                "Meta uyumluluk: tüm kaynaklar OK ✓", 5000,
            )
            return
        msg = (
            "Meta Reklam Modu açık. Bazı kaynaklarda dikkat edilmesi gereken "
            "noktalar var (encoder yine çalışacak, ama Meta'ya yüklerken "
            "sorun çıkabilir):\n\n" + "\n\n".join(problem_lines)
        )
        QMessageBox.information(self, "Meta uyumluluk öncesi", msg)

    def _on_preset_user_picked(self, _index: int) -> None:
        """User explicitly chose a preset — disable auto-detection from here on."""
        self._user_preset_chosen = True

    def _auto_pick_preset(self) -> None:
        """Set the preset combo to a sensible default based on the first job's
        aspect ratio. No-op when:
          - user already picked manually in this session,
          - no jobs probed yet,
          - first job's media info isn't readable,
          - the aspect doesn't map to a known preset.
        """
        if self._user_preset_chosen or not self._jobs:
            return
        media = self._jobs[0].media
        if media is None or media.video is None or media.video.height == 0:
            return
        aspect = media.video.width / media.video.height
        # Tolerance bands around common social-media aspects.
        if 0.50 <= aspect <= 0.63:           # 9:16 vertical
            preset_key = "tiktok"
        elif 0.75 <= aspect <= 0.85:         # 4:5 portrait
            preset_key = "ig_feed"
        elif 0.95 <= aspect <= 1.05:         # 1:1 square
            preset_key = "ig_feed"
        elif 1.30 <= aspect <= 1.40:         # 4:3
            preset_key = "yt_long"
        elif 1.70 <= aspect <= 1.85:         # 16:9 widescreen
            preset_key = "yt_long"
        else:
            return  # exotic aspect → don't second-guess the user
        idx = self.presets_panel.combo.findData(preset_key)
        if idx >= 0 and self.presets_panel.combo.currentIndex() != idx:
            self.presets_panel.combo.setCurrentIndex(idx)
            self.statusBar().showMessage(
                f"Preset otomatik: {preset_key} (kaynak {media.video.width}×{media.video.height})"
            )

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
        # Validate extender-specific requirements BEFORE submitting to the
        # batch runner. Mirrors what the CLI does in cli.main(); without
        # this the encode crashes deep inside build_job_command with a
        # ValueError that lands as a per-job FAILED row — far worse UX
        # than a single dialog.
        missing = self._validate_extender_requirements(spec)
        if missing is not None:
            QMessageBox.warning(self, "Eksik alan", missing)
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
        self._batch_paused = False
        self.pause_btn.setText("Duraklat")
        self.start_btn.setEnabled(False)
        self.retry_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.pause_btn.setEnabled(True)

    def _validate_extender_requirements(self, spec: JobSpec) -> str | None:
        """Return a Turkish error string when the chosen extender is missing
        required inputs (image for image_card, outro for intro_outro);
        return None when everything is valid."""
        opts = spec.extender_options or {}
        if spec.extender_name == "image_card":
            image = opts.get("image", "")
            if not image:
                return (
                    "Yöntem 'Bitiş kartı (resim)' seçili ama 'Bitiş kartı' "
                    "alanı boş.\n\nUzatma sekmesinde bir PNG/JPG seç ya da "
                    "yöntemi değiştir."
                )
            if not Path(image).exists():
                return f"Bitiş kartı dosyası bulunamadı:\n{image}"
        elif spec.extender_name == "intro_outro":
            outro = opts.get("outro", "")
            if not outro:
                return (
                    "Yöntem 'Intro/Outro klibi ekle' seçili ama 'Outro klip' "
                    "alanı boş.\n\nUzatma sekmesinde bir video seç (intro "
                    "opsiyonel, outro zorunlu) ya da yöntemi değiştir."
                )
            if not Path(outro).exists():
                return f"Outro klibi bulunamadı:\n{outro}"
            intro = opts.get("intro", "")
            if intro and not Path(intro).exists():
                return f"Intro klibi bulunamadı:\n{intro}"
        return None

    def _cancel_batch(self) -> None:
        if self._batch_thread is not None:
            self._batch_thread.cancel()
            self.statusBar().showMessage("İptal isteniyor…")

    def _toggle_pause(self) -> None:
        """Suspend / resume every running encoder. Unix-only: ffmpeg gets
        SIGSTOP and freezes; SIGCONT unfreezes it. Windows silently no-ops
        (no portable equivalent; would need ctypes NtSuspendProcess).
        """
        if self._batch_thread is None or not self._batch_thread.isRunning():
            return
        if not self._batch_paused:
            paused = self._batch_thread.pause_workers()
            if paused > 0:
                self._batch_paused = True
                self.pause_btn.setText("Devam Et")
                self.statusBar().showMessage(
                    f"Duraklatıldı ({paused} encoder askıda).",
                )
            else:
                QMessageBox.information(
                    self, "Duraklat",
                    "Bu platformda duraklatma desteklenmiyor (Windows: ileride NtSuspendProcess ile).",
                )
        else:
            resumed = self._batch_thread.resume_workers()
            self._batch_paused = False
            self.pause_btn.setText("Duraklat")
            self.statusBar().showMessage(
                f"Devam edildi ({resumed} encoder yeniden çalışıyor).",
            )

    # -----------------------------------------------------------------
    # Signal handlers
    # -----------------------------------------------------------------
    def _on_job_added(self, job: Job) -> None:
        self.video_list.add_job(job)
        self._apply_status_filter()

    def _on_job_updated(self, job: Job) -> None:
        self.video_list.update_job(job)
        self._apply_status_filter()
        self._update_batch_eta()

    def _apply_status_filter(self) -> None:
        """Hide rows whose status doesn't match the filter combo. 'Tümü'
        clears all hidden flags. Called both on combo change and after
        every job update so rows reappear/disappear as state transitions."""
        target = self.status_filter.currentData()
        if target is None:
            for row in range(self.video_list.rowCount()):
                self.video_list.setRowHidden(row, False)
            return
        # Build a status lookup keyed by source for the rows currently shown.
        status_by_source = {j.source: j.status for j in self._jobs}
        for src, row in self.video_list._row_for_source.items():
            self.video_list.setRowHidden(row, status_by_source.get(src) != target)

    def _update_batch_eta(self) -> None:
        """Aggregate per-job ETA into an overall batch ETA.

        Improved heuristic: instead of a flat mean of running speeds we use
        the MAX (fastest) speed as the canonical "per-worker" speed estimate
        — pending jobs almost always land on the fastest available slot
        (longest-job-first scheduling sees to it). Median was too pessimistic
        on mixed GPU+CPU runs where GPU is 5-10x faster.
        """
        if not self._jobs:
            return
        running = [j for j in self._jobs if j.status == JobStatus.RUNNING]
        pending = [j for j in self._jobs if j.status in (JobStatus.PENDING, JobStatus.QUEUED)]
        if not running and not pending:
            return
        speeds = [j.speed for j in running if j.speed > 0]
        mean_speed = (sum(speeds) / len(speeds)) if speeds else 1.0
        # Use max speed for pending-work projection: pending jobs will run on
        # whichever slot frees up next, which is most likely the fastest one
        # currently free (under longest-first scheduling).
        peak_speed = max(speeds, default=mean_speed)
        running_eta = sum(j.eta_seconds for j in running) / max(1, len(running))
        pending_remaining = 0.0
        for j in pending:
            est_target = j.target_duration if j.target_duration > 0 else (
                j.media.duration if j.media else 0.0
            )
            pending_remaining += est_target / peak_speed
        n_workers = max(1, len(running))
        eta_total = running_eta + (pending_remaining / n_workers)
        from video_extender.gui.widgets.video_list import _format_eta
        completed = sum(1 for j in self._jobs if j.status in (
            JobStatus.COMPLETED, JobStatus.SKIPPED, JobStatus.FAILED, JobStatus.CANCELLED))
        total = len(self._jobs)
        self.statusBar().showMessage(
            f"{completed}/{total} bitti · "
            f"hız ~{mean_speed:.1f}x (peak {peak_speed:.1f}x) · "
            f"toplam kalan ~{_format_eta(eta_total)}"
        )

    def _on_batch_started(self, count: int) -> None:
        self.statusBar().showMessage(f"{count} video işleniyor…")

    def _on_batch_finished(self, completed: int, failed: int, skipped: int) -> None:
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.pause_btn.setEnabled(False)
        self.pause_btn.setText("Duraklat")
        self._batch_paused = False
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
        import time
        t0 = time.monotonic()
        try:
            spec = self._gather_spec()
            self.summary_label.setText(self._build_batch_summary_html(spec))
        except Exception:  # noqa: BLE001
            self.summary_label.setText("")
        elapsed_ms = (time.monotonic() - t0) * 1000
        # Anything above ~50 ms shows up as visible lag on settings changes.
        # Log so we have a diagnostic trail if performance regresses later.
        if elapsed_ms > 50:
            log.info("_refresh_summary slow: %.0f ms", elapsed_ms)

    def _build_batch_summary_html(self, spec: JobSpec) -> str:
        """Multi-line pre-batch breakdown rendered as HTML in the summary label.

        Shows: video count, mode/method/quality, preset, output destination,
        total source duration → total target duration, estimated output size,
        filter count + Meta-Mode flag, encoder strategy preview.
        """
        n = len(self._jobs)
        if n == 0:
            return "<i>Klasör veya video sürükle / Seç düğmesine bas.</i>"

        # Line 1: high-level
        line1 = (
            f"<b>{n}</b> video · {self.settings_panel.summary()} · "
            f"preset: <b>{spec.preset_name}</b>"
        )
        if spec.meta_mode:
            line1 += " · <span style='color:#3a8;'>Meta Modu</span>"
        if self.settings_panel.compress_cb.isChecked() and not spec.meta_mode:
            line1 += " · <span style='color:#888;'>Sıkıştır</span>"

        # Line 2: duration + size
        total_src_dur = sum(
            j.media.duration for j in self._jobs if j.media is not None
        )
        from video_extender.core.job import ExtendMode
        total_out_dur = sum(
            (j.media.duration + spec.extend_seconds if spec.extend_mode == ExtendMode.ADD
             else max(j.media.duration, spec.extend_seconds))
            for j in self._jobs if j.media is not None
        )
        size_hint = self._estimate_total_output_size(spec) or "—"
        line2 = (
            f"<small>Süre toplam: {self._format_minutes(total_src_dur)} kaynak "
            f"→ {self._format_minutes(total_out_dur)} çıktı · "
            f"Boyut: <b>{size_hint}</b></small>"
        )

        # Line 3: output destination + filter + encoder strategy
        if spec.output_dir_override:
            out_dst = spec.output_dir_override
        elif self.folder_picker.folder is not None:
            out_dst = f"{self.folder_picker.folder}/{spec.output_subdir}/"
        else:
            out_dst = "(önce kaynak seç)"
        encoder_hint = self._encoder_strategy_hint(spec, n)
        line3 = (
            f"<small>Çıktı: {out_dst} · {len(spec.filters)} filtre · {encoder_hint}</small>"
        )

        return f"{line1}<br>{line2}<br>{line3}"

    @staticmethod
    def _format_minutes(seconds: float) -> str:
        if seconds < 60:
            return f"{int(seconds)}sn"
        m = seconds / 60
        if m < 60:
            return f"{m:.1f}dk"
        h = m / 60
        return f"{h:.1f}sa"

    def _encoder_strategy_hint(self, spec: JobSpec, n_jobs: int) -> str:
        """Best-effort one-line description of the scheduler's plan."""
        try:
            from video_extender.core.hardware import detect
            from video_extender.core.scheduler import plan
            sched = plan(
                n_jobs, hw=detect(), codec=spec.video_codec,
                encoder_override=spec.encoder_override,
                max_parallel_override=spec.max_parallel,
                probe_gpu=False,
            )
            gpu_count = len(sched.gpu_slots)
            cpu_count = len(sched.cpu_slots)
            parts: list[str] = []
            if gpu_count:
                # All GPU slots share an encoder; show the first one.
                enc = sched.gpu_slots[0].encoder
                parts.append(f"{gpu_count}× {enc}")
            if cpu_count:
                enc = sched.cpu_slots[0].encoder
                parts.append(f"{cpu_count}× {enc}")
            return "Worker'lar: " + (" + ".join(parts) if parts else "—")
        except Exception:  # noqa: BLE001
            return ""

    def _estimate_total_output_size(self, spec: JobSpec) -> str:
        """Rough output-size estimate. The formula is intentionally
        conservative — real encoders go BELOW these numbers on static
        content (freeze tails, black, image cards) because constant frames
        compress to near-zero bitrate. We label the result with ≤ to make
        the upper-bound nature explicit, and apply per-extender + per-codec
        + per-quality factors calibrated against real ad workloads.

        Empirical reference points (TikTok medium preset, 30 min output):
          H.264 standard         → ~1.1 GB
          HEVC standard          → ~550 MB
          HEVC + freeze tail     → ~280 MB (the static tail barely takes
                                            any bitrate, dominated by the
                                            small original moving portion)
          HEVC + compress + low  → ~180 MB
        """
        if not self._jobs:
            return ""
        try:
            params = PRESET_REGISTRY[spec.preset_name].for_quality(spec.quality)
        except KeyError:
            return ""

        # Calibrated codec efficiency factors against H.264 (lower = smaller).
        codec_factor = {
            "h264": 1.0,
            "hevc": 0.55,   # libx265 in CRF mode lands around 50-60% of H.264
            "av1":  0.40,
            "vp9":  0.55,
        }.get(spec.video_codec, 1.0)

        # Static-tail extenders barely consume bitrate because the encoder
        # detects constant frame content and drops the rate floor. Applies
        # to the EXTENSION portion only — source content still encodes
        # at full preset bitrate.
        static_tail_factor = {
            "freeze":     0.10,  # last-frame held → nearly free
            "black":      0.05,  # solid color → free-er
            "image_card": 0.08,  # still image → free-er
            "loop":       1.00,  # full-motion content, no discount
            "intro_outro": 1.00,
        }.get(spec.extender_name, 1.0)

        # Compress toggle additionally tightens the rate via CRF + low quality.
        compress_factor = 0.6 if self.settings_panel.compress_cb.isChecked() else 1.0

        v_bps = params.bitrate_kbps * 1000 * codec_factor * compress_factor
        a_bps = params.audio_bitrate_kbps * 1000
        total_bytes = 0.0
        for j in self._jobs:
            if j.media is None:
                continue
            src_dur = j.media.duration
            if spec.extend_mode == ExtendMode.ADD:
                tail_dur = max(0.0, spec.extend_seconds)
            else:
                tail_dur = max(0.0, spec.extend_seconds - src_dur)
            # Source portion encodes at full bitrate; tail portion at the
            # static-content discount when the extender produces static frames.
            total_bytes += (src_dur * v_bps) + (tail_dur * v_bps * static_tail_factor)
            total_bytes += (src_dur + tail_dur) * a_bps
        total_bytes /= 8
        if total_bytes <= 0:
            return ""
        mb = total_bytes / (1024 * 1024)
        if mb < 1024:
            return f"≤ {mb:.0f} MB tahmini çıktı"
        return f"≤ {mb / 1024:.1f} GB tahmini çıktı"

    # -----------------------------------------------------------------
    # Settings persistence (QSettings + last-used JobSpec)
    # -----------------------------------------------------------------
    def _restore_settings(self) -> None:
        s = QSettings("video-extender", "video-extender")
        geom = s.value("window/geometry")
        if geom is not None:
            self.restoreGeometry(geom)
            # Sanity-check: a saved geometry can place the window off-screen
            # (different monitor setup, scaling changed, hibernate quirk).
            # If the restored rect is outside every available screen, ignore
            # it and use the construction-time default (1100x720 centered).
            if not self._geometry_visible_on_any_screen():
                log.warning(
                    "Saved geometry (%dx%d at %d,%d) falls off all screens — "
                    "resetting to default.", self.width(), self.height(),
                    self.x(), self.y(),
                )
                self.resize(1100, 720)
                # Move to top-left of primary screen as a safe default.
                screen = QGuiApplication.primaryScreen()
                if screen is not None:
                    geo = screen.availableGeometry()
                    self.move(geo.x() + 100, geo.y() + 100)
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

    def _geometry_visible_on_any_screen(self) -> bool:
        """Whether the current window geometry overlaps any available screen."""
        win_rect = self.geometry()
        if win_rect.width() <= 0 or win_rect.height() <= 0:
            return False
        for screen in QGuiApplication.screens():
            if screen.availableGeometry().intersects(win_rect):
                return True
        return False

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        log.info("Pencere kapatma isteği alındı (closeEvent).")
        # Tray-resident mode: hide instead of accepting close. Real quit
        # comes from the tray menu's 'Çık' (which calls _quit_from_tray).
        # Skip this path when a batch is running — the user should see the
        # 'still working' confirmation dialog before the app vanishes.
        batch_running = (
            self._batch_thread is not None and self._batch_thread.isRunning()
        )
        if self._tray is not None and self._tray.isVisible() and not batch_running:
            log.info("Tray aktif — pencere tray'e gizleniyor; "
                     "tam çıkış için tray menüsünden Çık'ı kullan.")
            self.hide()
            event.ignore()
            return
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

    def _on_remove_rows(self, sources: list[Path]) -> None:
        """Bulk: remove every pending/queued row in the selection."""
        if self._batch_thread is not None and self._batch_thread.isRunning():
            QMessageBox.information(
                self, "İşlem devam ediyor",
                "Batch çalışırken video kaldırılamaz. Önce işlemi iptal et.",
            )
            return
        target_sources = {
            j.source for j in self._jobs
            if j.source in sources and j.status in (JobStatus.PENDING, JobStatus.QUEUED)
        }
        if not target_sources:
            return
        self._jobs = [j for j in self._jobs if j.source not in target_sources]
        for s in target_sources:
            self.video_list.remove_row_for(s)
        self.start_btn.setEnabled(bool(self._jobs))
        self._refresh_summary()

    def _on_retry_rows(self, sources: list[Path]) -> None:
        """Bulk: reset every FAILED row in the selection and re-run the batch."""
        if self._batch_thread is not None and self._batch_thread.isRunning():
            QMessageBox.information(
                self, "İşlem devam ediyor",
                "Batch çalışırken yeniden deneme başlatılamaz. Önce bitmesini bekle.",
            )
            return
        targets = [
            j for j in self._jobs
            if j.source in sources and j.status == JobStatus.FAILED
        ]
        if not targets:
            return
        for j in targets:
            self._reset_job_for_retry(j)
        self._start_batch()

    def _on_reveal_rows(self, sources: list[Path]) -> None:
        """Bulk: reveal the output of every completed row in the selection.
        We only launch the file manager ONCE (per common parent dir) to
        avoid spamming."""
        from video_extender.utils.paths import reveal_in_file_manager
        completed = [
            j for j in self._jobs
            if j.source in sources and j.status == JobStatus.COMPLETED
            and j.output is not None and j.output.exists()
        ]
        if not completed:
            return
        # Group by output parent dir; reveal one representative per dir.
        seen: set[Path] = set()
        for j in completed:
            assert j.output is not None
            parent = j.output.parent
            if parent in seen:
                continue
            seen.add(parent)
            reveal_in_file_manager(j.output)

    def _on_reveal_row(self, source: Path) -> None:
        """Right-click → 'Çıktıyı klasörde göster' on a completed/skipped row."""
        job = next((j for j in self._jobs if j.source == source), None)
        if job is None or job.output is None or not job.output.exists():
            QMessageBox.information(
                self, "Çıktı yok",
                "Bu video için çıktı dosyası henüz oluşmamış.",
            )
            return
        from video_extender.utils.paths import reveal_in_file_manager
        if not reveal_in_file_manager(job.output):
            QMessageBox.warning(
                self, "Dosya yöneticisi açılamadı",
                f"OS'in dosya yöneticisi başlatılamadı.\n\nÇıktı yolu:\n{job.output}",
            )

    def _on_show_log_row(self, source: Path) -> None:
        """Right-click → 'ffmpeg log'unu göster'."""
        job = next((j for j in self._jobs if j.source == source), None)
        if job is not None:
            self._show_job_log(job)

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
        if job is None:
            return
        # UX: most useful default is to reveal the produced output in the OS
        # file manager when the job is done. For other states the ffmpeg
        # log is the right tool (debugging in-progress / failed jobs).
        if (job.status == JobStatus.COMPLETED
                and job.output is not None and job.output.exists()):
            from video_extender.utils.paths import reveal_in_file_manager
            if reveal_in_file_manager(job.output):
                return
            # Fallback: file manager launch failed (very rare) — fall through
            # to the log dialog so the user still sees something.
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

    def _setup_tray_icon(self) -> None:
        """Add a system tray icon with show/hide + quit. When the tray is
        available we switch the app to *tray-resident* mode: closing the
        main window hides it (rather than quitting), and Qt's default
        "quit when last window closes" is disabled so a hidden window
        doesn't tear the whole app down. The only real quit path becomes
        tray menu → 'Çık'.

        This also defends against an obscure failure mode reported in
        the wild: on some compositors the WM briefly hid/closed the main
        window during startup. With quitOnLastWindowClosed = True (Qt's
        default) the app would silently exit — looking like "GUI kendi
        kendine kapanıyor". With this fix the worst case is the window
        going to tray; the app survives until the user explicitly quits.
        """
        self._tray: QSystemTrayIcon | None = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            log.info("System tray bulunamadı; tray-mode kapalı.")
            return
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.setQuitOnLastWindowClosed(False)
        icon: QIcon = self.style().standardIcon(
            QStyle.StandardPixmap.SP_MediaPlay,
        )
        tray = QSystemTrayIcon(icon, self)
        tray.setToolTip("Video Extender")
        menu = QMenu(self)
        show_action = QAction("Göster / Gizle", self)
        show_action.triggered.connect(self._toggle_window_visibility)
        quit_action = QAction("Çık", self)
        quit_action.triggered.connect(self._quit_from_tray)
        menu.addAction(show_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        tray.setContextMenu(menu)
        tray.activated.connect(self._on_tray_activated)
        tray.show()
        self._tray = tray
        log.info("Tray-mode aktif: X butonu pencereyi tray'e gizler, "
                 "tam çıkış sadece tray menüsünden.")

    def _toggle_window_visibility(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self.showNormal()
            self.raise_()
            self.activateWindow()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        # Single click on the tray icon toggles window visibility (Trigger
        # on X11/Windows, DoubleClick on macOS).
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._toggle_window_visibility()

    def _quit_from_tray(self) -> None:
        """Tray menu → Çık. Real exit, bypasses the close-to-tray check."""
        log.info("Tray'den Çık seçildi — uygulama kapatılıyor.")
        if self._batch_thread is not None and self._batch_thread.isRunning():
            self._batch_thread.cancel()
            self._batch_thread.wait(3000)
        self._save_settings()
        if self._tray is not None:
            self._tray.hide()
            self._tray = None  # ensures closeEvent won't try to hide-to-tray
        # Close all windows and quit the QApplication event loop.
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _wire_shortcuts(self) -> None:
        """Power-user keyboard bindings.
          Ctrl+O — open folder/file picker
          F5     — re-probe current folder (refresh)
          Esc    — cancel running batch
          Ctrl+R — retry all failed
          Delete — remove selected pending rows
          Ctrl+S — save profile, Ctrl+L — load profile
        """
        shortcuts: list[tuple[str, object]] = [
            ("Ctrl+O", self.folder_picker._pick),
            ("F5", self._refresh_folder),
            ("Esc", self._cancel_batch),
            ("Ctrl+R", self._retry_failed),
            ("Delete", self._delete_selected_rows),
            ("Ctrl+S", self.profiles_panel._save),
            ("Ctrl+L", self.profiles_panel._load),
        ]
        for key, slot in shortcuts:
            sc = QShortcut(QKeySequence(key), self)
            sc.activated.connect(slot)

    def _refresh_folder(self) -> None:
        """F5 shortcut: re-probe the current source. Pulls jobs back from disk."""
        if self.folder_picker.folder is not None and not (
            self._batch_thread is not None and self._batch_thread.isRunning()
        ):
            self._on_folder_chosen(self.folder_picker.folder)

    def _delete_selected_rows(self) -> None:
        """Delete shortcut: remove every pending/queued selected row."""
        selected = self.video_list._selected_sources()
        if selected:
            self._on_remove_rows(selected)

    def _reset_to_defaults(self) -> None:
        """Wipe QSettings + restore every panel to factory defaults.

        Used when settings get into a confused state (corrupt QSettings file,
        user wants to start fresh, etc.). Asks for confirmation; the action
        cannot be undone.
        """
        if self._batch_thread is not None and self._batch_thread.isRunning():
            QMessageBox.information(
                self, "İşlem devam ediyor",
                "Bir batch çalışırken sıfırlama yapılamaz. Önce iptal et.",
            )
            return
        reply = QMessageBox.question(
            self, "Varsayılana Döndür",
            "Tüm ayarlar, son seçili klasör, pencere geometrisi ve son spec "
            "sıfırlanacak.\nBu işlem geri alınamaz. Devam edilsin mi?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # 1) Wipe persisted QSettings (window geometry, last spec, last folder).
        qs = QSettings("video-extender", "video-extender")
        qs.clear()
        qs.sync()

        # 2) Reset SettingsPanel defaults (mirrors widget construction defaults).
        sp = self.settings_panel
        sp.duration_input.setValue(30)
        sp.unit_combo.setCurrentText("dakika")
        sp.add_radio.setChecked(True)
        freeze_idx = sp.method_combo.findData("freeze")
        if freeze_idx >= 0:
            sp.method_combo.setCurrentIndex(freeze_idx)
        sp.quality_combo.setCurrentText("medium")
        sp.codec_combo.setCurrentIndex(0)  # h264
        sp.compress_cb.setChecked(False)
        sp.meta_mode_cb.setChecked(False)
        sp.encoder_combo.setCurrentIndex(0)  # auto
        sp.parallel_slider.setValue(0)  # auto
        sp.fade_spin.setValue(1.5)
        sp.filename_template.setText("{name}_extended.{ext}")
        sp.output_dir_input.setText("")
        sp.intro_path.setText("")
        sp.outro_path.setText("")
        sp.endcard_path.setText("")

        # 3) PresetsPanel → tiktok.
        tt_idx = self.presets_panel.combo.findData("tiktok")
        if tt_idx >= 0:
            self.presets_panel.combo.setCurrentIndex(tt_idx)

        # 4) FiltersPanel defaults.
        fp = self.filters_panel
        fp.normalize_cb.setChecked(True)
        fp.strip_cb.setChecked(True)
        fp.final_fade_cb.setChecked(False)
        fp.wm_cb.setChecked(False)
        fp.wm_path.setText("")
        fp.wm_position.setCurrentText("bottom-right")
        fp.wm_opacity.setValue(0.8)
        fp.subs_cb.setChecked(False)
        fp.subs_path.setText("")
        fp.subs_font_size.setValue(24)
        fp.aspect_cb.setChecked(False)
        fp.aspect_target.setCurrentIndex(0)
        fp.aspect_mode.setCurrentText("blur_pad")
        fp.cg_cb.setChecked(False)
        fp.cg_brightness.setValue(0.0)
        fp.cg_contrast.setValue(1.0)
        fp.cg_saturation.setValue(1.0)
        fp.cg_gamma.setValue(1.0)

        # 5) Clear current job list + folder selection.
        self._jobs = []
        self.video_list.clear_rows()
        self.status_filter.setCurrentIndex(0)  # "Tümü"
        self.folder_picker._folder = None
        self.folder_picker.path_label.setText(
            "<i>Klasör veya video dosyalarını buraya sürükle — ya da seç düğmelerini kullan.</i>"
        )
        self.folder_picker.recursive_cb.setChecked(False)

        # 6) Reset window geometry + auto-preset memory to defaults.
        self.resize(1100, 720)
        self._user_preset_chosen = False

        self._refresh_summary()
        self.statusBar().showMessage("Ayarlar varsayılana döndürüldü.")

    def _run_initial_preflight(self) -> None:
        report = _preflight.run()
        if not report.ok:
            QMessageBox.critical(
                self, "Preflight başarısız",
                "\n".join(report.errors) + "\n\nUygulamayı kullanamazsın.",
            )

"""GUI widget interaction tests (offscreen Qt)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytestmark = pytest.mark.gui

PySide6 = pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication  # noqa: E402

from video_extender.core.job import ExtendMode  # noqa: E402
from video_extender.gui.widgets.filters_panel import FiltersPanel  # noqa: E402
from video_extender.gui.widgets.folder_picker import FolderPicker  # noqa: E402
from video_extender.gui.widgets.hardware_info import HardwareInfoWidget  # noqa: E402
from video_extender.gui.widgets.presets_panel import PresetsPanel  # noqa: E402
from video_extender.gui.widgets.settings_panel import SettingsPanel  # noqa: E402
from video_extender.gui.widgets.video_list import VideoListWidget  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class TestSettingsPanel:
    def test_seconds_conversion(self, qapp) -> None:
        sp = SettingsPanel()
        sp.duration_input.setValue(30)
        sp.unit_combo.setCurrentText("dakika")
        assert sp.extend_seconds == 1800
        sp.unit_combo.setCurrentText("saat")
        sp.duration_input.setValue(2)
        assert sp.extend_seconds == 7200

    def test_mode_radios(self, qapp) -> None:
        sp = SettingsPanel()
        assert sp.extend_mode == ExtendMode.ADD
        sp.fill_radio.setChecked(True)
        assert sp.extend_mode == ExtendMode.FILL

    def test_codec_dropdown(self, qapp) -> None:
        sp = SettingsPanel()
        assert sp.video_codec == "h264"
        sp.codec_combo.setCurrentIndex(1)
        assert sp.video_codec == "hevc"

    def test_default_codec_is_most_compatible(self, qapp) -> None:
        """Fresh-install default MUST be H.264 (universal compatibility).
        HEVC requires opt-in via dropdown or --codec hevc."""
        sp = SettingsPanel()
        # First combo item is the default
        assert sp.codec_combo.itemData(0) == "h264"
        assert "uyumlu" in sp.codec_combo.itemText(0).lower()
        assert sp.video_codec == "h264"

    def test_default_quality_is_medium(self, qapp) -> None:
        sp = SettingsPanel()
        assert sp.quality == "medium"

    def test_default_encoder_override_is_auto(self, qapp) -> None:
        """Default encoder is 'Otomatik' → None → scheduler auto-picks."""
        sp = SettingsPanel()
        assert sp.encoder_override is None
        assert sp.encoder_combo.itemData(0) is None

    def test_encoder_override_default_auto(self, qapp) -> None:
        sp = SettingsPanel()
        assert sp.encoder_override is None  # "Otomatik" = first item

    def test_max_parallel_auto_vs_explicit(self, qapp) -> None:
        sp = SettingsPanel()
        # Default: slider at 0 → None (auto)
        assert sp.max_parallel is None
        sp.parallel_slider.setValue(4)
        assert sp.max_parallel == 4

    def test_compress_toggle_overrides_codec_and_quality(self, qapp) -> None:
        """Compress checkbox pins codec=hevc and quality=low regardless of
        what the underlying combos say."""
        sp = SettingsPanel()
        sp.quality_combo.setCurrentText("high")
        sp.codec_combo.setCurrentIndex(0)  # h264
        # Without compress: returns what combos say
        assert sp.video_codec == "h264"
        assert sp.quality == "high"
        # With compress: overrides both
        sp.compress_cb.setChecked(True)
        assert sp.video_codec == "hevc"
        assert sp.quality == "low"
        # Unchecking restores the underlying choice
        sp.compress_cb.setChecked(False)
        assert sp.video_codec == "h264"
        assert sp.quality == "high"

    def test_extender_options_built(self, qapp) -> None:
        sp = SettingsPanel()
        sp.outro_path.setText("/x/outro.mp4")
        sp.endcard_path.setText("/y/card.png")
        opts = sp.extender_options()
        assert opts["outro"] == "/x/outro.mp4"
        assert opts["image"] == "/y/card.png"
        assert "intro" not in opts


class TestPresetsPanel:
    def test_preset_switching(self, qapp) -> None:
        pp = PresetsPanel()
        # All real preset keys should be selectable
        for key in ("tiktok", "ig_reels", "yt_shorts", "linkedin_feed"):
            idx = pp.combo.findData(key)
            assert idx >= 0, f"preset {key} not in dropdown"
            pp.combo.setCurrentIndex(idx)
            assert pp.preset_key == key


class TestFiltersPanel:
    def test_default_chain(self, qapp) -> None:
        fp = FiltersPanel()
        fp.normalize_cb.setChecked(True)
        fp.strip_cb.setChecked(True)
        names, _ = fp.build_filter_chain()
        assert "audio_normalize" in names
        assert "metadata_strip" in names

    def test_subtitle_burn_in_chain(self, qapp, tmp_path) -> None:
        fp = FiltersPanel()
        srt = tmp_path / "x.srt"
        srt.write_text("1\n00:00:00,500 --> 00:00:01,500\nx\n")
        fp.subs_cb.setChecked(True)
        fp.subs_path.setText(str(srt))
        names, opts = fp.build_filter_chain()
        assert "subtitle_burn" in names
        assert opts["subtitle_burn"]["file"] == str(srt)

    def test_color_grade_in_chain(self, qapp) -> None:
        fp = FiltersPanel()
        fp.cg_cb.setChecked(True)
        fp.cg_brightness.setValue(0.2)
        names, opts = fp.build_filter_chain()
        assert "color_grade" in names
        assert opts["color_grade"]["brightness"] == 0.2

    def test_color_grade_skipped_if_defaults(self, qapp) -> None:
        fp = FiltersPanel()
        fp.cg_cb.setChecked(True)
        # All defaults → should not appear in chain (no-op)
        names, _ = fp.build_filter_chain()
        assert "color_grade" not in names

    def test_aspect_first_in_chain(self, qapp) -> None:
        fp = FiltersPanel()
        fp.aspect_cb.setChecked(True)
        fp.normalize_cb.setChecked(True)
        fp.strip_cb.setChecked(True)
        names, _ = fp.build_filter_chain()
        # aspect_convert must come first
        assert names[0] == "aspect_convert"


class TestVideoList:
    def test_add_and_update_job(self, qapp, vertical_3s) -> None:
        from video_extender.core.job import Job, JobStatus
        from video_extender.core.probe import probe_file

        vl = VideoListWidget()
        media = probe_file(vertical_3s)
        job = Job(source=vertical_3s, media=media, status=JobStatus.PENDING)
        vl.add_job(job)
        assert vl.rowCount() == 1
        assert vl.item(0, 2).text() == "720×1280"
        job.progress = 0.42
        job.status = JobStatus.RUNNING
        vl.update_job(job)
        bar = vl.cellWidget(0, 4)
        assert bar.value() == 42

    def test_remove_row_reindexes(self, qapp, vertical_3s, tmp_path) -> None:
        from video_extender.core.job import Job, JobStatus
        from video_extender.core.probe import probe_file

        vl = VideoListWidget()
        media = probe_file(vertical_3s)
        a = tmp_path / "a.mp4"
        a.write_bytes(vertical_3s.read_bytes())
        b = tmp_path / "b.mp4"
        b.write_bytes(vertical_3s.read_bytes())
        c = tmp_path / "c.mp4"
        c.write_bytes(vertical_3s.read_bytes())
        for p in (a, b, c):
            vl.add_job(Job(source=p, media=media, status=JobStatus.PENDING))
        assert vl.rowCount() == 3
        # Remove middle row
        assert vl.remove_row_for(b)
        assert vl.rowCount() == 2
        # c should now be at row 1 (was 2)
        assert vl._row_for_source[c] == 1
        assert vl._row_for_source[a] == 0

    def test_remove_row_signal(self, qapp, vertical_3s) -> None:
        from video_extender.core.job import Job, JobStatus
        from video_extender.core.probe import probe_file

        vl = VideoListWidget()
        media = probe_file(vertical_3s)
        job = Job(source=vertical_3s, media=media, status=JobStatus.PENDING)
        vl.add_job(job)
        received = []
        vl.row_remove_requested.connect(lambda p: received.append(p))
        # Emit directly (testing menu trigger end-to-end requires Qt event loop)
        vl.row_remove_requested.emit(vertical_3s)
        assert received == [vertical_3s]


class TestProbeThread:
    def test_probe_thread_processes_folder(self, qapp, vertical_3s, tmp_path) -> None:
        from video_extender.core.job import ExtendMode, JobSpec
        from video_extender.gui.workers import BatchSignals, ProbeThread

        # Stage 2 copies so ProbeThread has work to do
        a = tmp_path / "a.mp4"
        a.write_bytes(vertical_3s.read_bytes())
        b = tmp_path / "b.mp4"
        b.write_bytes(vertical_3s.read_bytes())

        signals = BatchSignals()
        spec = JobSpec(extend_seconds=1.0, extend_mode=ExtendMode.ADD,
                       extender_name="freeze", preset_name="tiktok", quality="medium")
        t = ProbeThread(tmp_path, recursive=False, spec=spec, signals=signals)
        t.start()
        t.wait(10000)
        # Signals are queued and require an event loop to deliver; we just
        # verify the thread finished and populated its job list.
        assert not t.isRunning()
        assert len(t.jobs) == 2
        assert all(j.media is not None for j in t.jobs)

    def test_probe_thread_interruptible(self, qapp, vertical_3s, tmp_path) -> None:
        from video_extender.core.job import ExtendMode, JobSpec
        from video_extender.gui.workers import BatchSignals, ProbeThread

        # Create many files so interruption likely hits before completion
        for i in range(20):
            f = tmp_path / f"v{i}.mp4"
            f.write_bytes(vertical_3s.read_bytes())

        signals = BatchSignals()
        spec = JobSpec(extend_seconds=1.0, extend_mode=ExtendMode.ADD,
                       extender_name="freeze", preset_name="tiktok", quality="medium")
        t = ProbeThread(tmp_path, recursive=False, spec=spec, signals=signals)
        t.start()
        t.requestInterruption()
        t.wait(10000)
        # Thread exited cleanly; may have probed a subset before checking interruption.
        assert not t.isRunning()
        assert len(t.jobs) <= 20


class TestRetryFailed:
    def test_main_window_retry_button_enables_after_failure(
        self, qapp, vertical_3s, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            "video_extender.gui.main_window._preflight.run",
            lambda **_: __import__("video_extender.core.preflight",
                                   fromlist=["PreflightReport"]).PreflightReport(),
        )
        # Modal dialogs are auto-stubbed by conftest._stub_modals fixture.
        from video_extender.core.job import Job, JobStatus
        from video_extender.core.probe import probe_file
        from video_extender.gui.main_window import MainWindow

        w = MainWindow()
        media = probe_file(vertical_3s)
        ok_job = Job(source=tmp_path / "ok.mp4", media=media, status=JobStatus.COMPLETED)
        fail_job = Job(source=tmp_path / "bad.mp4", media=media,
                       status=JobStatus.FAILED, error="boom")
        w._jobs = [ok_job, fail_job]
        w.video_list.add_job(ok_job)
        w.video_list.add_job(fail_job)

        assert w.retry_btn.isEnabled() is False
        w._on_batch_finished(1, 1, 0)
        assert w.retry_btn.isEnabled() is True
        w.close()

    def test_reset_job_for_retry_clears_state(self, qapp, vertical_3s) -> None:
        from video_extender.core.job import Job, JobStatus
        from video_extender.core.probe import probe_file
        from video_extender.gui.main_window import MainWindow

        # Avoid preflight modal dialogs
        import video_extender.core.preflight as pf
        pf.run = lambda **_: pf.PreflightReport()

        w = MainWindow()
        media = probe_file(vertical_3s)
        job = Job(
            source=vertical_3s, media=media,
            status=JobStatus.FAILED, progress=0.4, error="ffmpeg exit 1",
            speed=5.0, eta_seconds=120.0, worker_label="GPU#0",
        )
        w._jobs = [job]
        w.video_list.add_job(job)
        w._reset_job_for_retry(job)
        assert job.status == JobStatus.PENDING
        assert job.progress == 0.0
        assert job.error is None
        assert job.speed == 0.0
        assert job.eta_seconds == 0.0
        assert job.worker_label == ""
        w.close()


class TestHardwareInfoWidget:
    def test_renders(self, qapp) -> None:
        hi = HardwareInfoWidget()
        assert hi.layout().count() > 0


class TestFolderPicker:
    def test_set_folder_signal(self, qapp, tmp_path) -> None:
        fp = FolderPicker()
        received = []
        fp.folder_changed.connect(lambda p: received.append(p))
        fp._set_folder(tmp_path)
        assert fp.folder == tmp_path
        assert received == [tmp_path]

    def test_set_files_emits_signal(self, qapp, tmp_path, vertical_3s) -> None:
        """Dropping or picking explicit files emits files_chosen, not folder_changed."""
        # Stage real video files so they pass the is_video() check
        f1 = tmp_path / "a.mp4"
        f1.write_bytes(vertical_3s.read_bytes())
        f2 = tmp_path / "b.mp4"
        f2.write_bytes(vertical_3s.read_bytes())
        fp = FolderPicker()
        files_received = []
        folder_received = []
        fp.files_chosen.connect(lambda lst: files_received.append(lst))
        fp.folder_changed.connect(lambda p: folder_received.append(p))
        fp._set_files([f1, f2])
        assert len(files_received) == 1
        assert files_received[0] == [f1, f2]
        assert folder_received == []  # folder signal NOT emitted for file drops
        # The internal _folder is set to parent for downstream output dir use
        assert fp.folder == tmp_path
        # Label reflects multi-file selection
        assert "2 video" in fp.path_label.text()

    def test_set_files_single_video_label(self, qapp, tmp_path, vertical_3s) -> None:
        f = tmp_path / "only.mp4"
        f.write_bytes(vertical_3s.read_bytes())
        fp = FolderPicker()
        fp._set_files([f])
        assert "only.mp4" in fp.path_label.text()

    def test_empty_files_no_signal(self, qapp) -> None:
        fp = FolderPicker()
        received = []
        fp.files_chosen.connect(lambda lst: received.append(lst))
        fp._set_files([])
        assert received == []


class TestSettingsPersistence:
    """MainWindow saves/restores last-used spec and window state via QSettings.
    QSettings auto-isolated by conftest._isolate_qsettings fixture."""

    def test_spec_roundtrip(self, qapp, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(
            "video_extender.gui.main_window._preflight.run",
            lambda **_: __import__("video_extender.core.preflight",
                                   fromlist=["PreflightReport"]).PreflightReport(),
        )
        from video_extender.gui.main_window import MainWindow

        # 1) Configure a window and save its settings
        w1 = MainWindow()
        w1.settings_panel.duration_input.setValue(45)
        w1.settings_panel.unit_combo.setCurrentText("dakika")
        w1.settings_panel.method_combo.setCurrentIndex(
            w1.settings_panel.method_combo.findData("black")
        )
        w1.settings_panel.codec_combo.setCurrentIndex(1)  # hevc
        w1.presets_panel.combo.setCurrentIndex(
            w1.presets_panel.combo.findData("ig_reels")
        )
        w1._save_settings()
        w1.close()

        # 2) New window should auto-restore
        w2 = MainWindow()
        w2._restore_settings()
        assert w2.settings_panel.extend_seconds == 45 * 60
        assert w2.settings_panel.method == "black"
        assert w2.settings_panel.video_codec == "hevc"
        assert w2.presets_panel.preset_key == "ig_reels"
        w2.close()


class TestAutoPreset:
    def test_vertical_video_picks_tiktok(self, qapp, vertical_3s, monkeypatch) -> None:
        """A 720x1280 vertical clip should auto-pick the TikTok preset."""
        monkeypatch.setattr(
            "video_extender.gui.main_window._preflight.run",
            lambda **_: __import__("video_extender.core.preflight",
                                   fromlist=["PreflightReport"]).PreflightReport(),
        )
        from video_extender.core.job import Job, JobStatus
        from video_extender.core.probe import probe_file
        from video_extender.gui.main_window import MainWindow

        w = MainWindow()
        # Force preset to something non-TikTok to verify auto-pick changes it
        idx = w.presets_panel.combo.findData("yt_long")
        w.presets_panel.combo.setCurrentIndex(idx)
        # Stage a vertical job
        media = probe_file(vertical_3s)
        w._jobs = [Job(source=vertical_3s, media=media, status=JobStatus.PENDING)]
        w._auto_pick_preset()
        assert w.presets_panel.preset_key == "tiktok"
        w.close()

    def test_user_choice_sticks(self, qapp, vertical_3s, monkeypatch) -> None:
        """Once user clicks the preset combo, auto-pick must not override."""
        monkeypatch.setattr(
            "video_extender.gui.main_window._preflight.run",
            lambda **_: __import__("video_extender.core.preflight",
                                   fromlist=["PreflightReport"]).PreflightReport(),
        )
        from video_extender.core.job import Job, JobStatus
        from video_extender.core.probe import probe_file
        from video_extender.gui.main_window import MainWindow

        w = MainWindow()
        # Simulate user picking yt_long manually
        w._on_preset_user_picked(0)
        idx = w.presets_panel.combo.findData("yt_long")
        w.presets_panel.combo.setCurrentIndex(idx)
        # Then a vertical job lands
        media = probe_file(vertical_3s)
        w._jobs = [Job(source=vertical_3s, media=media, status=JobStatus.PENDING)]
        w._auto_pick_preset()
        # User choice respected — still yt_long
        assert w.presets_panel.preset_key == "yt_long"
        w.close()


class TestResetToDefaults:
    def test_reset_clears_all_panels(self, qapp, tmp_path, monkeypatch) -> None:
        """Reset must restore every panel to factory defaults."""
        monkeypatch.setattr(
            "video_extender.gui.main_window._preflight.run",
            lambda **_: __import__("video_extender.core.preflight",
                                   fromlist=["PreflightReport"]).PreflightReport(),
        )
        from video_extender.gui.main_window import MainWindow
        w = MainWindow()
        # Mutate panels to non-default state
        w.settings_panel.duration_input.setValue(99)
        w.settings_panel.unit_combo.setCurrentText("saat")
        w.settings_panel.codec_combo.setCurrentIndex(1)  # hevc
        w.filters_panel.wm_cb.setChecked(True)
        w.filters_panel.wm_path.setText("/tmp/x.png")
        w.filters_panel.aspect_cb.setChecked(True)
        w.filters_panel.cg_cb.setChecked(True)
        w.filters_panel.cg_brightness.setValue(0.5)

        # Trigger reset (modal is auto-stubbed to Yes by conftest)
        w._reset_to_defaults()

        # All settings should be back to defaults
        assert w.settings_panel.duration_input.value() == 30
        assert w.settings_panel.unit_combo.currentText() == "dakika"
        assert w.settings_panel.video_codec == "h264"
        assert not w.filters_panel.wm_cb.isChecked()
        assert w.filters_panel.wm_path.text() == ""
        assert not w.filters_panel.aspect_cb.isChecked()
        assert not w.filters_panel.cg_cb.isChecked()
        assert w.filters_panel.cg_brightness.value() == 0.0
        assert w.presets_panel.preset_key == "tiktok"
        # Folder cleared
        assert w.folder_picker.folder is None
        # Jobs cleared
        assert w._jobs == []
        assert w.video_list.rowCount() == 0
        w.close()

    def test_reset_blocked_during_batch(self, qapp, vertical_3s, monkeypatch) -> None:
        """Reset must refuse to run while a batch is in progress."""
        monkeypatch.setattr(
            "video_extender.gui.main_window._preflight.run",
            lambda **_: __import__("video_extender.core.preflight",
                                   fromlist=["PreflightReport"]).PreflightReport(),
        )
        from video_extender.gui.main_window import MainWindow
        w = MainWindow()
        # Simulate a running batch — closeEvent will call .cancel() on it
        # when w.close() runs, so the fake must satisfy that protocol too.
        class FakeThread:
            def isRunning(self): return True
            def cancel(self): pass
            def wait(self, _timeout=0): pass
        w._batch_thread = FakeThread()  # type: ignore[assignment]
        # Mutate one setting
        w.settings_panel.duration_input.setValue(99)
        # Reset attempts → should be blocked (modal stub returns Ok = no action taken)
        w._reset_to_defaults()
        # Setting should still be 99 (not reset)
        assert w.settings_panel.duration_input.value() == 99
        # Detach the fake thread before close so closeEvent doesn't dispatch
        # cancel/wait on a non-real thread.
        w._batch_thread = None
        w.close()


class TestRowDoubleClick:
    def test_double_click_failed_job_shows_log(self, qapp, vertical_3s, tmp_path, monkeypatch) -> None:
        """Double-clicking a row should resolve to the underlying Job."""
        monkeypatch.setattr(
            "video_extender.gui.main_window._preflight.run",
            lambda **_: __import__("video_extender.core.preflight",
                                   fromlist=["PreflightReport"]).PreflightReport(),
        )
        from video_extender.core.job import Job, JobStatus
        from video_extender.core.probe import probe_file
        from video_extender.gui.main_window import MainWindow

        w = MainWindow()
        media = probe_file(vertical_3s)
        job = Job(source=vertical_3s, media=media, status=JobStatus.FAILED,
                  error="test error")
        w._jobs = [job]
        w.video_list.add_job(job)

        # Mock the dialog so test doesn't hang
        shown: list = []
        monkeypatch.setattr(w, "_show_job_log", lambda j: shown.append(j))

        w._on_row_double_clicked(0, 0)
        assert shown == [job]
        w.close()

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


class TestSettingsPersistence:
    """MainWindow saves/restores last-used spec and window state via QSettings."""

    def _isolated_settings(self, tmp_path):
        """Redirect QSettings storage to a tmp dir so tests don't pollute user settings."""
        from PySide6.QtCore import QCoreApplication, QSettings
        QCoreApplication.setOrganizationName("video-extender-test")
        QCoreApplication.setApplicationName("video-extender-test")
        QSettings.setDefaultFormat(QSettings.IniFormat)
        QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
        return QSettings("video-extender", "video-extender")

    def test_spec_roundtrip(self, qapp, tmp_path, monkeypatch) -> None:
        self._isolated_settings(tmp_path)
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

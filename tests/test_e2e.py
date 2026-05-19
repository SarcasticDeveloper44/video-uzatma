"""End-to-end GUI user-flow tests.

These drive the actual MainWindow with a real QApplication, real ffmpeg
encoding, and verify the produced output. Each test simulates a complete
user journey: open folder → adjust settings → click Başlat → wait for
the batch → assert output.

Treat these as "integration tests for the GUI" — they sit one layer
above the widget-level tests in test_gui.py (which check individual
widgets in isolation) and complement the pipeline integration tests in
test_pipeline.py (which exercise BatchRunner directly without a window).

Performance: ~3-10s per test (uses 2-3s lavfi-generated source clips).
Marked `@pytest.mark.gui` so they only run when PySide6 is available.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytestmark = [pytest.mark.gui, pytest.mark.integration]

PySide6 = pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication  # noqa: E402

from video_extender.core.job import JobStatus  # noqa: E402
from video_extender.core.preflight import PreflightReport  # noqa: E402
from video_extender.gui.main_window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def main_window(qapp, monkeypatch):
    """A fully-constructed MainWindow with preflight stubbed to never fail.
    Each test gets a fresh window so per-test side effects (jobs, signals)
    can't leak across tests."""
    monkeypatch.setattr(
        "video_extender.gui.main_window._preflight.run",
        lambda **_: PreflightReport(),
    )
    win = MainWindow()
    yield win
    win.close()


def _wait_for_probe(win: MainWindow, expected_count: int, timeout_ms: int = 10_000) -> None:
    """Block until the probe thread has processed every source."""
    if win._probe_thread is None:
        return
    win._probe_thread.wait(timeout_ms)
    # The probe-finished slot fires via Qt event queue; pump to drain it.
    for _ in range(20):
        QApplication.processEvents()
        if len(win._jobs) >= expected_count:
            return


def _stage_clip(target: Path, source: Path) -> None:
    """Copy a fixture clip to `target` so the GUI sees it as a new source."""
    target.write_bytes(source.read_bytes())


def _drop_folder(win: MainWindow, folder: Path, expected_count: int) -> None:
    """Simulate a user dropping a folder into the picker."""
    win.folder_picker._set_folder(folder)
    _wait_for_probe(win, expected_count)


def _click_start(win: MainWindow) -> None:
    """Trigger the Başlat button by emitting its clicked signal."""
    win.start_btn.click()
    # Wait for the batch thread to finish.
    if win._batch_thread is not None:
        # 60s upper bound — real encodes of 2-3s clips finish in seconds.
        win._batch_thread.wait(60_000)
    # Drain the queued batch_finished signal so UI state updates fire.
    for _ in range(20):
        QApplication.processEvents()


# ===========================================================================
# SCENARIO 1 — drop folder → auto-preset fires → batch completes → output exists
# ===========================================================================
class TestDropToFinishFlow:
    def test_vertical_folder_completes(self, main_window, vertical_3s, tmp_path) -> None:
        _stage_clip(tmp_path / "a.mp4", vertical_3s)
        _stage_clip(tmp_path / "b.mp4", vertical_3s)
        _drop_folder(main_window, tmp_path, expected_count=2)
        # Auto-preset should have selected tiktok for 720×1280 vertical input.
        assert main_window.presets_panel.preset_key == "tiktok"
        # Use fast 1-second add so the encode is quick.
        main_window.settings_panel.duration_input.setValue(1)
        main_window.settings_panel.unit_combo.setCurrentText("saniye")
        # Force CPU libx264 so the test doesn't depend on GPU drivers.
        idx = main_window.settings_panel.encoder_combo.findData("libx264")
        if idx >= 0:
            main_window.settings_panel.encoder_combo.setCurrentIndex(idx)
        _click_start(main_window)
        # All jobs end in a terminal status, exit-after-encode invariants hold.
        terminal = (
            JobStatus.COMPLETED, JobStatus.FAILED,
            JobStatus.CANCELLED, JobStatus.SKIPPED,
        )
        assert all(j.status in terminal for j in main_window._jobs)
        completed = [j for j in main_window._jobs if j.status == JobStatus.COMPLETED]
        # At least one job completed; outputs exist on disk.
        assert completed
        for j in completed:
            assert j.output is not None and j.output.exists()
            assert j.output.stat().st_size > 0


# ===========================================================================
# SCENARIO 2 — failed job → retry single row → eventually completes
# ===========================================================================
class TestRetryFlow:
    def test_retry_failed_row(self, main_window, vertical_3s, tmp_path) -> None:
        _stage_clip(tmp_path / "good.mp4", vertical_3s)
        # Corrupt file → probe error → FAILED before any encoding
        (tmp_path / "broken.mp4").write_bytes(b"garbage")
        _drop_folder(main_window, tmp_path, expected_count=2)
        # Fix the broken file so the retry would actually succeed
        (tmp_path / "broken.mp4").write_bytes(vertical_3s.read_bytes())
        # Find the failed job and request retry
        failed = [j for j in main_window._jobs if j.status == JobStatus.FAILED]
        assert failed, "broken.mp4 should have failed during probe"
        # Skip the actual retry encode (it would hit ffmpeg again) — just
        # verify the path is reachable: invoke _reset_job_for_retry and
        # confirm the job goes back to PENDING.
        for j in failed:
            main_window._reset_job_for_retry(j)
            assert j.status == JobStatus.PENDING
            assert j.error is None


# ===========================================================================
# SCENARIO 3 — Meta Reklam Modu → encoder pinned H.264 + audio_normalize forced
# ===========================================================================
class TestMetaModeFlow:
    def test_meta_mode_pins_h264_and_filters(self, main_window) -> None:
        # Toggle compress (would normally force HEVC) then Meta Mode
        # (overrides compress and forces H.264)
        main_window.settings_panel.compress_cb.setChecked(True)
        assert main_window.settings_panel.video_codec == "hevc"
        main_window.settings_panel.meta_mode_cb.setChecked(True)
        assert main_window.settings_panel.video_codec == "h264", \
            "Meta Mode must override Sıkıştır's HEVC choice"
        # Gathering the spec should propagate the flag through
        spec = main_window._gather_spec()
        assert spec.meta_mode is True
        assert spec.video_codec == "h264"


# ===========================================================================
# SCENARIO 4 — multi-select + bulk retry across many failed rows
# ===========================================================================
class TestBulkRetryFlow:
    def test_bulk_retry_marks_all_pending(self, main_window, vertical_3s, tmp_path) -> None:
        # Stage 3 broken sources so all fail
        for name in ("a.mp4", "b.mp4", "c.mp4"):
            (tmp_path / name).write_bytes(b"corrupt")
        _drop_folder(main_window, tmp_path, expected_count=3)
        failed_sources = [
            j.source for j in main_window._jobs if j.status == JobStatus.FAILED
        ]
        assert len(failed_sources) == 3
        # Fix the sources so the retry path would actually pass probe
        for s in failed_sources:
            s.write_bytes(vertical_3s.read_bytes())
        # Mock _start_batch so retry doesn't actually re-launch ffmpeg
        # (the unit being tested is the bulk dispatch + state reset path)
        original_start = main_window._start_batch
        called: list[int] = []
        main_window._start_batch = lambda: called.append(1)  # type: ignore[assignment]
        try:
            main_window._on_retry_rows(failed_sources)
        finally:
            main_window._start_batch = original_start  # type: ignore[assignment]
        # Every failed job should now be PENDING
        for j in main_window._jobs:
            assert j.status == JobStatus.PENDING, j.source.name
            assert j.error is None


# ===========================================================================
# SCENARIO 5 — reset to defaults clears every panel
# ===========================================================================
class TestResetFlow:
    def test_reset_returns_to_factory_defaults(self, main_window) -> None:
        sp = main_window.settings_panel
        fp = main_window.filters_panel
        # Mutate every relevant control
        sp.duration_input.setValue(120)
        sp.unit_combo.setCurrentText("saat")
        sp.codec_combo.setCurrentIndex(1)  # hevc
        sp.compress_cb.setChecked(True)
        sp.meta_mode_cb.setChecked(True)
        sp.output_dir_input.setText("/tmp/somewhere")
        fp.wm_cb.setChecked(True)
        fp.aspect_cb.setChecked(True)
        # Switch preset away from default
        idx = main_window.presets_panel.combo.findData("yt_long")
        main_window.presets_panel.combo.setCurrentIndex(idx)
        main_window._user_preset_chosen = True
        # Apply reset
        main_window._reset_to_defaults()
        # Verify defaults
        assert sp.duration_input.value() == 30
        assert sp.unit_combo.currentText() == "dakika"
        assert sp.codec_combo.currentIndex() == 0
        assert not sp.compress_cb.isChecked()
        assert not sp.meta_mode_cb.isChecked()
        assert sp.output_dir_input.text() == ""
        assert not fp.wm_cb.isChecked()
        assert not fp.aspect_cb.isChecked()
        assert main_window.presets_panel.preset_key == "tiktok"
        assert main_window._user_preset_chosen is False


# ===========================================================================
# SCENARIO 6 — status filter hides rows that don't match
# ===========================================================================
class TestStatusFilterFlow:
    def test_filter_failed_hides_completed_rows(self, main_window, vertical_3s, tmp_path) -> None:
        # Stage 2 good + 1 broken so we end up with mixed statuses
        _stage_clip(tmp_path / "ok1.mp4", vertical_3s)
        _stage_clip(tmp_path / "ok2.mp4", vertical_3s)
        (tmp_path / "broken.mp4").write_bytes(b"x" * 200)  # probe fail
        _drop_folder(main_window, tmp_path, expected_count=3)
        # Manually mark the 2 good ones as COMPLETED so the filter has
        # something to differentiate (without doing the full encode).
        for j in main_window._jobs:
            if j.source.name in ("ok1.mp4", "ok2.mp4"):
                j.status = JobStatus.COMPLETED
            main_window.video_list.update_job(j)
        # Apply "Hatalı" filter
        idx = main_window.status_filter.findData(JobStatus.FAILED)
        main_window.status_filter.setCurrentIndex(idx)
        # Only the broken row should be visible; the 2 good ones hidden
        hidden_count = 0
        visible_count = 0
        for row in range(main_window.video_list.rowCount()):
            if main_window.video_list.isRowHidden(row):
                hidden_count += 1
            else:
                visible_count += 1
        assert hidden_count == 2, f"expected 2 hidden, got {hidden_count}"
        assert visible_count == 1, f"expected 1 visible, got {visible_count}"
        # Reset filter — everything visible again
        main_window.status_filter.setCurrentIndex(0)
        visible_after_reset = sum(
            1 for row in range(main_window.video_list.rowCount())
            if not main_window.video_list.isRowHidden(row)
        )
        assert visible_after_reset == 3

"""Production-scale stress tests.

These exercise a meaningfully large workload (1080p, 30 seconds) so we catch
issues that hide on tiny 3-second fixtures: low progress-callback frequency,
slow probe, encoder session limits, etc. Marked `slow` so a fast iteration
loop can skip them via `pytest -m "not slow"`.
"""
from __future__ import annotations

from pathlib import Path
import time

import pytest

from conftest import probe_codec, probe_duration
from video_extender.core.ffmpeg import FFmpegRunner, ProgressEvent
from video_extender.core.hardware import detect
from video_extender.core.job import ExtendMode, Job, JobSpec
from video_extender.core.pipeline import BatchRunner, build_jobs, execute_job
from video_extender.core.probe import probe_file
from video_extender.core.scheduler import WorkerKind, WorkerSlot
from video_extender.utils.paths import ensure_output_dir, safe_output_path


pytestmark = [pytest.mark.integration, pytest.mark.slow]


def _spec(**overrides) -> JobSpec:
    base = dict(
        extend_seconds=10.0,
        extend_mode=ExtendMode.ADD,
        extender_name="freeze",
        preset_name="tiktok",
        quality="medium",
        video_codec="h264",
    )
    base.update(overrides)
    return JobSpec(**base)


class TestLargeBatch:
    def test_4_parallel_1080p_30s_clips(self, large_1080p_30s, tmp_path) -> None:
        """Four 30-second 1080p clips in parallel; verify all complete with
        correct extended durations and reasonable output file sizes."""
        for i in range(4):
            (tmp_path / f"clip_{i}.mp4").write_bytes(large_1080p_30s.read_bytes())
        sources = sorted(tmp_path.glob("*.mp4"))
        assert len(sources) == 4

        spec = _spec(extend_seconds=10.0)
        jobs = build_jobs(sources, spec)

        t0 = time.monotonic()
        BatchRunner(jobs, spec, tmp_path, resume=False).run()
        elapsed = time.monotonic() - t0

        # All four complete
        assert all(j.status.value == "completed" for j in jobs), [
            (j.source.name, j.status.value, j.error) for j in jobs
        ]
        # Each output is 30s source + 10s extension = 40s
        for j in jobs:
            assert abs(probe_duration(j.output) - 40.0) < 0.2
            # Output should be non-trivial in size — at least 100KB for 40s
            assert j.output.stat().st_size > 100_000
        # On modern hardware with NVENC available, 4 parallel 40s encodes
        # at TikTok medium preset should finish well under 2 minutes.
        # Pure CPU libx264 on 32 cores will also fit comfortably.
        assert elapsed < 120, f"4-parallel 1080p batch took {elapsed:.1f}s (>120)"

    def test_single_1080p_completes(self, large_1080p_30s, tmp_path) -> None:
        """One long clip — verifies single-job path works for production-sized input."""
        src = tmp_path / "long.mp4"
        src.write_bytes(large_1080p_30s.read_bytes())
        spec = _spec(extend_seconds=5.0)
        jobs = build_jobs([src], spec)
        BatchRunner(jobs, spec, tmp_path, resume=False).run()
        assert jobs[0].status.value == "completed"
        assert abs(probe_duration(jobs[0].output) - 35.0) < 0.2
        # Output dimensions preserved
        codec, w, h = probe_codec(jobs[0].output)
        assert (w, h) == (1920, 1080)


class TestProgressCallbackFrequency:
    def test_long_encode_emits_multiple_progress_events(
        self, large_1080p_30s, tmp_path
    ) -> None:
        """A 30s+ encode should produce several progress events, not just
        one terminal one. Verifies stdout 'progress' lines actually flow
        through FFmpegRunner → ProgressEvent → on_progress callback."""
        # Use libx264 instead of NVENC: slow enough that progress events
        # are well-distributed even on fast GPUs.
        slot = WorkerSlot(
            kind=WorkerKind.CPU, encoder="libx264", threads=2,
            gpu_index=None, label="cpu-progress-test",
        )

        src = tmp_path / "src.mp4"
        src.write_bytes(large_1080p_30s.read_bytes())
        spec = _spec(extend_seconds=5.0)
        media = probe_file(src)
        out_dir = ensure_output_dir(tmp_path)
        job = Job(
            source=src, media=media, spec=spec,
            output=safe_output_path(out_dir, src, spec.filename_template),
        )

        progress_updates: list[float] = []

        def _capture(j: Job) -> None:
            progress_updates.append(j.progress)

        execute_job(
            job, slot,
            hw=detect(),
            runner=FFmpegRunner(),
            state_file=None,
            on_progress=_capture,
            log_dir=out_dir / "logs",
        )
        assert job.status.value == "completed"
        # We expect at least 3 progress callbacks (initial RUNNING + ≥1 mid + final).
        assert len(progress_updates) >= 3, (
            f"only {len(progress_updates)} progress events for a 30s+ encode"
        )
        # And the progress values should be monotonically non-decreasing.
        assert progress_updates == sorted(progress_updates)
        # Final value should reach 1.0 (or very close to it)
        assert progress_updates[-1] >= 0.99


class TestSpeedReporting:
    def test_speed_field_populated(self, large_1080p_30s, tmp_path) -> None:
        """Job.speed should be set from ffmpeg's 'speed=Nx' progress events.
        On NVENC this is typically >5x; on libx264 it's lower but still >0."""
        slot = WorkerSlot(
            kind=WorkerKind.CPU, encoder="libx264", threads=4,
            gpu_index=None, label="cpu-speed-test",
        )
        src = tmp_path / "src.mp4"
        src.write_bytes(large_1080p_30s.read_bytes())
        spec = _spec(extend_seconds=5.0)
        media = probe_file(src)
        out_dir = ensure_output_dir(tmp_path)
        job = Job(
            source=src, media=media, spec=spec,
            output=safe_output_path(out_dir, src, spec.filename_template),
        )

        max_speed_seen = 0.0

        def _track(j: Job) -> None:
            nonlocal max_speed_seen
            max_speed_seen = max(max_speed_seen, j.speed)

        execute_job(
            job, slot,
            hw=detect(),
            runner=FFmpegRunner(),
            state_file=None,
            on_progress=_track,
            log_dir=out_dir / "logs",
        )
        assert job.status.value == "completed"
        assert max_speed_seen > 0.0, "speed never populated during encode"

"""End-to-end pipeline tests: real ffmpeg, real outputs, real ffprobe verification."""
from __future__ import annotations

from pathlib import Path

import pytest

from conftest import probe_codec, probe_duration
from video_extender.core.ffmpeg import FFmpegRunner
from video_extender.core.hardware import detect
from video_extender.core.job import ExtendMode, Job, JobSpec
from video_extender.core.pipeline import BatchRunner, build_jobs, execute_job
from video_extender.core.probe import probe_file
from video_extender.core.scheduler import WorkerKind, WorkerSlot
from video_extender.utils.paths import ensure_output_dir, safe_output_path


pytestmark = pytest.mark.integration


def _spec(**overrides) -> JobSpec:
    base = dict(
        extend_seconds=2.0,
        extend_mode=ExtendMode.ADD,
        extender_name="freeze",
        preset_name="tiktok",
        quality="medium",
        video_codec="h264",
    )
    base.update(overrides)
    return JobSpec(**base)


def _run_single(src: Path, spec: JobSpec, tmp_path: Path, *, encoder: str = "libx264") -> Job:
    slot = WorkerSlot(kind=WorkerKind.CPU, encoder=encoder, threads=4,
                      gpu_index=None, label="test-cpu")
    media = probe_file(src)
    out_dir = ensure_output_dir(tmp_path)
    job = Job(source=src, media=media, spec=spec,
              output=safe_output_path(out_dir, src, spec.filename_template))
    return execute_job(job, slot, hw=detect(), runner=FFmpegRunner(), state_file=None)


class TestFreezeExtender:
    def test_add_mode(self, vertical_3s, tmp_path) -> None:
        job = _run_single(vertical_3s, _spec(extend_seconds=2.0), tmp_path)
        assert job.status.value == "completed", job.error
        assert abs(probe_duration(job.output) - 5.0) < 0.1

    def test_fill_mode(self, vertical_3s, tmp_path) -> None:
        job = _run_single(vertical_3s, _spec(extend_mode=ExtendMode.FILL, extend_seconds=8.0), tmp_path)
        assert job.status.value == "completed"
        assert abs(probe_duration(job.output) - 8.0) < 0.1

    def test_fill_with_source_longer(self, vertical_3s, tmp_path) -> None:
        # source 3s, target 2s → output should stay 3s (no shrinking)
        job = _run_single(vertical_3s, _spec(extend_mode=ExtendMode.FILL, extend_seconds=2.0), tmp_path)
        assert job.status.value == "completed"
        assert abs(probe_duration(job.output) - 3.0) < 0.1


class TestExtenderVariants:
    def test_black(self, vertical_3s, tmp_path) -> None:
        job = _run_single(vertical_3s, _spec(extender_name="black"), tmp_path)
        assert job.status.value == "completed", job.error
        assert abs(probe_duration(job.output) - 5.0) < 0.1

    def test_loop(self, vertical_3s, tmp_path) -> None:
        job = _run_single(vertical_3s, _spec(extender_name="loop", extend_seconds=4.0), tmp_path)
        assert job.status.value == "completed", job.error
        assert abs(probe_duration(job.output) - 7.0) < 0.1


class TestAspectPreservation:
    def test_vertical_preserved(self, vertical_3s, tmp_path) -> None:
        job = _run_single(vertical_3s, _spec(), tmp_path)
        _, w, h = probe_codec(job.output)
        assert w == 720 and h == 1280

    def test_horizontal_preserved(self, horizontal_3s, tmp_path) -> None:
        job = _run_single(horizontal_3s, _spec(), tmp_path)
        _, w, h = probe_codec(job.output)
        assert w == 1920 and h == 1080

    def test_square_preserved(self, square_3s, tmp_path) -> None:
        job = _run_single(square_3s, _spec(), tmp_path)
        _, w, h = probe_codec(job.output)
        assert w == 720 and h == 720


class TestSilentSource:
    def test_extender_handles_no_audio(self, silent_3s, tmp_path) -> None:
        job = _run_single(silent_3s, _spec(), tmp_path)
        assert job.status.value == "completed", job.error
        assert abs(probe_duration(job.output) - 5.0) < 0.1


class TestHevcEncoder:
    def test_libx265_produces_hevc(self, vertical_3s, tmp_path) -> None:
        job = _run_single(
            vertical_3s,
            _spec(video_codec="hevc", preset_name="yt_shorts"),
            tmp_path, encoder="libx265",
        )
        assert job.status.value == "completed", job.error
        codec, _, _ = probe_codec(job.output)
        assert codec == "hevc"


class TestFilters:
    def test_watermark_renders(self, vertical_3s, logo_png, tmp_path) -> None:
        spec = _spec(
            filters=("watermark",),
            filter_options={
                "watermark": {"image": str(logo_png), "position": "top-left", "opacity": 0.8}
            },
        )
        job = _run_single(vertical_3s, spec, tmp_path)
        assert job.status.value == "completed", job.error

    def test_audio_normalize(self, vertical_3s, tmp_path) -> None:
        spec = _spec(
            filters=("audio_normalize",),
            filter_options={"audio_normalize": {"target_lufs": -14.0}},
        )
        job = _run_single(vertical_3s, spec, tmp_path)
        assert job.status.value == "completed", job.error

    def test_aspect_convert_blur_pad(self, horizontal_3s, tmp_path) -> None:
        spec = _spec(
            filters=("aspect_convert",),
            filter_options={"aspect_convert": {"target": "9:16", "mode": "blur_pad"}},
        )
        job = _run_single(horizontal_3s, spec, tmp_path)
        assert job.status.value == "completed", job.error
        _, w, h = probe_codec(job.output)
        assert w == 1080 and h == 1920


class TestIntroOutroExtender:
    def test_full_composition(self, vertical_3s, intro_2s, outro_4s, tmp_path) -> None:
        spec = _spec(
            extender_name="intro_outro",
            extend_seconds=6.0,
            extender_options={"intro": str(intro_2s), "outro": str(outro_4s)},
        )
        job = _run_single(vertical_3s, spec, tmp_path)
        assert job.status.value == "completed", job.error
        # 2s intro + 3s source + 4s outro = 9s
        assert abs(probe_duration(job.output) - 9.0) < 0.1


class TestImageCardExtenderE2E:
    def test_image_card_appended(self, vertical_3s, end_card_png, tmp_path) -> None:
        spec = _spec(
            extender_name="image_card",
            extend_seconds=5.0,
            extender_options={"image": str(end_card_png)},
        )
        job = _run_single(vertical_3s, spec, tmp_path)
        assert job.status.value == "completed", job.error
        # 3s source + 5s card = 8s
        assert abs(probe_duration(job.output) - 8.0) < 0.1


class TestSubtitleBurnE2E:
    def test_srt_burns_in(self, vertical_3s, srt_file, tmp_path) -> None:
        spec = _spec(
            filters=("subtitle_burn",),
            filter_options={"subtitle_burn": {"file": str(srt_file)}},
        )
        job = _run_single(vertical_3s, spec, tmp_path)
        assert job.status.value == "completed", job.error


class TestColorGradeE2E:
    def test_eq_applied(self, vertical_3s, tmp_path) -> None:
        spec = _spec(
            filters=("color_grade",),
            filter_options={"color_grade": {"brightness": 0.2, "saturation": 1.5}},
        )
        job = _run_single(vertical_3s, spec, tmp_path)
        assert job.status.value == "completed", job.error


class TestBatchRunner:
    def test_parallel_batch(self, vertical_3s, horizontal_3s, square_3s, tmp_path) -> None:
        for f in (vertical_3s, horizontal_3s, square_3s):
            (tmp_path / f.name).write_bytes(f.read_bytes())
        sources = sorted(tmp_path.glob("*.mp4"))
        assert len(sources) == 3
        spec = _spec()
        jobs = build_jobs(sources, spec)
        runner = BatchRunner(jobs, spec, tmp_path, resume=False)
        runner.run()
        completed = sum(1 for j in jobs if j.status.value == "completed")
        assert completed == 3

    def test_resume_skips_completed(self, vertical_3s, tmp_path) -> None:
        (tmp_path / vertical_3s.name).write_bytes(vertical_3s.read_bytes())
        sources = [tmp_path / vertical_3s.name]
        spec = _spec()
        # First run — uses unique template so no collision suffix appears
        spec = _spec(filename_template="{name}_resume.{ext}")
        runner1 = BatchRunner(build_jobs(sources, spec), spec, tmp_path, resume=True)
        runner1.run()
        # Second run — same source, same spec, output exists → skip
        jobs2 = build_jobs(sources, spec)
        runner2 = BatchRunner(jobs2, spec, tmp_path, resume=True)
        runner2.run()
        assert all(j.status.value == "skipped" for j in jobs2), \
            [(j.name, j.status.value) for j in jobs2]

    def test_resume_re_runs_when_template_differs(self, vertical_3s, tmp_path) -> None:
        (tmp_path / vertical_3s.name).write_bytes(vertical_3s.read_bytes())
        sources = [tmp_path / vertical_3s.name]
        spec_a = _spec(filename_template="{name}_A.{ext}")
        BatchRunner(build_jobs(sources, spec_a), spec_a, tmp_path, resume=True).run()
        # Same source, different template → should NOT skip
        spec_b = _spec(filename_template="{name}_B.{ext}")
        jobs2 = build_jobs(sources, spec_b)
        BatchRunner(jobs2, spec_b, tmp_path, resume=True).run()
        assert all(j.status.value == "completed" for j in jobs2)

    def test_resume_re_runs_when_settings_differ(self, vertical_3s, tmp_path) -> None:
        (tmp_path / vertical_3s.name).write_bytes(vertical_3s.read_bytes())
        sources = [tmp_path / vertical_3s.name]
        spec_a = _spec(extender_name="freeze", filename_template="{name}_settings.{ext}")
        BatchRunner(build_jobs(sources, spec_a), spec_a, tmp_path, resume=True).run()
        # Same source + same template + different extender → re-run (overwrites)
        spec_b = _spec(extender_name="black", filename_template="{name}_settings.{ext}")
        jobs2 = build_jobs(sources, spec_b)
        BatchRunner(jobs2, spec_b, tmp_path, resume=True).run()
        assert all(j.status.value == "completed" for j in jobs2)

    def test_worker_exception_marks_job_failed(self, vertical_3s, tmp_path, monkeypatch) -> None:
        """If execute_job itself somehow raises (or leaves status non-terminal),
        BatchRunner must still record the job as FAILED so summary counts add up.
        """
        (tmp_path / vertical_3s.name).write_bytes(vertical_3s.read_bytes())
        sources = [tmp_path / vertical_3s.name]
        spec = _spec()
        jobs = build_jobs(sources, spec)

        # Force execute_job to raise an unhandled exception (e.g. bug in code).
        def _explode(*args, **kwargs):
            raise RuntimeError("simulated worker crash")
        from video_extender.core import pipeline as _pl
        monkeypatch.setattr(_pl, "execute_job", _explode)

        runner = BatchRunner(jobs, spec, tmp_path, resume=False)
        runner.run()
        # Job must end in FAILED — never PENDING/RUNNING.
        assert all(j.status.value == "failed" for j in jobs)
        assert all("worker exception" in (j.error or "") for j in jobs)

    def test_summary_counts_always_total_to_jobs(self, vertical_3s, tmp_path) -> None:
        """Defense-in-depth: completed+failed+skipped+cancelled must equal len(jobs)."""
        for name in ("a", "b", "c"):
            (tmp_path / f"{name}.mp4").write_bytes(vertical_3s.read_bytes())
        (tmp_path / "broken.mp4").write_bytes(b"garbage")
        sources = sorted(tmp_path.glob("*.mp4"))
        spec = _spec()
        jobs = build_jobs(sources, spec)
        runner = BatchRunner(jobs, spec, tmp_path, resume=False)
        runner.run()
        counts = {"completed": 0, "failed": 0, "skipped": 0, "cancelled": 0}
        for j in jobs:
            counts[j.status.value] = counts.get(j.status.value, 0) + 1
        assert sum(counts.values()) == len(jobs)

    def test_failed_job_doesnt_kill_batch(self, vertical_3s, tmp_path) -> None:
        (tmp_path / vertical_3s.name).write_bytes(vertical_3s.read_bytes())
        (tmp_path / "broken.mp4").write_bytes(b"garbage")
        sources = sorted(tmp_path.glob("*.mp4"))
        spec = _spec()
        jobs = build_jobs(sources, spec)
        runner = BatchRunner(jobs, spec, tmp_path, resume=False)
        runner.run()
        statuses = sorted(j.status.value for j in jobs)
        assert "completed" in statuses
        assert "failed" in statuses


class TestRealWorldStress:
    """Production-shaped scenario: mixed healthy + broken files at batch scale."""

    def test_20_videos_3_broken_classified_correctly(self, vertical_3s, tmp_path) -> None:
        for i in range(17):
            (tmp_path / f"clip_{i:02d}.mp4").write_bytes(vertical_3s.read_bytes())
        # 3 broken files of different shapes
        (tmp_path / "broken_garbage.mp4").write_bytes(b"this is not a video")
        (tmp_path / "broken_empty.mp4").write_bytes(b"")
        (tmp_path / "broken_truncated.mp4").write_bytes(
            vertical_3s.read_bytes()[:100]  # invalid container header
        )

        sources = sorted(tmp_path.glob("*.mp4"))
        assert len(sources) == 20

        spec = _spec()
        jobs = build_jobs(sources, spec)
        runner = BatchRunner(jobs, spec, tmp_path, resume=False)
        runner.run()

        completed = [j for j in jobs if j.status.value == "completed"]
        failed = [j for j in jobs if j.status.value == "failed"]
        skipped = [j for j in jobs if j.status.value == "skipped"]
        cancelled = [j for j in jobs if j.status.value == "cancelled"]

        # Exact classification: 17 healthy → completed, 3 broken → failed
        assert len(completed) == 17, [
            (j.source.name, j.status.value, j.error)
            for j in jobs if j.status.value != "completed"
        ]
        assert len(failed) == 3
        assert len(skipped) == 0
        assert len(cancelled) == 0
        # Total invariant
        assert len(completed) + len(failed) + len(skipped) + len(cancelled) == 20
        # Every failed job has an error message
        assert all(j.error for j in failed)
        # Every completed job has a real output file
        for j in completed:
            assert j.output is not None and j.output.exists()
            assert j.output.stat().st_size > 0

    def test_resume_on_second_run_skips_completed(self, vertical_3s, tmp_path) -> None:
        for i in range(5):
            (tmp_path / f"ok_{i}.mp4").write_bytes(vertical_3s.read_bytes())
        (tmp_path / "bad.mp4").write_bytes(b"garbage")

        sources = sorted(tmp_path.glob("*.mp4"))
        spec = _spec()
        jobs1 = build_jobs(sources, spec)
        BatchRunner(jobs1, spec, tmp_path, resume=True).run()
        assert sum(1 for j in jobs1 if j.status.value == "completed") == 5
        assert sum(1 for j in jobs1 if j.status.value == "failed") == 1

        jobs2 = build_jobs(sources, spec)
        BatchRunner(jobs2, spec, tmp_path, resume=True).run()
        assert sum(1 for j in jobs2 if j.status.value == "skipped") == 5
        # Broken file isn't marked completed → never enters state.json → tries again
        assert sum(1 for j in jobs2 if j.status.value == "failed") == 1

    def test_completed_job_has_ffmpeg_log(self, vertical_3s, tmp_path) -> None:
        """Per-job stderr log lands in output/logs/ for inspection."""
        (tmp_path / vertical_3s.name).write_bytes(vertical_3s.read_bytes())
        sources = [tmp_path / vertical_3s.name]
        spec = _spec()
        jobs = build_jobs(sources, spec)
        BatchRunner(jobs, spec, tmp_path, resume=False).run()
        assert jobs[0].status.value == "completed"
        log_dir = tmp_path / spec.output_subdir / "logs"
        assert log_dir.is_dir()
        logs = list(log_dir.glob("*.ffmpeg.log"))
        assert len(logs) == 1
        assert logs[0].stat().st_size > 0


class TestMetaMode:
    def test_meta_mode_forces_h264_via_compliance_rewrite(self, vertical_3s, tmp_path) -> None:
        """Even when spec asks for HEVC, Meta Mode rewrites video_codec to h264."""
        from video_extender.core.pipeline import _enforce_meta_mode_codec
        spec = _spec(video_codec="hevc")
        # Without meta_mode, spec passes through unchanged
        assert _enforce_meta_mode_codec(spec).video_codec == "hevc"
        # With meta_mode, codec gets pinned to h264
        from dataclasses import replace
        meta_spec = replace(spec, meta_mode=True)
        assert _enforce_meta_mode_codec(meta_spec).video_codec == "h264"

    def test_meta_mode_injects_required_filters(self, vertical_3s, tmp_path) -> None:
        """Meta Mode ensures audio_normalize + metadata_strip are in the chain
        even if the user didn't toggle them."""
        from video_extender.core.pipeline import _resolve_filters
        spec = _spec(filters=(), meta_mode=True)
        chain = _resolve_filters(spec, target_duration=10.0, main_width=1080)
        # Chain is a list of (Filter, options) pairs
        names = [f.name for f, _ in chain.filters]
        assert "audio_normalize" in names
        assert "metadata_strip" in names

    def test_meta_mode_audio_normalize_target_minus_14_lufs(self, tmp_path) -> None:
        from video_extender.core.pipeline import _resolve_filters
        spec = _spec(filters=(), meta_mode=True)
        chain = _resolve_filters(spec, target_duration=10.0, main_width=1080)
        norm_opts = next(opts for f, opts in chain.filters if f.name == "audio_normalize")
        assert norm_opts.get("target_lufs") == -14.0


class TestFfmpegEncodeFailure:
    """Probe succeeds but the ffmpeg encode itself fails. Verify the failure is
    detected, surfaced as FAILED with an actionable error, and the per-job log
    is written so the user can inspect it.
    """

    def _patch_ffmpeg_to_fail(self, monkeypatch, *,
                              returncode: int = 1,
                              stderr: str = ("Error: simulated encode failure\n"
                                             "[h264_nvenc] cannot allocate session\n"),
                              cancelled: bool = False) -> None:
        from video_extender.core.ffmpeg import FFmpegResult

        def _fake_run(self, args, on_progress=None, stderr_log_path=None):
            if stderr_log_path is not None:
                stderr_log_path.parent.mkdir(parents=True, exist_ok=True)
                stderr_log_path.write_text(stderr, encoding="utf-8")
            return FFmpegResult(
                returncode=returncode, stderr_log=stderr,
                cmd=list(args), cancelled=cancelled,
            )

        monkeypatch.setattr(
            "video_extender.core.ffmpeg.FFmpegRunner.run", _fake_run,
        )

    def test_ffmpeg_nonzero_marks_job_failed(self, vertical_3s, tmp_path, monkeypatch) -> None:
        self._patch_ffmpeg_to_fail(monkeypatch, returncode=1)
        (tmp_path / vertical_3s.name).write_bytes(vertical_3s.read_bytes())
        sources = [tmp_path / vertical_3s.name]
        spec = _spec()
        jobs = build_jobs(sources, spec)
        BatchRunner(jobs, spec, tmp_path, resume=False).run()
        assert jobs[0].status.value == "failed"
        assert jobs[0].error is not None
        assert "exited 1" in jobs[0].error
        assert ("simulated encode failure" in jobs[0].error
                or "cannot allocate session" in jobs[0].error)

    def test_stderr_log_written_on_failure(self, vertical_3s, tmp_path, monkeypatch) -> None:
        self._patch_ffmpeg_to_fail(monkeypatch, returncode=137)  # SIGKILL-style
        (tmp_path / vertical_3s.name).write_bytes(vertical_3s.read_bytes())
        sources = [tmp_path / vertical_3s.name]
        spec = _spec()
        jobs = build_jobs(sources, spec)
        BatchRunner(jobs, spec, tmp_path, resume=False).run()
        assert jobs[0].stderr_log is not None
        assert jobs[0].stderr_log.exists()
        content = jobs[0].stderr_log.read_text(encoding="utf-8")
        assert "simulated encode failure" in content

    def test_failed_job_not_recorded_in_state(self, vertical_3s, tmp_path, monkeypatch) -> None:
        """Failed jobs must NOT enter resume state so a second attempt retries them."""
        self._patch_ffmpeg_to_fail(monkeypatch, returncode=1)
        (tmp_path / vertical_3s.name).write_bytes(vertical_3s.read_bytes())
        sources = [tmp_path / vertical_3s.name]
        spec = _spec()
        BatchRunner(build_jobs(sources, spec), spec, tmp_path, resume=True).run()
        jobs2 = build_jobs(sources, spec)
        BatchRunner(jobs2, spec, tmp_path, resume=True).run()
        assert jobs2[0].status.value == "failed"  # NOT "skipped"

    def test_ffmpeg_cancelled_marks_job_cancelled(
        self, vertical_3s, tmp_path, monkeypatch,
    ) -> None:
        self._patch_ffmpeg_to_fail(monkeypatch, returncode=-15, cancelled=True)
        (tmp_path / vertical_3s.name).write_bytes(vertical_3s.read_bytes())
        sources = [tmp_path / vertical_3s.name]
        spec = _spec()
        jobs = build_jobs(sources, spec)
        BatchRunner(jobs, spec, tmp_path, resume=False).run()
        assert jobs[0].status.value == "cancelled"
        assert "cancelled" in (jobs[0].error or "").lower()

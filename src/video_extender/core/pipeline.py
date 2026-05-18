"""Pipeline: orchestrate probe → filtergraph → encode → write.

Top-level entry: BatchRunner runs many Jobs in parallel using a SchedulePlan.
Per-job entry:   build_job_command + execute_job.
"""
from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from video_extender.core import config as _config
from video_extender.core import probe as _probe
from video_extender.core.encoders import ENCODER_REGISTRY
from video_extender.core.encoders.base import EncoderArgs, EncoderBackend
from video_extender.core.extenders import EXTENDER_REGISTRY
from video_extender.core.extenders.base import ExtenderPlan, ExtenderStrategy
from video_extender.core.ffmpeg import FFmpegResult, FFmpegRunner, ProgressEvent
from video_extender.core.filters import FILTER_REGISTRY
from video_extender.core.filters.base import FilterChain, FilterFragment
from video_extender.core.hardware import HardwareInfo, detect
from video_extender.core.job import ExtendMode, Job, JobSpec, JobStatus
from video_extender.core.presets import PRESET_REGISTRY
from video_extender.core.presets.base import PresetParams
from video_extender.core.scheduler import SchedulePlan, WorkerSlot, plan
from video_extender.utils import logging as _logging
from video_extender.utils.paths import ensure_output_dir, safe_output_path

log = _logging.get("pipeline")

# Job statuses that represent a finished outcome — no further work expected.
_TERMINAL_STATUSES = frozenset({
    JobStatus.COMPLETED, JobStatus.FAILED,
    JobStatus.CANCELLED, JobStatus.SKIPPED,
})


# ---------------------------------------------------------------------------
# Command builder
# ---------------------------------------------------------------------------

def _resolve_extender(spec: JobSpec) -> ExtenderStrategy:
    cls = EXTENDER_REGISTRY.get(spec.extender_name)
    if cls is None:
        raise ValueError(f"Unknown extender: {spec.extender_name}")
    return cls()


def _resolve_filters(spec: JobSpec, target_duration: float, main_width: int) -> FilterChain:
    """Resolve filter chain, injecting per-job runtime context (target_duration,
    main_width) into filter options that need it but were left as 0/missing by
    the caller.
    """
    chain = FilterChain()
    for fname in spec.filters:
        cls = FILTER_REGISTRY.get(fname)
        if cls is None:
            log.warning("unknown filter '%s' — skipping", fname)
            continue
        opts = dict(spec.filter_options.get(fname, {}))
        if fname == "audio_fade_out" and not opts.get("total_duration"):
            opts["total_duration"] = target_duration
        if fname == "watermark" and not opts.get("_main_width") and main_width > 0:
            opts["_main_width"] = main_width
        chain.append(cls(), opts)
    return chain


def _resolve_preset_params(spec: JobSpec) -> PresetParams:
    preset_cls = PRESET_REGISTRY.get(spec.preset_name)
    if preset_cls is None:
        raise ValueError(f"Unknown preset: {spec.preset_name}")
    return preset_cls.for_quality(spec.quality)


def _resolve_encoder_for_slot(slot: WorkerSlot, hw: HardwareInfo) -> EncoderBackend:
    # Match slot.encoder (ffmpeg encoder name) to a registered EncoderBackend.
    for cls in ENCODER_REGISTRY.values():
        if cls.ffmpeg_encoder == slot.encoder:
            return cls()
    raise RuntimeError(f"No EncoderBackend registered for ffmpeg encoder '{slot.encoder}'")


def _compute_target_duration(spec: JobSpec, source_duration: float) -> float:
    if spec.extend_mode == ExtendMode.ADD:
        return source_duration + spec.extend_seconds
    # FILL: extend up to target; clamp to at least source duration
    return max(source_duration, spec.extend_seconds)


@dataclass
class BuiltCommand:
    args: list[str]
    target_duration: float
    encoder_label: str
    output: Path


def _compose_filter_complex(
    ext_plan: ExtenderPlan,
    frags: list[FilterFragment],
    gpu_upload_filter: str,
) -> tuple[str, str, str]:
    """Stitch the extender's filtergraph + filter chain segments + (optional)
    GPU upload filter into a single -filter_complex string, tracking the
    currently-valid video/audio stream labels through each transformation.

    Returns (filter_complex_string, final_video_label, final_audio_label).
    """
    fc_parts: list[str] = []
    if ext_plan.filtergraph:
        fc_parts.append(ext_plan.filtergraph)

    cur_v = ext_plan.video_label or "[0:v]"
    cur_a = ext_plan.audio_label or "[0:a]"

    for f in frags:
        if f.filter_segment:
            fc_parts.append(f.filter_segment)
        if f.new_video_label:
            cur_v = f.new_video_label
        if f.new_audio_label:
            cur_a = f.new_audio_label

    # GPU encoders that need a hwframe input (VAAPI, QSV) terminate the chain
    # with a format-conversion+upload filter.
    if gpu_upload_filter:
        hw_label = f"[hwout_{cur_v.strip('[]')}]"
        fc_parts.append(f"{cur_v}{gpu_upload_filter}{hw_label}")
        cur_v = hw_label

    return ";".join(p for p in fc_parts if p), cur_v, cur_a


def _compose_inputs(
    source: Path,
    ext_plan: ExtenderPlan,
    frags: list[FilterFragment],
) -> list[str]:
    """Build the `-i ...` portion of the ffmpeg argv, including per-input
    prefix flags like `-stream_loop -1` and `-loop 1` placed BEFORE the
    input they apply to.
    """
    if ext_plan.extra_input_args and len(ext_plan.extra_input_args) != len(ext_plan.extra_inputs):
        raise RuntimeError(
            f"ExtenderPlan: extra_input_args ({len(ext_plan.extra_input_args)}) and "
            f"extra_inputs ({len(ext_plan.extra_inputs)}) length mismatch"
        )

    inputs: list[str] = []
    # Source first (with extender-supplied source flags like -stream_loop).
    inputs += list(ext_plan.source_input_args)
    inputs += ["-i", str(source)]
    # Extender's extra inputs (intro/outro/image), with per-input prefix args.
    for i, extra in enumerate(ext_plan.extra_inputs):
        if ext_plan.extra_input_args:
            inputs += list(ext_plan.extra_input_args[i])
        inputs += ["-i", str(extra)]
    # Filter extras (watermark image, subtitle file, etc.).
    for f in frags:
        for path in f.extra_inputs:
            inputs += list(f.prefix_input_args)
            inputs += ["-i", path]
    return inputs


def build_job_command(job: Job, slot: WorkerSlot, hw: HardwareInfo) -> BuiltCommand:
    """Produce the full ffmpeg argv (without the ffmpeg binary itself)."""
    assert job.media is not None and job.spec is not None and job.output is not None

    spec = job.spec
    extender = _resolve_extender(spec)
    params = _resolve_preset_params(spec)
    encoder = _resolve_encoder_for_slot(slot, hw)

    target = _compute_target_duration(spec, job.media.duration)
    main_w = job.media.video.width if job.media.video else 0
    chain = _resolve_filters(spec, target, main_w)

    ext_plan: ExtenderPlan = extender.build_plan(
        job.source, job.media, target,
        audio_fade_out_seconds=spec.audio_fade_out_seconds,
        options=spec.extender_options or {},
    )

    next_input = 1 + len(ext_plan.extra_inputs)
    frags: list[FilterFragment] = chain.build(
        in_video=ext_plan.video_label or "[0:v]",
        in_audio=ext_plan.audio_label or "[0:a]",
        next_input_index=next_input,
    )

    # Encoder args resolved early because GPU-class encoders contribute a
    # terminal upload filter to the filter_complex and prepend hw_init_args
    # ahead of every -i flag.
    enc_args: EncoderArgs = encoder.build_args(
        bitrate_kbps=params.bitrate_kbps,
        audio_bitrate_kbps=params.audio_bitrate_kbps,
        crf=None,
        gpu_index=slot.gpu_index,
        threads=slot.threads,
    )

    filter_complex, map_v, map_a = _compose_filter_complex(
        ext_plan, frags, enc_args.gpu_upload_filter,
    )
    inputs = _compose_inputs(job.source, ext_plan, frags)
    extra_output_args = [arg for f in frags for arg in f.output_metadata_args]

    # Final argv: hw_init_args > inputs > -filter_complex > -map > encoder > output.
    argv: list[str] = []
    argv += list(enc_args.hw_init_args)
    argv += inputs
    if filter_complex:
        argv += ["-filter_complex", filter_complex]
    argv += ["-map", map_v, "-map", map_a]
    argv += list(enc_args.video_args)
    argv += list(enc_args.audio_args)
    argv += list(enc_args.container_args)
    argv += extra_output_args
    argv += ["-t", f"{target:.3f}"]
    argv += [str(job.output)]

    return BuiltCommand(args=argv, target_duration=target, encoder_label=encoder.label, output=job.output)


# ---------------------------------------------------------------------------
# Job execution
# ---------------------------------------------------------------------------

ProgressFn = Callable[[Job], None]


def _make_progress_callback(
    job: Job,
    target_duration: float,
    on_progress: ProgressFn | None,
) -> Callable[[ProgressEvent], None]:
    """Build a per-job progress-event handler that keeps Job.progress
    monotonic and recomputes speed + ETA from each ffmpeg event.
    """
    def _cb(ev: ProgressEvent) -> None:
        if target_duration > 0:
            new_progress = min(1.0, ev.out_time_s / target_duration)
            # ffmpeg's terminal 'progress=end' event sometimes lacks a valid
            # out_time_ms, which would rewind the GUI bar to 0%. Only advance.
            if new_progress > job.progress:
                job.progress = new_progress
        if ev.speed > 0:
            job.speed = ev.speed
        if ev.speed > 0 and target_duration > 0:
            remaining = max(0.0, target_duration - ev.out_time_s)
            job.eta_seconds = remaining / ev.speed
        else:
            job.eta_seconds = 0.0
        if on_progress:
            on_progress(job)
    return _cb


def _apply_ffmpeg_result(
    job: Job, result: FFmpegResult, state_file: Path | None,
) -> None:
    """Translate the ffmpeg subprocess outcome into the job's terminal status."""
    if result.cancelled:
        job.status = JobStatus.CANCELLED
        job.error = "cancelled by user"
        return
    if result.success:
        job.status = JobStatus.COMPLETED
        job.progress = 1.0
        if state_file is not None and job.output is not None:
            _config.mark_completed(state_file, job.source, job.output, job.spec)
        return
    # Non-zero exit → FAILED with last 5 stderr lines for diagnosis.
    job.status = JobStatus.FAILED
    tail = result.stderr_log.splitlines()[-5:]
    job.error = f"ffmpeg exited {result.returncode}: {' | '.join(tail)}"
    if state_file is not None:
        _config.mark_failed(state_file, job.source, job.error)


def execute_job(
    job: Job,
    slot: WorkerSlot,
    *,
    hw: HardwareInfo,
    runner: FFmpegRunner,
    state_file: Path | None,
    on_progress: ProgressFn | None = None,
    log_dir: Path | None = None,
) -> Job:
    job.status = JobStatus.RUNNING
    job.worker_label = slot.label
    if on_progress:
        on_progress(job)

    try:
        built = build_job_command(job, slot, hw)
        job.target_duration = built.target_duration
        log.info("→ %s [%s] target=%.1fs", job.source.name, slot.label, built.target_duration)

        # Per-job stderr log — keyed by output stem so re-runs with different
        # filename templates don't overwrite each other's logs.
        stderr_log = None
        if log_dir is not None:
            log_dir.mkdir(parents=True, exist_ok=True)
            log_stem = job.output.stem if job.output else job.source.stem
            stderr_log = log_dir / f"{log_stem}.ffmpeg.log"
            job.stderr_log = stderr_log

        cb = _make_progress_callback(job, built.target_duration, on_progress)
        result: FFmpegResult = runner.run(built.args, on_progress=cb, stderr_log_path=stderr_log)
        _apply_ffmpeg_result(job, result, state_file)
    except NotImplementedError as exc:
        job.status = JobStatus.FAILED
        job.error = f"scaffold not implemented: {exc}"
    except Exception as exc:  # noqa: BLE001
        log.exception("job failed: %s", job.source)
        job.status = JobStatus.FAILED
        job.error = str(exc)
        if state_file is not None:
            _config.mark_failed(state_file, job.source, job.error)

    if on_progress:
        on_progress(job)
    return job


# ---------------------------------------------------------------------------
# BatchRunner
# ---------------------------------------------------------------------------

class BatchRunner:
    """Run many Jobs across the SchedulePlan with cancellation support."""

    def __init__(
        self,
        jobs: list[Job],
        spec: JobSpec,
        source_folder: Path,
        *,
        hw: HardwareInfo | None = None,
        resume: bool = True,
        on_progress: ProgressFn | None = None,
    ) -> None:
        self.jobs = jobs
        self.spec = spec
        self.source_folder = source_folder
        self.hw = hw or detect()
        self.resume = resume
        self.on_progress = on_progress
        self._cancel = threading.Event()
        self._runners: list[FFmpegRunner] = []
        self._lock = threading.Lock()

    def cancel(self) -> None:
        self._cancel.set()
        with self._lock:
            for r in self._runners:
                r.cancel()

    def run(self) -> list[Job]:
        out_dir = ensure_output_dir(self.source_folder, self.spec.output_subdir)
        state_path = out_dir / ".video_extender_state.json"
        log_dir = out_dir / "logs"

        self._plan_output_paths(out_dir)
        if self.resume:
            self._apply_resume_filter(state_path)

        pending = [j for j in self.jobs if j.status in (JobStatus.PENDING, JobStatus.QUEUED)]
        if not pending:
            return self.jobs

        sched: SchedulePlan = plan(
            len(pending), hw=self.hw, codec=self.spec.video_codec,
            encoder_override=self.spec.encoder_override,
            max_parallel_override=self.spec.max_parallel,
        )
        self._dispatch_pool(pending, sched, state_path, log_dir)
        self._final_sweep()
        return self.jobs

    # ---- run() phases ----
    def _plan_output_paths(self, out_dir: Path) -> None:
        """Assign each Job an output path via the user's filename_template."""
        for job in self.jobs:
            job.spec = self.spec
            if job.output is None:
                job.output = safe_output_path(
                    out_dir, job.source, self.spec.filename_template,
                    duration=self._duration_label(),
                    preset=self.spec.preset_name,
                )

    def _apply_resume_filter(self, state_path: Path) -> None:
        """Mark jobs SKIPPED when a prior completion matches (source, spec_hash)
        AND the output file still exists on disk."""
        for job in self.jobs:
            if _config.is_completed(state_path, job.source, self.spec, job.output):
                job.status = JobStatus.SKIPPED
                job.progress = 1.0
                if self.on_progress:
                    self.on_progress(job)

    def _dispatch_pool(
        self,
        pending: list[Job],
        sched: SchedulePlan,
        state_path: Path,
        log_dir: Path,
    ) -> None:
        """Submit each pending job to a worker slot and collect results.
        Unhandled worker exceptions are mapped back to the originating job."""
        worker_count = sched.total_workers
        with self._lock:
            self._runners = [FFmpegRunner() for _ in range(worker_count)]
        slots = list(sched.slots)

        with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="vx") as pool:
            future_to_job: dict[Future, Job] = {}

            for i, job in enumerate(pending):
                slot = slots[i % len(slots)]
                runner = self._runners[i % len(self._runners)]

                def _task(j: Job = job, s: WorkerSlot = slot, r: FFmpegRunner = runner) -> Job:
                    if self._cancel.is_set():
                        j.status = JobStatus.CANCELLED
                        return j
                    return execute_job(
                        j, s,
                        hw=self.hw, runner=r,
                        state_file=state_path,
                        on_progress=self.on_progress,
                        log_dir=log_dir,
                    )

                future_to_job[pool.submit(_task)] = job

            for fut, job in future_to_job.items():
                try:
                    fut.result()
                except Exception as exc:  # noqa: BLE001
                    log.exception("worker raised for %s", job.source)
                    if job.status not in _TERMINAL_STATUSES:
                        job.status = JobStatus.FAILED
                        job.error = f"worker exception: {exc}"
                        if self.on_progress:
                            self.on_progress(job)

    def _final_sweep(self) -> None:
        """Defense-in-depth: every job MUST end in a terminal state so that
        summary counts always equal len(jobs). Anything still non-terminal at
        this point gets forced to FAILED with an explanatory error.
        """
        for job in self.jobs:
            if job.status not in _TERMINAL_STATUSES:
                log.warning(
                    "job ended in non-terminal status %s; forcing FAILED: %s",
                    job.status.value, job.source,
                )
                job.status = JobStatus.FAILED
                job.error = job.error or "ended in non-terminal state (no completion signal)"
                if self.on_progress:
                    self.on_progress(job)

    def _duration_label(self) -> str:
        secs = int(self.spec.extend_seconds)
        if secs % 3600 == 0:
            return f"{secs // 3600}h"
        if secs % 60 == 0:
            return f"{secs // 60}m"
        return f"{secs}s"


# ---------------------------------------------------------------------------
# Convenience: build jobs from a folder
# ---------------------------------------------------------------------------

def build_jobs(sources: list[Path], spec: JobSpec) -> list[Job]:
    runner = FFmpegRunner()
    jobs: list[Job] = []
    for src in sources:
        try:
            media = _probe.probe_file(src, runner)
            jobs.append(Job(source=src, media=media, spec=spec))
        except Exception as exc:  # noqa: BLE001
            j = Job(source=src, spec=spec, status=JobStatus.FAILED, error=f"probe failed: {exc}")
            jobs.append(j)
    return jobs

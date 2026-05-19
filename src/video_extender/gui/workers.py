"""QThread wrappers around BatchRunner so progress reaches the GUI via signals."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from video_extender.core.hardware import detect
from video_extender.core.job import Job, JobSpec, JobStatus
from video_extender.core.pipeline import BatchRunner
from video_extender.core.probe import probe_file
from video_extender.utils.paths import discover_videos


class BatchSignals(QObject):
    job_updated = Signal(object)         # emits Job
    job_added = Signal(object)
    batch_started = Signal(int)
    batch_finished = Signal(int, int, int)  # completed, failed, skipped
    error = Signal(str)


class ProbeThread(QThread):
    """Discover & probe videos off the GUI thread.

    Probes one video at a time and checks `isInterruptionRequested()` between
    each, so a folder switch or window-close can stop the work mid-scan
    instead of blocking until every file is probed.
    """
    def __init__(self, folder: Path, recursive: bool, spec: JobSpec, signals: BatchSignals) -> None:
        super().__init__()
        self.folder = folder
        self.recursive = recursive
        self.spec = spec
        self.signals = signals
        self.jobs: list[Job] = []

    def run(self) -> None:
        try:
            sources = discover_videos(self.folder, recursive=self.recursive)
            if not sources:
                self.signals.error.emit("Klasörde video bulunamadı.")
                return
            # Parallel probe with bounded concurrency. ffprobe is a quick
            # metadata call, so 8x scales near-linearly. We use as_completed
            # so the GUI gets job_added signals as each probe finishes
            # (rather than waiting for the whole map to return), and we still
            # honour interruption between completions.
            from concurrent.futures import as_completed
            max_workers = min(8, len(sources))
            with ThreadPoolExecutor(max_workers=max_workers,
                                    thread_name_prefix="gui-probe") as pool:
                future_to_src = {
                    pool.submit(self._probe_one, src): src for src in sources
                }
                for fut in as_completed(future_to_src):
                    if self.isInterruptionRequested():
                        # Drain in-flight futures but don't emit further;
                        # cancellation should feel responsive.
                        for f in future_to_src:
                            f.cancel()
                        return
                    job = fut.result()
                    self.jobs.append(job)
                    self.signals.job_added.emit(job)
        except Exception as exc:  # noqa: BLE001
            self.signals.error.emit(f"Probe hatası: {exc}")

    def _probe_one(self, src: Path) -> Job:
        try:
            media = probe_file(src)
            return Job(source=src, media=media, spec=self.spec)
        except Exception as exc:  # noqa: BLE001
            return Job(source=src, spec=self.spec,
                       status=JobStatus.FAILED,
                       error=f"probe failed: {exc}")


class BatchThread(QThread):
    def __init__(self, jobs: list[Job], spec: JobSpec, folder: Path, signals: BatchSignals,
                 resume: bool = True) -> None:
        super().__init__()
        self.jobs = jobs
        self.spec = spec
        self.folder = folder
        self.signals = signals
        self.resume = resume
        self._runner: BatchRunner | None = None

    def run(self) -> None:
        hw = detect()
        self.signals.batch_started.emit(len(self.jobs))
        self._runner = BatchRunner(
            self.jobs, self.spec, self.folder,
            hw=hw, resume=self.resume,
            on_progress=lambda j: self.signals.job_updated.emit(j),
        )
        try:
            self._runner.run()
        except Exception as exc:  # noqa: BLE001
            self.signals.error.emit(f"Batch hatası: {exc}")
        completed = sum(1 for j in self.jobs if j.status == JobStatus.COMPLETED)
        failed = sum(1 for j in self.jobs if j.status == JobStatus.FAILED)
        skipped = sum(1 for j in self.jobs if j.status == JobStatus.SKIPPED)
        self.signals.batch_finished.emit(completed, failed, skipped)

    def cancel(self) -> None:
        if self._runner is not None:
            self._runner.cancel()

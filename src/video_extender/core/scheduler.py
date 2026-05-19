"""Smart parallel scheduler — assigns jobs to GPU vs CPU workers.

Strategy:
- GPU encoder chips (NVENC, QSV, VAAPI, AMF) run independently of CPU cores.
- libx264/libx265 on CPU saturates cores; estimate threads-per-job and pick a worker count that uses most cores without thrashing.
- A single video can be sent to GPU even when there's "no batch" — fastest path.
- When N >> 1, GPU + multiple CPU workers run concurrently and bottlenecks are decoupled.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from video_extender.core.hardware import HardwareInfo, detect, probe_encoder
from video_extender.utils import logging as _logging

log = _logging.get("scheduler")


class WorkerKind(StrEnum):
    GPU = "gpu"
    CPU = "cpu"


@dataclass(frozen=True)
class WorkerSlot:
    kind: WorkerKind
    encoder: str            # ffmpeg encoder name to use
    threads: int            # for CPU; for GPU informational only
    gpu_index: int | None   # ffmpeg -gpu index for NVENC; None for CPU
    label: str              # human-readable


@dataclass(frozen=True)
class SchedulePlan:
    slots: tuple[WorkerSlot, ...]
    total_workers: int

    @property
    def gpu_slots(self) -> tuple[WorkerSlot, ...]:
        return tuple(s for s in self.slots if s.kind == WorkerKind.GPU)

    @property
    def cpu_slots(self) -> tuple[WorkerSlot, ...]:
        return tuple(s for s in self.slots if s.kind == WorkerKind.CPU)


# NVENC concurrent session caps differ by GPU class.
# Consumer GeForce cards (RTX 30/40) accept many sessions via the patched driver;
# we cap conservatively at 3 to avoid driver throttling. Quadro/RTX A series: unlimited.
NVENC_SESSIONS_PER_GPU = 3


_GPU_ENCODER_PREFERENCE: dict[str, tuple[str, ...]] = {
    "h264": ("h264_nvenc", "h264_qsv", "h264_vaapi", "h264_amf", "h264_videotoolbox"),
    "hevc": ("hevc_nvenc", "hevc_qsv", "hevc_vaapi", "hevc_amf", "hevc_videotoolbox"),
    "av1":  ("av1_nvenc", "av1_qsv", "av1_vaapi", "av1_amf"),
}

_CPU_ENCODER_PREFERENCE: dict[str, tuple[str, ...]] = {
    "h264": ("libx264",),
    "hevc": ("libx265",),
    "av1":  ("libsvtav1", "libaom-av1"),
}


_GPU_SUFFIXES = ("_nvenc", "_qsv", "_vaapi", "_amf", "_videotoolbox")


def _is_gpu_encoder(name: str) -> bool:
    return any(name.endswith(s) for s in _GPU_SUFFIXES)


def _plan_with_override(
    job_count: int,
    hw: HardwareInfo,
    override: str,
    probe_gpu: bool,
    max_parallel_override: int | None,
) -> SchedulePlan:
    """Build a plan where every worker uses the user-forced encoder."""
    if override not in hw.available_encoders:
        log.warning("encoder override '%s' not available; falling back to CPU libx264", override)
        override = "libx264"
    if _is_gpu_encoder(override) and probe_gpu and not probe_encoder(override):
        log.warning("encoder override '%s' probe failed; falling back to CPU libx264", override)
        override = "libx264"

    slots: list[WorkerSlot] = []
    if _is_gpu_encoder(override):
        # Find the GPU that supports this encoder
        gpu_idx = 0
        for idx, gpu in enumerate(hw.gpus):
            if override in gpu.encoders:
                gpu_idx = idx
                break
        sessions = NVENC_SESSIONS_PER_GPU if override.endswith("_nvenc") else 1
        sessions = min(sessions, job_count)
        for s in range(sessions):
            label_suffix = f"/session{s+1}" if sessions > 1 else ""
            slots.append(WorkerSlot(
                kind=WorkerKind.GPU, encoder=override, threads=2,
                gpu_index=gpu_idx,
                label=f"GPU#{gpu_idx}{label_suffix} ({override}) [override]",
            ))
    else:
        cpu_cap = max(1, hw.cpu_count // 4)
        cpu_cap = min(cpu_cap, max(1, job_count))
        threads_each = _threads_per_cpu_job(hw, cpu_cap)
        for i in range(cpu_cap):
            slots.append(WorkerSlot(
                kind=WorkerKind.CPU, encoder=override, threads=threads_each,
                gpu_index=None,
                label=f"CPU#{i+1} ({override} x{threads_each}) [override]",
            ))

    if max_parallel_override is not None:
        slots = slots[:max(1, max_parallel_override)]

    plan_obj = SchedulePlan(slots=tuple(slots), total_workers=len(slots))
    log_fn = log.info if probe_gpu else log.debug
    log_fn("Schedule (override=%s) for %d jobs: %d workers", override, job_count, plan_obj.total_workers)
    return plan_obj


def _pick_gpu_encoder(encoders: frozenset[str], codec: str, *, probe: bool = True) -> str | None:
    """Pick the first GPU encoder for `codec` that is both LISTED and
    FUNCTIONALLY able to initialize (when probe=True).
    """
    for cand in _GPU_ENCODER_PREFERENCE.get(codec, ()):
        if cand not in encoders:
            continue
        if probe and not probe_encoder(cand):
            log.info("GPU encoder %s listed but probe failed → skipping", cand)
            continue
        return cand
    return None


def _pick_cpu_encoder(encoders: frozenset[str], codec: str) -> str:
    for cand in _CPU_ENCODER_PREFERENCE.get(codec, ("libx264",)):
        if cand in encoders:
            return cand
    return "libx264"  # universal fallback


def _threads_per_cpu_job(hw: HardwareInfo, parallel_jobs: int) -> int:
    """Divide cores across parallel CPU jobs; floor at 2, cap at 8 per job."""
    if parallel_jobs <= 0:
        return min(hw.cpu_count, 8)
    per = max(2, hw.cpu_count // parallel_jobs)
    return min(per, 8)


def plan(
    job_count: int,
    *,
    hw: HardwareInfo | None = None,
    max_parallel_override: int | None = None,
    codec: str = "h264",
    probe_gpu: bool = True,
    encoder_override: str | None = None,
) -> SchedulePlan:
    """Build an optimal slot plan for `job_count` jobs.

    `codec` selects which encoders to use ("h264", "hevc", "av1"). Falls back
    gracefully: if no GPU encoder for the requested codec, runs CPU-only.

    `encoder_override` forces a specific ffmpeg encoder (e.g. "libx265",
    "h264_nvenc"). Auto codec/GPU detection is bypassed. If the override is
    a GPU encoder, all slots are GPU; if it's a CPU encoder, all slots are CPU.

    `probe_gpu` (default True) verifies each GPU encoder can actually init
    before allocating slots for it. Pass False for unit tests against
    synthetic HardwareInfo.
    """
    hw = hw or detect()
    slots: list[WorkerSlot] = []

    if encoder_override:
        return _plan_with_override(job_count, hw, encoder_override, probe_gpu, max_parallel_override)

    cpu_encoder = _pick_cpu_encoder(hw.available_encoders, codec)

    gpu_slot_count = 0
    if hw.gpus:
        # Pick the best encoder PER GPU based on what that GPU supports.
        for idx, gpu in enumerate(hw.gpus):
            if not gpu.encoders:
                continue
            # Intersect this GPU's encoder list with codec preference, in order.
            picked: str | None = None
            for cand in _GPU_ENCODER_PREFERENCE.get(codec, ()):
                if cand in gpu.encoders:
                    if probe_gpu and not probe_encoder(cand):
                        log.info("GPU encoder %s on %s listed but probe failed → skipping",
                                 cand, gpu.name)
                        continue
                    picked = cand
                    break
            if picked is None:
                continue

            # Session count: NVIDIA's NVENC chip supports concurrent sessions;
            # other GPU encoders typically serialize internally — 1 slot each.
            sessions = NVENC_SESSIONS_PER_GPU if gpu.vendor == "nvidia" else 1
            for s in range(sessions):
                label_suffix = f"/session{s+1}" if sessions > 1 else ""
                slots.append(WorkerSlot(
                    kind=WorkerKind.GPU,
                    encoder=picked,
                    threads=2,
                    gpu_index=idx,
                    label=f"{gpu.vendor.upper()}#{idx}{label_suffix} ({picked})",
                ))
                gpu_slot_count += 1

    # CPU slots: enough to saturate the remaining cores, but not insane parallelism.
    # Aim: keep total parallel work ≈ min(job_count, sane_cap).
    cpu_cap = max(1, hw.cpu_count // 4)  # 32 cores -> 8 CPU workers
    cpu_cap = min(cpu_cap, max(1, job_count))  # don't spawn idle workers
    if gpu_slot_count >= job_count:
        cpu_slot_count = 0
    else:
        cpu_slot_count = min(cpu_cap, max(0, job_count - gpu_slot_count))

    threads_each = _threads_per_cpu_job(hw, cpu_slot_count)
    for i in range(cpu_slot_count):
        slots.append(WorkerSlot(
            kind=WorkerKind.CPU,
            encoder=cpu_encoder,
            threads=threads_each,
            gpu_index=None,
            label=f"CPU#{i+1} ({cpu_encoder} x{threads_each})",
        ))

    if not slots:
        # Pathological: no encoder detected; fall back to single libx264 worker.
        slots.append(WorkerSlot(
            kind=WorkerKind.CPU,
            encoder=cpu_encoder,
            threads=min(hw.cpu_count, 8),
            gpu_index=None,
            label=f"CPU#1 ({cpu_encoder}) [fallback]",
        ))

    if max_parallel_override is not None:
        slots = slots[:max(1, max_parallel_override)]

    plan_obj = SchedulePlan(slots=tuple(slots), total_workers=len(slots))
    # Widget-driven preview calls (probe_gpu=False) shouldn't pollute INFO logs;
    # only real scheduler decisions (about-to-run batch) deserve INFO.
    log_fn = log.info if probe_gpu else log.debug
    log_fn(
        "Schedule for %d job(s): %d GPU + %d CPU = %d workers",
        job_count,
        len(plan_obj.gpu_slots),
        len(plan_obj.cpu_slots),
        plan_obj.total_workers,
    )
    return plan_obj

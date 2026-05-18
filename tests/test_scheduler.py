"""Scheduler tests with synthetic HardwareInfo to keep behavior deterministic."""
from __future__ import annotations

from dataclasses import replace

from video_extender.core.hardware import GpuInfo, HardwareInfo
from video_extender.core.scheduler import WorkerKind, plan


def _hw(*, encoders: tuple[str, ...] = ("libx264",), gpus: tuple[GpuInfo, ...] = (), cpu: int = 8) -> HardwareInfo:
    return HardwareInfo(
        cpu_count=cpu,
        cpu_logical=cpu,
        ram_total_mb=8192,
        ffmpeg_path="/usr/bin/ffmpeg",
        ffprobe_path="/usr/bin/ffprobe",
        gpus=gpus,
        available_encoders=frozenset(encoders),
    )


def _nvidia_gpu() -> GpuInfo:
    return GpuInfo(vendor="nvidia", name="Test GPU", encoders=("h264_nvenc", "hevc_nvenc"))


class TestSchedulerCPUOnly:
    def test_no_gpu_falls_back_to_cpu(self) -> None:
        p = plan(5, hw=_hw(), probe_gpu=False)
        assert len(p.gpu_slots) == 0
        assert len(p.cpu_slots) > 0
        assert all(s.encoder == "libx264" for s in p.cpu_slots)

    def test_cpu_worker_count_bounded(self) -> None:
        # 32 cores → cap at cpu_count // 4 = 8 workers
        p = plan(100, hw=_hw(cpu=32), probe_gpu=False)
        assert len(p.cpu_slots) <= 8

    def test_single_job_single_worker(self) -> None:
        p = plan(1, hw=_hw(), probe_gpu=False)
        assert p.total_workers == 1

    def test_cpu_threads_divide_cores(self) -> None:
        p = plan(4, hw=_hw(cpu=32), probe_gpu=False)
        # 32 cores / 4 workers = 8 threads each, capped at 8
        for s in p.cpu_slots:
            assert s.threads <= 8
            assert s.threads >= 2


class TestSchedulerNVENC:
    def test_nvenc_used_when_available(self) -> None:
        p = plan(3, hw=_hw(
            encoders=("h264_nvenc", "libx264"),
            gpus=(_nvidia_gpu(),),
        ), probe_gpu=False)
        assert len(p.gpu_slots) > 0
        assert all(s.encoder == "h264_nvenc" for s in p.gpu_slots)

    def test_nvenc_session_cap(self) -> None:
        # NVIDIA GPU should provide 3 NVENC sessions
        p = plan(10, hw=_hw(
            encoders=("h264_nvenc", "libx264"),
            gpus=(_nvidia_gpu(),),
            cpu=32,
        ), probe_gpu=False)
        nvidia_slots = [s for s in p.gpu_slots if s.encoder == "h264_nvenc"]
        assert len(nvidia_slots) == 3

    def test_gpu_plus_cpu_total(self) -> None:
        # 10 jobs, 32 cores, NVENC → 3 GPU + min(8, 7) CPU = 10
        p = plan(10, hw=_hw(
            encoders=("h264_nvenc", "libx264"),
            gpus=(_nvidia_gpu(),),
            cpu=32,
        ), probe_gpu=False)
        assert p.total_workers == 10


class TestSchedulerCodecAware:
    def test_hevc_picks_hevc_nvenc(self) -> None:
        p = plan(2, hw=_hw(
            encoders=("h264_nvenc", "hevc_nvenc", "libx264", "libx265"),
            gpus=(_nvidia_gpu(),),
        ), codec="hevc", probe_gpu=False)
        gpu = [s for s in p.gpu_slots]
        assert all(s.encoder == "hevc_nvenc" for s in gpu)
        cpu = [s for s in p.cpu_slots]
        assert all(s.encoder == "libx265" for s in cpu)

    def test_h264_picks_h264_encoders(self) -> None:
        p = plan(2, hw=_hw(
            encoders=("h264_nvenc", "hevc_nvenc", "libx264", "libx265"),
            gpus=(_nvidia_gpu(),),
        ), codec="h264", probe_gpu=False)
        assert all(s.encoder == "h264_nvenc" for s in p.gpu_slots)
        assert all(s.encoder == "libx264" for s in p.cpu_slots)

    def test_no_gpu_for_codec_falls_back_to_cpu(self) -> None:
        # h264 GPU available but we ask for hevc → no hevc_nvenc → CPU libx265
        p = plan(2, hw=_hw(
            encoders=("h264_nvenc", "libx264", "libx265"),
            gpus=(GpuInfo(vendor="nvidia", name="GPU", encoders=("h264_nvenc",)),),
        ), codec="hevc", probe_gpu=False)
        assert len(p.gpu_slots) == 0
        assert all(s.encoder == "libx265" for s in p.cpu_slots)


class TestSchedulerCrossDeviceGPU:
    """Scheduler must correctly route to non-NVIDIA GPU encoders too."""

    def test_intel_vaapi_only(self) -> None:
        """Intel iGPU on Linux: only h264_vaapi available."""
        p = plan(3, hw=_hw(
            encoders=("h264_vaapi", "libx264"),
            gpus=(GpuInfo(vendor="intel", name="Intel UHD", encoders=("h264_vaapi",)),),
        ), probe_gpu=False)
        assert len(p.gpu_slots) >= 1
        assert all(s.encoder == "h264_vaapi" for s in p.gpu_slots)

    def test_amd_amf_only(self) -> None:
        """AMD GPU: only h264_amf available."""
        p = plan(3, hw=_hw(
            encoders=("h264_amf", "libx264"),
            gpus=(GpuInfo(vendor="amd", name="Radeon", encoders=("h264_amf",)),),
        ), probe_gpu=False)
        assert all(s.encoder == "h264_amf" for s in p.gpu_slots)

    def test_apple_videotoolbox(self) -> None:
        """macOS: VideoToolbox path."""
        p = plan(2, hw=_hw(
            encoders=("h264_videotoolbox", "libx264"),
            gpus=(GpuInfo(vendor="apple", name="Apple Silicon",
                          encoders=("h264_videotoolbox",)),),
        ), probe_gpu=False)
        assert all(s.encoder == "h264_videotoolbox" for s in p.gpu_slots)

    def test_per_gpu_encoder_selection(self) -> None:
        """Multi-GPU: each GPU gets its own appropriate encoder."""
        p = plan(5, hw=_hw(
            encoders=("h264_nvenc", "h264_vaapi", "libx264"),
            gpus=(
                GpuInfo(vendor="nvidia", name="RTX", encoders=("h264_nvenc",)),
                GpuInfo(vendor="intel", name="iGPU", encoders=("h264_vaapi",)),
            ),
        ), probe_gpu=False)
        encoders_used = {s.encoder for s in p.gpu_slots}
        assert "h264_nvenc" in encoders_used
        assert "h264_vaapi" in encoders_used


class TestSchedulerOverride:
    def test_max_parallel_override(self) -> None:
        p = plan(20, hw=_hw(
            encoders=("h264_nvenc", "libx264"),
            gpus=(_nvidia_gpu(),),
            cpu=32,
        ), max_parallel_override=2, probe_gpu=False)
        assert p.total_workers == 2


class TestEncoderOverride:
    def test_force_libx265_uses_cpu(self) -> None:
        p = plan(3, hw=_hw(
            encoders=("h264_nvenc", "libx264", "libx265"),
            gpus=(_nvidia_gpu(),),
            cpu=32,
        ), encoder_override="libx265", probe_gpu=False)
        # All slots should be CPU libx265 (no NVENC even though available)
        assert all(s.kind.value == "cpu" for s in p.slots)
        assert all(s.encoder == "libx265" for s in p.slots)

    def test_force_h264_nvenc(self) -> None:
        p = plan(5, hw=_hw(
            encoders=("h264_nvenc", "libx264"),
            gpus=(_nvidia_gpu(),),
        ), encoder_override="h264_nvenc", probe_gpu=False)
        assert all(s.encoder == "h264_nvenc" for s in p.slots)
        assert all(s.kind.value == "gpu" for s in p.slots)

    def test_unavailable_override_falls_back(self) -> None:
        # User forces hevc_nvenc but only libx264 is available
        p = plan(2, hw=_hw(encoders=("libx264",)),
                 encoder_override="hevc_nvenc", probe_gpu=False)
        assert all(s.encoder == "libx264" for s in p.slots)

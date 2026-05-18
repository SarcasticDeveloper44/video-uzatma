"""Hardware detection: CPU, RAM, GPU encoders available via ffmpeg."""
from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache

from video_extender.utils import logging as _logging

log = _logging.get("hardware")


@dataclass(frozen=True)
class GpuInfo:
    vendor: str           # "nvidia" | "intel" | "amd" | "apple" | "unknown"
    name: str
    encoders: tuple[str, ...]  # ffmpeg encoder names available (e.g. "h264_nvenc")


@dataclass(frozen=True)
class HardwareInfo:
    cpu_count: int
    cpu_logical: int
    ram_total_mb: int
    ffmpeg_path: str | None
    ffprobe_path: str | None
    gpus: tuple[GpuInfo, ...] = field(default_factory=tuple)
    available_encoders: frozenset[str] = field(default_factory=frozenset)

    @property
    def has_nvenc(self) -> bool:
        return any(e.endswith("_nvenc") for e in self.available_encoders)

    @property
    def has_qsv(self) -> bool:
        return any(e.endswith("_qsv") for e in self.available_encoders)

    @property
    def has_vaapi(self) -> bool:
        return any(e.endswith("_vaapi") for e in self.available_encoders)

    @property
    def has_amf(self) -> bool:
        return any(e.endswith("_amf") for e in self.available_encoders)

    @property
    def has_videotoolbox(self) -> bool:
        return any("videotoolbox" in e for e in self.available_encoders)

    @property
    def has_gpu_encoder(self) -> bool:
        return self.has_nvenc or self.has_qsv or self.has_vaapi or self.has_amf or self.has_videotoolbox


_INTERESTING_ENCODERS = (
    "h264_nvenc", "hevc_nvenc", "av1_nvenc",
    "h264_qsv", "hevc_qsv", "av1_qsv",
    "h264_vaapi", "hevc_vaapi", "av1_vaapi",
    "h264_amf", "hevc_amf", "av1_amf",
    "h264_videotoolbox", "hevc_videotoolbox",
    "libx264", "libx265", "libaom-av1", "libsvtav1", "libvpx-vp9",
)


# Per-encoder ffmpeg probe args — generates 1 frame to verify the encoder
# can actually initialize on this machine (driver/device/permission OK).
def _probe_args_for(encoder: str) -> list[str]:
    """Return ffmpeg arguments for a minimal one-frame probe of `encoder`.

    Returns the full argv tail (after the binary itself). Returns [] if we
    don't know how to probe this encoder.
    """
    common_in = [
        "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "nullsrc=size=256x256:duration=0.1",
    ]
    if encoder.endswith("_nvenc"):
        return [*common_in, "-c:v", encoder, "-frames:v", "1", "-f", "null", "-"]
    if encoder.endswith("_amf"):
        return [*common_in, "-c:v", encoder, "-frames:v", "1", "-f", "null", "-"]
    if encoder == "h264_videotoolbox" or encoder == "hevc_videotoolbox":
        return [*common_in, "-c:v", encoder, "-frames:v", "1", "-f", "null", "-"]
    if encoder.endswith("_vaapi"):
        # VAAPI probe needs vaapi_device + hwupload in filter chain.
        node = _first_render_node() or "/dev/dri/renderD128"
        return [
            "-hide_banner", "-loglevel", "error",
            "-vaapi_device", node,
            "-f", "lavfi", "-i", "nullsrc=size=256x256:duration=0.1",
            "-vf", "format=nv12,hwupload",
            "-c:v", encoder, "-frames:v", "1", "-f", "null", "-",
        ]
    if encoder.endswith("_qsv"):
        return [
            "-hide_banner", "-loglevel", "error",
            "-init_hw_device", "qsv=hw", "-filter_hw_device", "hw",
            "-f", "lavfi", "-i", "nullsrc=size=256x256:duration=0.1",
            "-vf", "format=nv12,hwupload=extra_hw_frames=64",
            "-c:v", encoder, "-frames:v", "1", "-f", "null", "-",
        ]
    return []


def _first_render_node() -> str | None:
    """Pick the first /dev/dri/renderD* on Linux."""
    if platform.system() != "Linux":
        return None
    try:
        nodes = sorted(os.listdir("/dev/dri"))
    except OSError:
        return None
    for n in nodes:
        if n.startswith("renderD"):
            return f"/dev/dri/{n}"
    return None


@lru_cache(maxsize=64)
def probe_encoder(encoder: str, timeout: float = 8.0) -> bool:
    """Functionally test whether `encoder` can initialize on this machine.

    Cached per-encoder. CPU encoders (libx*) always return True if listed.
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    if encoder.startswith("lib"):
        return True  # software encoders don't need device probe
    args = _probe_args_for(encoder)
    if not args:
        return True  # unknown encoder kind — assume listed = ok
    try:
        r = subprocess.run([ffmpeg, *args], capture_output=True, timeout=timeout)
        ok = (r.returncode == 0)
        if not ok:
            log.debug("encoder probe failed for %s: %s", encoder,
                      r.stderr.decode("utf-8", errors="replace")[-300:])
        return ok
    except (subprocess.SubprocessError, OSError) as exc:
        log.debug("encoder probe exception for %s: %s", encoder, exc)
        return False


def _list_ffmpeg_encoders(ffmpeg: str) -> frozenset[str]:
    try:
        out = subprocess.run(
            [ffmpeg, "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=10,
        ).stdout
    except (subprocess.SubprocessError, FileNotFoundError):
        return frozenset()
    found: set[str] = set()
    for line in out.splitlines():
        line = line.strip()
        # ffmpeg encoder list format: " V..... libx264   H.264 ..."
        m = re.match(r"^[VAS][.A-Z]{5}\s+(\S+)", line)
        if m and m.group(1) in _INTERESTING_ENCODERS:
            found.add(m.group(1))
    return frozenset(found)


def _detect_nvidia_gpus() -> list[GpuInfo]:
    nv = shutil.which("nvidia-smi")
    if not nv:
        return []
    try:
        out = subprocess.run(
            [nv, "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5,
        ).stdout
    except subprocess.SubprocessError:
        return []
    gpus: list[GpuInfo] = []
    for line in out.strip().splitlines():
        name = line.strip()
        if not name:
            continue
        gpus.append(GpuInfo(vendor="nvidia", name=name, encoders=()))
    return gpus


def _detect_other_gpus() -> list[GpuInfo]:
    """Best-effort detection of Intel/AMD GPUs on Linux via lspci."""
    lspci = shutil.which("lspci")
    if not lspci:
        return []
    try:
        out = subprocess.run([lspci], capture_output=True, text=True, timeout=5).stdout
    except subprocess.SubprocessError:
        return []
    gpus: list[GpuInfo] = []
    for line in out.splitlines():
        low = line.lower()
        if "vga" not in low and "3d controller" not in low and "display" not in low:
            continue
        if "nvidia" in low:
            continue  # handled by nvidia-smi path
        vendor = "intel" if "intel" in low else "amd" if ("amd" in low or "ati" in low) else "unknown"
        name = line.split(":", 2)[-1].strip()
        gpus.append(GpuInfo(vendor=vendor, name=name, encoders=()))
    return gpus


def _detect_apple_gpu() -> list[GpuInfo]:
    """Detect Apple Silicon / Intel Mac GPU on macOS."""
    if platform.system() != "Darwin":
        return []
    machine = platform.machine()  # "arm64" or "x86_64"
    if machine == "arm64":
        name = "Apple Silicon"
    else:
        # Best-effort; system_profiler is slow, skip detail.
        name = "Apple Mac GPU"
    return [GpuInfo(vendor="apple", name=name, encoders=())]


def _detect_windows_gpus() -> list[GpuInfo]:
    """Detect GPUs on Windows via WMI / PowerShell."""
    if platform.system() != "Windows":
        return []
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"],
            capture_output=True, text=True, timeout=10,
        ).stdout
    except (subprocess.SubprocessError, FileNotFoundError):
        return []
    gpus: list[GpuInfo] = []
    for raw in out.splitlines():
        name = raw.strip()
        if not name:
            continue
        low = name.lower()
        if "nvidia" in low:
            continue  # handled by nvidia-smi
        vendor = "intel" if "intel" in low else "amd" if ("amd" in low or "radeon" in low) else "unknown"
        gpus.append(GpuInfo(vendor=vendor, name=name, encoders=()))
    return gpus


def _ram_mb() -> int:
    sys = platform.system()
    if sys == "Linux":
        try:
            with open("/proc/meminfo", encoding="ascii") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        kb = int(line.split()[1])
                        return kb // 1024
        except (OSError, ValueError):
            pass
    elif sys == "Darwin":
        try:
            out = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True, text=True, timeout=3, check=True,
            ).stdout.strip()
            return int(out) // (1024 * 1024)
        except (subprocess.SubprocessError, ValueError, FileNotFoundError):
            pass
    elif sys == "Windows":
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory"],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()
            return int(out) // (1024 * 1024)
        except (subprocess.SubprocessError, ValueError, FileNotFoundError):
            pass
    return 0


def _assign_encoders_to_gpus(gpus: list[GpuInfo], encoders: frozenset[str]) -> list[GpuInfo]:
    out: list[GpuInfo] = []
    for g in gpus:
        if g.vendor == "nvidia":
            enc = tuple(e for e in encoders if e.endswith("_nvenc"))
        elif g.vendor == "intel":
            enc = tuple(e for e in encoders if e.endswith("_qsv") or e.endswith("_vaapi"))
        elif g.vendor == "amd":
            enc = tuple(e for e in encoders if e.endswith("_amf") or e.endswith("_vaapi"))
        elif g.vendor == "apple":
            enc = tuple(e for e in encoders if "videotoolbox" in e)
        else:
            enc = ()
        out.append(GpuInfo(vendor=g.vendor, name=g.name, encoders=enc))
    return out


@lru_cache(maxsize=1)
def detect() -> HardwareInfo:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    encoders = _list_ffmpeg_encoders(ffmpeg) if ffmpeg else frozenset()

    gpus_raw = (
        _detect_nvidia_gpus()
        + _detect_other_gpus()       # Linux Intel/AMD
        + _detect_apple_gpu()        # macOS
        + _detect_windows_gpus()     # Windows Intel/AMD
    )
    gpus = tuple(_assign_encoders_to_gpus(gpus_raw, encoders))

    info = HardwareInfo(
        cpu_count=os.cpu_count() or 1,
        cpu_logical=os.cpu_count() or 1,
        ram_total_mb=_ram_mb(),
        ffmpeg_path=ffmpeg,
        ffprobe_path=ffprobe,
        gpus=gpus,
        available_encoders=encoders,
    )
    log.info(
        "Detected: %d CPU, %d MB RAM, %d GPU(s), encoders=%s",
        info.cpu_count, info.ram_total_mb, len(info.gpus),
        sorted(info.available_encoders),
    )
    return info


def reset_cache() -> None:
    detect.cache_clear()

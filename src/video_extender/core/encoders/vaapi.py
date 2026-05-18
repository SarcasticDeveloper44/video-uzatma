"""VAAPI encoder (Intel + AMD GPUs on Linux) — h264 and hevc.

VAAPI requires an explicit hardware device. ffmpeg accepts:
    -vaapi_device /dev/dri/renderD128 ...
and the filter chain must upload frames via `format=nv12,hwupload`.

Common render nodes:
    /dev/dri/renderD128 (first GPU)
    /dev/dri/renderD129 (second GPU, e.g. discrete + iGPU)
"""
from __future__ import annotations

import os
from pathlib import Path

from video_extender.core.encoders.base import EncoderArgs, EncoderBackend


def _detect_render_node() -> str:
    """Find the first available DRM render node on Linux."""
    if not os.name == "posix":
        return "/dev/dri/renderD128"
    drm_dir = Path("/dev/dri")
    if not drm_dir.exists():
        return "/dev/dri/renderD128"  # best-effort default
    nodes = sorted(p for p in drm_dir.iterdir() if p.name.startswith("renderD"))
    return str(nodes[0]) if nodes else "/dev/dri/renderD128"


def _vaapi_common_args(ffmpeg_encoder: str, bitrate_kbps: int, crf: int | None) -> list[str]:
    v: list[str] = ["-c:v", ffmpeg_encoder]
    if crf is not None:
        # VAAPI uses -qp (or -global_quality for some impls); -qp is widely supported.
        v += ["-qp", str(max(0, min(51, crf)))]
    else:
        v += [
            "-b:v", f"{bitrate_kbps}k",
            "-maxrate", f"{int(bitrate_kbps * 1.5)}k",
            "-bufsize", f"{bitrate_kbps * 2}k",
            "-rc_mode", "VBR",
        ]
    return v


class VaapiH264(EncoderBackend):
    name = "vaapi_h264"
    label = "VAAPI H.264 (GPU, Intel/AMD)"
    ffmpeg_encoder = "h264_vaapi"
    kind = "gpu"
    codec = "h264"

    def build_args(
        self,
        *,
        bitrate_kbps: int,
        audio_bitrate_kbps: int,
        crf: int | None,
        gpu_index: int | None,
        threads: int,
        extra: dict | None = None,
    ) -> EncoderArgs:
        render_node = (extra or {}).get("render_node") or _detect_render_node()
        v = _vaapi_common_args(self.ffmpeg_encoder, bitrate_kbps, crf)
        v += ["-profile:v", "high"]
        return EncoderArgs(
            video_args=tuple(v),
            audio_args=("-c:a", "aac", "-b:a", f"{audio_bitrate_kbps}k"),
            container_args=("-movflags", "+faststart"),
            preferred_ext="mp4",
            hw_init_args=("-vaapi_device", render_node),
            gpu_upload_filter="format=nv12,hwupload",
        )


class VaapiHevc(EncoderBackend):
    name = "vaapi_hevc"
    label = "VAAPI HEVC (GPU, Intel/AMD)"
    ffmpeg_encoder = "hevc_vaapi"
    kind = "gpu"
    codec = "hevc"

    def build_args(
        self,
        *,
        bitrate_kbps: int,
        audio_bitrate_kbps: int,
        crf: int | None,
        gpu_index: int | None,
        threads: int,
        extra: dict | None = None,
    ) -> EncoderArgs:
        render_node = (extra or {}).get("render_node") or _detect_render_node()
        hevc_bitrate = int(bitrate_kbps * 0.7)
        v = _vaapi_common_args(self.ffmpeg_encoder, hevc_bitrate, crf)
        v += ["-tag:v", "hvc1", "-profile:v", "main"]
        return EncoderArgs(
            video_args=tuple(v),
            audio_args=("-c:a", "aac", "-b:a", f"{audio_bitrate_kbps}k"),
            container_args=("-movflags", "+faststart"),
            preferred_ext="mp4",
            hw_init_args=("-vaapi_device", render_node),
            gpu_upload_filter="format=nv12,hwupload",
        )

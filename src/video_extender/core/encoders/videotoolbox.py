"""Apple VideoToolbox encoder — h264 and hevc on macOS.

Native hardware encoding on Apple Silicon and Intel Macs. Accepts CPU
pixel formats directly. ProRes / HEVC HDR support also available but
we focus on H.264/HEVC for ad delivery.
"""
from __future__ import annotations

from video_extender.core.encoders.base import EncoderArgs, EncoderBackend


def _vt_common_args(ffmpeg_encoder: str, bitrate_kbps: int, crf: int | None) -> list[str]:
    v: list[str] = [
        "-c:v", ffmpeg_encoder,
        # VideoToolbox uses -q:v for constant-quality (1..100 scale, higher = better)
        # or -b:v for ABR. We map CRF→q:v inversely.
    ]
    if crf is not None:
        q_scale = max(1, min(100, int(round((51 - crf) / 51 * 100))))
        v += ["-q:v", str(q_scale)]
    else:
        v += [
            "-b:v", f"{bitrate_kbps}k",
            "-maxrate", f"{int(bitrate_kbps * 1.5)}k",
            "-bufsize", f"{bitrate_kbps * 2}k",
        ]
    return v


class VideoToolboxH264(EncoderBackend):
    name = "videotoolbox_h264"
    label = "Apple VideoToolbox H.264 (GPU)"
    ffmpeg_encoder = "h264_videotoolbox"
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
        v = _vt_common_args(self.ffmpeg_encoder, bitrate_kbps, crf)
        v += ["-pix_fmt", "yuv420p", "-profile:v", "high"]
        return EncoderArgs(
            video_args=tuple(v),
            audio_args=("-c:a", "aac", "-b:a", f"{audio_bitrate_kbps}k"),
            container_args=("-movflags", "+faststart"),
            preferred_ext="mp4",
        )


class VideoToolboxHevc(EncoderBackend):
    name = "videotoolbox_hevc"
    label = "Apple VideoToolbox HEVC (GPU)"
    ffmpeg_encoder = "hevc_videotoolbox"
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
        hevc_bitrate = int(bitrate_kbps * 0.7)
        v = _vt_common_args(self.ffmpeg_encoder, hevc_bitrate, crf)
        v += ["-pix_fmt", "yuv420p", "-tag:v", "hvc1", "-profile:v", "main"]
        return EncoderArgs(
            video_args=tuple(v),
            audio_args=("-c:a", "aac", "-b:a", f"{audio_bitrate_kbps}k"),
            container_args=("-movflags", "+faststart"),
            preferred_ext="mp4",
        )

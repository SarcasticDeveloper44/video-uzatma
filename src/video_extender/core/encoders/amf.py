"""AMD AMF encoder — h264 and hevc.

AMF (Advanced Media Framework) is AMD's hardware encoding API. It's available
on Windows natively and on Linux via the ROCm/AMF runtime. Unlike VAAPI/QSV,
AMF on ffmpeg accepts CPU pixel formats directly — no hwupload needed.
"""
from __future__ import annotations

from video_extender.core.encoders.base import EncoderArgs, EncoderBackend


def _amf_common_args(ffmpeg_encoder: str, bitrate_kbps: int, crf: int | None) -> list[str]:
    v: list[str] = [
        "-c:v", ffmpeg_encoder,
        "-usage", "transcoding",
        "-quality", "balanced",
    ]
    if crf is not None:
        # AMF uses -qp_p / -qp_i for quality mode.
        v += ["-rc", "cqp", "-qp_i", str(crf), "-qp_p", str(crf)]
    else:
        v += [
            "-rc", "vbr_latency",
            "-b:v", f"{bitrate_kbps}k",
            "-maxrate", f"{int(bitrate_kbps * 1.5)}k",
        ]
    return v


class AmfH264(EncoderBackend):
    name = "amf_h264"
    label = "AMD AMF H.264 (GPU)"
    ffmpeg_encoder = "h264_amf"
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
        v = _amf_common_args(self.ffmpeg_encoder, bitrate_kbps, crf)
        v += ["-pix_fmt", "yuv420p", "-profile:v", "high"]
        return EncoderArgs(
            video_args=tuple(v),
            audio_args=("-c:a", "aac", "-b:a", f"{audio_bitrate_kbps}k"),
            container_args=("-movflags", "+faststart"),
            preferred_ext="mp4",
        )


class AmfHevc(EncoderBackend):
    name = "amf_hevc"
    label = "AMD AMF HEVC (GPU)"
    ffmpeg_encoder = "hevc_amf"
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
        v = _amf_common_args(self.ffmpeg_encoder, hevc_bitrate, crf)
        v += ["-pix_fmt", "yuv420p", "-tag:v", "hvc1", "-profile:v", "main"]
        return EncoderArgs(
            video_args=tuple(v),
            audio_args=("-c:a", "aac", "-b:a", f"{audio_bitrate_kbps}k"),
            container_args=("-movflags", "+faststart"),
            preferred_ext="mp4",
        )

"""Intel QuickSync (QSV) encoder — h264 and hevc.

QSV uses Intel's Media SDK / oneVPL. ffmpeg initialization via either:
    -init_hw_device qsv=hw                          (auto)
    -init_hw_device qsv=hw,vendor_id=0x8086         (explicit)

Filter chain must end in nv12 + hwupload to feed QSV frames.
On Linux, QSV often shares the VA-API driver, so ensure libva-intel-driver
or intel-media-driver is installed.
"""
from __future__ import annotations

from video_extender.core.encoders.base import EncoderArgs, EncoderBackend


def _qsv_common_args(ffmpeg_encoder: str, bitrate_kbps: int, crf: int | None) -> list[str]:
    v: list[str] = [
        "-c:v", ffmpeg_encoder,
        "-preset", "medium",
        "-look_ahead", "1",
    ]
    if crf is not None:
        # QSV uses -global_quality with -look_ahead for ICQ mode.
        v += ["-global_quality", str(max(0, min(51, crf)))]
    else:
        v += [
            "-b:v", f"{bitrate_kbps}k",
            "-maxrate", f"{int(bitrate_kbps * 1.5)}k",
            "-bufsize", f"{bitrate_kbps * 2}k",
        ]
    return v


class QsvH264(EncoderBackend):
    name = "qsv_h264"
    label = "Intel QuickSync H.264 (GPU)"
    ffmpeg_encoder = "h264_qsv"
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
        v = _qsv_common_args(self.ffmpeg_encoder, bitrate_kbps, crf)
        v += ["-profile:v", "high"]
        return EncoderArgs(
            video_args=tuple(v),
            audio_args=("-c:a", "aac", "-b:a", f"{audio_bitrate_kbps}k"),
            container_args=("-movflags", "+faststart"),
            preferred_ext="mp4",
            hw_init_args=("-init_hw_device", "qsv=hw", "-filter_hw_device", "hw"),
            gpu_upload_filter="format=nv12,hwupload=extra_hw_frames=64",
        )


class QsvHevc(EncoderBackend):
    name = "qsv_hevc"
    label = "Intel QuickSync HEVC (GPU)"
    ffmpeg_encoder = "hevc_qsv"
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
        v = _qsv_common_args(self.ffmpeg_encoder, hevc_bitrate, crf)
        v += ["-tag:v", "hvc1", "-profile:v", "main"]
        return EncoderArgs(
            video_args=tuple(v),
            audio_args=("-c:a", "aac", "-b:a", f"{audio_bitrate_kbps}k"),
            container_args=("-movflags", "+faststart"),
            preferred_ext="mp4",
            hw_init_args=("-init_hw_device", "qsv=hw", "-filter_hw_device", "hw"),
            gpu_upload_filter="format=nv12,hwupload=extra_hw_frames=64",
        )

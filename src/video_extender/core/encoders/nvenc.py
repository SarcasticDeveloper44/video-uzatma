"""NVIDIA NVENC encoders (h264, hevc, av1)."""
from __future__ import annotations

from video_extender.core.encoders.base import EncoderArgs, EncoderBackend


class NvencH264(EncoderBackend):
    name = "nvenc_h264"
    label = "NVIDIA NVENC H.264 (GPU)"
    ffmpeg_encoder = "h264_nvenc"
    kind = "gpu"

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
        # NVENC: use VBR with target bitrate; CQ when crf provided.
        v: list[str] = ["-c:v", self.ffmpeg_encoder, "-preset", "p5", "-tune", "hq"]
        if gpu_index is not None:
            v += ["-gpu", str(gpu_index)]
        if crf is not None:
            # NVENC uses -cq (constant quality) — map 0..51 roughly.
            v += ["-rc", "vbr", "-cq", str(max(0, min(51, crf))), "-b:v", "0"]
        else:
            v += [
                "-rc", "vbr",
                "-b:v", f"{bitrate_kbps}k",
                "-maxrate", f"{int(bitrate_kbps * 1.5)}k",
                "-bufsize", f"{bitrate_kbps * 2}k",
            ]
        v += ["-pix_fmt", "yuv420p", "-profile:v", "high"]

        a = ("-c:a", "aac", "-b:a", f"{audio_bitrate_kbps}k")
        c = ("-movflags", "+faststart")
        return EncoderArgs(video_args=tuple(v), audio_args=a, container_args=c, preferred_ext="mp4")


class NvencHevc(EncoderBackend):
    """NVENC HEVC — ~30% smaller files vs H.264 at same visual quality.

    NOTE: Some ad platforms (notably some Meta ad placements) prefer H.264.
    Use for storage/distribution, not always safe for direct ad upload.
    """
    name = "nvenc_hevc"
    label = "NVIDIA NVENC HEVC (GPU)"
    ffmpeg_encoder = "hevc_nvenc"
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
        # HEVC compresses ~30% better than H.264, so we drop the target bitrate
        # accordingly for similar perceived quality. tag:v hvc1 ensures iOS/Safari playback.
        v: list[str] = ["-c:v", self.ffmpeg_encoder, "-preset", "p5", "-tag:v", "hvc1"]
        if gpu_index is not None:
            v += ["-gpu", str(gpu_index)]
        hevc_bitrate = int(bitrate_kbps * 0.7)
        if crf is not None:
            v += ["-rc", "vbr", "-cq", str(max(0, min(51, crf))), "-b:v", "0"]
        else:
            v += [
                "-rc", "vbr",
                "-b:v", f"{hevc_bitrate}k",
                "-maxrate", f"{int(hevc_bitrate * 1.5)}k",
                "-bufsize", f"{hevc_bitrate * 2}k",
            ]
        v += ["-pix_fmt", "yuv420p", "-profile:v", "main"]
        return EncoderArgs(
            video_args=tuple(v),
            audio_args=("-c:a", "aac", "-b:a", f"{audio_bitrate_kbps}k"),
            container_args=("-movflags", "+faststart"),
            preferred_ext="mp4",
        )

"""libx265 (CPU HEVC) — best quality/size ratio, slowest."""
from __future__ import annotations

from video_extender.core.encoders.base import EncoderArgs, EncoderBackend


class Libx265(EncoderBackend):
    name = "libx265"
    label = "libx265 HEVC (CPU)"
    ffmpeg_encoder = "libx265"
    kind = "cpu"
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
        # HEVC is ~30% more efficient than H.264 — same visual at ~70% bitrate.
        hevc_bitrate = int(bitrate_kbps * 0.7)
        v: list[str] = [
            "-c:v", self.ffmpeg_encoder,
            "-preset", "medium",
            "-pix_fmt", "yuv420p",
            "-tag:v", "hvc1",  # iOS/Safari compat
            "-x265-params", "log-level=error",
            "-threads", str(max(1, threads)),
        ]
        if crf is not None:
            v += ["-crf", str(max(0, min(51, crf)))]
        else:
            v += [
                "-b:v", f"{hevc_bitrate}k",
                "-maxrate", f"{int(hevc_bitrate * 1.5)}k",
                "-bufsize", f"{hevc_bitrate * 2}k",
            ]
        return EncoderArgs(
            video_args=tuple(v),
            audio_args=("-c:a", "aac", "-b:a", f"{audio_bitrate_kbps}k"),
            container_args=("-movflags", "+faststart"),
            preferred_ext="mp4",
        )

"""libvpx-vp9 (CPU VP9) — YouTube/Google's preferred codec for VOD."""
from __future__ import annotations

from video_extender.core.encoders.base import EncoderArgs, EncoderBackend


class LibvpxVp9(EncoderBackend):
    name = "libvpx_vp9"
    label = "libvpx VP9 (CPU)"
    ffmpeg_encoder = "libvpx-vp9"
    kind = "cpu"
    codec = "vp9"

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
        # VP9 ~40% better than H.264 at same visual quality.
        vp9_bitrate = int(bitrate_kbps * 0.6)
        v: list[str] = [
            "-c:v", self.ffmpeg_encoder,
            "-deadline", "good",
            "-cpu-used", "2",
            "-row-mt", "1",
            "-pix_fmt", "yuv420p",
            "-threads", str(max(1, threads)),
        ]
        if crf is not None:
            v += ["-crf", str(max(0, min(63, crf))), "-b:v", "0"]
        else:
            v += [
                "-b:v", f"{vp9_bitrate}k",
                "-maxrate", f"{int(vp9_bitrate * 1.5)}k",
                "-bufsize", f"{vp9_bitrate * 2}k",
            ]
        # VP9 in webm by default, but mp4 also supported in modern ffmpeg.
        return EncoderArgs(
            video_args=tuple(v),
            audio_args=("-c:a", "libopus", "-b:a", f"{audio_bitrate_kbps}k"),
            container_args=(),
            preferred_ext="webm",
        )

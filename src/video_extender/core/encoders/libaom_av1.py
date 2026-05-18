"""libaom-av1 (CPU AV1) — high quality, slow."""
from __future__ import annotations

from video_extender.core.encoders.base import EncoderArgs, EncoderBackend


class LibaomAv1(EncoderBackend):
    name = "libaom_av1"
    label = "libaom AV1 (CPU)"
    ffmpeg_encoder = "libaom-av1"
    kind = "cpu"
    codec = "av1"

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
        # AV1 compresses ~50% better than H.264. Bitrate dropped further.
        av1_bitrate = int(bitrate_kbps * 0.55)
        v: list[str] = [
            "-c:v", self.ffmpeg_encoder,
            "-row-mt", "1",
            "-cpu-used", "6",   # 0=slowest/best, 8=fastest; 6 is a balanced default
            "-pix_fmt", "yuv420p",
            "-threads", str(max(1, threads)),
        ]
        if crf is not None:
            v += ["-crf", str(max(0, min(63, crf))), "-b:v", "0"]
        else:
            v += [
                "-b:v", f"{av1_bitrate}k",
                "-maxrate", f"{int(av1_bitrate * 1.5)}k",
                "-bufsize", f"{av1_bitrate * 2}k",
            ]
        return EncoderArgs(
            video_args=tuple(v),
            audio_args=("-c:a", "aac", "-b:a", f"{audio_bitrate_kbps}k"),
            container_args=("-movflags", "+faststart"),
            preferred_ext="mp4",
        )


class LibSvtAv1(EncoderBackend):
    """SVT-AV1 — much faster than libaom for AV1, recommended default for CPU AV1."""
    name = "libsvtav1"
    label = "SVT-AV1 (CPU, hızlı)"
    ffmpeg_encoder = "libsvtav1"
    kind = "cpu"
    codec = "av1"

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
        av1_bitrate = int(bitrate_kbps * 0.55)
        v: list[str] = [
            "-c:v", self.ffmpeg_encoder,
            "-preset", "6",      # 0..13; lower = slower/better
            "-pix_fmt", "yuv420p",
            "-threads", str(max(1, threads)),
        ]
        if crf is not None:
            v += ["-crf", str(max(0, min(63, crf))), "-b:v", "0"]
        else:
            v += [
                "-b:v", f"{av1_bitrate}k",
                "-maxrate", f"{int(av1_bitrate * 1.5)}k",
                "-bufsize", f"{av1_bitrate * 2}k",
            ]
        return EncoderArgs(
            video_args=tuple(v),
            audio_args=("-c:a", "aac", "-b:a", f"{audio_bitrate_kbps}k"),
            container_args=("-movflags", "+faststart"),
            preferred_ext="mp4",
        )

"""libx264 (CPU H.264) — universal fallback and high-quality reference."""
from __future__ import annotations
from typing import Any

from video_extender.core.encoders.base import EncoderArgs, EncoderBackend

_X264_PRESET_BY_HINT = {"speed": "fast", "quality": "slow"}


def _x264_preset(extra: dict[str, Any] | None) -> str:
    extra = extra or {}
    if "preset" in extra:
        return str(extra["preset"])
    hint = extra.get("preset_hint")
    if hint in _X264_PRESET_BY_HINT:
        return _X264_PRESET_BY_HINT[hint]
    return "medium"


class Libx264(EncoderBackend):
    name = "libx264"
    label = "libx264 H.264 (CPU)"
    ffmpeg_encoder = "libx264"
    kind = "cpu"

    def build_args(
        self,
        *,
        bitrate_kbps: int,
        audio_bitrate_kbps: int,
        crf: int | None,
        gpu_index: int | None,
        threads: int,
        extra: dict[str, Any] | None = None,
    ) -> EncoderArgs:
        v: list[str] = [
            "-c:v", self.ffmpeg_encoder,
            "-preset", _x264_preset(extra),
            "-pix_fmt", "yuv420p",
            "-profile:v", "high",
            "-threads", str(max(1, threads)),
        ]
        if crf is not None:
            v += ["-crf", str(max(0, min(51, crf)))]
        else:
            v += [
                "-b:v", f"{bitrate_kbps}k",
                "-maxrate", f"{int(bitrate_kbps * 1.5)}k",
                "-bufsize", f"{bitrate_kbps * 2}k",
            ]
        return EncoderArgs(
            video_args=tuple(v),
            audio_args=("-c:a", "aac", "-b:a", f"{audio_bitrate_kbps}k"),
            container_args=("-movflags", "+faststart"),
            preferred_ext="mp4",
        )

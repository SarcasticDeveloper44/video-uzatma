"""Pad with a black screen (and silence) to reach the target duration."""
from __future__ import annotations
from typing import Any

from pathlib import Path

from video_extender.core.extenders.base import ExtenderPlan, ExtenderStrategy
from video_extender.utils.ffprobe_parser import MediaInfo


class BlackExtender(ExtenderStrategy):
    name = "black"
    label = "Siyah ekran"
    description = "Video bitince siyah ekran ve sessizlik (en küçük dosya boyutu)."

    def build_plan(
        self,
        source: Path,
        media: MediaInfo,
        target_duration: float,
        *,
        audio_fade_out_seconds: float = 1.5,
        options: dict[str, Any] | None = None,
    ) -> ExtenderPlan:
        if media.video is None:
            raise ValueError(f"No video stream in {source}")

        # tpad with color=black appends black frames of matching size/fps to
        # the source. tpad keeps source SAR; color frames inherit the input
        # pixel format on concat, so we don't need to specify dimensions here.
        video_fc = (
            f"[0:v]tpad=stop_mode=add:stop_duration={target_duration - media.duration:.3f}"
            f":color=black[vout]"
        )

        if media.audio is None:
            audio_fc = (
                f"anullsrc=channel_layout=stereo:sample_rate=44100,atrim=duration={target_duration:.3f}[aout]"
            )
            return ExtenderPlan(
                filtergraph=f"{video_fc};{audio_fc}",
                video_label="[vout]",
                audio_label="[aout]",
            )

        fade_start = max(0.0, media.duration - audio_fade_out_seconds)
        fade_dur = min(audio_fade_out_seconds, media.duration)
        audio_fc = (
            f"[0:a]afade=t=out:st={fade_start:.3f}:d={fade_dur:.3f},"
            f"apad=whole_dur={target_duration:.3f}[aout]"
        )
        return ExtenderPlan(
            filtergraph=f"{video_fc};{audio_fc}",
            video_label="[vout]",
            audio_label="[aout]",
        )

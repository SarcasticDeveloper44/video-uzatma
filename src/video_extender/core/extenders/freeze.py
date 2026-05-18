"""Freeze the last frame and pad audio with silence (with optional fade-out)."""
from __future__ import annotations

from pathlib import Path

from video_extender.core.extenders.base import ExtenderPlan, ExtenderStrategy
from video_extender.utils.ffprobe_parser import MediaInfo


class FreezeExtender(ExtenderStrategy):
    name = "freeze"
    label = "Son kareyi dondur"
    description = "Videonun son karesi sona kadar sabit kalır; ses fade-out + sessizlik."

    def build_plan(
        self,
        source: Path,
        media: MediaInfo,
        target_duration: float,
        *,
        audio_fade_out_seconds: float = 1.5,
        options: dict | None = None,
    ) -> ExtenderPlan:
        # tpad clones the last frame to extend video to target duration.
        # apad pads audio with silence; afade fades audio out smoothly before silence.
        target_ms = max(int(target_duration * 1000), int(media.duration * 1000))

        video_fc = f"[0:v]tpad=stop_mode=clone:stop_duration={target_duration - media.duration:.3f}[vout]"

        if media.audio is None:
            # No audio in source: synthesize silent track for the full target duration.
            audio_fc = (
                f"anullsrc=channel_layout=stereo:sample_rate=44100,atrim=duration={target_duration:.3f}[aout]"
            )
            filtergraph = f"{video_fc};{audio_fc}"
            return ExtenderPlan(
                filtergraph=filtergraph,
                video_label="[vout]",
                audio_label="[aout]",
            )

        fade_start = max(0.0, media.duration - audio_fade_out_seconds)
        fade_dur = min(audio_fade_out_seconds, media.duration)
        audio_fc = (
            f"[0:a]afade=t=out:st={fade_start:.3f}:d={fade_dur:.3f},"
            f"apad=whole_dur={target_duration:.3f}[aout]"
        )
        filtergraph = f"{video_fc};{audio_fc}"
        return ExtenderPlan(
            filtergraph=filtergraph,
            video_label="[vout]",
            audio_label="[aout]",
        )

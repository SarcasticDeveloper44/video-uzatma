"""Loop the source video to reach target duration."""
from __future__ import annotations

from pathlib import Path

from video_extender.core.extenders.base import ExtenderPlan, ExtenderStrategy
from video_extender.utils.ffprobe_parser import MediaInfo


class LoopExtender(ExtenderStrategy):
    name = "loop"
    label = "Döngü (loop)"
    description = "Video baştan başlar ve hedef süreye kadar tekrar eder."

    def build_plan(
        self,
        source: Path,
        media: MediaInfo,
        target_duration: float,
        *,
        audio_fade_out_seconds: float = 1.5,
        options: dict | None = None,
    ) -> ExtenderPlan:
        # `-stream_loop -1` repeats the input infinitely; final duration capped by `-t`
        # applied at output. We also explicitly trim via filter to be deterministic.
        # The input loop affects ffmpeg input args, so we expose that via extra_input_args.
        # Here input idx 0 (the source) has `-stream_loop -1` flag.
        video_fc = f"[0:v]trim=duration={target_duration:.3f},setpts=PTS-STARTPTS[vout]"

        if media.audio is None:
            audio_fc = (
                f"anullsrc=channel_layout=stereo:sample_rate=44100,atrim=duration={target_duration:.3f}[aout]"
            )
        else:
            audio_fc = (
                f"[0:a]atrim=duration={target_duration:.3f},asetpts=PTS-STARTPTS[aout]"
            )

        return ExtenderPlan(
            filtergraph=f"{video_fc};{audio_fc}",
            video_label="[vout]",
            audio_label="[aout]",
            source_input_args=("-stream_loop", "-1"),
        )

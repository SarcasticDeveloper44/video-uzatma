"""Loop the source video to reach target duration."""
from __future__ import annotations
from typing import Any

from pathlib import Path

from video_extender.core.encoders.base import EncoderArgs, EncoderBackend
from video_extender.core.extenders.base import ExtenderPlan, ExtenderStrategy
from video_extender.core.fast_path import FastPathPlan
from video_extender.core.scheduler import WorkerSlot
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
        options: dict[str, Any] | None = None,
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

    def build_fast_path(
        self,
        *,
        source: Path,
        media: MediaInfo,
        target_duration: float,
        output: Path,
        encoder: EncoderBackend,
        encoder_args: EncoderArgs,
        slot: WorkerSlot,
        tmp_dir: Path,
        audio_fade_out_seconds: float,
        options: dict[str, Any] | None = None,
    ) -> FastPathPlan | None:
        """Loop with stream-copy: one ffmpeg call, NO re-encode.

            ffmpeg -stream_loop -1 -i source -c copy -t target out.mp4

        Works because the source is already in a target-compatible codec
        (caller verifies via fast_path.is_eligible). 100x+ faster than full
        re-encode.
        """
        cmd = [
            "-stream_loop", "-1",
            "-i", str(source),
            "-c", "copy",
            "-t", f"{target_duration:.3f}",
            *encoder_args.container_args,  # -movflags +faststart
            str(output),
        ]
        return FastPathPlan(commands=[cmd], temp_files=[], output=output)

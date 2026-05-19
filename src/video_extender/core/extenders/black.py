"""Pad with a black screen (and silence) to reach the target duration."""
from __future__ import annotations
from typing import Any

from pathlib import Path

from video_extender.core.encoders.base import EncoderArgs, EncoderBackend
from video_extender.core.extenders.base import ExtenderPlan, ExtenderStrategy
from video_extender.core.fast_path import FastPathPlan
from video_extender.core.scheduler import WorkerSlot
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
        """Two-stage fast path:
          1) Encode the black tail from lavfi (no source decode needed —
             generates frames synthetically; ~100x faster than encoding
             content from the source).
          2) Concat source + tail with -c copy.
        """
        if media.video is None:
            return None
        tail_dur = max(0.0, target_duration - media.duration)
        if tail_dur < 0.05:
            return None
        fps = media.video.fps if media.video.fps > 0 else 30.0
        W, H = media.video.width, media.video.height

        tmp_dir.mkdir(parents=True, exist_ok=True)
        tail = tmp_dir / f"black_tail_{source.stem}.mp4"
        listfile = tmp_dir / f"black_concat_{source.stem}.txt"
        listfile.write_text(
            f"file '{source.resolve().as_posix()}'\n"
            f"file '{tail.resolve().as_posix()}'\n",
            encoding="utf-8",
        )

        encode_cmd = [
            "-f", "lavfi", "-i",
            f"color=c=black:s={W}x{H}:r={fps}:d={tail_dur:.3f}",
            "-f", "lavfi", "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-vf", "format=yuv420p",
            *encoder_args.video_args,
            *encoder_args.audio_args,
            "-shortest", "-t", f"{tail_dur:.3f}",
            str(tail),
        ]
        concat_cmd = [
            "-f", "concat", "-safe", "0",
            "-i", str(listfile),
            "-c", "copy",
            *encoder_args.container_args,
            str(output),
        ]
        return FastPathPlan(
            commands=[encode_cmd, concat_cmd],
            temp_files=[tail, listfile],
            output=output,
        )

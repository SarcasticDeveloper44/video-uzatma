"""Freeze the last frame and pad audio with silence (with optional fade-out)."""
from __future__ import annotations
from typing import Any

from pathlib import Path

from video_extender.core.encoders.base import EncoderArgs, EncoderBackend
from video_extender.core.extenders.base import ExtenderPlan, ExtenderStrategy
from video_extender.core.fast_path import FastPathPlan
from video_extender.core.scheduler import WorkerSlot
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
        options: dict[str, Any] | None = None,
    ) -> ExtenderPlan:
        # tpad clones the last frame to extend video to target duration.
        # apad pads audio with silence; afade fades audio out smoothly before silence.
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
        """Three-stage fast path:
          1) Extract the source's last frame to a PNG (cheap).
          2) Encode the freeze tail (static image + silence) at target params —
             a static-content encode is ~100x faster than encoding moving video.
          3) Concat source + tail with -c copy (no re-decode of either).

        Total: a few seconds for tails that would otherwise take minutes.
        """
        if media.video is None:
            return None
        tail_dur = max(0.0, target_duration - media.duration)
        if tail_dur < 0.05:
            return None  # nothing to extend → standard pipeline handles trivially
        fps = media.video.fps if media.video.fps > 0 else 30.0
        W, H = media.video.width, media.video.height

        tmp_dir.mkdir(parents=True, exist_ok=True)
        last_frame = tmp_dir / f"freeze_lastframe_{source.stem}.png"
        tail = tmp_dir / f"freeze_tail_{source.stem}.mp4"
        listfile = tmp_dir / f"freeze_concat_{source.stem}.txt"
        listfile.write_text(
            f"file '{source.resolve().as_posix()}'\n"
            f"file '{tail.resolve().as_posix()}'\n",
            encoding="utf-8",
        )

        # 1) Extract last frame: seek to slightly before end, grab 1 frame.
        extract_cmd = [
            "-sseof", "-0.5",
            "-i", str(source),
            "-update", "1", "-frames:v", "1",
            str(last_frame),
        ]
        # 2) Encode tail: loop the still image + silent audio for tail_dur.
        encode_cmd = [
            "-loop", "1", "-framerate", f"{fps}",
            "-i", str(last_frame),
            "-f", "lavfi", "-i",
            f"anullsrc=channel_layout=stereo:sample_rate=44100",
            "-vf", f"scale={W}:{H},format=yuv420p",
            *encoder_args.video_args,
            *encoder_args.audio_args,
            "-shortest", "-t", f"{tail_dur:.3f}",
            str(tail),
        ]
        # 3) Concat with stream-copy.
        concat_cmd = [
            "-f", "concat", "-safe", "0",
            "-i", str(listfile),
            "-c", "copy",
            *encoder_args.container_args,
            str(output),
        ]
        return FastPathPlan(
            commands=[extract_cmd, encode_cmd, concat_cmd],
            temp_files=[last_frame, tail, listfile],
            output=output,
        )

"""Append a static image (PNG/JPG end card / CTA) to the source video.

Useful for advertising: append a "Visit website" / "Swipe up" still image
to the end of a video.
"""
from __future__ import annotations
from typing import Any

from pathlib import Path

from video_extender.core.encoders.base import EncoderArgs, EncoderBackend
from video_extender.core.extenders.base import ExtenderPlan, ExtenderStrategy
from video_extender.core.fast_path import FastPathPlan
from video_extender.core.scheduler import WorkerSlot
from video_extender.utils.ffprobe_parser import MediaInfo


class ImageCardExtender(ExtenderStrategy):
    name = "image_card"
    label = "Bitiş kartı (resim)"
    description = "Video bitince sabit bir resim/CTA kartı gösterir. Sesi sessizlik veya orijinal ses fade-out."

    def build_plan(
        self,
        source: Path,
        media: MediaInfo,
        target_duration: float,
        *,
        audio_fade_out_seconds: float = 1.5,
        options: dict[str, Any] | None = None,
    ) -> ExtenderPlan:
        opts = options or {}
        image = opts.get("image")
        if not image:
            raise ValueError(
                "image_card extender requires options['image'] = path to a PNG/JPG"
            )
        image_path = Path(image)
        if not image_path.exists():
            raise FileNotFoundError(f"image file not found: {image_path}")

        if media.video is None:
            raise ValueError(f"source has no video stream: {source}")

        W, H = media.video.width, media.video.height
        fps = media.video.fps if media.video.fps > 0 else 30.0
        card_duration = max(0.0, target_duration - media.duration)
        # Cap card duration to a minimum of one frame; if no extension needed, no card.
        if card_duration < 0.05:
            # No extension needed — just re-encode source.
            video_fc = f"[0:v]setsar=1,fps={fps},format=yuv420p[vout]"
            if media.audio:
                audio_fc = "[0:a]aresample=44100[aout]"
            else:
                audio_fc = (
                    f"anullsrc=channel_layout=stereo:sample_rate=44100,"
                    f"atrim=duration={media.duration:.3f}[aout]"
                )
            return ExtenderPlan(
                filtergraph=f"{video_fc};{audio_fc}",
                video_label="[vout]",
                audio_label="[aout]",
            )

        # Image input is index 1; -loop 1 makes it an infinite frame stream.
        # Source normalized → [v_s][a_s]; image normalized → [v_c][a_c]; then concat.
        video_src = f"[0:v]setsar=1,fps={fps},format=yuv420p[v_s]"
        video_card = (
            f"[1:v]scale={W}:{H}:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps={fps},"
            f"format=yuv420p,trim=duration={card_duration:.3f},"
            f"setpts=PTS-STARTPTS[v_c]"
        )

        if media.audio:
            fade_start = max(0.0, media.duration - audio_fade_out_seconds)
            fade_dur = min(audio_fade_out_seconds, media.duration)
            audio_src = (
                f"[0:a]afade=t=out:st={fade_start:.3f}:d={fade_dur:.3f},"
                f"aresample=44100[a_s]"
            )
        else:
            audio_src = (
                f"anullsrc=channel_layout=stereo:sample_rate=44100,"
                f"atrim=duration={media.duration:.3f}[a_s]"
            )
        audio_card = (
            f"anullsrc=channel_layout=stereo:sample_rate=44100,"
            f"atrim=duration={card_duration:.3f}[a_c]"
        )

        filtergraph = ";".join([
            video_src, audio_src, video_card, audio_card,
            "[v_s][a_s][v_c][a_c]concat=n=2:v=1:a=1[vout][aout]",
        ])

        return ExtenderPlan(
            extra_inputs=(image_path,),
            extra_input_args=(("-loop", "1"),),
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
        """Two-stage fast path: encode looped image tail at target params,
        then concat-copy with the source. Same content shape as the full
        build_plan but with stream-copy of the source segment (3-10x faster
        for typical card durations).
        """
        if media.video is None:
            return None
        card_dur = max(0.0, target_duration - media.duration)
        if card_dur < 0.05:
            return None
        opts = options or {}
        image = opts.get("image")
        if not image:
            return None
        image_path = Path(image)
        if not image_path.exists():
            return None
        fps = media.video.fps if media.video.fps > 0 else 30.0
        W, H = media.video.width, media.video.height

        tmp_dir.mkdir(parents=True, exist_ok=True)
        tail = tmp_dir / f"card_tail_{source.stem}.mp4"
        listfile = tmp_dir / f"card_concat_{source.stem}.txt"
        listfile.write_text(
            f"file '{source.resolve().as_posix()}'\n"
            f"file '{tail.resolve().as_posix()}'\n",
            encoding="utf-8",
        )

        encode_cmd = [
            "-loop", "1", "-framerate", f"{fps}",
            "-i", str(image_path),
            "-f", "lavfi", "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-vf",
            f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:black,format=yuv420p",
            *encoder_args.video_args,
            *encoder_args.audio_args,
            "-shortest", "-t", f"{card_dur:.3f}",
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

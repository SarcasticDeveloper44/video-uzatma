"""Append a static image (PNG/JPG end card / CTA) to the source video.

Useful for advertising: append a "Visit website" / "Swipe up" still image
to the end of a video.
"""
from __future__ import annotations

from pathlib import Path

from video_extender.core.extenders.base import ExtenderPlan, ExtenderStrategy
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
        options: dict | None = None,
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

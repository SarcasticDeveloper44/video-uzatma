"""Append a user-supplied outro video (and optional intro) to the source.

Layout: [intro?] + source + [outro_loop_or_freeze_to_fill]

Behavior:
- `outro` is REQUIRED; without one, use the `freeze` or `black` extender instead.
- `intro` is optional (prepended to the front).
- All clips are normalized to the SOURCE video's resolution/SAR/fps and yuv420p.
- If intro_dur + source_dur + outro_dur >= target_duration: outro is trimmed.
- Else outro is stream-looped to fill the remaining duration.
- Missing audio in any clip is replaced with silence so concat=v=1:a=1 succeeds.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from video_extender.core.extenders.base import ExtenderPlan, ExtenderStrategy
from video_extender.utils.ffprobe_parser import MediaInfo, parse


def _probe(path: Path) -> MediaInfo:
    """Inline ffprobe to avoid importing FFmpegRunner into the build path."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, timeout=30,
    )
    if out.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {path}: {out.stderr.strip()}")
    return parse(json.loads(out.stdout), str(path))


class IntroOutroExtender(ExtenderStrategy):
    name = "intro_outro"
    label = "Intro/Outro klibi ekle"
    description = "Outro klibi sona ekler (gerekirse döngüye alır); opsiyonel intro önüne konur."

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
        outro_path = opts.get("outro")
        intro_path = opts.get("intro")

        if not outro_path:
            raise ValueError(
                "intro_outro extender requires options['outro'] = path to an outro clip"
            )
        outro_path = Path(outro_path)
        if not outro_path.exists():
            raise FileNotFoundError(f"outro file not found: {outro_path}")

        intro_media: MediaInfo | None = None
        if intro_path:
            intro_path = Path(intro_path)
            if not intro_path.exists():
                raise FileNotFoundError(f"intro file not found: {intro_path}")
            intro_media = _probe(intro_path)

        outro_media = _probe(outro_path)

        if media.video is None:
            raise ValueError(f"source has no video stream: {source}")

        W, H = media.video.width, media.video.height
        fps = media.video.fps if media.video.fps > 0 else 30.0
        intro_dur = intro_media.duration if intro_media else 0.0
        source_dur = media.duration
        outro_dur_avail = outro_media.duration

        outro_target = max(0.0, target_duration - intro_dur - source_dur)
        if outro_target <= 0.01:
            # Intro alone (+source) already meets target; output just intro+source.
            outro_target = 0.0

        # Decide whether outro needs looping.
        need_loop = outro_dur_avail > 0 and outro_target > outro_dur_avail + 0.05

        # ---- Inputs ----
        extra_inputs: list[Path] = []
        extra_input_args: list[tuple[str, ...]] = []
        # Source is always input #0 (no extra_input_args before it; pipeline owns that).
        # Order matters: extra_inputs are appended AFTER source.
        # We need intro before outro if both present (so indices are predictable).
        intro_idx: int | None = None
        outro_idx: int | None = None
        next_idx = 1
        if intro_media is not None and intro_path is not None:
            extra_inputs.append(intro_path)
            extra_input_args.append(())  # no per-input args for intro
            intro_idx = next_idx
            next_idx += 1
        if outro_target > 0:
            extra_inputs.append(outro_path)
            if need_loop:
                extra_input_args.append(("-stream_loop", "-1"))
            else:
                extra_input_args.append(())
            outro_idx = next_idx
            next_idx += 1

        # ---- Filtergraph ----
        # Normalizer template: scale-pad-to-fit, force SAR=1, fps, yuv420p.
        def vnorm(in_label: str, out_label: str, trim_dur: float | None = None) -> str:
            seg = (
                f"{in_label}scale={W}:{H}:force_original_aspect_ratio=decrease,"
                f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,"
                f"fps={fps},format=yuv420p"
            )
            if trim_dur is not None:
                seg += f",trim=duration={trim_dur:.3f},setpts=PTS-STARTPTS"
            seg += out_label
            return seg

        def anorm(stream_index: int, in_audio: str | None, out_label: str, dur: float) -> str:
            """Audio normalize: if source has audio, resample; else synth silence."""
            if in_audio:
                return (
                    f"{in_audio}aresample=44100:async=1,asetpts=PTS-STARTPTS,"
                    f"atrim=duration={dur:.3f}{out_label}"
                )
            return (
                f"anullsrc=channel_layout=stereo:sample_rate=44100,"
                f"atrim=duration={dur:.3f}{out_label}"
            )

        fc_parts: list[str] = []
        concat_inputs: list[str] = []

        # Intro normalization
        if intro_idx is not None and intro_media is not None:
            fc_parts.append(vnorm(f"[{intro_idx}:v]", "[v_i]"))
            if intro_media.audio:
                fc_parts.append(anorm(intro_idx, f"[{intro_idx}:a]", "[a_i]", intro_media.duration))
            else:
                fc_parts.append(anorm(intro_idx, None, "[a_i]", intro_media.duration))
            concat_inputs += ["[v_i]", "[a_i]"]

        # Source normalization (only setsar/fps/format — keep resolution as-is)
        fc_parts.append(
            f"[0:v]setsar=1,fps={fps},format=yuv420p[v_s]"
        )
        if media.audio:
            fc_parts.append(anorm(0, "[0:a]", "[a_s]", source_dur))
        else:
            fc_parts.append(anorm(0, None, "[a_s]", source_dur))
        concat_inputs += ["[v_s]", "[a_s]"]

        # Outro (with trim to fit remaining time)
        if outro_idx is not None and outro_target > 0:
            fc_parts.append(vnorm(f"[{outro_idx}:v]", "[v_o]", trim_dur=outro_target))
            if outro_media.audio:
                fc_parts.append(anorm(outro_idx, f"[{outro_idx}:a]", "[a_o]", outro_target))
            else:
                fc_parts.append(anorm(outro_idx, None, "[a_o]", outro_target))
            concat_inputs += ["[v_o]", "[a_o]"]

        n = len(concat_inputs) // 2
        fc_parts.append(
            "".join(concat_inputs) + f"concat=n={n}:v=1:a=1[vout][aout]"
        )

        return ExtenderPlan(
            extra_inputs=tuple(extra_inputs),
            extra_input_args=tuple(extra_input_args),
            filtergraph=";".join(fc_parts),
            video_label="[vout]",
            audio_label="[aout]",
        )

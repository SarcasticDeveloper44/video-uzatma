"""Append a user-supplied outro video (and optional intro) to the source.

Layout: [intro?] + source + [outro_loop_or_freeze_to_fill]

Behavior:
- `outro` is REQUIRED; without one, use the `freeze` or `black` extender instead.
- `intro` is optional (prepended to the front).
- All clips are normalized to the SOURCE video's resolution/SAR/fps and yuv420p.
- If intro_dur + source_dur + outro_dur >= target_duration: outro is trimmed.
- Else outro is stream-looped to fill the remaining duration.
- Missing audio in any clip is replaced with silence so concat=v=1:a=1 succeeds.

FAST PATH (v0.12.0+):
- When source video codec matches the target encoder codec and the filter
  chain is empty, build_fast_path pre-encodes intro + outro to source-
  matching params ONCE, caches them under the batch tmp dir, and uses
  concat-demux + -c copy to glue intro + source + outro. The 30-minute
  source no longer re-encodes — only intro/outro do (a few seconds total).
  For batches reusing the same intro/outro, the encoded files are cache
  hits on every job after the first.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

from video_extender.core.extenders.base import ExtenderPlan, ExtenderStrategy
from video_extender.core.fast_path import FastPathPlan
from video_extender.utils.ffprobe_parser import MediaInfo, parse

if TYPE_CHECKING:
    from video_extender.core.encoders.base import EncoderArgs, EncoderBackend
    from video_extender.core.scheduler import WorkerSlot


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
        options: dict[str, Any] | None = None,
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
        """Stream-copy concat fast path.

        Source stays as-is (no re-decode/re-encode) — its 30-minute body is
        the dominant cost of the standard path, and we sidestep it entirely.

        Intro and outro ARE re-encoded but only ONCE per (source-params,
        intro_or_outro_file) combination. The cache lives under tmp_dir so
        subsequent jobs in the same batch hit it instead of re-encoding
        their copy of the same intro/outro.

        Eligibility (checked here so the standard path absorbs anything
        unusual — e.g., source codec doesn't match target, intro/outro
        params would force re-encode on the source side):
          • outro option present and exists on disk
          • media.video known (probe succeeded)
          • source codec matches encoder.codec
          • source pix_fmt is yuv420p
          • source has audio (we'd need silent track gen otherwise — out
            of fast-path scope for now)
        """
        opts = options or {}
        outro_path_str = opts.get("outro", "")
        if not outro_path_str:
            return None
        outro_path = Path(outro_path_str)
        if not outro_path.exists():
            return None
        if media.video is None or media.audio is None:
            return None
        # Codec match between source and target encoder. Without this we'd
        # need to re-encode source too — defeating the fast path's purpose.
        codec_aliases = {
            "h264": {"h264", "avc", "avc1"},
            "hevc": {"hevc", "h265", "hev1", "hvc1"},
        }
        target_codec = encoder.codec
        valid_codecs = codec_aliases.get(target_codec, {target_codec})
        if media.video.codec not in valid_codecs:
            return None
        # Stream-copy concat is happiest when every clip shares pix_fmt.
        # yuv420p is the default we'd produce, so skip non-yuv420p sources.
        if media.video.pix_fmt != "yuv420p":
            return None
        # Audio: source must be AAC for stream-copy concat to work with
        # our re-encoded intro/outro (we always produce AAC for them).
        if media.audio.codec != "aac":
            return None

        # Probe intro if provided. Missing intro path is fine — we just
        # skip the intro segment.
        intro_path_str = opts.get("intro", "")
        intro_media: MediaInfo | None = None
        intro_path: Path | None = None
        if intro_path_str:
            ip = Path(intro_path_str)
            if not ip.exists():
                return None
            try:
                intro_media = _probe(ip)
            except Exception:  # noqa: BLE001
                return None
            intro_path = ip
        try:
            outro_media = _probe(outro_path)
        except Exception:  # noqa: BLE001
            return None

        W, H = media.video.width, media.video.height
        fps = media.video.fps if media.video.fps > 0 else 30.0
        sample_rate = media.audio.sample_rate or 44100

        intro_dur = intro_media.duration if intro_media else 0.0
        source_dur = media.duration
        outro_target = max(0.0, target_duration - intro_dur - source_dur)
        if outro_target <= 0.01:
            outro_target = 0.0

        # Cache files live in a shared subdir so jobs after the first one
        # in a batch hit the cache. Cleaned up at end of batch with the
        # rest of tmp_dir.
        cache_dir = tmp_dir / "intro_outro_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)

        # Identity tag — same (source params + intro/outro file + bitrate)
        # combination produces a reusable cache file.
        def _content_key(p: Path) -> str:
            try:
                st = p.stat()
                material = f"{p.resolve()}|{st.st_mtime_ns}|{st.st_size}"
            except OSError:
                material = str(p)
            return hashlib.sha1(material.encode("utf-8")).hexdigest()[:16]

        common_tag = (
            f"{W}x{H}_{fps:.2f}fps_{sample_rate}_"
            f"{target_codec}_{slot.encoder}"
        )

        commands: list[list[str]] = []
        concat_entries: list[str] = []

        # 1) Intro segment (if any)
        cached_intro: Path | None = None
        if intro_path is not None and intro_media is not None:
            intro_key = _content_key(intro_path)
            cached_intro = cache_dir / f"intro_{intro_key}_{common_tag}.mp4"
            if not cached_intro.exists():
                intro_audio_filter = (
                    f"aresample={sample_rate}:async=1,asetpts=PTS-STARTPTS,"
                    f"atrim=duration={intro_media.duration:.3f}"
                ) if intro_media.audio else (
                    f"anullsrc=channel_layout=stereo:sample_rate={sample_rate},"
                    f"atrim=duration={intro_media.duration:.3f}"
                )
                intro_audio_input = ["-i", str(intro_path)] if intro_media.audio else [
                    "-f", "lavfi", "-i",
                    f"anullsrc=channel_layout=stereo:sample_rate={sample_rate}",
                ]
                commands.append([
                    "-i", str(intro_path),
                    *intro_audio_input,
                    "-filter_complex",
                    (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=decrease,"
                     f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,"
                     f"fps={fps},format=yuv420p[v];"
                     f"[1:a]{intro_audio_filter}[a]"),
                    "-map", "[v]", "-map", "[a]",
                    *encoder_args.video_args,
                    "-c:a", "aac", "-b:a", "128k", "-ar", str(sample_rate),
                    "-shortest",
                    str(cached_intro),
                ])
            concat_entries.append(f"file '{cached_intro.resolve().as_posix()}'")

        # 2) Source — always stream-copy, no cache needed
        concat_entries.append(f"file '{source.resolve().as_posix()}'")

        # 3) Outro segment (if duration > 0)
        cached_outro: Path | None = None
        if outro_target > 0:
            outro_key = _content_key(outro_path)
            cached_outro = cache_dir / f"outro_{outro_key}_{outro_target:.3f}_{common_tag}.mp4"
            if not cached_outro.exists():
                need_loop = outro_media.duration > 0 and outro_target > outro_media.duration + 0.05
                outro_input_args: list[str] = []
                if need_loop:
                    outro_input_args = ["-stream_loop", "-1"]
                outro_audio_filter = (
                    f"aresample={sample_rate}:async=1,asetpts=PTS-STARTPTS,"
                    f"atrim=duration={outro_target:.3f}"
                ) if outro_media.audio else (
                    f"anullsrc=channel_layout=stereo:sample_rate={sample_rate},"
                    f"atrim=duration={outro_target:.3f}"
                )
                if outro_media.audio:
                    outro_audio_input = [*outro_input_args, "-i", str(outro_path)]
                    audio_label = "[1:a]"
                else:
                    outro_audio_input = [
                        "-f", "lavfi", "-i",
                        f"anullsrc=channel_layout=stereo:sample_rate={sample_rate}",
                    ]
                    audio_label = "[1:a]"
                commands.append([
                    *outro_input_args, "-i", str(outro_path),
                    *outro_audio_input,
                    "-filter_complex",
                    (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=decrease,"
                     f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,"
                     f"fps={fps},format=yuv420p,trim=duration={outro_target:.3f},"
                     f"setpts=PTS-STARTPTS[v];"
                     f"{audio_label}{outro_audio_filter}[a]"),
                    "-map", "[v]", "-map", "[a]",
                    *encoder_args.video_args,
                    "-c:a", "aac", "-b:a", "128k", "-ar", str(sample_rate),
                    "-shortest", "-t", f"{outro_target:.3f}",
                    str(cached_outro),
                ])
            concat_entries.append(f"file '{cached_outro.resolve().as_posix()}'")

        # If we somehow ended up with only the source (no intro, outro_target=0),
        # fast path isn't useful — fall back so the standard pipeline handles
        # the trivial pass-through.
        if len(concat_entries) < 2:
            return None

        # 4) Final concat with stream-copy — the source is just bytes-spliced
        # into the output, no decode/encode happens for its long body.
        listfile = tmp_dir / f"intro_outro_concat_{source.stem}.txt"
        listfile.write_text("\n".join(concat_entries) + "\n", encoding="utf-8")
        commands.append([
            "-f", "concat", "-safe", "0",
            "-i", str(listfile),
            "-c", "copy",
            *encoder_args.container_args,
            str(output),
        ])

        # Only the listfile is per-job temp; cached_intro/cached_outro are
        # batch-level cache (BatchRunner cleans tmp_dir at end).
        return FastPathPlan(
            commands=commands,
            temp_files=[listfile],
            output=output,
        )

"""Stream-copy fast path: skip re-encoding the source when only the extension
tail actually needs new pixels.

For the common "extend 30s ad to 30 minutes" workload, the full-encode pipeline
re-encodes the whole 30-minute output. The fast path generates only the tail
(black/static frame/image card) at target params and concatenates the source
via stream-copy — no decode, no re-encode of the original pixels.

Typical speedup: 30-100x for freeze/black/image_card; effectively instant for
`loop` when the source codec already matches the target.

Eligibility is conservative: any condition that would require re-encoding
the source (filter chain, codec mismatch, container change) disables the
fast path and the caller falls back to the full pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from video_extender.core.encoders.base import EncoderArgs, EncoderBackend
from video_extender.core.extenders.base import ExtenderStrategy
from video_extender.core.job import ExtendMode, Job, JobSpec
from video_extender.core.presets.base import PresetParams
from video_extender.core.scheduler import WorkerKind, WorkerSlot
from video_extender.utils.ffprobe_parser import MediaInfo


@dataclass
class FastPathPlan:
    """A sequence of ffmpeg argv's to execute in order. The last one MUST
    produce `output`. Intermediate temp files are deleted by the caller
    after the chain succeeds.
    """
    commands: list[list[str]]
    temp_files: list[Path]
    output: Path


# Container suffix that supports stream-copy concat for our codecs.
_COMPAT_CONTAINERS = {".mp4", ".mov", ".m4v"}

# Source codec ↔ target codec compatibility for stream-copy.
# Only matching codec pairs let us concat without re-encode.
_CODEC_ALIASES: dict[str, set[str]] = {
    "h264": {"h264", "avc", "avc1"},
    "hevc": {"hevc", "h265", "hev1", "hvc1"},
}


def is_eligible(job: Job, spec: JobSpec) -> tuple[bool, str]:
    """Return (eligible, reason). Reason is logged when not eligible."""
    if job.media is None or job.media.video is None:
        return False, "no probe data"
    # Any filter forces touching every frame.
    if spec.filters:
        return False, f"filter chain active ({len(spec.filters)} filters)"
    # CRF override is honored by both paths but bitrate semantics differ for
    # tail encoding; conservatively skip fast path under custom CRF (the user
    # presumably wants tight control over output).
    if spec.quality_mode == "crf":
        return False, "crf mode requested (skip fast path)"
    # Source must already be in a target-codec family.
    target_codec = spec.video_codec.lower()
    source_codec = job.media.video.codec.lower()
    aliases = _CODEC_ALIASES.get(target_codec, {target_codec})
    if source_codec not in aliases:
        return False, f"codec mismatch ({source_codec} → {target_codec})"
    # Source container must be mp4-family (mov/m4v also concat-copy-safe).
    src_suffix = Path(job.source).suffix.lower()
    if src_suffix not in _COMPAT_CONTAINERS:
        return False, f"source container {src_suffix} incompatible"
    # Extender must support the fast path.
    return True, ""


def _target_duration(spec: JobSpec, source_duration: float) -> float:
    if spec.extend_mode == ExtendMode.ADD:
        return source_duration + spec.extend_seconds
    return max(source_duration, spec.extend_seconds)


def _video_args_only(enc_args: EncoderArgs) -> tuple[str, ...]:
    """Strip container_args (e.g. movflags) from the tail encode — those
    belong on the FINAL output, not the intermediate."""
    return enc_args.video_args


def _audio_args_for_tail(enc_args: EncoderArgs) -> tuple[str, ...]:
    return enc_args.audio_args


def build_plan(
    job: Job,
    spec: JobSpec,
    media: MediaInfo,
    extender: ExtenderStrategy,
    encoder: EncoderBackend,
    params: PresetParams,
    slot: WorkerSlot,
    tmp_dir: Path,
) -> FastPathPlan | None:
    """Build a FastPathPlan if the extender supports it for these inputs.

    Returns None when the extender has no fast-path implementation, signalling
    the caller to fall back to the standard pipeline.
    """
    builder = getattr(extender, "build_fast_path", None)
    if builder is None:
        return None
    assert job.output is not None
    target = _target_duration(spec, media.duration)
    enc_args = encoder.build_args(
        bitrate_kbps=params.bitrate_kbps,
        audio_bitrate_kbps=params.audio_bitrate_kbps,
        crf=None,
        gpu_index=slot.gpu_index,
        threads=slot.threads,
    )
    return builder(
        source=Path(job.source),
        media=media,
        target_duration=target,
        output=job.output,
        encoder=encoder,
        encoder_args=enc_args,
        slot=slot,
        tmp_dir=tmp_dir,
        audio_fade_out_seconds=spec.audio_fade_out_seconds,
    )


def cleanup(plan: FastPathPlan) -> None:
    """Best-effort delete of intermediate temp files."""
    for p in plan.temp_files:
        try:
            if p.is_file():
                p.unlink()
        except OSError:
            pass


__all__ = ["FastPathPlan", "build_plan", "cleanup", "is_eligible"]

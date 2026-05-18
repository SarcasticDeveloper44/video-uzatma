"""Audio loudness normalization (EBU R128 / single-pass loudnorm)."""
from __future__ import annotations

from typing import Any

from video_extender.core.filters.base import Filter, FilterFragment


class AudioNormalizeFilter(Filter):
    name = "audio_normalize"
    label = "Ses normalizasyonu (LUFS)"

    def build(
        self,
        *,
        in_video: str,
        in_audio: str,
        next_input_index: int,
        options: dict[str, Any] | None = None,
    ) -> FilterFragment:
        opts = options or {}
        # Defaults align with Meta's Audio Recommendations (~-14 LUFS).
        target_lufs = float(opts.get("target_lufs", -14.0))
        true_peak = float(opts.get("true_peak", -1.5))
        lra = float(opts.get("loudness_range", 11.0))

        out_a = f"{in_audio.strip('[]')}_norm"
        out_label = f"[{out_a}]"
        seg = (
            f"{in_audio}loudnorm=I={target_lufs}:TP={true_peak}:LRA={lra}{out_label}"
        )
        return FilterFragment(
            filter_segment=seg,
            new_audio_label=out_label,
        )

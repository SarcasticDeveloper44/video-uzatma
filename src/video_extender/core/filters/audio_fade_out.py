"""Audio fade-out filter — applied at the boundary of original→extended audio.

NOTE: For freeze/black extenders, fade-out is already baked into the extender's
filtergraph (afade before apad). This filter is here for cases where the user
wants a fade-out applied to the FINAL output (e.g. before the very end of the
extended target duration).
"""
from __future__ import annotations

from typing import Any

from video_extender.core.filters.base import Filter, FilterFragment


class AudioFadeOutFilter(Filter):
    name = "audio_fade_out"
    label = "Ses fade-out (son)"

    def build(
        self,
        *,
        in_video: str,
        in_audio: str,
        next_input_index: int,
        options: dict[str, Any] | None = None,
    ) -> FilterFragment:
        opts = options or {}
        duration = float(opts.get("duration", 1.5))
        target = float(opts.get("total_duration", 0.0))
        if target <= 0:
            return FilterFragment()  # need total_duration to know when to start

        start = max(0.0, target - duration)
        out_label = f"[{in_audio.strip('[]')}_fo]"
        seg = f"{in_audio}afade=t=out:st={start:.3f}:d={duration:.3f}{out_label}"
        return FilterFragment(filter_segment=seg, new_audio_label=out_label)

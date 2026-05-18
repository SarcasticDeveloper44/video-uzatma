"""Basic color grading (brightness / contrast / saturation / gamma).

Useful for brand consistency across mixed-source ad clips: normalize all
videos to the same look before publishing.
"""
from __future__ import annotations

from typing import Any

from video_extender.core.filters.base import Filter, FilterFragment


class ColorGradeFilter(Filter):
    name = "color_grade"
    label = "Renk düzenle"

    def build(
        self,
        *,
        in_video: str,
        in_audio: str,
        next_input_index: int,
        options: dict[str, Any] | None = None,
    ) -> FilterFragment:
        opts = options or {}
        # All ranges match ffmpeg eq filter semantics:
        brightness = float(opts.get("brightness", 0.0))   # -1.0..1.0, default 0
        contrast   = float(opts.get("contrast",   1.0))   # -1000..1000, default 1
        saturation = float(opts.get("saturation", 1.0))   # 0..3, default 1
        gamma      = float(opts.get("gamma",      1.0))   # 0.1..10, default 1

        # If all defaults, no-op.
        if (brightness == 0.0 and contrast == 1.0
                and saturation == 1.0 and gamma == 1.0):
            return FilterFragment()

        # Clamp to ffmpeg's accepted ranges to avoid filter errors.
        brightness = max(-1.0, min(1.0, brightness))
        contrast   = max(-1000.0, min(1000.0, contrast))
        saturation = max(0.0, min(3.0, saturation))
        gamma      = max(0.1, min(10.0, gamma))

        suffix = in_video.strip("[]")
        out_label = f"[cg_{suffix}]"
        seg = (
            f"{in_video}eq=brightness={brightness:.3f}:contrast={contrast:.3f}"
            f":saturation={saturation:.3f}:gamma={gamma:.3f}{out_label}"
        )
        return FilterFragment(
            filter_segment=seg,
            new_video_label=out_label,
        )

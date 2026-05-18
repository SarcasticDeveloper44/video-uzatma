"""Aspect ratio conversion (e.g. 16:9 → 9:16) with blur-pad or crop strategies."""
from __future__ import annotations

from typing import Any

from video_extender.core.filters.base import Filter, FilterFragment

# Common target aspect presets
ASPECT_PRESETS: dict[str, tuple[int, int]] = {
    "9:16":  (1080, 1920),
    "16:9":  (1920, 1080),
    "1:1":   (1080, 1080),
    "4:5":   (1080, 1350),
    "4:3":   (1440, 1080),
}


def _resolve_target(target: str | tuple[int, int]) -> tuple[int, int]:
    if isinstance(target, tuple):
        return target
    if target in ASPECT_PRESETS:
        return ASPECT_PRESETS[target]
    # Accept "WxH" form
    if "x" in target.lower():
        w, h = target.lower().split("x", 1)
        return int(w), int(h)
    raise ValueError(f"unknown aspect target: {target!r}")


class AspectConvertFilter(Filter):
    name = "aspect_convert"
    label = "En-boy oranı dönüştür"

    def build(
        self,
        *,
        in_video: str,
        in_audio: str,
        next_input_index: int,
        options: dict[str, Any] | None = None,
    ) -> FilterFragment:
        opts = options or {}
        target = opts.get("target", "9:16")
        mode = opts.get("mode", "blur_pad")
        blur_strength = int(opts.get("blur_strength", 20))

        try:
            W, H = _resolve_target(target)
        except ValueError as exc:
            # Don't kill the chain — just skip the filter.
            return FilterFragment()

        # Unique labels so multiple aspect_convert instances don't collide.
        suffix = in_video.strip("[]")
        out_label = f"[ac_{suffix}]"

        if mode == "crop":
            seg = (
                f"{in_video}scale={W}:{H}:force_original_aspect_ratio=increase,"
                f"crop={W}:{H},setsar=1{out_label}"
            )
        elif mode == "blur_pad":
            bg_label = f"[ac_bg_{suffix}]"
            fg_label = f"[ac_fg_{suffix}]"
            split_label = f"[ac_split_{suffix}]"
            # Split incoming stream into BG (zoomed+blurred) and FG (letterboxed).
            seg = (
                f"{in_video}split=2{bg_label}{split_label};"
                # Background: cover full target frame, blur heavily
                f"{bg_label}scale={W}:{H}:force_original_aspect_ratio=increase,"
                f"crop={W}:{H},boxblur={blur_strength}:1[ac_bgb_{suffix}];"
                # Foreground: fit inside target frame preserving aspect
                f"{split_label}scale={W}:{H}:force_original_aspect_ratio=decrease{fg_label};"
                # Composite FG centered over BG
                f"[ac_bgb_{suffix}]{fg_label}overlay=(W-w)/2:(H-h)/2,setsar=1{out_label}"
            )
        else:
            # Unknown mode — pass through (no-op)
            return FilterFragment()

        return FilterFragment(
            filter_segment=seg,
            new_video_label=out_label,
        )

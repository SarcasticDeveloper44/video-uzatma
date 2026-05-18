"""Burn subtitles (SRT/ASS) into the video.

Essential for sound-off social media viewing — Meta says ~85% of ad views
on mobile feeds are muted by default.

NOTE: ffmpeg's `subtitles=` filter has notoriously tricky escaping; we route
through the `filename=` keyword form and escape colons/backslashes/single-quotes.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from video_extender.core.filters.base import Filter, FilterFragment


def _escape_filter_path(p: str) -> str:
    """ffmpeg filter values need ':' and '\\' escaped; for cross-platform path
    safety also escape single quotes.
    """
    # Order matters: backslash first.
    return p.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


class SubtitleBurnFilter(Filter):
    name = "subtitle_burn"
    label = "Altyazı yak (SRT/ASS)"

    def build(
        self,
        *,
        in_video: str,
        in_audio: str,
        next_input_index: int,
        options: dict[str, Any] | None = None,
    ) -> FilterFragment:
        opts = options or {}
        srt = opts.get("file")
        if not srt:
            return FilterFragment()

        srt_path = Path(srt)
        if not srt_path.exists():
            raise FileNotFoundError(f"subtitle file not found: {srt_path}")

        # Force_style for SRT (ignored for ASS). Reasonable defaults for ad use:
        #  - Fontsize=24, white text, black outline, bottom-center
        font_size = int(opts.get("font_size", 24))
        font_color = opts.get("font_color", "FFFFFF")  # ASS BGR hex (white)
        outline_color = opts.get("outline_color", "000000")
        margin_v = int(opts.get("margin_v", 80))   # pixels from bottom
        alignment = int(opts.get("alignment", 2))  # 2 = bottom center

        force_style = (
            f"FontSize={font_size},PrimaryColour=&H{font_color},"
            f"OutlineColour=&H{outline_color},Outline=2,"
            f"MarginV={margin_v},Alignment={alignment}"
        )

        # Use suffix-aware filter: .ass uses `ass=`, others use `subtitles=`.
        escaped = _escape_filter_path(str(srt_path.resolve()))
        if srt_path.suffix.lower() == ".ass":
            sub_filter = f"ass=filename='{escaped}'"
        else:
            sub_filter = (
                f"subtitles=filename='{escaped}':force_style='{force_style}'"
            )

        suffix = in_video.strip("[]")
        out_label = f"[sub_{suffix}]"
        seg = f"{in_video}{sub_filter}{out_label}"

        return FilterFragment(
            filter_segment=seg,
            new_video_label=out_label,
        )

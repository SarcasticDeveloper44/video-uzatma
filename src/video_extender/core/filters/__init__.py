"""Video/audio filter chain — composable, auto-discovered."""
from video_extender.core.filters.base import Filter, FilterChain, FILTER_REGISTRY
from video_extender.core.filters import (  # noqa: F401
    aspect_convert,
    audio_fade_out,
    audio_normalize,
    color_grade,
    metadata_strip,
    subtitle_burn,
    watermark,
)

__all__ = ["Filter", "FilterChain", "FILTER_REGISTRY"]

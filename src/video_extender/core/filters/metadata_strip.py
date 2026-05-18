"""Strip container metadata (GPS, camera info, exif-like tags).

This is an output-level filter; it contributes -map_metadata -1 (and similar)
rather than a filtergraph segment.
"""
from __future__ import annotations

from typing import Any

from video_extender.core.filters.base import Filter, FilterFragment


class MetadataStripFilter(Filter):
    name = "metadata_strip"
    label = "Metadata temizle (privacy)"

    def build(
        self,
        *,
        in_video: str,
        in_audio: str,
        next_input_index: int,
        options: dict[str, Any] | None = None,
    ) -> FilterFragment:
        return FilterFragment(
            output_metadata_args=("-map_metadata", "-1", "-map_chapters", "-1"),
        )

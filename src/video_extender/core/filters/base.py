"""Filter chain — composable filters that augment the extender's filtergraph.

A filter takes the currently-labeled video/audio streams and produces
a new pair of labeled streams. The pipeline composes them in order.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar


@dataclass
class FilterFragment:
    """Filter contribution to the final ffmpeg invocation.

    - prefix_input_args: extra `-i` inputs needed (e.g. watermark image).
    - filter_segment: filter chain fragment producing new labeled outputs.
    - new_video_label / new_audio_label: the resulting labels (or None to keep).
    - output_metadata_args: top-level args (e.g. -map_metadata -1).
    """
    prefix_input_args: tuple[str, ...] = ()
    extra_inputs: tuple[str, ...] = ()              # paths
    filter_segment: str = ""
    new_video_label: str | None = None
    new_audio_label: str | None = None
    output_metadata_args: tuple[str, ...] = ()


FILTER_REGISTRY: dict[str, type[Filter]] = {}


class Filter(ABC):
    name: ClassVar[str] = ""
    label: ClassVar[str] = ""

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if getattr(cls, "name", ""):
            FILTER_REGISTRY[cls.name] = cls

    @abstractmethod
    def build(
        self,
        *,
        in_video: str,
        in_audio: str,
        next_input_index: int,
        options: dict[str, Any] | None = None,
    ) -> FilterFragment:
        """Build the filter's contribution.

        `in_video` / `in_audio` are bracketed stream labels (e.g. "[vout]")
        currently in scope. The filter MUST output labels (when transforming)
        so the chain remains composable.
        `next_input_index` is the next free `-i` slot.
        """
        raise NotImplementedError


@dataclass
class FilterChain:
    """Ordered chain of Filter instances + their per-filter options."""
    filters: list[tuple[Filter, dict[str, Any]]] = field(default_factory=list)

    def append(self, f: Filter, options: dict[str, Any] | None = None) -> None:
        self.filters.append((f, options or {}))

    def build(self, *, in_video: str, in_audio: str, next_input_index: int) -> list[FilterFragment]:
        frags: list[FilterFragment] = []
        cur_v, cur_a = in_video, in_audio
        idx = next_input_index
        for f, opts in self.filters:
            frag = f.build(in_video=cur_v, in_audio=cur_a, next_input_index=idx, options=opts)
            frags.append(frag)
            if frag.new_video_label:
                cur_v = frag.new_video_label
            if frag.new_audio_label:
                cur_a = frag.new_audio_label
            idx += len(frag.extra_inputs)
        return frags

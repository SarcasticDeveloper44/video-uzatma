"""ExtenderStrategy ABC + auto-registry."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from video_extender.utils.ffprobe_parser import MediaInfo


@dataclass
class ExtenderPlan:
    """What the extender contributes to the ffmpeg command.

    Input ordering in the final ffmpeg invocation:
        [source_input_args] -i <source>
        [extra_input_args[0]] -i <extra_inputs[0]>
        [extra_input_args[1]] -i <extra_inputs[1]>
        ...

    - source_input_args: flags before the source input (e.g. "-stream_loop -1"
      for the loop extender).
    - extra_inputs: additional `-i <path>` (e.g. intro/outro file, image).
    - extra_input_args: per-extra-input prefix flags; len MUST equal len(extra_inputs).
    - filtergraph: the full -filter_complex string.
    - video_label / audio_label: labels of the final streams to map (e.g. "[vout]").
      If None, the encoder maps 0:v / 0:a by default.
    """
    source_input_args: tuple[str, ...] = ()
    extra_inputs: tuple[Path, ...] = ()
    extra_input_args: tuple[tuple[str, ...], ...] = ()
    filtergraph: str = ""
    video_label: str | None = None
    audio_label: str | None = None


EXTENDER_REGISTRY: dict[str, type["ExtenderStrategy"]] = {}


class ExtenderStrategy(ABC):
    """Each strategy produces a partial ffmpeg plan for the extension."""

    name: ClassVar[str] = ""           # short id, e.g. "freeze"
    label: ClassVar[str] = ""          # human-readable
    description: ClassVar[str] = ""

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if getattr(cls, "name", ""):
            EXTENDER_REGISTRY[cls.name] = cls

    @abstractmethod
    def build_plan(
        self,
        source: Path,
        media: MediaInfo,
        target_duration: float,
        *,
        audio_fade_out_seconds: float = 1.5,
        options: dict | None = None,
    ) -> ExtenderPlan:
        """Build the ffmpeg fragment that produces a `target_duration`-long output.

        `target_duration` is the FINAL desired duration in seconds (>= media.duration).
        """
        raise NotImplementedError

"""Platform preset ABC + auto-registry."""
from __future__ import annotations

from abc import ABC
from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True)
class PresetParams:
    """Encoder targets a preset wants."""
    bitrate_kbps: int
    audio_bitrate_kbps: int
    audio_lufs: float
    max_width: int | None = None
    max_height: int | None = None
    fps_cap: float | None = None
    container_ext: str = "mp4"


PRESET_REGISTRY: dict[str, type[PlatformPreset]] = {}


class PlatformPreset(ABC):
    name: ClassVar[str] = ""
    label: ClassVar[str] = ""
    description: ClassVar[str] = ""

    # Per-quality params: low/medium/high
    params_low: ClassVar[PresetParams]
    params_medium: ClassVar[PresetParams]
    params_high: ClassVar[PresetParams]

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if getattr(cls, "name", ""):
            PRESET_REGISTRY[cls.name] = cls

    @classmethod
    def for_quality(cls, quality: str) -> PresetParams:
        q = quality.lower()
        if q == "low":
            return cls.params_low
        if q == "high":
            return cls.params_high
        return cls.params_medium

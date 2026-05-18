"""Generic CRF/bitrate quality tiers (used when no platform preset is selected)."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Quality(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class QualityTier:
    crf: int
    bitrate_kbps: int
    audio_bitrate_kbps: int


QUALITY_PRESETS: dict[Quality, QualityTier] = {
    Quality.LOW:    QualityTier(crf=28, bitrate_kbps=2500, audio_bitrate_kbps=96),
    Quality.MEDIUM: QualityTier(crf=23, bitrate_kbps=5000, audio_bitrate_kbps=128),
    Quality.HIGH:   QualityTier(crf=20, bitrate_kbps=8000, audio_bitrate_kbps=192),
}

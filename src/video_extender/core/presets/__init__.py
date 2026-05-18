"""Platform target presets — auto-discovered via registry."""
from video_extender.core.presets.base import PlatformPreset, PRESET_REGISTRY
from video_extender.core.presets import meta, tiktok, twitter, youtube, linkedin  # noqa: F401
from video_extender.core.presets.quality import Quality, QUALITY_PRESETS  # noqa: F401

__all__ = ["PlatformPreset", "PRESET_REGISTRY", "Quality", "QUALITY_PRESETS"]

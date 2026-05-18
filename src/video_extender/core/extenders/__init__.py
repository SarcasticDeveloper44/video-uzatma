"""Extender strategies — auto-discovered via registry."""
from video_extender.core.extenders.base import ExtenderStrategy, EXTENDER_REGISTRY
from video_extender.core.extenders import black, freeze, image_card, intro_outro, loop  # noqa: F401

__all__ = ["ExtenderStrategy", "EXTENDER_REGISTRY"]

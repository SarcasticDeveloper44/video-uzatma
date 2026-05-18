"""Encoder backends — auto-discovered via registry."""
from video_extender.core.encoders.base import EncoderBackend, ENCODER_REGISTRY
from video_extender.core.encoders import (  # noqa: F401
    amf,
    libaom_av1,
    libvpx_vp9,
    libx264,
    libx265,
    nvenc,
    qsv,
    vaapi,
    videotoolbox,
)

__all__ = ["EncoderBackend", "ENCODER_REGISTRY"]

"""X / Twitter video presets.

Spec (as of 2025): MP4/MOV H.264 + AAC, up to 2:20 free, up to 60min Premium.
Recommended max bitrate ~25Mbps, file size limits vary by tier.
"""
from __future__ import annotations

from video_extender.core.presets.base import PlatformPreset, PresetParams


class Twitter(PlatformPreset):
    name = "twitter"
    label = "X / Twitter"
    description = "X video reklam/post; max ~25 Mbps, ~-14 LUFS. H.264 + AAC."
    params_low = PresetParams(
        bitrate_kbps=3000, audio_bitrate_kbps=128, audio_lufs=-14.0,
        max_width=1280, max_height=720, fps_cap=30.0,
    )
    params_medium = PresetParams(
        bitrate_kbps=6000, audio_bitrate_kbps=192, audio_lufs=-14.0,
        max_width=1920, max_height=1080, fps_cap=30.0,
    )
    params_high = PresetParams(
        bitrate_kbps=12000, audio_bitrate_kbps=192, audio_lufs=-14.0,
        max_width=1920, max_height=1080, fps_cap=60.0,
    )

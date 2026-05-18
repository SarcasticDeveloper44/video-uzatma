"""LinkedIn video preset.

Specs: MP4/MOV H.264 + AAC, 1080p @ 30fps, 10s-30min, up to 5GB.
Square (1:1) and landscape (16:9) most common for organic / Sponsored Content.
"""
from __future__ import annotations

from video_extender.core.presets.base import PlatformPreset, PresetParams


class LinkedInFeed(PlatformPreset):
    name = "linkedin_feed"
    label = "LinkedIn Feed"
    description = "Sponsored content / organic video. 1080p, H.264, ~-14 LUFS."
    params_low = PresetParams(
        bitrate_kbps=3000, audio_bitrate_kbps=128, audio_lufs=-14.0,
        max_width=1920, max_height=1080, fps_cap=30.0,
    )
    params_medium = PresetParams(
        bitrate_kbps=5000, audio_bitrate_kbps=192, audio_lufs=-14.0,
        max_width=1920, max_height=1080, fps_cap=30.0,
    )
    params_high = PresetParams(
        bitrate_kbps=8000, audio_bitrate_kbps=192, audio_lufs=-14.0,
        max_width=1920, max_height=1080, fps_cap=30.0,
    )

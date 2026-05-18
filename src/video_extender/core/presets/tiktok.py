"""TikTok platform preset."""
from __future__ import annotations

from video_extender.core.presets.base import PlatformPreset, PresetParams


class TikTok(PlatformPreset):
    name = "tiktok"
    label = "TikTok (9:16)"
    description = "1080x1920 önerilen, 30fps, ~-13 LUFS."
    params_low = PresetParams(
        bitrate_kbps=3500, audio_bitrate_kbps=128, audio_lufs=-13.0,
        max_width=1080, max_height=1920, fps_cap=30.0,
    )
    params_medium = PresetParams(
        bitrate_kbps=5000, audio_bitrate_kbps=128, audio_lufs=-13.0,
        max_width=1080, max_height=1920, fps_cap=30.0,
    )
    params_high = PresetParams(
        bitrate_kbps=9000, audio_bitrate_kbps=192, audio_lufs=-13.0,
        max_width=1080, max_height=1920, fps_cap=60.0,
    )

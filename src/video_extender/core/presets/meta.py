"""Meta (Facebook + Instagram) platform presets."""
from __future__ import annotations

from video_extender.core.presets.base import PlatformPreset, PresetParams


class InstagramReels(PlatformPreset):
    name = "ig_reels"
    label = "Instagram Reels (9:16)"
    description = "1080x1920 önerilen, 30fps, ~-14 LUFS."
    params_low = PresetParams(bitrate_kbps=3500, audio_bitrate_kbps=128, audio_lufs=-14.0,
                              max_width=1080, max_height=1920, fps_cap=30.0)
    params_medium = PresetParams(bitrate_kbps=5000, audio_bitrate_kbps=128, audio_lufs=-14.0,
                                 max_width=1080, max_height=1920, fps_cap=30.0)
    params_high = PresetParams(bitrate_kbps=8000, audio_bitrate_kbps=192, audio_lufs=-14.0,
                               max_width=1080, max_height=1920, fps_cap=30.0)


class InstagramFeed(PlatformPreset):
    name = "ig_feed"
    label = "Instagram Feed (1:1 / 4:5)"
    description = "1080 genişlik, 30fps, ~-14 LUFS."
    params_low = PresetParams(bitrate_kbps=3500, audio_bitrate_kbps=128, audio_lufs=-14.0,
                              max_width=1080, fps_cap=30.0)
    params_medium = PresetParams(bitrate_kbps=5000, audio_bitrate_kbps=128, audio_lufs=-14.0,
                                 max_width=1080, fps_cap=30.0)
    params_high = PresetParams(bitrate_kbps=8000, audio_bitrate_kbps=192, audio_lufs=-14.0,
                               max_width=1080, fps_cap=30.0)


class InstagramStory(PlatformPreset):
    name = "ig_story"
    label = "Instagram Story (9:16)"
    description = "1080x1920, 30fps."
    params_low = PresetParams(bitrate_kbps=3500, audio_bitrate_kbps=128, audio_lufs=-14.0,
                              max_width=1080, max_height=1920, fps_cap=30.0)
    params_medium = PresetParams(bitrate_kbps=5000, audio_bitrate_kbps=128, audio_lufs=-14.0,
                                 max_width=1080, max_height=1920, fps_cap=30.0)
    params_high = PresetParams(bitrate_kbps=8000, audio_bitrate_kbps=192, audio_lufs=-14.0,
                               max_width=1080, max_height=1920, fps_cap=30.0)


class FacebookFeed(PlatformPreset):
    name = "fb_feed"
    label = "Facebook Feed"
    description = "Genel feed reklamı; oranı koruyarak max 1080 genişlik."
    params_low = PresetParams(bitrate_kbps=3500, audio_bitrate_kbps=128, audio_lufs=-14.0,
                              max_width=1080, fps_cap=30.0)
    params_medium = PresetParams(bitrate_kbps=5000, audio_bitrate_kbps=128, audio_lufs=-14.0,
                                 max_width=1080, fps_cap=30.0)
    params_high = PresetParams(bitrate_kbps=8000, audio_bitrate_kbps=192, audio_lufs=-14.0,
                               max_width=1080, fps_cap=30.0)


class FacebookReels(PlatformPreset):
    name = "fb_reels"
    label = "Facebook Reels (9:16)"
    description = "1080x1920, 30fps."
    params_low = PresetParams(bitrate_kbps=3500, audio_bitrate_kbps=128, audio_lufs=-14.0,
                              max_width=1080, max_height=1920, fps_cap=30.0)
    params_medium = PresetParams(bitrate_kbps=5000, audio_bitrate_kbps=128, audio_lufs=-14.0,
                                 max_width=1080, max_height=1920, fps_cap=30.0)
    params_high = PresetParams(bitrate_kbps=8000, audio_bitrate_kbps=192, audio_lufs=-14.0,
                               max_width=1080, max_height=1920, fps_cap=30.0)

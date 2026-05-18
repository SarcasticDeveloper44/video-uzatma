"""YouTube Shorts & Long-form presets (aligned with YouTube's recommended upload settings).

References:
- https://support.google.com/youtube/answer/1722171 (recommended upload encoding)
- Shorts: 9:16 vertical, up to 60s, 1080p preferred
- Long: 16:9 horizontal, 1080p @ 30/60fps, 4K @ 30fps for high quality
- YouTube re-encodes uploads; we feed slightly above recommended bitrate so re-encode
  doesn't degrade visibly.
"""
from __future__ import annotations

from video_extender.core.presets.base import PlatformPreset, PresetParams


class YouTubeShorts(PlatformPreset):
    name = "yt_shorts"
    label = "YouTube Shorts (9:16)"
    description = "1080×1920 dikey, 30-60fps, ~-14 LUFS. YouTube'un önerdiği yükleme bitrate'leri."
    params_low = PresetParams(
        bitrate_kbps=5000, audio_bitrate_kbps=192, audio_lufs=-14.0,
        max_width=1080, max_height=1920, fps_cap=30.0,
    )
    params_medium = PresetParams(
        bitrate_kbps=8000, audio_bitrate_kbps=192, audio_lufs=-14.0,
        max_width=1080, max_height=1920, fps_cap=30.0,
    )
    params_high = PresetParams(
        bitrate_kbps=12000, audio_bitrate_kbps=256, audio_lufs=-14.0,
        max_width=1080, max_height=1920, fps_cap=60.0,
    )


class YouTubeLong(PlatformPreset):
    name = "yt_long"
    label = "YouTube uzun video (16:9)"
    description = "Standart YouTube içeriği; 1080p @ 30/60fps. YouTube önerilen bitrate'lerinin biraz üzerinde."
    params_low = PresetParams(
        bitrate_kbps=5000, audio_bitrate_kbps=192, audio_lufs=-14.0,
        max_width=1280, max_height=720, fps_cap=30.0,
    )
    params_medium = PresetParams(
        bitrate_kbps=10000, audio_bitrate_kbps=256, audio_lufs=-14.0,
        max_width=1920, max_height=1080, fps_cap=30.0,
    )
    params_high = PresetParams(
        bitrate_kbps=18000, audio_bitrate_kbps=384, audio_lufs=-14.0,
        max_width=1920, max_height=1080, fps_cap=60.0,
    )


class YouTube4K(PlatformPreset):
    name = "yt_4k"
    label = "YouTube 4K (16:9)"
    description = "3840×2160 @ 30fps. Çok yüksek bitrate; arşivleme / üst sınır kalite."
    params_low = PresetParams(
        bitrate_kbps=20000, audio_bitrate_kbps=256, audio_lufs=-14.0,
        max_width=3840, max_height=2160, fps_cap=30.0,
    )
    params_medium = PresetParams(
        bitrate_kbps=35000, audio_bitrate_kbps=384, audio_lufs=-14.0,
        max_width=3840, max_height=2160, fps_cap=30.0,
    )
    params_high = PresetParams(
        bitrate_kbps=45000, audio_bitrate_kbps=384, audio_lufs=-14.0,
        max_width=3840, max_height=2160, fps_cap=60.0,
    )

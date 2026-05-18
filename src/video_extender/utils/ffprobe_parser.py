"""Parse ffprobe JSON output into a typed dict."""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Any


@dataclass(frozen=True)
class VideoStream:
    index: int
    codec: str
    width: int
    height: int
    fps: float
    pix_fmt: str
    bitrate: int | None


@dataclass(frozen=True)
class AudioStream:
    index: int
    codec: str
    sample_rate: int
    channels: int
    bitrate: int | None


@dataclass(frozen=True)
class MediaInfo:
    path: str
    duration: float
    size: int
    container: str
    video: VideoStream | None
    audio: AudioStream | None

    @property
    def aspect_ratio(self) -> float:
        if self.video is None or self.video.height == 0:
            return 0.0
        return self.video.width / self.video.height

    @property
    def is_vertical(self) -> bool:
        return self.aspect_ratio > 0 and self.aspect_ratio < 1

    @property
    def is_square(self) -> bool:
        return 0.95 <= self.aspect_ratio <= 1.05


def _parse_fps(value: str | None) -> float:
    if not value or value == "0/0":
        return 0.0
    try:
        return float(Fraction(value))
    except (ZeroDivisionError, ValueError):
        return 0.0


def _int_or_none(value: Any) -> int | None:
    if value in (None, "", "N/A"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse(data: dict[str, Any], path: str) -> MediaInfo:
    fmt = data.get("format", {})
    streams = data.get("streams", [])

    video: VideoStream | None = None
    audio: AudioStream | None = None

    for s in streams:
        if s.get("codec_type") == "video" and video is None:
            video = VideoStream(
                index=int(s.get("index", 0)),
                codec=s.get("codec_name", "?"),
                width=int(s.get("width", 0)),
                height=int(s.get("height", 0)),
                fps=_parse_fps(s.get("r_frame_rate") or s.get("avg_frame_rate")),
                pix_fmt=s.get("pix_fmt", "?"),
                bitrate=_int_or_none(s.get("bit_rate")),
            )
        elif s.get("codec_type") == "audio" and audio is None:
            audio = AudioStream(
                index=int(s.get("index", 0)),
                codec=s.get("codec_name", "?"),
                sample_rate=int(s.get("sample_rate", 0) or 0),
                channels=int(s.get("channels", 0) or 0),
                bitrate=_int_or_none(s.get("bit_rate")),
            )

    try:
        duration = float(fmt.get("duration", 0) or 0)
    except (TypeError, ValueError):
        duration = 0.0

    try:
        size = int(fmt.get("size", 0) or 0)
    except (TypeError, ValueError):
        size = 0

    return MediaInfo(
        path=path,
        duration=duration,
        size=size,
        container=fmt.get("format_name", "?"),
        video=video,
        audio=audio,
    )

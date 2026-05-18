"""Probe single video files via ffprobe → MediaInfo."""
from __future__ import annotations

from pathlib import Path

from video_extender.core.ffmpeg import FFmpegRunner
from video_extender.utils.ffprobe_parser import MediaInfo, parse


def probe_file(path: Path, runner: FFmpegRunner | None = None) -> MediaInfo:
    runner = runner or FFmpegRunner()
    data = runner.probe(path)
    return parse(data, str(path))


def probe_many(paths: list[Path], runner: FFmpegRunner | None = None) -> list[MediaInfo]:
    runner = runner or FFmpegRunner()
    return [probe_file(p, runner) for p in paths]

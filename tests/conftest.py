"""Shared pytest fixtures: real H.264 video clips of varied aspects + a logo PNG.

These are generated on-demand via ffmpeg lavfi (NOT placeholders/demo data) and
exercise the real codec / decoder paths. Cached for the whole session.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


def _has(binary: str) -> bool:
    return shutil.which(binary) is not None


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True, timeout=30)


@pytest.fixture(scope="session")
def fixture_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    d = tmp_path_factory.mktemp("vx_fixtures")
    return d


@pytest.fixture(scope="session")
def ffmpeg_available() -> bool:
    return _has("ffmpeg") and _has("ffprobe")


@pytest.fixture(scope="session")
def vertical_3s(fixture_dir: Path, ffmpeg_available: bool) -> Path:
    if not ffmpeg_available:
        pytest.skip("ffmpeg not available")
    p = fixture_dir / "vertical_9x16.mp4"
    if not p.exists():
        _run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=720x1280:duration=3:rate=30",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(p),
        ])
    return p


@pytest.fixture(scope="session")
def horizontal_3s(fixture_dir: Path, ffmpeg_available: bool) -> Path:
    if not ffmpeg_available:
        pytest.skip("ffmpeg not available")
    p = fixture_dir / "horizontal_16x9.mp4"
    if not p.exists():
        _run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=1920x1080:duration=3:rate=30",
            "-f", "lavfi", "-i", "sine=frequency=550:duration=3",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(p),
        ])
    return p


@pytest.fixture(scope="session")
def square_3s(fixture_dir: Path, ffmpeg_available: bool) -> Path:
    if not ffmpeg_available:
        pytest.skip("ffmpeg not available")
    p = fixture_dir / "square_1x1.mp4"
    if not p.exists():
        _run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=720x720:duration=3:rate=30",
            "-f", "lavfi", "-i", "sine=frequency=660:duration=3",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(p),
        ])
    return p


@pytest.fixture(scope="session")
def silent_3s(fixture_dir: Path, ffmpeg_available: bool) -> Path:
    if not ffmpeg_available:
        pytest.skip("ffmpeg not available")
    p = fixture_dir / "silent.mp4"
    if not p.exists():
        _run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=720x1280:duration=3:rate=30",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(p),
        ])
    return p


@pytest.fixture(scope="session")
def logo_png(fixture_dir: Path, ffmpeg_available: bool) -> Path:
    if not ffmpeg_available:
        pytest.skip("ffmpeg not available")
    p = fixture_dir / "logo.png"
    if not p.exists():
        _run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "color=red:size=200x60:duration=0.1",
            "-frames:v", "1", str(p),
        ])
    return p


@pytest.fixture(scope="session")
def srt_file(fixture_dir: Path) -> Path:
    p = fixture_dir / "subs.srt"
    if not p.exists():
        p.write_text(
            "1\n00:00:00,500 --> 00:00:02,000\nTest altyazi\n\n"
            "2\n00:00:02,500 --> 00:00:04,500\nSatir iki\n",
            encoding="utf-8",
        )
    return p


@pytest.fixture(scope="session")
def intro_2s(fixture_dir: Path, ffmpeg_available: bool) -> Path:
    if not ffmpeg_available:
        pytest.skip("ffmpeg not available")
    p = fixture_dir / "intro.mp4"
    if not p.exists():
        _run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "color=red:size=1920x1080:duration=2:rate=30",
            "-f", "lavfi", "-i", "sine=frequency=800:duration=2",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(p),
        ])
    return p


@pytest.fixture(scope="session")
def outro_4s(fixture_dir: Path, ffmpeg_available: bool) -> Path:
    if not ffmpeg_available:
        pytest.skip("ffmpeg not available")
    p = fixture_dir / "outro.mp4"
    if not p.exists():
        _run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "color=blue:size=1280x720:duration=4:rate=30",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(p),
        ])
    return p


@pytest.fixture(scope="session")
def end_card_png(fixture_dir: Path, ffmpeg_available: bool) -> Path:
    if not ffmpeg_available:
        pytest.skip("ffmpeg not available")
    p = fixture_dir / "endcard.png"
    if not p.exists():
        _run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "color=green:size=1080x1920:duration=0.1",
            "-frames:v", "1", str(p),
        ])
    return p


# ---- Helper to introspect produced media ----
def probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, timeout=10, check=True,
    )
    return float(out.stdout.strip())


def probe_codec(path: Path) -> tuple[str, int, int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v",
         "-show_entries", "stream=codec_name,width,height",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, timeout=10, check=True,
    )
    parts = out.stdout.strip().split(",")
    return parts[0], int(parts[1]), int(parts[2])

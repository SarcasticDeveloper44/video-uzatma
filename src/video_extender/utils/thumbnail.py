"""Extract a single representative frame from a video as a small PNG.

Used by the GUI to show a per-row preview in the video list. Frames are
cached on disk (keyed by source path + mtime + size) so re-opening the
same folder doesn't re-extract.
"""
from __future__ import annotations

import hashlib
import platform
import subprocess
from pathlib import Path


THUMBNAIL_WIDTH = 96   # pixels — fits cleanly into a Qt list-item cell
THUMBNAIL_HEIGHT = 54  # 16:9 by default


def _cache_root() -> Path:
    """Per-user cache dir for extracted thumbnails. Survives across runs."""
    if platform.system() == "Windows":
        base = Path.home() / "AppData" / "Local" / "video-extender" / "thumbnails"
    elif platform.system() == "Darwin":
        base = Path.home() / "Library" / "Caches" / "video-extender" / "thumbnails"
    else:
        base = Path.home() / ".cache" / "video-extender" / "thumbnails"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _cache_key(source: Path) -> str:
    """Stable hash over (path, mtime, size) — invalidates when the source
    is replaced with a different file at the same path."""
    try:
        stat = source.stat()
        material = f"{source.resolve()}|{stat.st_mtime_ns}|{stat.st_size}"
    except OSError:
        material = str(source)
    return hashlib.sha1(material.encode("utf-8")).hexdigest()[:20]


def extract(source: Path, timestamp: float = 1.0) -> Path | None:
    """Extract a thumbnail for `source` at `timestamp` seconds. Returns the
    cached PNG path, or None on failure. Cached.

    Falls back from extraction failure (corrupt source, missing ffmpeg) by
    returning None — caller should treat as 'no thumb available'.
    """
    if not source.exists():
        return None
    cache_path = _cache_root() / f"{_cache_key(source)}.png"
    if cache_path.exists() and cache_path.stat().st_size > 0:
        return cache_path

    # Build ffmpeg command. Seek before -i for fast keyframe seek.
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{max(0.0, timestamp):.3f}",
        "-i", str(source),
        "-frames:v", "1",
        "-vf", f"scale={THUMBNAIL_WIDTH}:{THUMBNAIL_HEIGHT}:force_original_aspect_ratio=decrease",
        str(cache_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=10)
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return None
    if result.returncode != 0 or not cache_path.exists():
        # Clean up the partial file (ffmpeg sometimes touches it before failing).
        try:
            cache_path.unlink()
        except OSError:
            pass
        return None
    return cache_path


def extract_to(source: Path, dest: Path, timestamp: float = 1.0) -> bool:
    """Extract a thumbnail to a specific destination (bypasses cache).
    Returns True on success.
    """
    # Try with ffmpeg directly without cache (test path)
    if not source.exists():
        return False
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{max(0.0, timestamp):.3f}",
        "-i", str(source),
        "-frames:v", "1",
        "-vf", f"scale={THUMBNAIL_WIDTH}:{THUMBNAIL_HEIGHT}:force_original_aspect_ratio=decrease",
        str(dest),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=10)
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return False
    return result.returncode == 0 and dest.exists()


def clear_cache() -> int:
    """Wipe the thumbnail cache. Returns the number of files deleted.
    Useful for the reset-settings flow."""
    root = _cache_root()
    n = 0
    for p in root.glob("*.png"):
        try:
            p.unlink()
            n += 1
        except OSError:
            pass
    return n

"""Filesystem helpers: video discovery, output paths, temp dirs."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

VIDEO_EXTENSIONS = {
    ".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".flv",
    ".wmv", ".mpg", ".mpeg", ".ts", ".m2ts", ".3gp", ".vob",
    ".ogv", ".mxf", ".f4v",
}


def is_video(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS


def discover_videos(folder: Path, recursive: bool = False) -> list[Path]:
    if not folder.is_dir():
        return []
    iterator: Iterable[Path] = folder.rglob("*") if recursive else folder.iterdir()
    return sorted(p for p in iterator if is_video(p))


def ensure_output_dir(source_folder: Path, name: str = "output") -> Path:
    out = source_folder / name
    out.mkdir(parents=True, exist_ok=True)
    return out


def safe_output_path(out_dir: Path, source: Path, template: str, **kwargs: str) -> Path:
    """Apply filename template and ensure no overwrite collisions."""
    base = template.format(name=source.stem, ext=source.suffix.lstrip("."), **kwargs)
    candidate = out_dir / base
    if not candidate.exists():
        return candidate
    stem, ext = candidate.stem, candidate.suffix
    i = 1
    while True:
        candidate = out_dir / f"{stem}_{i}{ext}"
        if not candidate.exists():
            return candidate
        i += 1


def temp_dir_for(source: Path, root: Path | None = None) -> Path:
    """Per-job temp directory."""
    base = root or (source.parent / ".video_extender_tmp")
    base.mkdir(parents=True, exist_ok=True)
    return base


def state_file(folder: Path) -> Path:
    """Resume state file location."""
    return folder / ".video_extender_state.json"

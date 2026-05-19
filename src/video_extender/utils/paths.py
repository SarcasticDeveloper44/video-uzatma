"""Filesystem helpers: video discovery, output paths, temp dirs."""
from __future__ import annotations

import platform
import shutil
import subprocess
from collections.abc import Iterable
from pathlib import Path

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


# Linux file managers that support a "select this file" command-line flag.
# In preference order — first one found on PATH wins.
_LINUX_FILE_MANAGERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("nautilus", ("--select",)),     # GNOME / Ubuntu default
    ("dolphin",  ("--select",)),     # KDE Plasma
    ("nemo",     ()),                # Cinnamon (auto-selects when given a file)
    ("thunar",   ()),                # XFCE (opens parent, no select)
    ("pcmanfm",  ()),                # LXDE/LXQt
    ("caja",     ()),                # MATE
)


def reveal_in_file_manager(path: Path) -> bool:
    """Open the OS file manager focused on `path` (file or folder).

    On macOS the file is selected/highlighted in Finder (-R flag). On Windows
    Explorer opens with the file pre-selected (/select,<path>). On Linux we
    try the running desktop's file manager with its select-flag, falling back
    to `xdg-open` on the parent folder.

    Returns True iff a process was successfully launched. Best-effort —
    failures are non-fatal because revealing a path is a UX nicety, not a
    critical operation.
    """
    if not path.exists():
        return False
    sys_name = platform.system()
    try:
        if sys_name == "Windows":
            # Quirky comma syntax — no space before path, that's the Explorer rule.
            subprocess.Popen(["explorer", f"/select,{path}"])
            return True
        if sys_name == "Darwin":
            subprocess.Popen(["open", "-R", str(path)])
            return True
        # Linux: try a known file manager first; fall back to xdg-open.
        for fm, select_args in _LINUX_FILE_MANAGERS:
            if shutil.which(fm) is None:
                continue
            argv = [fm, *select_args, str(path)] if select_args else [fm, str(path)]
            try:
                subprocess.Popen(argv)
                return True
            except (FileNotFoundError, OSError):
                continue
        # Last resort: open the containing folder.
        target = path.parent if path.is_file() else path
        if shutil.which("xdg-open") is not None:
            subprocess.Popen(["xdg-open", str(target)])
            return True
    except OSError:
        pass
    return False


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



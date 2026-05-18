#!/usr/bin/env python3
"""Cross-platform launcher: bootstrap venv, install deps, run app.

Works on Linux, macOS, and Windows with only stdlib Python (>=3.11).
Auto-detects the right `python` executable, creates `.venv/` if missing,
installs requirements once, and executes the app.

Usage:
    python run.py                   # GUI
    python run.py --folder ./vids   # CLI
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
REQ = ROOT / "requirements.txt"
SRC = ROOT / "src"


def _venv_python() -> Path:
    if platform.system() == "Windows":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def _venv_pip() -> Path:
    if platform.system() == "Windows":
        return VENV / "Scripts" / "pip.exe"
    return VENV / "bin" / "pip"


def _ensure_venv() -> None:
    if _venv_python().exists():
        return
    print(">> Creating virtual environment in .venv/")
    subprocess.check_call([sys.executable, "-m", "venv", str(VENV)])
    subprocess.check_call([str(_venv_pip()), "install", "--upgrade", "pip", "--quiet"])
    if REQ.exists():
        print(">> Installing requirements")
        subprocess.check_call([str(_venv_pip()), "install", "-r", str(REQ), "--quiet"])


def _check_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        print(
            "HATA: ffmpeg PATH'te bulunamadı.\n"
            "Linux:   pacman -S ffmpeg / apt install ffmpeg / dnf install ffmpeg\n"
            "macOS:   brew install ffmpeg\n"
            "Windows: winget install Gyan.FFmpeg  (veya https://www.gyan.dev/ffmpeg/)",
            file=sys.stderr,
        )
        sys.exit(2)


def main(argv: list[str]) -> int:
    _check_ffmpeg()
    _ensure_venv()
    env = os.environ.copy()
    # PYTHONPATH so 'video_extender' resolves from src/
    existing_pp = env.get("PYTHONPATH", "")
    sep = ";" if platform.system() == "Windows" else ":"
    env["PYTHONPATH"] = str(SRC) + (sep + existing_pp if existing_pp else "")
    cmd = [str(_venv_python()), "-m", "video_extender", *argv]
    return subprocess.call(cmd, env=env)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

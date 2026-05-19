"""Entry point: `python -m video_extender [args]`.

With no args -> launches GUI.
With args -> delegates to CLI.
"""
from __future__ import annotations

import os
import sys


def _patch_bundled_ffmpeg_path() -> None:
    """When running as a PyInstaller --onefile bundle, ffmpeg + ffprobe are
    extracted next to the executable inside sys._MEIPASS. Prepend that dir to
    PATH so `shutil.which("ffmpeg")` in core.hardware finds them.

    No-op when running from source (sys.frozen is unset)."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        meipass = sys._MEIPASS
        os.environ["PATH"] = meipass + os.pathsep + os.environ.get("PATH", "")


def main() -> int:
    _patch_bundled_ffmpeg_path()
    if len(sys.argv) > 1:
        from video_extender.cli import main as cli_main
        return cli_main()
    from video_extender.app import main as gui_main
    return gui_main()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130) from None

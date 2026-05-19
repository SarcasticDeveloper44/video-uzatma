"""Entry point: `python -m video_extender [args]`.

With no args -> launches GUI.
With args -> delegates to CLI.
"""
from __future__ import annotations

import sys


def main() -> int:
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

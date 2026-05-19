"""FFmpeg subprocess wrapper with structured progress events.

Uses `-progress pipe:1` for clean machine-readable progress (key=value lines)
on stdout, keeping stderr for human/debug logs.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import shlex
import subprocess
import sys
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from video_extender.core.hardware import detect
from video_extender.utils import logging as _logging

log = _logging.get("ffmpeg")


def _nice_popen_kwargs() -> dict[str, object]:
    """Popen kwargs that lower ffmpeg's priority so long batches don't lag
    the user's interactive use. CPU-only — we don't touch I/O priority
    because the user might be on a fast NVMe where it doesn't matter, or
    on a network share where ionice has no effect.

    Linux/macOS: `preexec_fn=os.nice(10)` runs in the forked child before
    exec, so only the ffmpeg process gets niced (the parent Python stays
    at normal priority).

    Windows: `creationflags=BELOW_NORMAL_PRIORITY_CLASS` is the equivalent.
    Equivalent constant value 0x4000 used directly so we don't depend on
    the platform-specific subprocess attribute (which lives on
    subprocess.BELOW_NORMAL_PRIORITY_CLASS on Windows but doesn't exist
    on POSIX).
    """
    if sys.platform == "win32":
        return {"creationflags": 0x4000}  # BELOW_NORMAL_PRIORITY_CLASS
    # POSIX: nice +10 in the child only. Caught exceptions ensure we never
    # break ffmpeg start over a niceness adjustment.
    def _nice_child() -> None:
        try:
            os.nice(10)
        except OSError:
            pass
    return {"preexec_fn": _nice_child}


@dataclass
class ProgressEvent:
    out_time_us: int = 0           # current output time in microseconds
    frame: int = 0
    fps: float = 0.0
    bitrate: str = ""
    speed: float = 0.0
    total_size: int = 0
    finished: bool = False
    raw: dict[str, str] = field(default_factory=dict)

    @property
    def out_time_s(self) -> float:
        return self.out_time_us / 1_000_000.0


ProgressCallback = Callable[[ProgressEvent], None]


@dataclass
class FFmpegResult:
    returncode: int
    stderr_log: str
    cmd: list[str]
    cancelled: bool = False

    @property
    def success(self) -> bool:
        return self.returncode == 0 and not self.cancelled


_KEYVAL_RE = re.compile(r"^([^=]+)=(.*)$")


def _coerce_progress_kv(buffer: dict[str, str]) -> ProgressEvent:
    ev = ProgressEvent(raw=dict(buffer))
    try:
        if "out_time_ms" in buffer:
            # ffmpeg's `out_time_ms` is actually microseconds despite name.
            ev.out_time_us = int(buffer["out_time_ms"])
        if "frame" in buffer:
            ev.frame = int(buffer["frame"])
        if "fps" in buffer and buffer["fps"] != "N/A":
            ev.fps = float(buffer["fps"])
        if "bitrate" in buffer:
            ev.bitrate = buffer["bitrate"]
        if "speed" in buffer and buffer["speed"] not in ("N/A", "0x"):
            ev.speed = float(buffer["speed"].rstrip("x")) if buffer["speed"].endswith("x") else float(buffer["speed"])
        if "total_size" in buffer and buffer["total_size"] != "N/A":
            ev.total_size = int(buffer["total_size"])
        if buffer.get("progress") == "end":
            ev.finished = True
    except (ValueError, KeyError):
        pass
    return ev


class FFmpegRunner:
    """Single-shot ffmpeg runner with cancellation and progress callbacks."""

    def __init__(
        self,
        *,
        ffmpeg_path: str | None = None,
        ffprobe_path: str | None = None,
    ) -> None:
        hw = detect()
        ffmpeg = ffmpeg_path or hw.ffmpeg_path
        ffprobe = ffprobe_path or hw.ffprobe_path
        if not ffmpeg:
            raise FileNotFoundError("ffmpeg binary not found on PATH")
        if not ffprobe:
            raise FileNotFoundError("ffprobe binary not found on PATH")
        # Type-narrowed in local scope; assign to typed attributes.
        self.ffmpeg: str = ffmpeg
        self.ffprobe: str = ffprobe
        self._proc: subprocess.Popen[bytes] | None = None
        self._cancelled = False
        self._lock = threading.Lock()

    # ---- ffprobe ----
    def probe(self, path: Path) -> dict[str, Any]:
        cmd = [
            self.ffprobe, "-v", "error",
            "-print_format", "json",
            "-show_format", "-show_streams",
            str(path),
        ]
        log.debug("ffprobe: %s", shlex.join(cmd))
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
        if out.returncode != 0:
            raise RuntimeError(f"ffprobe failed: {out.stderr.strip()}")
        result: dict[str, Any] = json.loads(out.stdout)
        return result

    # ---- ffmpeg ----
    def run(
        self,
        args: Iterable[str],
        *,
        on_progress: ProgressCallback | None = None,
        stderr_log_path: Path | None = None,
    ) -> FFmpegResult:
        """Run ffmpeg with structured progress.

        `args` should NOT include the ffmpeg binary itself, nor `-progress`/`-nostats`
        flags — those are injected. Caller provides inputs, filters, outputs.
        """
        cmd = [
            self.ffmpeg, "-hide_banner", "-y",
            "-nostats", "-progress", "pipe:1",
            *args,
        ]
        log.info("ffmpeg: %s", shlex.join(cmd))
        with self._lock:
            self._cancelled = False
            # `_nice_popen_kwargs()` returns `creationflags` on Windows and
            # `preexec_fn` on POSIX — the union doesn't satisfy any single
            # Popen overload, but the runtime call is correct.
            self._proc = subprocess.Popen(  # type: ignore[call-overload]
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                **_nice_popen_kwargs(),
            )
        proc = self._proc

        stderr_lines: list[str] = []

        def _drain_stderr() -> None:
            assert proc.stderr is not None
            for line in iter(proc.stderr.readline, b""):
                try:
                    decoded = line.decode("utf-8", errors="replace").rstrip()
                except Exception:
                    continue
                stderr_lines.append(decoded)
                if log.isEnabledFor(10):  # DEBUG
                    log.debug("ffmpeg-stderr: %s", decoded)

        t = threading.Thread(target=_drain_stderr, daemon=True)
        t.start()

        buffer: dict[str, str] = {}
        try:
            assert proc.stdout is not None
            for raw in iter(proc.stdout.readline, b""):
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                m = _KEYVAL_RE.match(line)
                if not m:
                    continue
                key, val = m.group(1), m.group(2)
                buffer[key] = val
                if key == "progress":
                    ev = _coerce_progress_kv(buffer)
                    if on_progress is not None:
                        try:
                            on_progress(ev)
                        except Exception as exc:
                            log.warning("progress callback raised: %s", exc)
                    buffer.clear()
                    if ev.finished:
                        break
        finally:
            proc.wait()
            t.join(timeout=1.0)
            # Explicitly close the pipe file descriptors. Popen.__del__ would
            # eventually close them but we'd leak fds + emit ResourceWarning
            # during the batch (one leak per encode × 50 videos = exhaustion).
            for stream in (proc.stdout, proc.stderr):
                if stream is not None:
                    with contextlib.suppress(OSError):
                        stream.close()

        stderr_log = "\n".join(stderr_lines)
        if stderr_log_path is not None:
            try:
                stderr_log_path.parent.mkdir(parents=True, exist_ok=True)
                stderr_log_path.write_text(stderr_log, encoding="utf-8")
            except OSError as exc:
                log.warning("failed to write stderr log: %s", exc)

        with self._lock:
            cancelled = self._cancelled
            self._proc = None

        return FFmpegResult(
            returncode=proc.returncode,
            stderr_log=stderr_log,
            cmd=cmd,
            cancelled=cancelled,
        )

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
            if self._proc is not None and self._proc.poll() is None:
                with contextlib.suppress(OSError):
                    self._proc.terminate()

    def pause(self) -> bool:
        """Suspend the encoder subprocess. SIGSTOP on Unix; on Windows
        falls back to no-op (no portable pause primitive — would need
        NtSuspendProcess). Returns True on success."""
        with self._lock:
            proc = self._proc
        if proc is None or proc.poll() is not None:
            return False
        try:
            import signal
            proc.send_signal(signal.SIGSTOP)
            return True
        except (AttributeError, OSError, ValueError):
            return False

    def resume(self) -> bool:
        """Resume a paused encoder subprocess (SIGCONT)."""
        with self._lock:
            proc = self._proc
        if proc is None or proc.poll() is not None:
            return False
        try:
            import signal
            proc.send_signal(signal.SIGCONT)
            return True
        except (AttributeError, OSError, ValueError):
            return False

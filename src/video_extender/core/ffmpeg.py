"""FFmpeg subprocess wrapper with structured progress events.

Uses `-progress pipe:1` for clean machine-readable progress (key=value lines)
on stdout, keeping stderr for human/debug logs.
"""
from __future__ import annotations

import json
import re
import shlex
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from video_extender.core.hardware import detect
from video_extender.utils import logging as _logging

log = _logging.get("ffmpeg")


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
        self.ffmpeg = ffmpeg_path or hw.ffmpeg_path
        self.ffprobe = ffprobe_path or hw.ffprobe_path
        if not self.ffmpeg:
            raise FileNotFoundError("ffmpeg binary not found on PATH")
        if not self.ffprobe:
            raise FileNotFoundError("ffprobe binary not found on PATH")
        self._proc: subprocess.Popen[bytes] | None = None
        self._cancelled = False
        self._lock = threading.Lock()

    # ---- ffprobe ----
    def probe(self, path: Path) -> dict:
        cmd = [
            self.ffprobe, "-v", "error",
            "-print_format", "json",
            "-show_format", "-show_streams",
            str(path),
        ]
        log.debug("ffprobe: %s", shlex.join(cmd))
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if out.returncode != 0:
            raise RuntimeError(f"ffprobe failed: {out.stderr.strip()}")
        return json.loads(out.stdout)

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
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
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
                try:
                    self._proc.terminate()
                except OSError:
                    pass

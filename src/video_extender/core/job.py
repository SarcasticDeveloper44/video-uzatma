"""Job model: source video → planned output, status, progress."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from video_extender.utils.ffprobe_parser import MediaInfo


class JobStatus(str, Enum):
    PENDING = "pending"
    PROBING = "probing"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class ExtendMode(str, Enum):
    ADD = "add"        # add N seconds to current duration
    FILL = "fill"      # extend up to a target total duration


@dataclass
class JobSpec:
    """Per-batch settings applied to every video in the batch."""
    extend_seconds: float
    extend_mode: ExtendMode
    extender_name: str                 # e.g. "freeze", "black", "loop"
    preset_name: str                   # e.g. "tiktok", "meta_reels"
    quality: str = "medium"            # "low" | "medium" | "high"
    video_codec: str = "h264"          # "h264" | "hevc" (more in future)
    filters: tuple[str, ...] = ()      # filter chain names, in order
    filter_options: dict[str, Any] = field(default_factory=dict)
    extender_options: dict[str, Any] = field(default_factory=dict)
    filename_template: str = "{name}_extended.{ext}"
    audio_fade_out_seconds: float = 1.5
    output_subdir: str = "output"


@dataclass
class Job:
    source: Path
    media: MediaInfo | None = None
    output: Path | None = None
    spec: JobSpec | None = None
    status: JobStatus = JobStatus.PENDING
    progress: float = 0.0              # 0.0–1.0
    error: str | None = None
    stderr_log: Path | None = None
    target_duration: float = 0.0       # computed final duration (s)

    @property
    def name(self) -> str:
        return self.source.name

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": str(self.source),
            "output": str(self.output) if self.output else None,
            "status": self.status.value,
            "progress": self.progress,
            "error": self.error,
            "target_duration": self.target_duration,
        }

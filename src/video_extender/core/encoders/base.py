"""EncoderBackend ABC + auto-registry."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import ClassVar

from video_extender.core.hardware import HardwareInfo


@dataclass
class EncoderArgs:
    """ffmpeg arguments contributed by an encoder backend.

    Pipeline integration:
        ffmpeg [hw_init_args] -hide_banner -y -progress pipe:1 \\
               [...input args + filter_complex...] \\
               <video_args> <audio_args> <container_args> output

    If `gpu_upload_filter` is set, the pipeline appends it to the END of the
    video filter_complex (e.g. "format=nv12,hwupload" before VAAPI encode),
    producing a hwframe stream that the encoder consumes.
    """
    video_args: tuple[str, ...] = ()
    audio_args: tuple[str, ...] = ()
    container_args: tuple[str, ...] = ()   # e.g. ("-movflags", "+faststart")
    preferred_ext: str = "mp4"
    hw_init_args: tuple[str, ...] = field(default_factory=tuple)
    # Filter to append at the end of the chain to convert frames into a
    # format the encoder accepts. Empty for CPU encoders / encoders that
    # accept arbitrary CPU pixel formats (AMF, VideoToolbox, NVENC).
    gpu_upload_filter: str = ""


ENCODER_REGISTRY: dict[str, type["EncoderBackend"]] = {}


class EncoderBackend(ABC):
    name: ClassVar[str] = ""           # internal id, e.g. "nvenc_h264"
    label: ClassVar[str] = ""
    ffmpeg_encoder: ClassVar[str] = "" # ffmpeg encoder name, e.g. "h264_nvenc"
    kind: ClassVar[str] = "cpu"        # "gpu" | "cpu"
    codec: ClassVar[str] = "h264"      # "h264" | "hevc" | "av1" | "vp9"

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if getattr(cls, "name", ""):
            ENCODER_REGISTRY[cls.name] = cls

    @classmethod
    def available(cls, hw: HardwareInfo) -> bool:
        return cls.ffmpeg_encoder in hw.available_encoders

    @abstractmethod
    def build_args(
        self,
        *,
        bitrate_kbps: int,
        audio_bitrate_kbps: int,
        crf: int | None,
        gpu_index: int | None,
        threads: int,
        extra: dict | None = None,
    ) -> EncoderArgs:
        raise NotImplementedError

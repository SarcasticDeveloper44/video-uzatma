"""Unit tests for the stream-copy fast path eligibility + plan construction."""
from __future__ import annotations

from pathlib import Path

import pytest

from video_extender.core import fast_path
from video_extender.core.extenders import EXTENDER_REGISTRY
from video_extender.core.job import ExtendMode, Job, JobSpec
from video_extender.utils.ffprobe_parser import AudioStream, MediaInfo, VideoStream


def _h264_media(codec: str = "h264", duration: float = 3.0) -> MediaInfo:
    return MediaInfo(
        path="/x/in.mp4", duration=duration, size=1000, container="mov,mp4",
        video=VideoStream(
            index=0, codec=codec, width=720, height=1280, fps=30.0,
            pix_fmt="yuv420p", bitrate=1_000_000,
        ),
        audio=AudioStream(
            index=1, codec="aac", sample_rate=44100, channels=2,
            bitrate=128_000,
        ),
    )


def _make_job(
    *,
    src: str = "/tmp/in.mp4",
    media: MediaInfo | None = None,
    spec: JobSpec | None = None,
) -> Job:
    return Job(
        source=Path(src),
        media=media or _h264_media(),
        spec=spec,
        output=Path("/tmp/out.mp4"),
    )


def _spec(**kw: object) -> JobSpec:
    base: dict[str, object] = dict(
        extend_seconds=10.0, extend_mode=ExtendMode.ADD,
        extender_name="loop", preset_name="tiktok",
        quality="medium", video_codec="h264",
    )
    base.update(kw)
    return JobSpec(**base)  # type: ignore[arg-type]


class TestEligibility:
    def test_happy_path_h264_mp4(self) -> None:
        ok, reason = fast_path.is_eligible(_make_job(), _spec())
        assert ok, reason

    def test_codec_family_h264_aliases(self) -> None:
        for src_codec in ("h264", "avc", "avc1"):
            job = _make_job(media=_h264_media(codec=src_codec))
            ok, _ = fast_path.is_eligible(job, _spec(video_codec="h264"))
            assert ok, src_codec

    def test_codec_family_hevc_aliases(self) -> None:
        for src_codec in ("hevc", "h265", "hev1", "hvc1"):
            job = _make_job(media=_h264_media(codec=src_codec))
            ok, _ = fast_path.is_eligible(job, _spec(video_codec="hevc"))
            assert ok, src_codec

    def test_codec_mismatch_disqualifies(self) -> None:
        job = _make_job(media=_h264_media(codec="vp9"))
        ok, reason = fast_path.is_eligible(job, _spec(video_codec="h264"))
        assert not ok and "codec" in reason

    def test_filter_chain_disqualifies(self) -> None:
        ok, reason = fast_path.is_eligible(
            _make_job(), _spec(filters=("watermark",)),
        )
        assert not ok and "filter" in reason

    def test_crf_mode_disqualifies(self) -> None:
        ok, reason = fast_path.is_eligible(
            _make_job(), _spec(quality_mode="crf", crf=23),
        )
        assert not ok and "crf" in reason

    def test_unprobed_source_disqualifies(self) -> None:
        job = Job(source=Path("/x/y.mp4"), media=None, output=Path("/x/out.mp4"))
        ok, reason = fast_path.is_eligible(job, _spec())
        assert not ok and "probe" in reason.lower()

    def test_unsupported_container_disqualifies(self) -> None:
        job = _make_job(src="/tmp/in.webm")
        ok, reason = fast_path.is_eligible(job, _spec())
        assert not ok and "container" in reason


class TestExtenderFastPaths:
    """Each extender that implements build_fast_path must produce a usable plan."""

    def test_loop_single_command(self, tmp_path: Path) -> None:
        ext = EXTENDER_REGISTRY["loop"]()
        # encoder_args is supplied by caller; we mock with a trivial value.
        from video_extender.core.encoders.libx264 import Libx264
        enc = Libx264()
        enc_args = enc.build_args(
            bitrate_kbps=5000, audio_bitrate_kbps=128,
            crf=None, gpu_index=None, threads=4,
        )
        from video_extender.core.scheduler import WorkerKind, WorkerSlot
        slot = WorkerSlot(kind=WorkerKind.CPU, encoder="libx264",
                          threads=4, gpu_index=None, label="t")
        plan = ext.build_fast_path(
            source=Path("/tmp/in.mp4"), media=_h264_media(),
            target_duration=30.0, output=tmp_path / "out.mp4",
            encoder=enc, encoder_args=enc_args, slot=slot,
            tmp_dir=tmp_path, audio_fade_out_seconds=1.5,
        )
        assert plan is not None
        # Loop fast path is exactly ONE command (stream_loop + -c copy + -t).
        assert len(plan.commands) == 1
        cmd = plan.commands[0]
        assert "-stream_loop" in cmd and "-1" in cmd
        assert "-c" in cmd and "copy" in cmd
        assert "-t" in cmd and "30.000" in cmd
        assert plan.temp_files == []

    def test_freeze_three_stage(self, tmp_path: Path) -> None:
        ext = EXTENDER_REGISTRY["freeze"]()
        from video_extender.core.encoders.libx264 import Libx264
        enc = Libx264()
        enc_args = enc.build_args(
            bitrate_kbps=5000, audio_bitrate_kbps=128,
            crf=None, gpu_index=None, threads=4,
        )
        from video_extender.core.scheduler import WorkerKind, WorkerSlot
        slot = WorkerSlot(kind=WorkerKind.CPU, encoder="libx264",
                          threads=4, gpu_index=None, label="t")
        plan = ext.build_fast_path(
            source=Path("/tmp/in.mp4"), media=_h264_media(duration=3.0),
            target_duration=30.0, output=tmp_path / "out.mp4",
            encoder=enc, encoder_args=enc_args, slot=slot,
            tmp_dir=tmp_path, audio_fade_out_seconds=1.5,
        )
        assert plan is not None
        # freeze: extract last frame, encode tail, concat-copy → 3 commands.
        assert len(plan.commands) == 3
        extract, encode, concat = plan.commands
        assert "-sseof" in extract
        assert "-loop" in encode and "1" in encode
        assert "-f" in concat and "concat" in concat
        # 3 temp files: lastframe.png, tail.mp4, concat.txt
        assert len(plan.temp_files) == 3

    def test_freeze_returns_none_when_no_extension_needed(
        self, tmp_path: Path,
    ) -> None:
        ext = EXTENDER_REGISTRY["freeze"]()
        from video_extender.core.encoders.libx264 import Libx264
        enc = Libx264()
        enc_args = enc.build_args(
            bitrate_kbps=5000, audio_bitrate_kbps=128, crf=None,
            gpu_index=None, threads=4,
        )
        from video_extender.core.scheduler import WorkerKind, WorkerSlot
        slot = WorkerSlot(kind=WorkerKind.CPU, encoder="libx264",
                          threads=4, gpu_index=None, label="t")
        # target == source → no tail needed, fast path declines.
        plan = ext.build_fast_path(
            source=Path("/tmp/in.mp4"), media=_h264_media(duration=10.0),
            target_duration=10.0, output=tmp_path / "out.mp4",
            encoder=enc, encoder_args=enc_args, slot=slot,
            tmp_dir=tmp_path, audio_fade_out_seconds=1.5,
        )
        assert plan is None

    def test_black_two_stage(self, tmp_path: Path) -> None:
        ext = EXTENDER_REGISTRY["black"]()
        from video_extender.core.encoders.libx264 import Libx264
        enc = Libx264()
        enc_args = enc.build_args(
            bitrate_kbps=5000, audio_bitrate_kbps=128, crf=None,
            gpu_index=None, threads=4,
        )
        from video_extender.core.scheduler import WorkerKind, WorkerSlot
        slot = WorkerSlot(kind=WorkerKind.CPU, encoder="libx264",
                          threads=4, gpu_index=None, label="t")
        plan = ext.build_fast_path(
            source=Path("/tmp/in.mp4"), media=_h264_media(duration=3.0),
            target_duration=30.0, output=tmp_path / "out.mp4",
            encoder=enc, encoder_args=enc_args, slot=slot,
            tmp_dir=tmp_path, audio_fade_out_seconds=1.5,
        )
        assert plan is not None
        # black: lavfi tail + concat-copy → 2 commands.
        assert len(plan.commands) == 2
        encode, concat = plan.commands
        assert "lavfi" in encode and "color=c=black" in " ".join(encode)
        assert "concat" in concat

    def test_image_card_fast_path(self, tmp_path: Path) -> None:
        """image_card with options['image'] → 2-stage fast path."""
        # Create a small PNG fixture
        png = tmp_path / "card.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        ext = EXTENDER_REGISTRY["image_card"]()
        from video_extender.core.encoders.libx264 import Libx264
        enc = Libx264()
        enc_args = enc.build_args(
            bitrate_kbps=5000, audio_bitrate_kbps=128, crf=None,
            gpu_index=None, threads=4,
        )
        from video_extender.core.scheduler import WorkerKind, WorkerSlot
        slot = WorkerSlot(kind=WorkerKind.CPU, encoder="libx264",
                          threads=4, gpu_index=None, label="t")
        plan = ext.build_fast_path(
            source=Path("/tmp/in.mp4"), media=_h264_media(duration=3.0),
            target_duration=10.0, output=tmp_path / "out.mp4",
            encoder=enc, encoder_args=enc_args, slot=slot,
            tmp_dir=tmp_path, audio_fade_out_seconds=1.5,
            options={"image": str(png)},
        )
        assert plan is not None
        # encode (looped image + silence) + concat-copy → 2 commands
        assert len(plan.commands) == 2

    def test_image_card_returns_none_without_options(self, tmp_path: Path) -> None:
        ext = EXTENDER_REGISTRY["image_card"]()
        from video_extender.core.encoders.libx264 import Libx264
        enc = Libx264()
        enc_args = enc.build_args(
            bitrate_kbps=5000, audio_bitrate_kbps=128, crf=None,
            gpu_index=None, threads=4,
        )
        from video_extender.core.scheduler import WorkerKind, WorkerSlot
        slot = WorkerSlot(kind=WorkerKind.CPU, encoder="libx264",
                          threads=4, gpu_index=None, label="t")
        plan = ext.build_fast_path(
            source=Path("/tmp/in.mp4"), media=_h264_media(duration=3.0),
            target_duration=10.0, output=tmp_path / "out.mp4",
            encoder=enc, encoder_args=enc_args, slot=slot,
            tmp_dir=tmp_path, audio_fade_out_seconds=1.5,
            options={},  # missing 'image'
        )
        assert plan is None

    def test_intro_outro_has_no_fast_path(self) -> None:
        """intro_outro composition is too complex; deferred."""
        ext = EXTENDER_REGISTRY["intro_outro"]()
        assert not hasattr(ext, "build_fast_path")


class TestCleanup:
    def test_cleanup_removes_existing_files(self, tmp_path: Path) -> None:
        f1 = tmp_path / "a.txt"
        f1.write_text("x")
        f2 = tmp_path / "b.txt"
        f2.write_text("y")
        plan = fast_path.FastPathPlan(
            commands=[], temp_files=[f1, f2], output=tmp_path / "out.mp4",
        )
        fast_path.cleanup(plan)
        assert not f1.exists()
        assert not f2.exists()

    def test_cleanup_tolerates_missing(self, tmp_path: Path) -> None:
        ghost = tmp_path / "ghost.txt"  # never created
        plan = fast_path.FastPathPlan(
            commands=[], temp_files=[ghost], output=tmp_path / "out.mp4",
        )
        # Must not raise.
        fast_path.cleanup(plan)

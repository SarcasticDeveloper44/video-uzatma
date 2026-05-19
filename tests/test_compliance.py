"""Tests for Meta Ads technical compliance checks."""
from __future__ import annotations

from pathlib import Path

from video_extender.core import compliance
from video_extender.utils.ffprobe_parser import AudioStream, MediaInfo, VideoStream


def _media(
    *,
    width: int = 1080,
    height: int = 1920,
    duration: float = 30.0,
    fps: float = 30.0,
    codec: str = "h264",
    pix_fmt: str = "yuv420p",
    audio_codec: str = "aac",
) -> MediaInfo:
    return MediaInfo(
        path="/x/in.mp4", duration=duration, size=1000, container="mov,mp4",
        video=VideoStream(
            index=0, codec=codec, width=width, height=height, fps=fps,
            pix_fmt=pix_fmt, bitrate=5_000_000,
        ),
        audio=AudioStream(
            index=1, codec=audio_codec, sample_rate=44100, channels=2,
            bitrate=128_000,
        ),
    )


class TestSourceCompliance:
    def test_compliant_source_no_issues(self) -> None:
        report = compliance.check_source(_media())
        assert report.ok
        assert not report.issues

    def test_no_video_stream_fails(self) -> None:
        report = compliance.check_source(MediaInfo(
            path="/x", duration=10.0, size=100, container="?",
            video=None, audio=None,
        ))
        assert not report.ok
        assert any(i.code == "no-video" for i in report.issues)

    def test_low_resolution_warns(self) -> None:
        # 720p is below Meta's 1080p preferred minimum
        report = compliance.check_source(_media(width=720, height=1280))
        codes = [i.code for i in report.issues]
        assert "low-resolution" in codes

    def test_nonstandard_aspect_warns(self) -> None:
        # 2.39:1 is cinematic; Meta doesn't accept it natively
        report = compliance.check_source(_media(width=2390, height=1000))
        codes = [i.code for i in report.issues]
        assert "nonstandard-aspect" in codes

    def test_supported_aspects_pass(self) -> None:
        cases = [(1080, 1920), (1920, 1080), (1080, 1080), (1080, 1350)]
        for w, h in cases:
            report = compliance.check_source(_media(width=w, height=h))
            codes = [i.code for i in report.issues]
            assert "nonstandard-aspect" not in codes, f"{w}x{h} should pass"

    def test_high_fps_warns(self) -> None:
        report = compliance.check_source(_media(fps=120.0))
        codes = [i.code for i in report.issues]
        assert "high-fps" in codes

    def test_long_duration_warns(self) -> None:
        report = compliance.check_source(_media(duration=600.0))
        codes = [i.code for i in report.issues]
        assert "long-duration" in codes


class TestReportSemantics:
    def test_empty_report_summary(self) -> None:
        r = compliance.ComplianceReport()
        assert r.summary() == "✓ Meta uyumlu"
        assert r.ok
        assert not r.has_warnings

    def test_mixed_report_summary(self) -> None:
        r = compliance.ComplianceReport()
        r.issues.append(compliance.ComplianceIssue(
            severity="warning", code="x", message="m1",
        ))
        r.issues.append(compliance.ComplianceIssue(
            severity="fail", code="y", message="m2",
        ))
        assert not r.ok
        assert r.has_warnings
        assert "hata" in r.summary()
        assert "uyarı" in r.summary()


class TestOutputCompliance:
    def test_missing_file_fails(self, tmp_path: Path) -> None:
        report = compliance.check_output(tmp_path / "ghost.mp4")
        assert not report.ok
        assert any(i.code == "missing-output" for i in report.issues)

    def test_unprobable_file_fails(self, tmp_path: Path) -> None:
        # Empty/garbage file → ffprobe fails
        bad = tmp_path / "bad.mp4"
        bad.write_bytes(b"not a video")
        report = compliance.check_output(bad)
        assert not report.ok
        # Either unprobable or no-video-out — both are "fail" severity
        codes = [i.code for i in report.issues]
        assert any(c in codes for c in ("unprobable-output", "no-video-out"))


class TestMetaModeOverrides:
    def test_overrides_include_h264_and_forced_filters(self) -> None:
        overrides = compliance.meta_mode_spec_overrides()
        assert overrides["video_codec"] == "h264"
        assert "audio_normalize" in overrides["_force_filters"]
        assert "metadata_strip" in overrides["_force_filters"]

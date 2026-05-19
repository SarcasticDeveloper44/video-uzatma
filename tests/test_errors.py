"""Unit tests for actionable ffmpeg error parsing."""
from __future__ import annotations

from video_extender.core import errors


class TestParseFFmpegFailure:
    def test_nvenc_session_exhaustion(self) -> None:
        stderr = (
            "Some normal lines\n"
            "[h264_nvenc @ 0x55] OpenEncodeSessionEx failed: out of memory (10)\n"
            "Final error\n"
        )
        r = errors.parse_ffmpeg_failure(1, stderr)
        assert "NVENC" in r.message
        assert "max-parallel" in r.suggestion or "driver" in r.suggestion

    def test_nvenc_driver_missing(self) -> None:
        stderr = "Cannot load nvenc — no NVENC capable devices found\n"
        r = errors.parse_ffmpeg_failure(1, stderr)
        assert "NVENC" in r.message
        assert "driver" in r.suggestion.lower()

    def test_disk_full(self) -> None:
        stderr = "Error writing output: No space left on device\n"
        r = errors.parse_ffmpeg_failure(1, stderr)
        assert "Disk dolu" in r.message
        assert "yer aç" in r.suggestion or "yer ac" in r.suggestion.lower()

    def test_permission_denied(self) -> None:
        stderr = "av_open: Permission denied\n"
        r = errors.parse_ffmpeg_failure(1, stderr)
        assert "izin" in r.message.lower() or "izni" in r.message.lower()

    def test_corrupt_source(self) -> None:
        stderr = "[mov,mp4] moov atom not found\n"
        r = errors.parse_ffmpeg_failure(1, stderr)
        assert "bozuk" in r.message.lower() or "moov" in r.message.lower()

    def test_oom(self) -> None:
        stderr = "Cannot allocate memory while encoding frame\n"
        r = errors.parse_ffmpeg_failure(1, stderr)
        assert "Bellek" in r.message or "bellek" in r.message.lower()

    def test_unknown_encoder(self) -> None:
        stderr = "Unknown encoder 'h266_nvenc'\n"
        r = errors.parse_ffmpeg_failure(1, stderr)
        assert "Encoder bulunamadı" in r.message
        # Captured group substituted in.
        assert "h266" in r.message

    def test_filter_not_found(self) -> None:
        stderr = "[AVFilterGraph] No such filter: 'scale_npp'\n"
        r = errors.parse_ffmpeg_failure(1, stderr)
        assert "Filter bulunamadı" in r.message
        assert "scale_npp" in r.message

    def test_vaapi_init_failure(self) -> None:
        stderr = "Failed to initialise VAAPI device\n"
        r = errors.parse_ffmpeg_failure(1, stderr)
        assert "VAAPI" in r.message
        assert "video" in r.suggestion.lower() or "dri" in r.suggestion.lower()

    def test_unrecognized_falls_back_to_raw(self) -> None:
        stderr = "Some completely novel error pattern we've never seen\n"
        r = errors.parse_ffmpeg_failure(7, stderr)
        # No pattern matched — falls back to raw tail with exit code.
        assert "exited 7" in r.message
        assert r.suggestion == ""

    def test_empty_stderr(self) -> None:
        r = errors.parse_ffmpeg_failure(1, "")
        # Should not crash.
        assert r.message  # has SOMETHING
        assert "exited 1" in r.message

    def test_format_with_suggestion(self) -> None:
        stderr = "No space left on device\n"
        r = errors.parse_ffmpeg_failure(1, stderr)
        formatted = r.format()
        assert "Disk dolu" in formatted
        assert "—" in formatted  # separator between message and suggestion

    def test_format_without_suggestion(self) -> None:
        stderr = "novel error\n"
        r = errors.parse_ffmpeg_failure(1, stderr)
        formatted = r.format()
        # No suggestion → no "Cözüm:" segment.
        assert "Cözüm" not in formatted

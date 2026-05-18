from unittest.mock import patch

from video_extender.core.hardware import _os_can_probe, detect


class TestHardwareDetection:
    def test_returns_hardware_info(self) -> None:
        hw = detect()
        assert hw.cpu_count > 0
        assert hw.ram_total_mb >= 0
        # ffmpeg should be present in our dev/CI env
        assert hw.ffmpeg_path is not None

    def test_encoder_capability_flags_consistent(self) -> None:
        hw = detect()
        assert hw.has_nvenc == any(e.endswith("_nvenc") for e in hw.available_encoders)
        assert hw.has_vaapi == any(e.endswith("_vaapi") for e in hw.available_encoders)
        assert hw.has_qsv == any(e.endswith("_qsv") for e in hw.available_encoders)
        assert hw.has_amf == any(e.endswith("_amf") for e in hw.available_encoders)

    def test_has_gpu_encoder_aggregates(self) -> None:
        hw = detect()
        expected = any([hw.has_nvenc, hw.has_qsv, hw.has_vaapi, hw.has_amf, hw.has_videotoolbox])
        assert hw.has_gpu_encoder == expected

    def test_cached(self) -> None:
        hw1 = detect()
        hw2 = detect()
        assert hw1 is hw2  # lru_cache hit


class TestOsEncoderCompat:
    """`_os_can_probe` must short-circuit impossible OS x encoder combos so
    we don't waste seconds running ffmpeg probes that cannot succeed."""

    def _set_platform(self, name: str):
        return patch("video_extender.core.hardware.platform.system", return_value=name)

    def test_linux_skips_videotoolbox(self) -> None:
        with self._set_platform("Linux"):
            assert _os_can_probe("h264_videotoolbox") is False
            assert _os_can_probe("h264_nvenc") is True
            assert _os_can_probe("h264_vaapi") is True
            assert _os_can_probe("h264_qsv") is True

    def test_macos_skips_nvenc_vaapi_amf_qsv(self) -> None:
        with self._set_platform("Darwin"):
            for inc in ("h264_nvenc", "h264_vaapi", "h264_amf", "h264_qsv",
                        "hevc_nvenc", "hevc_vaapi"):
                assert _os_can_probe(inc) is False, inc
            assert _os_can_probe("h264_videotoolbox") is True
            assert _os_can_probe("hevc_videotoolbox") is True

    def test_windows_skips_vaapi(self) -> None:
        with self._set_platform("Windows"):
            assert _os_can_probe("h264_vaapi") is False
            assert _os_can_probe("hevc_vaapi") is False
            # Windows supports NVENC + AMF + QSV
            assert _os_can_probe("h264_nvenc") is True
            assert _os_can_probe("h264_amf") is True
            assert _os_can_probe("h264_qsv") is True

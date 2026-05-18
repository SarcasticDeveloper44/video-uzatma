from video_extender.core.hardware import detect


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

from video_extender.core.encoders import ENCODER_REGISTRY


class TestEncoderRegistry:
    def test_has_working_encoders(self) -> None:
        for name in ("nvenc_h264", "libx264", "nvenc_hevc", "libx265"):
            assert name in ENCODER_REGISTRY

    def test_codec_metadata(self) -> None:
        assert ENCODER_REGISTRY["nvenc_h264"].codec == "h264"
        assert ENCODER_REGISTRY["libx264"].codec == "h264"
        assert ENCODER_REGISTRY["nvenc_hevc"].codec == "hevc"
        assert ENCODER_REGISTRY["libx265"].codec == "hevc"

    def test_kind_metadata(self) -> None:
        assert ENCODER_REGISTRY["nvenc_h264"].kind == "gpu"
        assert ENCODER_REGISTRY["libx264"].kind == "cpu"


class TestNvencH264:
    def test_vbr_args(self) -> None:
        enc = ENCODER_REGISTRY["nvenc_h264"]()
        args = enc.build_args(bitrate_kbps=5000, audio_bitrate_kbps=128,
                              crf=None, gpu_index=0, threads=2)
        vargs = list(args.video_args)
        assert "-c:v" in vargs and "h264_nvenc" in vargs
        assert "-b:v" in vargs and "5000k" in vargs
        assert "-gpu" in vargs and "0" in vargs

    def test_crf_mode(self) -> None:
        enc = ENCODER_REGISTRY["nvenc_h264"]()
        args = enc.build_args(bitrate_kbps=5000, audio_bitrate_kbps=128,
                              crf=23, gpu_index=0, threads=2)
        vargs = list(args.video_args)
        assert "-cq" in vargs and "23" in vargs

    def test_faststart(self) -> None:
        enc = ENCODER_REGISTRY["nvenc_h264"]()
        args = enc.build_args(bitrate_kbps=5000, audio_bitrate_kbps=128,
                              crf=None, gpu_index=0, threads=2)
        assert "-movflags" in args.container_args
        assert "+faststart" in args.container_args


class TestNvencHevc:
    def test_hevc_bitrate_reduced(self) -> None:
        """HEVC compresses ~30% better, so we expect lower target bitrate."""
        enc = ENCODER_REGISTRY["nvenc_hevc"]()
        args = enc.build_args(bitrate_kbps=10000, audio_bitrate_kbps=128,
                              crf=None, gpu_index=0, threads=2)
        vargs = list(args.video_args)
        # 10000 * 0.7 = 7000k expected
        assert "-b:v" in vargs and "7000k" in vargs
        assert "-tag:v" in vargs and "hvc1" in vargs


class TestLibx264:
    def test_cpu_thread_count_applied(self) -> None:
        enc = ENCODER_REGISTRY["libx264"]()
        args = enc.build_args(bitrate_kbps=5000, audio_bitrate_kbps=128,
                              crf=None, gpu_index=None, threads=6)
        vargs = list(args.video_args)
        assert "-threads" in vargs
        idx = vargs.index("-threads")
        assert vargs[idx + 1] == "6"


class TestLibx265:
    def test_hevc_tag_and_bitrate(self) -> None:
        enc = ENCODER_REGISTRY["libx265"]()
        args = enc.build_args(bitrate_kbps=10000, audio_bitrate_kbps=128,
                              crf=None, gpu_index=None, threads=4)
        vargs = list(args.video_args)
        assert "-tag:v" in vargs and "hvc1" in vargs
        # HEVC ~70% of H.264 bitrate
        assert "7000k" in vargs


class TestVaapi:
    def test_h264_vaapi_args(self) -> None:
        enc = ENCODER_REGISTRY["vaapi_h264"]()
        args = enc.build_args(bitrate_kbps=5000, audio_bitrate_kbps=128,
                              crf=None, gpu_index=None, threads=2)
        assert args.video_args[:2] == ("-c:v", "h264_vaapi")
        # Must declare hw init + filter upload
        assert "-vaapi_device" in args.hw_init_args
        assert "hwupload" in args.gpu_upload_filter
        assert "format=nv12" in args.gpu_upload_filter

    def test_hevc_vaapi_bitrate_dropped(self) -> None:
        enc = ENCODER_REGISTRY["vaapi_hevc"]()
        args = enc.build_args(bitrate_kbps=10000, audio_bitrate_kbps=128,
                              crf=None, gpu_index=None, threads=2)
        vargs = list(args.video_args)
        assert "-c:v" in vargs and "hevc_vaapi" in vargs
        assert "-tag:v" in vargs and "hvc1" in vargs
        # 10000 * 0.7 = 7000
        assert "7000k" in vargs


class TestQsv:
    def test_h264_qsv_args(self) -> None:
        enc = ENCODER_REGISTRY["qsv_h264"]()
        args = enc.build_args(bitrate_kbps=5000, audio_bitrate_kbps=128,
                              crf=None, gpu_index=None, threads=2)
        assert args.video_args[:2] == ("-c:v", "h264_qsv")
        assert "-init_hw_device" in args.hw_init_args
        assert "qsv=hw" in args.hw_init_args
        assert "hwupload" in args.gpu_upload_filter

    def test_hevc_qsv_tag(self) -> None:
        enc = ENCODER_REGISTRY["qsv_hevc"]()
        args = enc.build_args(bitrate_kbps=10000, audio_bitrate_kbps=128,
                              crf=None, gpu_index=None, threads=2)
        vargs = list(args.video_args)
        assert "hvc1" in vargs


class TestAmf:
    def test_h264_amf_no_hwupload_needed(self) -> None:
        """AMF accepts CPU pixel formats — no hw init / upload needed."""
        enc = ENCODER_REGISTRY["amf_h264"]()
        args = enc.build_args(bitrate_kbps=5000, audio_bitrate_kbps=128,
                              crf=None, gpu_index=None, threads=2)
        assert "-c:v" in args.video_args and "h264_amf" in args.video_args
        assert args.hw_init_args == ()
        assert args.gpu_upload_filter == ""

    def test_amf_hevc_tag(self) -> None:
        enc = ENCODER_REGISTRY["amf_hevc"]()
        args = enc.build_args(bitrate_kbps=10000, audio_bitrate_kbps=128,
                              crf=None, gpu_index=None, threads=2)
        vargs = list(args.video_args)
        assert "hvc1" in vargs


class TestVideoToolbox:
    def test_h264_vt_no_hwupload_needed(self) -> None:
        enc = ENCODER_REGISTRY["videotoolbox_h264"]()
        args = enc.build_args(bitrate_kbps=5000, audio_bitrate_kbps=128,
                              crf=None, gpu_index=None, threads=2)
        assert args.video_args[:2] == ("-c:v", "h264_videotoolbox")
        assert args.hw_init_args == ()
        assert args.gpu_upload_filter == ""

    def test_vt_hevc_tag(self) -> None:
        enc = ENCODER_REGISTRY["videotoolbox_hevc"]()
        args = enc.build_args(bitrate_kbps=10000, audio_bitrate_kbps=128,
                              crf=None, gpu_index=None, threads=2)
        vargs = list(args.video_args)
        assert "hvc1" in vargs


class TestAv1Vp9:
    def test_libsvtav1_args(self) -> None:
        enc = ENCODER_REGISTRY["libsvtav1"]()
        args = enc.build_args(bitrate_kbps=10000, audio_bitrate_kbps=128,
                              crf=None, gpu_index=None, threads=4)
        vargs = list(args.video_args)
        assert "-c:v" in vargs and "libsvtav1" in vargs
        # AV1 ~55% of H.264 bitrate
        assert "5500k" in vargs

    def test_libvpx_vp9_webm_default(self) -> None:
        enc = ENCODER_REGISTRY["libvpx_vp9"]()
        args = enc.build_args(bitrate_kbps=10000, audio_bitrate_kbps=128,
                              crf=None, gpu_index=None, threads=4)
        assert args.preferred_ext == "webm"
        # VP9 typically pairs with Opus audio
        assert "libopus" in args.audio_args


class TestCrossDeviceRegistry:
    def test_every_encoder_present(self) -> None:
        for name in ("vaapi_h264", "vaapi_hevc", "qsv_h264", "qsv_hevc",
                     "amf_h264", "amf_hevc", "videotoolbox_h264",
                     "videotoolbox_hevc", "libsvtav1", "libaom_av1", "libvpx_vp9"):
            assert name in ENCODER_REGISTRY, f"missing encoder: {name}"

    def test_no_encoder_raises_not_implemented(self) -> None:
        """Every registered encoder must produce real ffmpeg args — no scaffolds."""
        for name, cls in ENCODER_REGISTRY.items():
            try:
                cls().build_args(
                    bitrate_kbps=5000, audio_bitrate_kbps=128,
                    crf=None, gpu_index=None, threads=2,
                )
            except NotImplementedError as exc:
                raise AssertionError(
                    f"encoder {name} still scaffold (NotImplementedError)"
                ) from exc
            except Exception:  # noqa: BLE001
                # Some encoders may raise other errors on specific inputs; we
                # care that NotImplementedError is gone.
                pass

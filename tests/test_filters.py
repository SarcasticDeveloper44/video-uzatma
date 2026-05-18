from video_extender.core.filters import FILTER_REGISTRY


class TestFilterRegistry:
    def test_working_filters_registered(self) -> None:
        for name in ("watermark", "audio_normalize", "audio_fade_out",
                     "metadata_strip", "aspect_convert"):
            assert name in FILTER_REGISTRY


class TestWatermark:
    def test_no_image_disables_filter(self) -> None:
        frag = FILTER_REGISTRY["watermark"]().build(
            in_video="[v]", in_audio="[a]", next_input_index=1, options={},
        )
        assert frag.filter_segment == ""
        assert frag.extra_inputs == ()

    def test_image_path_added_with_loop(self, logo_png) -> None:
        frag = FILTER_REGISTRY["watermark"]().build(
            in_video="[v]", in_audio="[a]", next_input_index=1,
            options={"image": str(logo_png), "_main_width": 1080},
        )
        assert frag.extra_inputs == (str(logo_png),)
        assert frag.prefix_input_args == ("-loop", "1")
        # 1080 * 0.15 = 162
        assert "scale=162:-1" in frag.filter_segment
        assert "overlay=" in frag.filter_segment

    def test_position_presets(self, logo_png) -> None:
        for pos, expected_x in [
            ("top-left", "10:10"),
            ("top-right", "W-w-10:10"),
            ("bottom-left", "10:H-h-10"),
            ("bottom-right", "W-w-10:H-h-10"),
            ("center", "(W-w)/2:(H-h)/2"),
        ]:
            frag = FILTER_REGISTRY["watermark"]().build(
                in_video="[v]", in_audio="[a]", next_input_index=1,
                options={"image": str(logo_png), "position": pos, "_main_width": 1080},
            )
            assert expected_x in frag.filter_segment, f"position={pos} expected {expected_x}"

    def test_opacity_applied(self, logo_png) -> None:
        frag = FILTER_REGISTRY["watermark"]().build(
            in_video="[v]", in_audio="[a]", next_input_index=1,
            options={"image": str(logo_png), "opacity": 0.5, "_main_width": 1080},
        )
        assert "colorchannelmixer=aa=0.500" in frag.filter_segment


class TestAudioNormalize:
    def test_loudnorm_with_target_lufs(self) -> None:
        frag = FILTER_REGISTRY["audio_normalize"]().build(
            in_video="[v]", in_audio="[a]", next_input_index=1,
            options={"target_lufs": -13.0},
        )
        assert "loudnorm=I=-13.0" in frag.filter_segment
        assert frag.new_audio_label is not None
        assert frag.new_audio_label != "[a]"


class TestAudioFadeOut:
    def test_no_op_when_no_target_duration(self) -> None:
        frag = FILTER_REGISTRY["audio_fade_out"]().build(
            in_video="[v]", in_audio="[a]", next_input_index=1,
            options={"duration": 1.5},
        )
        assert frag.filter_segment == ""

    def test_computes_fade_start(self) -> None:
        frag = FILTER_REGISTRY["audio_fade_out"]().build(
            in_video="[v]", in_audio="[a]", next_input_index=1,
            options={"duration": 1.5, "total_duration": 10.0},
        )
        # fade starts at 10 - 1.5 = 8.5
        assert "afade=t=out:st=8.500:d=1.500" in frag.filter_segment


class TestMetadataStrip:
    def test_emits_strip_args(self) -> None:
        frag = FILTER_REGISTRY["metadata_strip"]().build(
            in_video="[v]", in_audio="[a]", next_input_index=1, options={},
        )
        assert "-map_metadata" in frag.output_metadata_args
        assert "-1" in frag.output_metadata_args


class TestAspectConvert:
    def test_blur_pad_mode(self) -> None:
        frag = FILTER_REGISTRY["aspect_convert"]().build(
            in_video="[v]", in_audio="[a]", next_input_index=1,
            options={"target": "9:16", "mode": "blur_pad"},
        )
        seg = frag.filter_segment
        assert "split=2" in seg
        assert "boxblur" in seg
        assert "overlay=" in seg

    def test_crop_mode(self) -> None:
        frag = FILTER_REGISTRY["aspect_convert"]().build(
            in_video="[v]", in_audio="[a]", next_input_index=1,
            options={"target": "9:16", "mode": "crop"},
        )
        seg = frag.filter_segment
        assert "crop=1080:1920" in seg
        assert "boxblur" not in seg  # crop mode doesn't blur

    def test_custom_aspect_wxh(self) -> None:
        frag = FILTER_REGISTRY["aspect_convert"]().build(
            in_video="[v]", in_audio="[a]", next_input_index=1,
            options={"target": "800x600", "mode": "crop"},
        )
        assert "crop=800:600" in frag.filter_segment

    def test_invalid_target_skips(self) -> None:
        # Currently swallows ValueError silently to keep chain alive
        frag = FILTER_REGISTRY["aspect_convert"]().build(
            in_video="[v]", in_audio="[a]", next_input_index=1,
            options={"target": "invalid", "mode": "crop"},
        )
        assert frag.filter_segment == ""


class TestSubtitleBurn:
    def test_no_file_skips(self) -> None:
        frag = FILTER_REGISTRY["subtitle_burn"]().build(
            in_video="[v]", in_audio="[a]", next_input_index=1, options={},
        )
        assert frag.filter_segment == ""

    def test_missing_file_raises(self) -> None:
        import pytest
        with pytest.raises(FileNotFoundError):
            FILTER_REGISTRY["subtitle_burn"]().build(
                in_video="[v]", in_audio="[a]", next_input_index=1,
                options={"file": "/no/such/subs.srt"},
            )

    def test_srt_uses_subtitles_filter(self, srt_file) -> None:
        frag = FILTER_REGISTRY["subtitle_burn"]().build(
            in_video="[v]", in_audio="[a]", next_input_index=1,
            options={"file": str(srt_file)},
        )
        assert "subtitles=filename=" in frag.filter_segment
        assert "force_style=" in frag.filter_segment

    def test_path_special_chars_escaped(self, tmp_path) -> None:
        # Path with colon (Windows-style drive emulation in unit form)
        special = tmp_path / "co:lon" / "sub.srt"
        special.parent.mkdir()
        special.write_text("1\n00:00:00,500 --> 00:00:01,500\nx\n")
        frag = FILTER_REGISTRY["subtitle_burn"]().build(
            in_video="[v]", in_audio="[a]", next_input_index=1,
            options={"file": str(special)},
        )
        # Colon in path must be escaped (\:)
        assert "co\\:lon" in frag.filter_segment


class TestColorGrade:
    def test_defaults_are_noop(self) -> None:
        frag = FILTER_REGISTRY["color_grade"]().build(
            in_video="[v]", in_audio="[a]", next_input_index=1, options={},
        )
        assert frag.filter_segment == ""

    def test_brightness_only(self) -> None:
        frag = FILTER_REGISTRY["color_grade"]().build(
            in_video="[v]", in_audio="[a]", next_input_index=1,
            options={"brightness": 0.2},
        )
        assert "eq=brightness=0.200" in frag.filter_segment

    def test_all_params(self) -> None:
        frag = FILTER_REGISTRY["color_grade"]().build(
            in_video="[v]", in_audio="[a]", next_input_index=1,
            options={"brightness": 0.1, "contrast": 1.2, "saturation": 1.3, "gamma": 1.1},
        )
        seg = frag.filter_segment
        assert "brightness=0.100" in seg
        assert "contrast=1.200" in seg
        assert "saturation=1.300" in seg
        assert "gamma=1.100" in seg

    def test_clamps_out_of_range(self) -> None:
        frag = FILTER_REGISTRY["color_grade"]().build(
            in_video="[v]", in_audio="[a]", next_input_index=1,
            options={"brightness": 5.0, "saturation": -2.0, "gamma": 0.001},
        )
        # brightness clamped to 1.0, saturation to 0.0, gamma to 0.1
        seg = frag.filter_segment
        assert "brightness=1.000" in seg
        assert "saturation=0.000" in seg
        assert "gamma=0.100" in seg

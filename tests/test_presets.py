from video_extender.core.presets import PRESET_REGISTRY


class TestPresetRegistry:
    def test_all_platforms_present(self) -> None:
        expected = [
            "ig_reels", "ig_feed", "ig_story", "fb_feed", "fb_reels",
            "tiktok", "yt_shorts", "yt_long", "yt_4k", "twitter", "linkedin_feed",
        ]
        for name in expected:
            assert name in PRESET_REGISTRY, f"missing preset: {name}"

    def test_each_preset_has_three_qualities(self) -> None:
        for name, cls in PRESET_REGISTRY.items():
            for q in ("low", "medium", "high"):
                params = cls.for_quality(q)
                assert params.bitrate_kbps > 0, f"{name}/{q}: zero bitrate"
                assert params.audio_bitrate_kbps > 0, f"{name}/{q}: zero audio bitrate"

    def test_quality_ordering(self) -> None:
        """high quality should not be lower bitrate than low."""
        for name, cls in PRESET_REGISTRY.items():
            low = cls.params_low.bitrate_kbps
            high = cls.params_high.bitrate_kbps
            assert high >= low, f"{name}: high ({high}) < low ({low})"


class TestPlatformLufsTargets:
    def test_tiktok_at_13_lufs(self) -> None:
        # TikTok recommends ~-13 LUFS
        for q in ("low", "medium", "high"):
            assert PRESET_REGISTRY["tiktok"].for_quality(q).audio_lufs == -13.0

    def test_meta_at_14_lufs(self) -> None:
        # Meta recommends ~-14 LUFS
        for k in ("ig_reels", "ig_feed", "fb_feed"):
            for q in ("low", "medium", "high"):
                assert PRESET_REGISTRY[k].for_quality(q).audio_lufs == -14.0


class TestPlatformResolution:
    def test_vertical_presets_have_9_16(self) -> None:
        for k in ("tiktok", "ig_reels", "fb_reels", "yt_shorts"):
            params = PRESET_REGISTRY[k].for_quality("medium")
            assert params.max_width == 1080
            assert params.max_height == 1920

    def test_youtube_long_landscape(self) -> None:
        params = PRESET_REGISTRY["yt_long"].for_quality("medium")
        assert params.max_width == 1920
        assert params.max_height == 1080

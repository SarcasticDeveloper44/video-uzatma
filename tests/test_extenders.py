"""Test extender filtergraph construction (unit-level)."""
from __future__ import annotations

import pytest

from video_extender.core.extenders import EXTENDER_REGISTRY
from video_extender.utils.ffprobe_parser import AudioStream, MediaInfo, VideoStream


def _media(width: int = 720, height: int = 1280, duration: float = 3.0, has_audio: bool = True) -> MediaInfo:
    return MediaInfo(
        path="/x/in.mp4",
        duration=duration,
        size=1000,
        container="mov,mp4",
        video=VideoStream(index=0, codec="h264", width=width, height=height, fps=30.0, pix_fmt="yuv420p", bitrate=1_000_000),
        audio=AudioStream(index=1, codec="aac", sample_rate=44100, channels=2, bitrate=128_000) if has_audio else None,
    )


class TestRegistry:
    def test_registry_populated(self) -> None:
        # Working extenders that must exist
        for name in ("freeze", "black", "loop", "intro_outro", "image_card"):
            assert name in EXTENDER_REGISTRY, f"missing extender: {name}"


class TestFreeze:
    def test_audio_fade_out_baked_in(self) -> None:
        plan = EXTENDER_REGISTRY["freeze"]().build_plan(
            None, _media(), target_duration=8.0, audio_fade_out_seconds=1.5
        )
        assert "tpad=stop_mode=clone" in plan.filtergraph
        assert "afade=t=out" in plan.filtergraph
        assert "apad=whole_dur=8.000" in plan.filtergraph
        assert plan.video_label == "[vout]"
        assert plan.audio_label == "[aout]"

    def test_silent_source_synthesizes_silence(self) -> None:
        plan = EXTENDER_REGISTRY["freeze"]().build_plan(
            None, _media(has_audio=False), target_duration=5.0
        )
        assert "anullsrc" in plan.filtergraph
        assert plan.audio_label == "[aout]"

    def test_short_source_clamps_fade(self) -> None:
        """Fade-out duration should not exceed source duration."""
        plan = EXTENDER_REGISTRY["freeze"]().build_plan(
            None, _media(duration=0.5), target_duration=3.0, audio_fade_out_seconds=2.0
        )
        assert "afade=t=out:st=0.000:d=0.500" in plan.filtergraph


class TestBlack:
    def test_uses_tpad_color_black(self) -> None:
        plan = EXTENDER_REGISTRY["black"]().build_plan(
            None, _media(), target_duration=6.0
        )
        assert "tpad=stop_mode=add" in plan.filtergraph
        assert "color=black" in plan.filtergraph


class TestLoop:
    def test_uses_stream_loop(self) -> None:
        plan = EXTENDER_REGISTRY["loop"]().build_plan(
            None, _media(), target_duration=10.0
        )
        assert plan.source_input_args == ("-stream_loop", "-1")
        assert "trim=duration=10.000" in plan.filtergraph

    def test_no_extra_inputs(self) -> None:
        plan = EXTENDER_REGISTRY["loop"]().build_plan(
            None, _media(), target_duration=10.0
        )
        assert plan.extra_inputs == ()


class TestImageCard:
    def test_requires_image(self) -> None:
        with pytest.raises(ValueError, match="image"):
            EXTENDER_REGISTRY["image_card"]().build_plan(
                None, _media(), target_duration=8.0, options={},
            )

    def test_missing_image_file(self) -> None:
        with pytest.raises(FileNotFoundError):
            EXTENDER_REGISTRY["image_card"]().build_plan(
                None, _media(), target_duration=8.0,
                options={"image": "/nonexistent/x.png"},
            )

    def test_card_duration_computed(self, end_card_png) -> None:
        plan = EXTENDER_REGISTRY["image_card"]().build_plan(
            None, _media(duration=3.0), target_duration=10.0,
            options={"image": str(end_card_png)},
        )
        # card_duration = 10 - 3 = 7
        assert "trim=duration=7.000" in plan.filtergraph
        assert plan.extra_input_args == (("-loop", "1"),)

    def test_no_extension_needed(self, end_card_png) -> None:
        # target == source duration → no card needed
        plan = EXTENDER_REGISTRY["image_card"]().build_plan(
            None, _media(duration=5.0), target_duration=5.0,
            options={"image": str(end_card_png)},
        )
        assert plan.extra_inputs == ()
        # Re-encode pass-through
        assert "[v_s]" not in plan.filtergraph  # uses simpler [vout] mapping
        assert plan.video_label == "[vout]"


class TestIntroOutro:
    def test_requires_outro(self) -> None:
        with pytest.raises(ValueError, match="outro"):
            EXTENDER_REGISTRY["intro_outro"]().build_plan(
                None, _media(), target_duration=10.0, options={},
            )

    def test_with_outro_only(self, outro_4s) -> None:
        plan = EXTENDER_REGISTRY["intro_outro"]().build_plan(
            None, _media(), target_duration=10.0,
            options={"outro": str(outro_4s)},
        )
        assert len(plan.extra_inputs) == 1
        assert "concat=n=2:v=1:a=1" in plan.filtergraph

    def test_with_intro_and_outro(self, intro_2s, outro_4s) -> None:
        plan = EXTENDER_REGISTRY["intro_outro"]().build_plan(
            None, _media(), target_duration=10.0,
            options={"intro": str(intro_2s), "outro": str(outro_4s)},
        )
        assert len(plan.extra_inputs) == 2
        assert "concat=n=3:v=1:a=1" in plan.filtergraph

    def test_loops_outro_when_short(self, intro_2s, outro_4s) -> None:
        # intro 2s + source 3s + outro_target 10s (outro_avail 4s) → must loop
        plan = EXTENDER_REGISTRY["intro_outro"]().build_plan(
            None, _media(), target_duration=15.0,
            options={"intro": str(intro_2s), "outro": str(outro_4s)},
        )
        # Outro is the 2nd extra input (index 1) — should have -stream_loop -1
        assert plan.extra_input_args[1] == ("-stream_loop", "-1")

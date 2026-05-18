from pathlib import Path

from video_extender.core import config
from video_extender.core.job import ExtendMode, JobSpec


def _spec(**overrides) -> JobSpec:
    base = dict(
        extend_seconds=1800.0,
        extend_mode=ExtendMode.FILL,
        extender_name="black",
        preset_name="tiktok",
        quality="high",
        video_codec="hevc",
        filters=("audio_normalize", "watermark", "metadata_strip"),
        filter_options={
            "audio_normalize": {"target_lufs": -13.0},
            "watermark": {"image": "/home/pc/logo.png", "position": "top-right", "opacity": 0.7},
        },
        extender_options={"outro": "/path/outro.mp4"},
        filename_template="{name}_{preset}_{duration}.{ext}",
        audio_fade_out_seconds=2.0,
        output_subdir="out",
    )
    base.update(overrides)
    return JobSpec(**base)


class TestProfileRoundtrip:
    def test_save_load(self, tmp_path: Path) -> None:
        s = _spec()
        p = tmp_path / "profile.json"
        config.save_profile(p, s)
        loaded, extra = config.load_profile(p)
        assert loaded.extend_seconds == s.extend_seconds
        assert loaded.extend_mode == s.extend_mode
        assert loaded.extender_name == s.extender_name
        assert loaded.preset_name == s.preset_name
        assert loaded.video_codec == s.video_codec
        assert tuple(loaded.filters) == s.filters
        assert loaded.filter_options == s.filter_options
        assert loaded.extender_options == s.extender_options
        assert loaded.audio_fade_out_seconds == s.audio_fade_out_seconds
        assert extra == {}

    def test_extra_payload_preserved(self, tmp_path: Path) -> None:
        p = tmp_path / "profile.json"
        config.save_profile(p, _spec(), extra={"note": "30min TikTok"})
        _, extra = config.load_profile(p)
        assert extra == {"note": "30min TikTok"}


class TestResumeState:
    def test_no_state_initial(self, tmp_path: Path) -> None:
        state = config.load_state(tmp_path / "state.json")
        assert state == {"completed": [], "failed": {}}

    def test_mark_and_check_completed_legacy(self, tmp_path: Path) -> None:
        """Legacy API without spec: matches source+output."""
        sp = tmp_path / "state.json"
        src = Path("/x/y/in.mp4")
        out = Path("/x/y/output/in_ext.mp4")
        config.mark_completed(sp, src, out)
        # Legacy is_completed (no spec) — falls back to source+output match
        assert config.is_completed(sp, src, output=out)

    def test_resume_with_spec_hash(self, tmp_path: Path) -> None:
        """New API: spec_hash determines skip — output file existence verified."""
        sp = tmp_path / "state.json"
        src = Path("/x/in.mp4")
        out = tmp_path / "in_v1.mp4"
        out.touch()  # output must exist for skip
        spec = _spec()
        config.mark_completed(sp, src, out, spec)
        # Same source + same spec + output exists → skip
        assert config.is_completed(sp, src, spec, out)
        # Same source, DIFFERENT spec (extender changed) → re-run
        spec2 = _spec(extender_name="loop")
        assert not config.is_completed(sp, src, spec2, out)

    def test_missing_output_invalidates_skip(self, tmp_path: Path) -> None:
        """If recorded output got deleted, re-run."""
        sp = tmp_path / "state.json"
        src = Path("/x/in.mp4")
        deleted = tmp_path / "deleted.mp4"
        spec = _spec()
        config.mark_completed(sp, src, deleted, spec)
        # Output not on disk → must re-run
        assert not config.is_completed(sp, src, spec, deleted)

    def test_legacy_source_only_check(self, tmp_path: Path) -> None:
        sp = tmp_path / "state.json"
        src = Path("/x/in.mp4")
        config.mark_completed(sp, src, Path("/x/output/in.mp4"))
        # When output not supplied, just check source
        assert config.is_completed(sp, src)

    def test_failed_tracking(self, tmp_path: Path) -> None:
        sp = tmp_path / "state.json"
        src = Path("/x/bad.mp4")
        config.mark_failed(sp, src, "ffprobe failed")
        state = config.load_state(sp)
        assert str(src) in state["failed"]

    def test_completed_removes_from_failed(self, tmp_path: Path) -> None:
        sp = tmp_path / "state.json"
        src = Path("/x/x.mp4")
        config.mark_failed(sp, src, "error")
        config.mark_completed(sp, src, Path("/x/output/x.mp4"))
        state = config.load_state(sp)
        assert str(src) not in state["failed"]

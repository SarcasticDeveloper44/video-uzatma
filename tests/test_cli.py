"""CLI argument parser + spec construction tests (no actual encoding)."""
from __future__ import annotations

import pytest

from video_extender.cli import _build_parser


class TestParser:
    def test_basic_parse(self) -> None:
        p = _build_parser()
        args = p.parse_args(["--folder", "/x", "--add", "30m"])
        assert str(args.folder) == "/x"
        assert args.add == "30m"
        assert args.target is None
        assert args.method == "freeze"
        assert args.preset == "tiktok"
        assert args.quality == "medium"
        assert args.codec == "h264"

    def test_add_target_mutually_exclusive(self) -> None:
        p = _build_parser()
        with pytest.raises(SystemExit):
            p.parse_args(["--folder", "/x", "--add", "30m", "--target", "1h"])

    def test_invalid_method_rejected(self) -> None:
        p = _build_parser()
        with pytest.raises(SystemExit):
            p.parse_args(["--folder", "/x", "--add", "1s", "--method", "bogus"])

    def test_invalid_codec_rejected(self) -> None:
        p = _build_parser()
        with pytest.raises(SystemExit):
            p.parse_args(["--folder", "/x", "--add", "1s", "--codec", "vp9"])

    def test_codec_hevc_accepted(self) -> None:
        p = _build_parser()
        args = p.parse_args(["--folder", "/x", "--add", "1s", "--codec", "hevc"])
        assert args.codec == "hevc"

    def test_encoder_override_accepted(self) -> None:
        p = _build_parser()
        args = p.parse_args(["--folder", "/x", "--add", "1s",
                             "--encoder", "libx264"])
        assert args.encoder == "libx264"

    def test_max_parallel(self) -> None:
        p = _build_parser()
        args = p.parse_args(["--folder", "/x", "--add", "1s", "--max-parallel", "3"])
        assert args.max_parallel == 3

    def test_aspect_options(self) -> None:
        p = _build_parser()
        args = p.parse_args([
            "--folder", "/x", "--add", "1s",
            "--aspect", "9:16", "--aspect-mode", "crop",
        ])
        assert args.aspect == "9:16"
        assert args.aspect_mode == "crop"

    def test_filter_toggles(self) -> None:
        p = _build_parser()
        args = p.parse_args([
            "--folder", "/x", "--add", "1s",
            "--audio-normalize", "--strip-metadata", "--fade-out-final",
        ])
        assert args.audio_normalize is True
        assert args.strip_metadata is True
        assert args.fade_out_final is True

    def test_color_grade_defaults(self) -> None:
        p = _build_parser()
        args = p.parse_args(["--folder", "/x", "--add", "1s"])
        assert args.brightness == 0.0
        assert args.contrast == 1.0
        assert args.saturation == 1.0
        assert args.gamma == 1.0


class TestListMode:
    def test_list_presets_outputs_known(self, capsys) -> None:
        from video_extender.cli import main
        rc = main(["--list-presets"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "tiktok" in out
        assert "ig_reels" in out
        assert "linkedin_feed" in out

    def test_list_methods_outputs_known(self, capsys) -> None:
        from video_extender.cli import main
        rc = main(["--list-methods"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "freeze" in out
        assert "black" in out
        assert "loop" in out
        assert "intro_outro" in out
        assert "image_card" in out

    def test_list_encoders_outputs_table(self, capsys) -> None:
        from video_extender.cli import main
        rc = main(["--list-encoders"])
        assert rc == 0
        out = capsys.readouterr().out
        # Table header + at least the universal CPU encoders
        assert "libx264" in out
        assert "libx265" in out


class TestErrorPaths:
    def test_no_folder_or_lists_errors(self) -> None:
        from video_extender.cli import main
        with pytest.raises(SystemExit) as exc:
            main(["--add", "1s"])
        assert exc.value.code != 0

    def test_missing_folder_returns_2(self) -> None:
        from video_extender.cli import main
        rc = main(["--folder", "/tmp/nonexistent_xy_vx", "--add", "1s"])
        assert rc == 2

    def test_intro_outro_requires_outro(self, tmp_path) -> None:
        """When preflight passes (real folder), missing --outro must fail."""
        from video_extender.cli import main
        with pytest.raises(SystemExit):
            main(["--folder", str(tmp_path), "--add", "1s",
                  "--method", "intro_outro"])

    def test_image_card_requires_end_card(self, tmp_path) -> None:
        from video_extender.cli import main
        with pytest.raises(SystemExit):
            main(["--folder", str(tmp_path), "--add", "1s",
                  "--method", "image_card"])

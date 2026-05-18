from pathlib import Path

from video_extender.utils.paths import (
    discover_videos, ensure_output_dir, is_video, safe_output_path,
)


class TestIsVideo:
    def test_recognized_extensions(self, tmp_path: Path) -> None:
        for ext in [".mp4", ".mov", ".mkv", ".avi", ".webm"]:
            p = tmp_path / f"x{ext}"
            p.touch()
            assert is_video(p), f"{ext} should be recognized"

    def test_uppercase_extension(self, tmp_path: Path) -> None:
        p = tmp_path / "X.MP4"
        p.touch()
        assert is_video(p)

    def test_unrecognized_extension(self, tmp_path: Path) -> None:
        p = tmp_path / "doc.pdf"
        p.touch()
        assert not is_video(p)

    def test_directory_not_video(self, tmp_path: Path) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        assert not is_video(sub)


class TestDiscoverVideos:
    def test_flat_scan(self, tmp_path: Path) -> None:
        (tmp_path / "a.mp4").touch()
        (tmp_path / "b.mov").touch()
        (tmp_path / "c.txt").touch()
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "d.mp4").touch()

        result = discover_videos(tmp_path, recursive=False)
        names = [p.name for p in result]
        assert sorted(names) == ["a.mp4", "b.mov"]

    def test_recursive_scan(self, tmp_path: Path) -> None:
        (tmp_path / "a.mp4").touch()
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "b.mp4").touch()
        deep = sub / "deep"
        deep.mkdir()
        (deep / "c.mov").touch()

        result = discover_videos(tmp_path, recursive=True)
        names = sorted(p.name for p in result)
        assert names == ["a.mp4", "b.mp4", "c.mov"]

    def test_nonexistent_dir(self, tmp_path: Path) -> None:
        assert discover_videos(tmp_path / "ghost") == []


class TestSafeOutputPath:
    def test_first_use(self, tmp_path: Path) -> None:
        src = Path("/tmp/source.mp4")
        p = safe_output_path(tmp_path, src, "{name}_ext.{ext}")
        assert p.name == "source_ext.mp4"
        assert p.parent == tmp_path

    def test_template_tokens(self, tmp_path: Path) -> None:
        src = Path("/tmp/x.mp4")
        p = safe_output_path(tmp_path, src, "{name}_{duration}_{preset}.{ext}",
                             duration="30m", preset="tiktok")
        assert p.name == "x_30m_tiktok.mp4"

    def test_collision_appends_suffix(self, tmp_path: Path) -> None:
        src = Path("/tmp/src.mp4")
        existing = tmp_path / "src_ext.mp4"
        existing.touch()
        p = safe_output_path(tmp_path, src, "{name}_ext.{ext}")
        assert p.name == "src_ext_1.mp4"

        # Add a second collision
        p.touch()
        p2 = safe_output_path(tmp_path, src, "{name}_ext.{ext}")
        assert p2.name == "src_ext_2.mp4"


class TestEnsureOutputDir:
    def test_creates_subdir(self, tmp_path: Path) -> None:
        out = ensure_output_dir(tmp_path)
        assert out == tmp_path / "output"
        assert out.is_dir()

    def test_custom_name(self, tmp_path: Path) -> None:
        out = ensure_output_dir(tmp_path, "out")
        assert out == tmp_path / "out"
        assert out.is_dir()

    def test_idempotent(self, tmp_path: Path) -> None:
        out1 = ensure_output_dir(tmp_path)
        out2 = ensure_output_dir(tmp_path)
        assert out1 == out2

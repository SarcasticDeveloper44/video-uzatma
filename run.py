#!/usr/bin/env python3
"""Cross-platform launcher: bootstrap venv + ffmpeg, install deps, run app.

Stdlib-only (Python >=3.11). Auto-installs:
  - .venv/   — Python venv with PySide6 (falls back to user-cache on OneDrive)
  - .ffmpeg/ — static ffmpeg + ffprobe (first run, ~50–100 MB cached)
Sistem PATH'inde ffmpeg varsa onu kullanır; yoksa .ffmpeg/'i indirir.

Usage:
    python run.py                   # GUI
    python run.py --folder ./vids   # CLI
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REQ = ROOT / "requirements.txt"
SRC = ROOT / "src"
FFMPEG_CACHE = ROOT / ".ffmpeg"

# Minimum Python supported (matches pyproject.toml requires-python). No upper
# bound — PySide6 keeps up with new Pythons; if a future Python lacks wheels
# we detect that at pip-install time and fall back to a sibling interpreter.
MIN_PYTHON: tuple[int, int] = (3, 11)
# Search candidates when the current Python lacks wheels or is older than MIN.
# Newest first because newer == more likely to have current PySide6 wheels.
_PYTHON_FALLBACK_VERSIONS: tuple[tuple[int, int], ...] = (
    (3, 14), (3, 13), (3, 12), (3, 11),
)

# venv lives in project dir by default; on Windows OneDrive-synced Desktop the
# project dir is racy (OneDrive locks `.venv/.gitignore` for a moment while
# Python's venv module tries to write it), so we keep a user-local fallback.
_VENV_PRIMARY = ROOT / ".venv"
if platform.system() == "Windows":
    _VENV_FALLBACK = (
        Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        / "video-extender" / "venv"
    )
else:
    _VENV_FALLBACK = Path.home() / ".cache" / "video-extender" / "venv"
_VENV_LOCATIONS = (_VENV_PRIMARY, _VENV_FALLBACK)
_VENV_MARKER = ROOT / ".venv-location"  # remembers which location actually worked

# Static ffmpeg distributions per (system, arch). All HTTPS, all stdlib-extractable.
_FFMPEG_SOURCES: dict[tuple[str, str], tuple[str, ...]] = {
    ("Linux", "x86_64"):  ("https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz",),
    ("Linux", "amd64"):   ("https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz",),
    ("Linux", "aarch64"): ("https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-arm64-static.tar.xz",),
    ("Linux", "arm64"):   ("https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-arm64-static.tar.xz",),
    ("Darwin", "x86_64"): (
        "https://evermeet.cx/ffmpeg/getrelease/ffmpeg/zip",
        "https://evermeet.cx/ffmpeg/getrelease/ffprobe/zip",
    ),
    ("Darwin", "arm64"):  (
        "https://evermeet.cx/ffmpeg/getrelease/ffmpeg/zip",
        "https://evermeet.cx/ffmpeg/getrelease/ffprobe/zip",
    ),
    ("Windows", "AMD64"): ("https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",),
    ("Windows", "x86_64"):("https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",),
}

_MANUAL_INSTALL_HINT = (
    "Manuel kurulum:\n"
    "Linux:   pacman -S ffmpeg / apt install ffmpeg / dnf install ffmpeg\n"
    "macOS:   brew install ffmpeg\n"
    "Windows: winget install Gyan.FFmpeg  (veya https://www.gyan.dev/ffmpeg/)"
)


# ---- Python version dispatch ----------------------------------------------

def _find_alternative_python() -> str | None:
    """Locate any installed Python in _PYTHON_FALLBACK_VERSIONS (newest first)."""
    # Windows: the Python launcher (py.exe) is the canonical way to look up
    # specific installed Python versions across user/system installs.
    if platform.system() == "Windows":
        py = shutil.which("py")
        if py:
            for major, minor in _PYTHON_FALLBACK_VERSIONS:
                try:
                    exe = subprocess.check_output(
                        [py, f"-{major}.{minor}",
                         "-c", "import sys; print(sys.executable)"],
                        text=True, timeout=10, stderr=subprocess.DEVNULL,
                    ).strip()
                    if exe and Path(exe).exists() and exe != sys.executable:
                        return exe
                except (subprocess.SubprocessError, OSError):
                    continue
    # Unix + Windows fallback: versioned binary names on PATH.
    for major, minor in _PYTHON_FALLBACK_VERSIONS:
        for name in (f"python{major}.{minor}", f"python{major}.{minor}.exe"):
            cand = shutil.which(name)
            if cand and cand != sys.executable:
                return cand
    return None


def _choose_python_for_venv() -> str:
    """Return the Python interpreter to use for creating the venv.

    If the current interpreter meets MIN_PYTHON, use it. If it's older, hunt
    for a newer sibling. Newer-than-PySide6 mismatches are caught at pip
    install time and trigger the same fallback hunt (see _ensure_venv).
    """
    cur = sys.version_info[:2]
    if cur >= MIN_PYTHON:
        return sys.executable
    alt = _find_alternative_python()
    if alt:
        print(
            f">> Python {cur[0]}.{cur[1]} cok eski (min {MIN_PYTHON[0]}.{MIN_PYTHON[1]}); "
            f"daha yeni Python kullaniliyor: {alt}"
        )
        return alt
    print(
        f"HATA: Bu sistemdeki Python {cur[0]}.{cur[1]} cok eski "
        f"(en az {MIN_PYTHON[0]}.{MIN_PYTHON[1]} gerekli).\n\n"
        f"Cozum: Guncel Python yukle:\n"
        f"  Windows: https://www.python.org/downloads/windows/\n"
        f"  macOS:   https://www.python.org/downloads/macos/\n"
        f"  Linux:   pacman -S python  /  apt install python3.13  /  dnf install python3.13",
        file=sys.stderr,
    )
    sys.exit(2)


# ---- venv ------------------------------------------------------------------

def _venv_python_at(venv: Path) -> Path:
    if platform.system() == "Windows":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def _venv_pip_at(venv: Path) -> Path:
    if platform.system() == "Windows":
        return venv / "Scripts" / "pip.exe"
    return venv / "bin" / "pip"


def _resolve_existing_venv() -> Path | None:
    """Return the path of an already-working venv (project-local or fallback),
    consulting the marker file from a prior successful run."""
    if _VENV_MARKER.exists():
        try:
            remembered = Path(_VENV_MARKER.read_text(encoding="utf-8").strip())
            if _venv_python_at(remembered).exists():
                return remembered
        except OSError:
            pass
    for venv in _VENV_LOCATIONS:
        if _venv_python_at(venv).exists():
            return venv
    return None


def _ensure_venv() -> Path:
    """Create a venv at the first writable location. Returns its path.

    On Windows, the project dir is often inside OneDrive (the "Desktop" folder
    is OneDrive-synced by default on modern Windows installs). OneDrive grabs
    a brief lock on newly-created files in synced folders, racing with the
    venv module's `.gitignore` write and surfacing as Errno 13. We retry in
    %LOCALAPPDATA% which OneDrive doesn't touch.
    """
    existing = _resolve_existing_venv()
    if existing is not None:
        return existing

    primary_python = _choose_python_for_venv()
    # Build the python-candidate list: primary first; if PySide6 install fails
    # (e.g., current Python is newer than the latest PySide6 wheels), retry
    # with an alternative installed Python.
    python_candidates: list[str] = [primary_python]
    alt = _find_alternative_python()
    if alt and alt not in python_candidates:
        python_candidates.append(alt)

    last_exc: Exception | None = None
    for python in python_candidates:
        for venv in _VENV_LOCATIONS:
            try:
                print(f">> Creating virtual environment in {venv} (Python: {python})")
                # Clean up any partial leftover from a previous failed attempt at
                # this location. Without this, venv would refuse to overwrite.
                if venv.exists() and not _venv_python_at(venv).exists():
                    shutil.rmtree(venv, ignore_errors=True)
                venv.parent.mkdir(parents=True, exist_ok=True)
                subprocess.check_call([python, "-m", "venv", str(venv)])
                # Use `python -m pip` (not pip.exe) so pip can self-upgrade on
                # Windows; pip.exe cannot rewrite itself while running.
                venv_py = str(_venv_python_at(venv))
                subprocess.check_call(
                    [venv_py, "-m", "pip", "install", "--upgrade", "pip", "--quiet"]
                )
                if REQ.exists():
                    print(">> Installing requirements")
                    subprocess.check_call(
                        [venv_py, "-m", "pip", "install", "-r", str(REQ), "--quiet"]
                    )
                # Remember which location worked so next launches skip the racy path.
                try:
                    _VENV_MARKER.write_text(str(venv), encoding="utf-8")
                except OSError:
                    pass
                return venv
            except (subprocess.CalledProcessError, OSError) as exc:
                print(f"   .. basarisiz: {exc}", file=sys.stderr)
                last_exc = exc
                shutil.rmtree(venv, ignore_errors=True)
                continue

    print(
        "HATA: venv hicbir konumda olusturulamadi.\n"
        f"Denenen Python'lar: {python_candidates}\n"
        f"Denenen konumlar: {[str(p) for p in _VENV_LOCATIONS]}\n"
        f"Son hata: {last_exc}\n\n"
        "Olasi sebepler:\n"
        "  - OneDrive / antivirus klasoru kilitliyor (proje 'Desktop'taysa)\n"
        "  - Sistemdeki Python sürümü icin PySide6 wheel'i yok\n"
        "  - Internet baglantisi yok (PySide6 ilk indirilirken)\n\n"
        "Coz:\n"
        "  - Projeyi Desktop disindaki bir klasore tasi (C:\\Tools\\... gibi)\n"
        "  - Guncel Python yukle: https://www.python.org/downloads/",
        file=sys.stderr,
    )
    sys.exit(1)


# ---- ffmpeg auto-bootstrap -------------------------------------------------

def _bundled_ffmpeg() -> tuple[Path, Path] | None:
    """Locate (ffmpeg, ffprobe) under .ffmpeg/ — searches recursively because
    each platform's archive lays out binaries differently (subfolder on Linux,
    flat on macOS evermeet, bin/ on Windows gyan)."""
    if not FFMPEG_CACHE.exists():
        return None
    ext = ".exe" if platform.system() == "Windows" else ""
    ffmpeg = next((p for p in FFMPEG_CACHE.rglob(f"ffmpeg{ext}") if p.is_file()), None)
    ffprobe = next((p for p in FFMPEG_CACHE.rglob(f"ffprobe{ext}") if p.is_file()), None)
    if ffmpeg and ffprobe:
        return ffmpeg, ffprobe
    return None


def _ffmpeg_urls() -> tuple[str, ...] | None:
    key = (platform.system(), platform.machine())
    return _FFMPEG_SOURCES.get(key)


def _download_and_extract(url: str, dest_dir: Path) -> None:
    """Download `url` to a temp file in dest_dir, extract supported archives,
    then delete the archive. Streams progress to stderr."""
    # Some URLs (evermeet) end in `/zip` rather than `*.zip` — normalise.
    fname = (url.rsplit("/", 1)[-1].split("?", 1)[0] or "download").lower()
    if not fname.endswith((".zip", ".tar.xz", ".tar.gz", ".tgz")):
        fname = fname + ".zip"
    archive = dest_dir / fname

    last_pct = [-1]
    def _report(count: int, block: int, total: int) -> None:
        if total <= 0:
            return
        pct = min(100, int(count * block * 100 / total))
        if pct == last_pct[0]:
            return
        last_pct[0] = pct
        mb_done = count * block / (1024 * 1024)
        mb_total = total / (1024 * 1024)
        sys.stderr.write(f"\r   {pct:3d}%  ({mb_done:.1f} / {mb_total:.1f} MB)")
        sys.stderr.flush()

    print(f">> Indiriliyor: {url}")
    urllib.request.urlretrieve(url, str(archive), reporthook=_report)
    sys.stderr.write("\n")

    if fname.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(dest_dir)
    elif fname.endswith((".tar.xz", ".tar.gz", ".tgz")):
        with tarfile.open(archive) as tf:
            tf.extractall(dest_dir)
    archive.unlink(missing_ok=True)


def _download_bundled_ffmpeg() -> tuple[Path, Path]:
    """Force-download ffmpeg + ffprobe into .ffmpeg/ regardless of system PATH.
    Used by build.py to guarantee a local copy to bundle into the binary."""
    bundled = _bundled_ffmpeg()
    if bundled is not None:
        return bundled

    urls = _ffmpeg_urls()
    if urls is None:
        print(
            f"HATA: Bu platform ({platform.system()} / {platform.machine()}) icin "
            f"otomatik ffmpeg indirme listesinde yok.\n{_MANUAL_INSTALL_HINT}",
            file=sys.stderr,
        )
        sys.exit(2)
    print(">> ffmpeg .ffmpeg/ klasorune indiriliyor (tek seferlik, ~50-100 MB)")
    FFMPEG_CACHE.mkdir(parents=True, exist_ok=True)
    try:
        for url in urls:
            _download_and_extract(url, FFMPEG_CACHE)
    except (urllib.error.URLError, OSError, zipfile.BadZipFile, tarfile.TarError) as exc:
        print(
            f"HATA: ffmpeg indirilemedi: {exc}\n"
            f"Internet baglantisini kontrol et.\n{_MANUAL_INSTALL_HINT}",
            file=sys.stderr,
        )
        sys.exit(2)

    bundled = _bundled_ffmpeg()
    if bundled is None:
        print(
            f"HATA: ffmpeg indirildi ama binary bulunamadi ({FFMPEG_CACHE}).\n"
            f"{_MANUAL_INSTALL_HINT}",
            file=sys.stderr,
        )
        sys.exit(2)

    if platform.system() != "Windows":
        for b in bundled:
            try:
                os.chmod(b, 0o755)
            except OSError:
                pass
    return bundled


def _ensure_ffmpeg() -> str | None:
    """Return the bin directory to prepend to PATH, or None if system PATH
    already has working ffmpeg + ffprobe."""
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        return None
    bundled = _download_bundled_ffmpeg()
    print(f">> ffmpeg hazir: {bundled[0]}")
    return str(bundled[0].parent)


# ---- main ------------------------------------------------------------------

def main(argv: list[str]) -> int:
    ffmpeg_bin_dir = _ensure_ffmpeg()
    venv = _ensure_venv()
    env = os.environ.copy()
    sep = ";" if platform.system() == "Windows" else ":"
    if ffmpeg_bin_dir:
        env["PATH"] = ffmpeg_bin_dir + sep + env.get("PATH", "")
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(SRC) + (sep + existing_pp if existing_pp else "")
    cmd = [str(_venv_python_at(venv)), "-m", "video_extender", *argv]
    try:
        return subprocess.call(cmd, env=env)
    except KeyboardInterrupt:
        # Ctrl+C in the parent terminal — already propagated to the child.
        # Exit cleanly without dumping a traceback at the user.
        return 130


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        raise SystemExit(130) from None

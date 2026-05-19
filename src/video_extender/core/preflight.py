"""Preflight checks: validate environment before running a batch."""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from video_extender.core.hardware import HardwareInfo, detect, probe_encoder
from video_extender.utils.paths import is_video


@dataclass
class PreflightReport:
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)

    def fail(self, msg: str) -> None:
        self.ok = False
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def note(self, msg: str) -> None:
        self.info.append(msg)


_GPU_PROBE_TARGETS = (
    ("h264_nvenc",        "NVIDIA NVENC H.264"),
    ("hevc_nvenc",        "NVIDIA NVENC HEVC"),
    ("h264_vaapi",        "VAAPI H.264"),
    ("hevc_vaapi",        "VAAPI HEVC"),
    ("h264_qsv",          "Intel QuickSync H.264"),
    ("hevc_qsv",          "Intel QuickSync HEVC"),
    ("h264_amf",          "AMD AMF H.264"),
    ("hevc_amf",          "AMD AMF HEVC"),
    ("h264_videotoolbox", "Apple VideoToolbox H.264"),
    ("hevc_videotoolbox", "Apple VideoToolbox HEVC"),
)


def run(
    *,
    source_folder: Path | None = None,
    output_subdir: str = "output",
    hw: HardwareInfo | None = None,
) -> PreflightReport:
    rep = PreflightReport()
    hw = hw or detect()

    if not hw.ffmpeg_path:
        rep.fail("ffmpeg PATH'te bulunamadı. Lütfen kurun (örn: pacman -S ffmpeg).")
        return rep
    if not hw.ffprobe_path:
        rep.fail("ffprobe PATH'te bulunamadı (ffmpeg paketi ile birlikte gelir).")

    rep.note(f"ffmpeg: {hw.ffmpeg_path}")
    rep.note(f"CPU çekirdek: {hw.cpu_count}, RAM: {hw.ram_total_mb} MB")
    if hw.gpus:
        for g in hw.gpus:
            rep.note(f"GPU: {g.vendor} {g.name} → encoders: {', '.join(g.encoders) or '(yok)'}")
    else:
        rep.warn("Donanım hızlandırmalı GPU encoder bulunamadı; CPU (libx264) kullanılacak.")

    # Functional probe every GPU encoder we found in ffmpeg's encoder list.
    # Failures here are NOT user-actionable in the common case — most systems
    # have only one GPU vendor and "VAAPI doesn't work on this NVIDIA system"
    # is expected, not a problem. Only escalate to a warning if NO GPU
    # encoder works at all. Otherwise: succinct info line.
    functional: list[str] = []
    nonfunctional: list[str] = []
    for enc_name, label in _GPU_PROBE_TARGETS:
        if enc_name not in hw.available_encoders:
            continue
        if probe_encoder(enc_name):
            functional.append(label)
        else:
            nonfunctional.append(label)
    if functional:
        rep.note(f"Çalışan GPU encoder'lar: {', '.join(functional)}")
    if nonfunctional:
        # Quiet info — not a warning. Most users have only one GPU vendor and
        # other vendors' encoders failing to probe is expected, not a problem.
        rep.note(f"Bu sistemde devre dışı GPU encoder'lar (normal): {', '.join(nonfunctional)}")
    if hw.has_gpu_encoder and not functional:
        rep.warn("Hiçbir GPU encoder işlevsel değil; CPU (libx264) fallback kullanılacak.")

    if source_folder is not None:
        if not source_folder.is_dir():
            rep.fail(f"Kaynak klasör bulunamadı: {source_folder}")
        else:
            videos = [p for p in source_folder.iterdir() if is_video(p)]
            if not videos:
                rep.warn(f"Klasörde video bulunamadı: {source_folder}")
            else:
                rep.note(f"{len(videos)} video bulundu.")
            out = source_folder / output_subdir
            try:
                out.mkdir(parents=True, exist_ok=True)
                test = out / ".write_test"
                test.write_text("ok", encoding="utf-8")
                test.unlink()
            except OSError as exc:
                rep.fail(f"Output klasörüne yazılamıyor ({out}): {exc}")

            # Disk-space sanity: estimate output footprint as 2× source total
            # (worst case for re-encode at higher bitrate; fast path is much
            # smaller). Fail if free space less than estimate; warn if tight.
            if videos:
                try:
                    src_bytes = sum(v.stat().st_size for v in videos)
                    free = shutil.disk_usage(out).free
                    estimate = src_bytes * 2
                    if free < estimate:
                        rep.fail(
                            f"Disk alanı yetersiz: çıktı için ~{estimate / 1024**3:.1f} GB "
                            f"gerekli, sadece {free / 1024**3:.1f} GB boş."
                        )
                    elif free < estimate * 1.5:
                        rep.warn(
                            f"Disk alanı sınırda: çıktı için ~{estimate / 1024**3:.1f} GB, "
                            f"{free / 1024**3:.1f} GB boş (komfor için 1.5x öneririz)."
                        )
                except OSError as exc:
                    rep.warn(f"Disk alanı kontrol edilemedi: {exc}")

    # Ulimit sanity check (mostly Linux): open files
    try:
        import resource  # noqa: WPS433
        soft, _ = resource.getrlimit(resource.RLIMIT_NOFILE)
        if soft < 1024:
            rep.warn(f"open-file limiti düşük ({soft}); çok video varsa sorun olabilir.")
    except ImportError:
        pass

    return rep

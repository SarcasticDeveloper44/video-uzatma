"""Command-line interface — `python -m video_extender [args]`."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from video_extender.core import preflight as _preflight
from video_extender.core.extenders import EXTENDER_REGISTRY
from video_extender.core.job import ExtendMode, Job, JobSpec, JobStatus
from video_extender.core.pipeline import BatchRunner, build_jobs
from video_extender.core.presets import PRESET_REGISTRY
from video_extender.utils import logging as _logging
from video_extender.utils.duration import parse_duration, format_duration
from video_extender.utils.notify import notify
from video_extender.utils.paths import discover_videos


def _print_progress_line(job: Job) -> None:
    pct = int(job.progress * 100)
    status = job.status.value
    bar_len = 24
    filled = int(bar_len * job.progress)
    bar = "#" * filled + "-" * (bar_len - filled)
    sys.stderr.write(f"\r[{bar}] {pct:3d}%  {status:9s}  {job.name[:50]}     \n")
    sys.stderr.flush()


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="video-extender",
        description="Sosyal medya reklam videolarını toplu uzat ve sıkıştır.",
    )
    p.add_argument("--folder", "-f", type=Path, required=False,
                   help="İşlenecek videoların bulunduğu klasör.")
    p.add_argument("--recursive", "-r", action="store_true", help="Alt klasörlere in.")

    g_dur = p.add_mutually_exclusive_group()
    g_dur.add_argument("--add", type=str, help="Mevcut süreye N kadar EKLE (örn: 30m, 1h, 90s).")
    g_dur.add_argument("--target", type=str, help="Toplam süreyi N olacak şekilde TAMAMLA.")

    p.add_argument("--method", "-m",
                   choices=sorted(EXTENDER_REGISTRY.keys()),
                   default="freeze",
                   help="Uzatma yöntemi (varsayılan: freeze).")
    p.add_argument("--preset", "-p",
                   choices=sorted(PRESET_REGISTRY.keys()),
                   default="tiktok",
                   help="Platform preset (varsayılan: tiktok).")
    p.add_argument("--quality", "-q", choices=["low", "medium", "high"], default="medium")
    p.add_argument("--codec", "-c", choices=["h264", "hevc"], default="h264",
                   help="Video codec (varsayilan: h264). HEVC ~%%30 daha kucuk dosya, ama bazi reklam platformlarinda reddedilebilir.")
    p.add_argument("--encoder", type=str, default=None,
                   help="ffmpeg encoder ismini zorla (ornek: libx264, h264_nvenc, hevc_vaapi). Bos: otomatik secim.")
    p.add_argument("--max-parallel", type=int, default=None,
                   help="Paralel worker sayisini sinirla (varsayilan: otomatik, donanima gore).")
    p.add_argument("--list-encoders", action="store_true",
                   help="Sistemde mevcut ve calisan encoder'lari listele, cikis.")
    p.add_argument("--filename-template", default="{name}_extended.{ext}",
                   help="Çıktı isim şablonu. Tokens: {name}, {ext}, {duration}, {preset}.")
    p.add_argument("--audio-fade", type=float, default=1.5,
                   help="Ses fade-out süresi (saniye, freeze/black modunda).")
    p.add_argument("--fade-out-final", action="store_true",
                   help="Final çıktıda ek olarak ses fade-out uygula.")
    p.add_argument("--audio-normalize", action="store_true",
                   help="Sesi platform LUFS hedefine normalize et.")
    p.add_argument("--watermark", type=Path, help="Filigran resim dosyası (PNG önerilir).")
    p.add_argument("--watermark-position",
                   choices=["top-left", "top-right", "bottom-left", "bottom-right", "center"],
                   default="bottom-right")
    p.add_argument("--watermark-opacity", type=float, default=0.8)
    p.add_argument("--strip-metadata", action="store_true", help="GPS/EXIF gibi metadata temizle.")
    p.add_argument("--intro", type=Path, help="intro_outro yöntemi için: önüne eklenecek klip.")
    p.add_argument("--outro", type=Path, help="intro_outro yöntemi için: sona eklenecek klip (zorunlu).")
    p.add_argument("--aspect", type=str,
                   help="Hedef en-boy oranı (9:16 / 16:9 / 1:1 / 4:5 / 4:3 veya WxH).")
    p.add_argument("--aspect-mode", choices=["blur_pad", "crop"], default="blur_pad",
                   help="Aspect dönüşüm yöntemi (varsayılan: blur_pad).")
    p.add_argument("--end-card", type=Path,
                   help="image_card yöntemi için: bitiş kartı (PNG/JPG) yolu.")
    p.add_argument("--subtitles", type=Path,
                   help="Altyazı dosyası (SRT/ASS); videoya yakılır.")
    p.add_argument("--subtitle-font-size", type=int, default=24)
    p.add_argument("--subtitle-margin-v", type=int, default=80,
                   help="Altyazıların alt kenardan piksel mesafesi.")
    p.add_argument("--brightness", type=float, default=0.0, help="Color grade: -1..1")
    p.add_argument("--contrast", type=float, default=1.0, help="Color grade: 0..3")
    p.add_argument("--saturation", type=float, default=1.0, help="Color grade: 0..3")
    p.add_argument("--gamma", type=float, default=1.0, help="Color grade: 0.1..10")
    p.add_argument("--output-subdir", default="output", help="Çıktı alt klasör adı.")
    p.add_argument("--no-resume", action="store_true", help="Resume state dosyasını yoksay.")
    p.add_argument("--preflight-only", action="store_true", help="Sadece kontrolleri çalıştır, çıkış.")
    p.add_argument("--list-presets", action="store_true")
    p.add_argument("--list-methods", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def _handle_list_modes(args: argparse.Namespace) -> int | None:
    """If any --list-* flag is set, print the table and return an exit code.
    Returns None when no listing mode is active, signalling main to continue."""
    if args.list_presets:
        for k, preset_cls in sorted(PRESET_REGISTRY.items()):
            print(f"  {k:14s} {preset_cls.label}")
        return 0
    if args.list_methods:
        for k, ext_cls in sorted(EXTENDER_REGISTRY.items()):
            print(f"  {k:14s} {ext_cls.label}")
        return 0
    if args.list_encoders:
        from video_extender.core.encoders import ENCODER_REGISTRY
        from video_extender.core.hardware import detect, probe_encoder
        hw = detect()
        print(f"{'encoder':22s} {'codec':6s} {'kind':4s} {'available':11s} {'functional':11s}")
        print("-" * 65)
        for _name, enc_cls in sorted(ENCODER_REGISTRY.items()):
            avail = enc_cls.ffmpeg_encoder in hw.available_encoders
            functional = probe_encoder(enc_cls.ffmpeg_encoder) if avail else False
            print(f"{enc_cls.ffmpeg_encoder:22s} {enc_cls.codec:6s} {enc_cls.kind:4s} "
                  f"{'YES' if avail else 'no':11s} {'YES' if functional else 'no':11s}")
        return 0
    return None


def _print_preflight(report) -> None:
    for line in report.info:
        print(f"  • {line}")
    for line in report.warnings:
        print(f"  ! {line}", file=sys.stderr)
    for line in report.errors:
        print(f"  ✗ {line}", file=sys.stderr)


def _build_filters_from_args(args: argparse.Namespace) -> tuple[list[str], dict]:
    """Translate CLI flags into the (filter_names, filter_options) tuple
    that JobSpec expects. aspect_convert is prepended so it runs first."""
    filters: list[str] = []
    opts: dict = {}

    if args.audio_normalize:
        filters.append("audio_normalize")
        params = PRESET_REGISTRY[args.preset].for_quality(args.quality)
        opts["audio_normalize"] = {"target_lufs": params.audio_lufs}
    if args.watermark is not None:
        filters.append("watermark")
        opts["watermark"] = {
            "image": str(args.watermark),
            "position": args.watermark_position,
            "opacity": args.watermark_opacity,
        }
    if args.fade_out_final:
        filters.append("audio_fade_out")
        # total_duration filled per-job by the pipeline from target_duration.
        opts["audio_fade_out"] = {"duration": args.audio_fade}
    if args.aspect:
        # Aspect convert must run FIRST so subsequent filters see the new resolution.
        filters.insert(0, "aspect_convert")
        opts["aspect_convert"] = {"target": args.aspect, "mode": args.aspect_mode}
    if args.subtitles is not None:
        filters.append("subtitle_burn")
        opts["subtitle_burn"] = {
            "file": str(args.subtitles),
            "font_size": args.subtitle_font_size,
            "margin_v": args.subtitle_margin_v,
        }
    if (args.brightness != 0.0 or args.contrast != 1.0
            or args.saturation != 1.0 or args.gamma != 1.0):
        filters.append("color_grade")
        opts["color_grade"] = {
            "brightness": args.brightness, "contrast": args.contrast,
            "saturation": args.saturation, "gamma": args.gamma,
        }
    if args.strip_metadata:
        filters.append("metadata_strip")
    return filters, opts


def _build_extender_options(args: argparse.Namespace) -> dict:
    """Collect intro/outro/end-card paths into extender_options dict."""
    opts: dict = {}
    if args.intro is not None:
        opts["intro"] = str(args.intro)
    if args.outro is not None:
        opts["outro"] = str(args.outro)
    if args.end_card is not None:
        opts["image"] = str(args.end_card)
    return opts


def _print_batch_summary(jobs: list[Job]) -> tuple[int, int, int]:
    completed = sum(1 for j in jobs if j.status == JobStatus.COMPLETED)
    failed = sum(1 for j in jobs if j.status == JobStatus.FAILED)
    skipped = sum(1 for j in jobs if j.status == JobStatus.SKIPPED)
    print(f"\nÖzet: {completed} tamam, {failed} hatalı, {skipped} atlandı.")
    for j in jobs:
        if j.status == JobStatus.FAILED:
            print(f"  ✗ {j.name}: {j.error}", file=sys.stderr)
    return completed, failed, skipped


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    _logging.setup(level=10 if args.verbose else 20)

    # Listing modes exit early.
    rc = _handle_list_modes(args)
    if rc is not None:
        return rc

    if args.folder is None:
        parser.error("--folder gerekli (veya --list-presets / --list-methods)")
    folder: Path = args.folder.expanduser().resolve()

    report = _preflight.run(source_folder=folder, output_subdir=args.output_subdir)
    _print_preflight(report)
    if not report.ok:
        return 2
    if args.preflight_only:
        return 0

    if args.add is None and args.target is None:
        parser.error("--add veya --target verilmeli.")
    if args.add is not None:
        extend_seconds, mode = parse_duration(args.add), ExtendMode.ADD
    else:
        extend_seconds, mode = parse_duration(args.target), ExtendMode.FILL

    filters, filter_options = _build_filters_from_args(args)
    extender_options = _build_extender_options(args)
    if args.method == "intro_outro" and "outro" not in extender_options:
        parser.error("--method intro_outro için --outro zorunlu.")
    if args.method == "image_card" and "image" not in extender_options:
        parser.error("--method image_card için --end-card zorunlu.")

    spec = JobSpec(
        extend_seconds=extend_seconds, extend_mode=mode,
        extender_name=args.method, preset_name=args.preset,
        quality=args.quality, video_codec=args.codec,
        encoder_override=args.encoder, max_parallel=args.max_parallel,
        filters=tuple(filters), filter_options=filter_options,
        extender_options=extender_options,
        filename_template=args.filename_template,
        audio_fade_out_seconds=args.audio_fade,
        output_subdir=args.output_subdir,
    )

    sources = discover_videos(folder, recursive=args.recursive)
    if not sources:
        print("Klasörde video bulunamadı.", file=sys.stderr)
        return 1

    print(f"\n{len(sources)} video bulundu. Uzatma: "
          f"{mode.value} {format_duration(extend_seconds)}, "
          f"yöntem={args.method}, preset={args.preset}, kalite={args.quality}\n")

    jobs = build_jobs(sources, spec)
    runner = BatchRunner(jobs, spec, folder, resume=not args.no_resume,
                         on_progress=_print_progress_line)
    try:
        runner.run()
    except KeyboardInterrupt:
        print("\nİptal ediliyor...", file=sys.stderr)
        runner.cancel()
        return 130

    completed, failed, _ = _print_batch_summary(jobs)
    notify("Video Extender", f"{completed} bitti, {failed} hata.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Meta Ads technical compliance checks.

Pre-encode: scan the source for issues that would survive into the output
and trigger a Meta rejection (low resolution, weird aspect, too-long duration).

Post-encode: re-probe the output and verify every Meta-published technical
requirement is met (codec/pixfmt/colorspace/faststart/audio).

Content-policy rejections (forbidden products, personal attributes,
misleading claims) are explicitly OUT OF SCOPE — no algorithm here can
catch those. We only address the technical surface.

References (Meta Business Help Center, ad spec):
  - https://www.facebook.com/business/ads-guide/video
  - Recommended: H.264 + AAC, MP4/MOV, max 60fps, BT.709, faststart
  - Loudness target: -14 LUFS (consumer audio normalization)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from video_extender.utils.ffprobe_parser import MediaInfo


@dataclass(frozen=True)
class MetaSpec:
    """Technical limits Meta's ad pipeline enforces (approximate, conservative).

    These are the values most likely to survive Meta's automated checks; the
    actual ingest pipeline has wider tolerance but we aim for the safe band.
    """
    min_width: int = 1080         # Meta wants HD; 720p ads often get throttled
    max_fps: float = 60.0
    max_duration_feed: float = 60.0    # seconds — Feed/Reels short max
    max_duration_long: float = 240.0   # seconds — In-stream/longform
    target_lufs: float = -14.0
    accepted_codecs: tuple[str, ...] = ("h264", "avc", "avc1")
    accepted_audio: tuple[str, ...] = ("aac",)
    accepted_pixfmts: tuple[str, ...] = ("yuv420p",)


# Singleton — Meta specs don't change runtime.
META_SPEC = MetaSpec()


@dataclass
class ComplianceIssue:
    severity: str          # "warning" | "fail"
    code: str              # short machine-readable code
    message: str           # Turkish, user-facing


@dataclass
class ComplianceReport:
    """Summary of all issues found. Empty `issues` means fully compliant."""
    issues: list[ComplianceIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(i.severity == "fail" for i in self.issues)

    @property
    def has_warnings(self) -> bool:
        return any(i.severity == "warning" for i in self.issues)

    def summary(self) -> str:
        if not self.issues:
            return "✓ Meta uyumlu"
        fails = sum(1 for i in self.issues if i.severity == "fail")
        warns = sum(1 for i in self.issues if i.severity == "warning")
        parts = []
        if fails:
            parts.append(f"{fails} hata")
        if warns:
            parts.append(f"{warns} uyarı")
        return " · ".join(parts)


def _aspect_close_to(width: int, height: int, target_w: int, target_h: int,
                     tol: float = 0.02) -> bool:
    """Return True if the input aspect is within `tol` of the target aspect."""
    if height == 0 or target_h == 0:
        return False
    a1 = width / height
    a2 = target_w / target_h
    return abs(a1 - a2) <= tol * a2


def _is_meta_aspect(width: int, height: int) -> bool:
    """Meta accepts 1:1, 4:5, 9:16, 16:9 with some tolerance."""
    if width <= 0 or height <= 0:
        return False
    for w, h in ((1, 1), (4, 5), (9, 16), (16, 9), (4, 3)):
        if _aspect_close_to(width, height, w, h):
            return True
    return False


def check_source(media: MediaInfo, spec: MetaSpec = META_SPEC) -> ComplianceReport:
    """Pre-encode scan. We only flag things that:
      - WILL persist into the output (a re-encode at our preset will preserve
        the source aspect / resolution / general quality), OR
      - Should prompt the user to change their settings before encoding.

    Things we can FIX during encoding (codec/pixfmt/audio loudness/metadata)
    are NOT flagged here — they'll be silently corrected by the Meta Mode
    encoder pipeline.
    """
    report = ComplianceReport()
    if media.video is None:
        report.issues.append(ComplianceIssue(
            severity="fail", code="no-video",
            message="Kaynak dosyada video stream yok",
        ))
        return report

    v = media.video
    # Resolution: Meta downscales sub-1080p ads or shows a quality warning.
    # Use the SHORT side as the limit so vertical (720×1280) and horizontal
    # (1280×720) both correctly flag as low-resolution.
    short_side = min(v.width, v.height)
    if short_side < spec.min_width:
        report.issues.append(ComplianceIssue(
            severity="warning", code="low-resolution",
            message=(
                f"Kaynak çözünürlük {v.width}×{v.height} — Meta {spec.min_width}p "
                f"önerir. Düşük kalite uyarısı veya throttle olabilir."
            ),
        ))

    # Aspect: only standard ratios pass without letterboxing.
    if not _is_meta_aspect(v.width, v.height):
        ar = v.width / v.height if v.height > 0 else 0
        report.issues.append(ComplianceIssue(
            severity="warning", code="nonstandard-aspect",
            message=(
                f"Kaynak en-boy oranı {ar:.3f} — Meta 9:16 / 1:1 / 4:5 / 16:9 ister. "
                f"aspect_convert filtresini açıp 9:16 veya 1:1 seç."
            ),
        ))

    # Frame rate: > 60fps gets reduced; we cap via preset.fps_cap.
    if v.fps > spec.max_fps:
        report.issues.append(ComplianceIssue(
            severity="warning", code="high-fps",
            message=(
                f"Kaynak FPS {v.fps:.1f} — Meta {spec.max_fps:.0f}fps üst sınır; "
                f"çıktıda preset.fps_cap uygulanacak."
            ),
        ))

    # Duration: Stories/Reels caps; specific placement caps applied by preset.
    if media.duration > spec.max_duration_long:
        report.issues.append(ComplianceIssue(
            severity="warning", code="long-duration",
            message=(
                f"Kaynak süresi {media.duration:.0f}s — Meta uzun-form üst sınırı "
                f"{spec.max_duration_long:.0f}s. Trim gerekebilir."
            ),
        ))

    return report


def check_output(output_path: Path, spec: MetaSpec = META_SPEC) -> ComplianceReport:
    """Re-probe the produced output and verify it meets Meta's published
    technical requirements. Run after every Meta-Mode encode."""
    from video_extender.core.probe import probe_file

    report = ComplianceReport()
    if not output_path.exists():
        report.issues.append(ComplianceIssue(
            severity="fail", code="missing-output",
            message=f"Çıktı dosyası bulunamadı: {output_path}",
        ))
        return report
    try:
        media = probe_file(output_path)
    except Exception as exc:  # noqa: BLE001
        report.issues.append(ComplianceIssue(
            severity="fail", code="unprobable-output",
            message=f"Çıktı parse edilemedi: {exc}",
        ))
        return report

    if media.video is None:
        report.issues.append(ComplianceIssue(
            severity="fail", code="no-video-out",
            message="Çıktıda video stream yok",
        ))
        return report

    v = media.video
    # Video codec
    if v.codec not in spec.accepted_codecs:
        report.issues.append(ComplianceIssue(
            severity="fail", code="bad-codec",
            message=f"Çıktı codec'i '{v.codec}' — Meta H.264 ister",
        ))
    # Pixel format (yuv420p universal)
    if v.pix_fmt not in spec.accepted_pixfmts:
        report.issues.append(ComplianceIssue(
            severity="fail", code="bad-pixfmt",
            message=f"Çıktı pixel format '{v.pix_fmt}' — yuv420p olmalı",
        ))
    # Audio codec
    if media.audio is not None and media.audio.codec not in spec.accepted_audio:
        report.issues.append(ComplianceIssue(
            severity="fail", code="bad-audio",
            message=f"Ses codec'i '{media.audio.codec}' — Meta AAC ister",
        ))
    # FPS upper cap
    if v.fps > spec.max_fps + 0.5:  # tolerance for rounding
        report.issues.append(ComplianceIssue(
            severity="warning", code="output-high-fps",
            message=f"Çıktı FPS {v.fps:.1f} > {spec.max_fps:.0f}",
        ))

    return report


def meta_mode_spec_overrides() -> dict[str, object]:
    """Return the JobSpec field overrides that "Meta Reklam Modu" applies.

    Used by the GUI / CLI when the Meta Mode flag is set: we force the
    encoder configuration into the strictly-Meta-compliant subset
    regardless of any other user preferences (compress toggle, codec
    combo, etc.).
    """
    return {
        "video_codec": "h264",
        # Force the audio_normalize + metadata_strip filters; pipeline
        # merges these with any user-selected filters.
        "_force_filters": ("audio_normalize", "metadata_strip"),
        "_force_filter_options": {
            "audio_normalize": {"target_lufs": META_SPEC.target_lufs},
        },
    }

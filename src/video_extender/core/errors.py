"""Translate raw ffmpeg failures into actionable Turkish error messages.

ffmpeg's stderr is verbose and English-only. End users see the last 5 lines
and have no idea what to do. This module pattern-matches the most common
failure modes and produces a one-line message with the cause and the fix.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedError:
    """Result of parsing an ffmpeg failure."""
    message: str          # one-line Turkish summary
    suggestion: str = ""  # actionable fix (may be empty if the cause is unclear)
    raw_tail: str = ""    # last few lines of stderr for power users

    def format(self) -> str:
        out = self.message
        if self.suggestion:
            out += f" — Cözüm: {self.suggestion}"
        return out


# Pattern → (Turkish message, suggested fix). Patterns are tried in order;
# more specific patterns must come before generic catch-alls.
_PATTERNS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    # NVENC session exhaustion (driver/license cap reached)
    (
        re.compile(r"OpenEncodeSessionEx.*(?:cannot create|out of memory|invalid)",
                   re.IGNORECASE),
        "NVENC oturumu açılamadı (GPU eş zamanlı limit doldu)",
        "max-parallel sayısını azalt veya driver/oyun kapatıp tekrar dene",
    ),
    (
        re.compile(r"nvenc.*?(?:no nvenc capable devices|driver does not support|"
                   r"required nvenc api version)", re.IGNORECASE),
        "NVENC desteği yok veya driver çok eski",
        "NVIDIA driver'ı güncelle (>= 525) veya --encoder libx264 ile CPU kullan",
    ),
    # VAAPI device init failure
    (
        re.compile(r"Failed to (?:initialise|init) (?:VAAPI|hw device)", re.IGNORECASE),
        "VAAPI cihazı başlatılamadı",
        "/dev/dri/renderD128 erişimini kontrol et (sudo usermod -aG video $USER) "
        "veya --encoder libx264 kullan",
    ),
    # QSV init failure
    (
        re.compile(r"Could not (?:open|create) Intel.*?(?:device|qsv)", re.IGNORECASE),
        "Intel QuickSync (QSV) başlatılamadı",
        "intel-media-driver / libva paketlerini yükle veya CPU encoder kullan",
    ),
    # Disk full
    (
        re.compile(r"No space left on device|ENOSPC|disk.*?full", re.IGNORECASE),
        "Disk dolu",
        "Çıktı klasörü disk'inde yer aç ve yeniden dene",
    ),
    # Permission denied on output
    (
        re.compile(r"Permission denied", re.IGNORECASE),
        "Yazma izni reddedildi",
        "Çıktı klasörünün yazma izinlerini kontrol et",
    ),
    # Codec not supported
    (
        re.compile(r"(?:Unknown encoder|Encoder not found):?\s*'?(\S+)'?",
                   re.IGNORECASE),
        "Encoder bulunamadı: {0}",
        "ffmpeg'in bu encoder'la derlenmiş olması gerek; başka encoder kullan",
    ),
    # Filter not found
    (
        re.compile(r"No such filter:?\s*'?(\S+)'?", re.IGNORECASE),
        "Filter bulunamadı: {0}",
        "ffmpeg'in bu filter ile derlenmiş olması gerek (örn. libnpp veya cuda support)",
    ),
    # Moov atom (truncated/corrupt mp4)
    (
        re.compile(r"moov atom not found|Invalid data found when processing input",
                   re.IGNORECASE),
        "Kaynak video bozuk veya eksik (moov atom yok)",
        "Bu video atlanıyor; dosyayı yeniden indir/çevir",
    ),
    # Format probe failure
    (
        re.compile(r"Could not (?:find|probe) (?:codec|format)", re.IGNORECASE),
        "Video formatı tespit edilemedi",
        "Kaynak dosya bozuk olabilir; ffprobe ile manual test et",
    ),
    # OOM during encode
    (
        re.compile(r"(?:Cannot allocate memory|Out of memory|bad_alloc)",
                   re.IGNORECASE),
        "Bellek yetmedi",
        "max-parallel sayısını azalt veya 4K içeriği daha küçük çözünürlüğe çek",
    ),
    # Filter graph syntax error (usually internal bug)
    (
        re.compile(r"(?:Error (?:parsing|initializing) filter|"
                   r"Invalid argument while opening filter)", re.IGNORECASE),
        "Filter zinciri hatalı (iç hata olabilir)",
        "GitHub issue aç ve ffmpeg log'unu paylaş",
    ),
    # Hardware decode/encode mismatch
    (
        re.compile(r"hwaccel .*?does not support|"
                   r"Failed setup for format \w+",
                   re.IGNORECASE),
        "Donanım hızlandırma desteklemedi",
        "--encoder libx264 ile CPU kullan",
    ),
)


def parse_ffmpeg_failure(returncode: int, stderr: str) -> ParsedError:
    """Best-effort parse. Always returns a ParsedError; falls back to the raw
    tail if no pattern matches.
    """
    tail_lines = stderr.strip().splitlines()[-10:]  # look at last 10 for context
    tail = "\n".join(tail_lines)

    for pattern, msg_template, suggestion in _PATTERNS:
        for line in tail_lines:
            m = pattern.search(line)
            if m:
                # Substitute captures into the message template if any.
                try:
                    msg = msg_template.format(*m.groups())
                except (IndexError, KeyError):
                    msg = msg_template
                return ParsedError(message=msg, suggestion=suggestion, raw_tail=tail)

    # Unrecognised — fall back to "exit N + last 3 lines"
    short_tail = " | ".join(tail_lines[-3:]) if tail_lines else "(stderr boş)"
    return ParsedError(
        message=f"ffmpeg exited {returncode}: {short_tail}",
        suggestion="",
        raw_tail=tail,
    )

# Video Extender

Facebook / Instagram / TikTok / YouTube / X / LinkedIn reklam videolarını toplu olarak **uzatıp sıkıştıran** GUI + CLI aracı. Tek videoyu da, 100 videoyu da seçilen klasörden topluca işler; GPU + CPU encoder'larını paralel kullanır. Linux / macOS / Windows; NVIDIA / Intel / AMD / Apple Silicon — hepsi destekli.

## Desteklenen platformlar

| OS | GPU | Encoder | Test |
|----|-----|---------|------|
| Linux | NVIDIA | NVENC H.264/HEVC | ✓ Üretime doğrulandı |
| Linux | Intel / AMD | VAAPI H.264/HEVC | ✓ Pipeline doğru, runtime hardware'e bağlı |
| Linux | Intel | QSV H.264/HEVC | ✓ Pipeline doğru |
| Linux / Windows | AMD | AMF H.264/HEVC | ✓ Pipeline doğru |
| Windows | NVIDIA | NVENC | ✓ (ffmpeg üzerinden) |
| Windows | Intel | QSV | ✓ |
| macOS | Apple Silicon / Intel | VideoToolbox H.264/HEVC | ✓ |
| Hepsi | (yok) | libx264 / libx265 / libsvtav1 / libvpx-vp9 (CPU) | ✓ |

Scheduler her donanım encoder'ını başlamadan önce **functional probe** ediyor (gerçek 1-frame encode denemesi). Başarısız olanı atlayıp CPU veya başka bir GPU encoder'a düşüyor — kullanıcının elle ayar yapmasına gerek yok.

## Hızlı Başlangıç

```bash
# Linux / macOS:
./run.sh

# Windows (cmd / PowerShell):
run.bat

# Veya doğrudan Python ile (cross-platform):
python run.py
```

İlk çalıştırma `.venv/` oluşturur ve PySide6'yı yükler. Sonraki çalıştırmalarda hızlıca açılır. **ffmpeg + ffprobe** sistemde olmalı:

- Linux: `pacman -S ffmpeg` / `apt install ffmpeg` / `dnf install ffmpeg`
- macOS: `brew install ffmpeg`
- Windows: `winget install Gyan.FFmpeg`

### CLI ile çalıştırma

```bash
# 30dk ekle, freeze yöntemi, TikTok preset, watermark, ses normalize
./run.sh --folder ~/Videos/reklamlar --add 30m --method freeze --preset tiktok \
         --audio-normalize --strip-metadata --watermark ~/logo.png

# Toplam süre 30dk olsun, siyah ekran ile Meta IG Reels'e hazırla
./run.sh --folder ~/Videos/reklamlar --target 30m --method black --preset ig_reels

# Intro/outro klipleri ekle
./run.sh --folder ~/Videos --add 10m --method intro_outro \
         --intro ~/clips/intro.mp4 --outro ~/clips/outro.mp4 --preset tiktok

# 16:9 yatay videoyu 9:16 TikTok dikey'e çevir (arka plan blur)
./run.sh --folder ~/Videos --add 15s --method freeze --preset tiktok \
         --aspect 9:16 --aspect-mode blur_pad

# HEVC ile %30 daha küçük dosya
./run.sh --folder ~/Videos --add 30m --codec hevc --preset yt_shorts

# Bitiş kartı + altyazı yakma + renk düzenleme birlikte
./run.sh --folder ~/Videos --add 5s --method image_card \
         --end-card ~/cta.png --preset tiktok \
         --subtitles ~/subs.srt --brightness 0.05 --saturation 1.2

# Listeler
./run.sh --list-presets
./run.sh --list-methods

# Sadece preflight
./run.sh --folder ~/Videos --preflight-only
```

Bayraklar: `--add <süre>` veya `--target <süre>` (örn: `45s`, `30m`, `1h30m`). Uzatma yöntemleri: `freeze`, `black`, `loop`, `intro_outro`, `image_card` (iskelet). Codec: `h264` (varsayılan) veya `hevc`.

## Özellikler

### Çalışan
- **5 uzatma yöntemi:** son kareyi dondur, siyah ekran, döngü, intro/outro klibi, **image_card (PNG/JPG bitiş kartı)**
- **4 encoder (H.264 + HEVC):** NVENC H.264/HEVC (GPU) + libx264/libx265 (CPU). HEVC ~%30 daha küçük dosya.
- **11 platform preset:** Instagram Reels/Feed/Story, Facebook Feed/Reels, TikTok, YouTube Shorts/Long/4K, X/Twitter, LinkedIn Feed
- **Akıllı paralel scheduler:** Codec'e göre encoder seçimi (NVENC varsa 3 GPU + N CPU worker eş zamanlı)
- **7 filtre:**
  - `watermark` (PNG/JPG overlay, opaklık, konum)
  - `audio_normalize` (EBU R128 loudness, preset LUFS hedefi)
  - `audio_fade_out` (final çıktıda)
  - `metadata_strip` (GPS/EXIF temizle)
  - `aspect_convert` (9:16, 16:9, 1:1, 4:5, 4:3 veya WxH; blur_pad veya crop modu)
  - **`subtitle_burn`** (SRT/ASS altyazıyı videoya yakar — sound-off izleyiciler için)
  - **`color_grade`** (brightness/contrast/saturation/gamma — brand consistency için)
- **İki süre modu:** ADD (orijinal + N) ve FILL (toplam N olsun, source ≥ target ise clamp)
- **Resume:** crash sonrası tamamlananları atlar; **filename template değişikliğini de algılar** (source+output çiftiyle eşleşir)
- **Per-job ffmpeg log:** her job için `output/logs/<output_name>.ffmpeg.log`
- **Cancel/Pause:** GUI butonu + CLI Ctrl+C
- **Preflight check:** ffmpeg / NVENC / output yazılabilirlik kontrolü + functional NVENC encode testi
- **Drag & drop:** klasörü pencereye sürükle
- **JSON profiller:** kaydet/yükle (Profiller tab'ı), tüm spec alanları korunur
- **Sistem bildirimi:** batch bitince notify-send

### Test paketi

```bash
.venv/bin/pytest             # 134 test
.venv/bin/pytest -m "not integration"  # birim testler, ffmpeg gerekmez
.venv/bin/pytest -m gui      # sadece GUI testleri
```

Test paketi şu katmanları kapsar: duration parser, path discovery, hardware detection, scheduler (3 codec, GPU/CPU karışımı), config (JSON profil roundtrip + resume state hash), extenders (ünite + entegrasyon), encoders (args yapısı + e2e HEVC/H.264), filters (filtergraph üretimi + e2e), presets, pipeline (resume, fail tolerance, paralel batch), GUI widget davranışları.

### Production'da çalışan encoder'lar

| Encoder | Codec | Donanım | Notlar |
|---------|-------|---------|--------|
| `nvenc_h264` / `nvenc_hevc` | H.264 / HEVC | NVIDIA | Konsumer kartlarda 3 paralel session |
| `vaapi_h264` / `vaapi_hevc` | H.264 / HEVC | Intel / AMD (Linux) | `/dev/dri/renderD128` üzerinden |
| `qsv_h264` / `qsv_hevc` | H.264 / HEVC | Intel CPU iGPU | oneVPL/MFX gerektirir |
| `amf_h264` / `amf_hevc` | H.264 / HEVC | AMD (Win + Linux ROCm/AMF) | CPU pixel format kabul ediyor |
| `videotoolbox_h264` / `videotoolbox_hevc` | H.264 / HEVC | Apple Silicon + Intel Mac | Native macOS |
| `libx264` / `libx265` | H.264 / HEVC | CPU | Universal fallback |
| `libsvtav1` / `libaom_av1` | AV1 | CPU | YouTube optimize |
| `libvpx_vp9` | VP9 | CPU | WebM container |

## Mimari

```
src/video_extender/
├── core/         # Qt'siz, CLI'lanabilir, test edilebilir
│   ├── hardware.py        # GPU/CPU tespiti (NVENC/VAAPI/QSV/AMF)
│   ├── scheduler.py       # Akıllı paralel worker tahsisi
│   ├── ffmpeg.py          # subprocess wrapper + progress parse
│   ├── pipeline.py        # probe → filter → extend → encode orkestra
│   ├── preflight.py       # başlamadan sanity check
│   ├── config.py          # JSON profil + resume state
│   ├── extenders/         # ▼ Strategy pattern — yeni yöntem = 1 dosya
│   ├── encoders/          # ▼ Strategy pattern — yeni codec backend
│   ├── filters/           # ▼ Composable filter chain
│   └── presets/           # ▼ Platform target preset'leri
├── gui/          # PySide6 UI (core'a bağımlı, tersi değil)
└── utils/        # logging, paths, duration, notify
```

### Yeni özellik eklemek
- **Yeni uzatma yöntemi?** `core/extenders/yeni.py` yaz, `ExtenderStrategy`'den türet, `EXTENDER_REGISTRY` otomatik bulur.
- **Yeni encoder?** `core/encoders/yeni.py` yaz, `EncoderBackend`'den türet.
- **Yeni platform?** `core/presets/yeni.py` yaz, `PlatformPreset`'ten türet, 3 kalite parametresi tanımla.
- **Yeni filter?** `core/filters/yeni.py` yaz, `Filter`'dan türet.

Orkestrasyon kodunda **hiçbir değişiklik gerekmez** — auto-discovery.

## Gereksinimler

- Python ≥ 3.11
- ffmpeg + ffprobe (NVENC için CUDA destekli)
- (İsteğe bağlı) NVIDIA GPU + driver — NVENC otomatik kullanılır
- Linux (test edildi: CachyOS, RTX 3070). macOS/Windows için VideoToolbox/AMF iskelet hazır.

## Yapı

| Dosya / Dizin | Amaç |
|---------------|------|
| `run.sh` | Tek komut: venv kurulumu + uygulama |
| `pyproject.toml` | Paket tanımı + entry points |
| `requirements.txt` | PySide6 |
| `src/video_extender/` | Tüm kaynak |
| `<klasör>/output/` | Çıktı + log + resume state |

## Lisans

Kişisel kullanım.

# Video Extender

Facebook / Instagram / TikTok / YouTube / X / LinkedIn reklam videolarını toplu olarak **uzatıp sıkıştıran** GUI + CLI aracı. Tek videoyu da, yüzlerce videoyu da seçilen klasörden topluca işler; GPU + CPU encoder'larını paralel kullanır. Linux / macOS / Windows; NVIDIA / Intel / AMD / Apple Silicon — hepsi destekli.

## Hızlı Başlangıç (Son Kullanıcı — Tak Çalıştır)

İşletim sistemine uygun **tek dosyayı** [Releases sayfasından](../../releases/latest) indir, çift tıkla — açılır. Python, pip, venv, ffmpeg — hiçbir şey gerekmez. Her şey gömülü.

| Platform | İndirilecek | Nasıl çalıştırılır |
|----------|-------------|---------------------|
| Windows 10/11 (64-bit) | `video-extender-windows-amd64.exe` | Çift tıkla |
| macOS (Apple Silicon) | `Video-Extender-darwin-arm64.app.zip` | Zip'i aç, `.app`'i çift tıkla |
| macOS (Intel) | `Video-Extender-darwin-x86_64.app.zip` | Zip'i aç, `.app`'i çift tıkla |
| Linux (x86_64) | `video-extender-linux-x86_64` | `chmod +x` sonra çift tıkla veya `./video-extender-linux-x86_64` |

İlk açılış birkaç saniye sürebilir (PyInstaller içeriği temp klasöre extract eder). Sonraki açılışlar anında.

## Geliştirici / kaynaktan çalıştırma

Kaynak koddan çalıştırmak istersen launcher otomatik bootstrap yapar:

```bash
# Linux / macOS
./run.sh

# Windows
run.bat        # veya: python run.py
```

İlk çalıştırma:
- `.venv/` oluşturulup PySide6 indirilir (sürüm uyumsuzluğunda `py.exe -3.13` / `python3.13` gibi alternatif Python otomatik bulunur)
- OneDrive-sync'li klasörlerde venv kurulumu başarısız olursa `%LOCALAPPDATA%\video-extender\venv` (Windows) / `~/.cache/video-extender/venv` (Linux/macOS) fallback'i devreye girer
- ffmpeg + ffprobe sistemde yoksa `.ffmpeg/` klasörüne statik binary indirilir
  - Linux: [johnvansickle.com](https://johnvansickle.com/ffmpeg/)
  - macOS: [evermeet.cx](https://evermeet.cx/ffmpeg/)
  - Windows: [gyan.dev](https://www.gyan.dev/ffmpeg/)

## Standalone binary üretmek (kendi platformunun için)

```bash
python build.py
```

Çıktı: `dist/video-extender-<os>-<arch>` — tek dosyalık plug-and-play executable (Python + PySide6 + ffmpeg gömülü). PyInstaller cross-compile yapmaz; her platform için o platformda build alınmalı veya `.github/workflows/release.yml`'i tetiklemek için `git tag v0.1.0 && git push --tags` yap — GitHub Actions üç platformu da paralel build eder ve Release artifact'i olarak yayınlar.

## Desteklenen donanım

Scheduler her donanım encoder'ını başlamadan önce **functional probe** ediyor (1-frame deneme encode). Başarısız olanı atlayıp diğerine veya CPU'ya düşüyor — kullanıcı elle ayar yapmıyor.

| OS | NVIDIA | Intel | AMD | Apple |
|----|--------|-------|-----|-------|
| Linux | NVENC ✓ | VAAPI / QSV ✓ | VAAPI / AMF ✓ | — |
| Windows | NVENC ✓ | QSV ✓ | AMF ✓ | — |
| macOS | — | VideoToolbox ✓ | VideoToolbox ✓ | VideoToolbox ✓ |
| GPU yok | libx264 / libx265 / libsvtav1 / libvpx-vp9 (CPU) ✓ | | | |

## Özellikler

- **5 uzatma yöntemi:** `freeze` (son kareyi dondur), `black` (siyah ekran), `loop`, `intro_outro` (klibinizi sona ekle, gerekirse döngüle), `image_card` (PNG/JPG bitiş kartı).
- **15 encoder:** NVENC / VAAPI / QSV / AMF / VideoToolbox H.264 + HEVC + AV1 (mevcutsa); libx264 / libx265 / libsvtav1 / libaom-av1 / libvpx-vp9 (CPU). Codec seç (`--codec hevc` ile ~%30 küçük dosya); encoder zorla (`--encoder libx264`) veya scheduler otomatik en hızlısını seçer.
- **11 platform preset:** Instagram Reels / Feed / Story, Facebook Feed / Reels, TikTok, YouTube Shorts / Long / 4K, X (Twitter), LinkedIn Feed. Her birinde 3 kalite (low / medium / high) ve platforma uygun LUFS hedefi.
- **Akıllı paralel scheduler:** Codec'e göre encoder seçimi; NVIDIA'da 3 paralel NVENC session + N CPU worker eş zamanlı. Toplam paralelliği `--max-parallel N` veya GUI slider ile kısıtla.
- **7 filtre:** `watermark` (PNG/JPG overlay, opaklık + konum), `audio_normalize` (EBU R128 loudness, preset hedefi), `audio_fade_out`, `metadata_strip` (GPS / EXIF temizle), `aspect_convert` (9:16 / 16:9 / 1:1 / 4:5 / 4:3 veya WxH; `blur_pad` veya `crop`), `subtitle_burn` (SRT/ASS yakma), `color_grade` (brightness / contrast / saturation / gamma).
- **İki süre modu:** ADD (orijinal + N) veya FILL (toplam N olsun, source ≥ target ise clamp).
- **Resume:** Crash sonrası `(source, spec_hash)` eşleşen tamamlananları atlar; ayar değişikliği = otomatik yeniden çalıştır.
- **Cancel + retry:** GUI butonları + CLI Ctrl+C. Batch sonunda "Başarısızları Yeniden Dene"; tek satır için sağ-tık → "Bu video'yu yeniden dene".
- **Per-job ffmpeg log:** her job için `output/logs/<output_name>.ffmpeg.log`; GUI'de satıra çift tıklayınca popup.
- **Aspect koruma:** Her video kendi orijinal oranıyla işlenir — bir klasördeki 1:1 / 9:16 / 16:9 karışık videolar birbirini bozmadan çıkar. (Aspect dönüşümü `--aspect` ile opt-in.)
- **Canlı ETA + hız:** Her satır için `speed` (NVENC ~10x), `ETA`, atanmış worker (`GPU#0` / `CPU#3`); status bar'da toplam batch ETA.
- **Settings persistence:** Son spec, pencere geometrisi ve son klasör QSettings'te otomatik saklanır.
- **Cross-OS bildirim:** Linux `notify-send` / macOS `osascript` / Windows PowerShell toast.
- **Drag & drop:** Klasörü pencereye sürükle.
- **JSON profil:** Tüm spec alanlarını export / import.

## Test paketi

```bash
.venv/bin/pytest -m "not slow"   # 201 hızlı test (~28sn)
.venv/bin/pytest                 # 205 test (fast + 4 slow integration, ~65sn)
.venv/bin/pytest -m gui          # sadece GUI widget testleri
```

Kapsamı: utils, hardware tespiti (cross-OS), scheduler (3 codec × GPU/CPU/override), config (JSON profil + resume hash), extenders + encoders + filters + presets (ünite + e2e), pipeline (resume / fail tolerance / paralel batch / worker exception sweep / progress monotonluğu), CLI (argparse + list modes + error paths), GUI widgets, 1080p × 30sn stress.

## CLI örnekleri

```bash
# 30dk freeze yöntemi, TikTok preset, watermark + ses normalize
./run.sh --folder ~/Videos/reklamlar --add 30m --method freeze --preset tiktok \
         --audio-normalize --strip-metadata --watermark ~/logo.png

# Toplam süre 30dk olsun, siyah ekran + IG Reels preset
./run.sh --folder ~/Videos --target 30m --method black --preset ig_reels

# Intro / outro klipleri ekle
./run.sh --folder ~/Videos --add 10m --method intro_outro \
         --intro ~/clips/intro.mp4 --outro ~/clips/outro.mp4 --preset tiktok

# 16:9 yatay → 9:16 TikTok dikey (blur padded arka plan)
./run.sh --folder ~/Videos --add 15s --method freeze --preset tiktok \
         --aspect 9:16 --aspect-mode blur_pad

# Bitiş kartı + altyazı yakma + renk ayarı
./run.sh --folder ~/Videos --add 5s --method image_card \
         --end-card ~/cta.png --preset tiktok \
         --subtitles ~/subs.srt --brightness 0.05 --saturation 1.2

# HEVC ile %30 daha küçük dosya
./run.sh --folder ~/Videos --add 30m --codec hevc --preset yt_shorts

# Listeler ve preflight
./run.sh --list-presets
./run.sh --list-methods
./run.sh --list-encoders
./run.sh --folder ~/Videos --preflight-only
```

## Geliştirici dokümantasyonu

Codebase mimarisi, veri akışı, extension noktaları, threading modeli, hata yolları, status state machine → **[ARCHITECTURE.md](ARCHITECTURE.md)**.

### Yeni özellik eklemek (Strategy + auto-discovery)

| Ne | Dosya | Base class |
|----|-------|------------|
| Yeni uzatma yöntemi | `core/extenders/yeni.py` | `ExtenderStrategy` |
| Yeni encoder | `core/encoders/yeni.py` | `EncoderBackend` |
| Yeni filter | `core/filters/yeni.py` | `Filter` |
| Yeni platform preset | `core/presets/yeni.py` | `PlatformPreset` |

Orkestrasyon kodunda hiçbir değişiklik gerekmez — registry'ler `__init_subclass__` ile otomatik dolar.

## Gereksinimler

- Python ≥ 3.11
- ffmpeg + ffprobe (donanım hızlandırma için codec destekli derleme: NVIDIA için CUDA, AMD/Intel için VAAPI/QSV/AMF, Apple için VideoToolbox)
- (Opsiyonel) GPU + driver — varsa otomatik kullanılır

## Lisans

Kişisel kullanım.

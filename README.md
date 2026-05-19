# Video Extender

Facebook / Instagram / TikTok / YouTube / X / LinkedIn reklam videolarını toplu olarak **uzatıp sıkıştıran** GUI + CLI aracı. Tek videoyu da, yüzlerce videoyu da topluca işler; GPU + CPU encoder'larını paralel kullanır. Linux / macOS / Windows; NVIDIA / Intel / AMD / Apple Silicon — hepsi destekli.

## Hızlı Başlangıç (Son Kullanıcı — Tak Çalıştır)

İşletim sistemine uygun **tek dosyayı** [Releases sayfasından](../../releases/latest) indir, çift tıkla — açılır. Python, pip, venv, ffmpeg — hiçbir şey gerekmez. Her şey gömülü.

| Platform | İndirilecek | Nasıl çalıştırılır |
|---|---|---|
| Windows 10/11 (64-bit) | `video-extender-windows-amd64.exe` | Çift tıkla |
| macOS (Apple Silicon) | `Video-Extender-darwin-arm64.app.zip` | Zip'i aç, `.app`'i çift tıkla |
| macOS (Intel) | `Video-Extender-darwin-x86_64.app.zip` | Zip'i aç, `.app`'i çift tıkla |
| Linux (x86_64) | `video-extender-linux-x86_64` | `chmod +x` sonra çift tıkla |

İlk açılış birkaç saniye (PyInstaller içeriği temp'e extract eder). Sonraki açılışlar anında.

## Geliştirici / kaynaktan çalıştırma

```bash
./run.sh            # Linux / macOS
run.bat             # Windows (çift tıkla veya cmd'den)
python run.py       # Her yerde
```

İlk çalıştırma otomatik bootstrap:
- `.venv/` + PySide6 yüklenir; uyumsuz Python varsa `py.exe -3.13` / `python3.13` aranır
- OneDrive-sync'li klasörde venv başarısız olursa `%LOCALAPPDATA%\video-extender\venv` (Windows) / `~/.cache/video-extender/venv` (Linux/macOS) fallback'i
- ffmpeg + ffprobe sistemde yoksa `.ffmpeg/` altına statik binary indirilir (johnvansickle / evermeet / gyan.dev)

GUI hatalı açılırsa: `video-extender --reset-settings` ile QSettings'i temizle.

## Standalone binary üretmek

```bash
python build.py     # dist/video-extender-<os>-<arch> üretilir
```

PyInstaller cross-compile yapmaz; her platform için o platformda build alınmalı. Üç platformu birden almak için `git tag v0.x.y && git push --tags` → `.github/workflows/release.yml` Linux/macOS/Windows runner'larında paralel build alır ve Release artifact'ı olarak yayınlar.

## Desteklenen donanım

Scheduler her encoder'ı başlamadan önce **functional probe** ediyor (1-frame deneme encode). Başarısız olanı atlayıp diğerine veya CPU'ya düşüyor — kullanıcı elle ayar yapmıyor.

| OS | NVIDIA | Intel | AMD | Apple |
|---|---|---|---|---|
| Linux | NVENC ✓ | VAAPI / QSV ✓ | VAAPI / AMF ✓ | — |
| Windows | NVENC ✓ | QSV ✓ | AMF ✓ | — |
| macOS | — | VideoToolbox ✓ | VideoToolbox ✓ | VideoToolbox ✓ |
| GPU yok | libx264 / libx265 / libsvtav1 / libvpx-vp9 (CPU) ✓ | | | |

## Özellikler

### Çekirdek

- **5 uzatma yöntemi:** `freeze` (son kareyi dondur), `black` (siyah ekran), `loop`, `intro_outro` (klip ekle, döngüle), `image_card` (PNG/JPG bitiş kartı)
- **15 encoder:** NVENC / VAAPI / QSV / AMF / VideoToolbox H.264 + HEVC + AV1 (mevcutsa); libx264 / libx265 / libsvtav1 / libaom-av1 / libvpx-vp9 (CPU). `--codec hevc` ile %30 küçük dosya
- **11 platform preset:** Instagram Reels / Feed / Story, Facebook Feed / Reels, TikTok, YouTube Shorts / Long / 4K, X (Twitter), LinkedIn Feed — her birinde 3 kalite × platforma uygun LUFS hedefi
- **Akıllı paralel scheduler:** NVIDIA'da 3 paralel NVENC session (dinamik probe ile 5/8'e çıkabilir) + N CPU worker eş zamanlı
- **7 filtre:** watermark, audio_normalize (EBU R128), audio_fade_out, metadata_strip, aspect_convert (9:16 / 16:9 / 1:1 / 4:5 / 4:3, blur_pad / crop), subtitle_burn (SRT/ASS), color_grade
- **İki süre modu:** ADD (orijinal + N) / FILL (toplam N olsun, source ≥ target ise clamp)

### Stream-copy fast path (v0.2+, v0.4 image_card, **v0.12 intro_outro**)

| Extender | Strateji | Kazanç |
|---|---|---|
| `loop` | `ffmpeg -stream_loop -1 -c copy` (encode YOK) | **100x+** |
| `freeze` / `black` | static tail encode + concat-copy | 30-100x |
| `image_card` | image-as-video tail + concat-copy | 3-10x |
| **`intro_outro`** | intro+outro encode-once cache + **source stream-copy** | **10-60x** (workflow-defining) |

Eligibility: source codec/pixfmt/audio target ile uyumlu olmalı. Uymazsa otomatik full encode'a düşer.

### Akıllı planlama

- **Longest-job-first scheduling:** En uzun video en hızlı encoder'a — batch critical path %20-40 kısalır
- **Auto-preset:** İlk videonun aspect oranından TikTok / IG Feed / YouTube Long otomatik seçilir (kullanıcı manuel değiştirirse o seçim kalır)
- **Compress toggle (1 tık):** HEVC + low quality + CRF → dosya boyutu %50
- **Meta Reklam Modu:** FB/IG için tüm Meta teknik spec'lerini zorlar (H.264 + AAC + -14 LUFS + BT.709 + faststart + metadata strip + post-encode validation)
- **Resource-aware parallelism:** HDD source → cap 2 paralel (seek thrashing önlenir); Free RAM düşük → otomatik azalt
- **Process priority:** Her ffmpeg subprocess'i nice +10 (Unix) / BELOW_NORMAL (Windows) — uzun batch sistemi yavaşlatmaz

### Güvenilirlik

- **Output integrity validation:** Her encode sonrası ffprobe — dosya var, parse edilebilir, video stream var, duration ±2% target
- **Disk-space preflight:** Çıktı tahmini × 1.5 vs disk free; yetersizse fail, sınırdaysa uyarı
- **Akıllı hata mesajları:** ffmpeg stderr 11 pattern ile parse edilir — NVENC session, VAAPI init, disk full, codec missing, OOM, corrupt source vs. → Türkçe mesaj + çözüm
- **Resume:** Crash sonrası `(source, spec_hash)` eşleşen tamamlananları atlar; ayar değişikliği = otomatik yeniden çalıştır
- **Cancel / Pause / Resume:** GUI düğmeleri + CLI Ctrl+C; pause SIGSTOP/SIGCONT ile ffmpeg subprocess'leri dondurur
- **Cross-OS bildirim:** Linux `notify-send` / macOS `osascript` / Windows PowerShell toast

### GUI (v0.10+)

- **Drag-drop:** Klasör, tek video veya çoklu video — hepsi kabul
- **Tek "Seç…" düğmesi:** Tek dialog, içinde hem dosyalar hem klasörler — "Aç" dosya seçer, "Bu klasörü kullan" klasörü seçer
- **Video thumbnails:** Her satırda küçük frame preview (96×54, async + cached)
- **Sıralanabilir sütunlar:** Süre / Çözünürlük / Durum / Hız / ETA — başlığa tıkla
- **Çoklu seçim + toplu işlem:** Ctrl/Shift+klik → sağ tık: "Hatalıları yeniden dene (N)", "Bekleyenleri kaldır (N)", "Çıktıları aç (N)"
- **Status filter:** "Tümü / Bekleyen / Çalışan / Tamamlanan / Hatalı / Atlanan / İptal"
- **Custom output folder:** Absolute path picker (boş = `<kaynak>/output/`)
- **Pre-batch summary:** 3 satır canlı özet — N video × süre × preset → çıktı süresi × tahmini boyut × encoder strategy
- **System tray:** X butonu → tray'e gizle (tray menüsü → Çık ile gerçek çıkış)
- **Dark mode:** OS teması Dark ise Fusion + custom palette otomatik
- **Klavye kısayolları:** Ctrl+O / F5 / Esc / Ctrl+R / Delete / Ctrl+S / Ctrl+L
- **"Varsayılana Döndür"** Profiller sekmesinde tek tık reset
- **Output reveal:** Tamamlanan satıra çift tıkla → OS file manager'da dosya highlighted açılır
- **Per-job ffmpeg log:** Satırda sağ tık → "ffmpeg log'unu göster"
- **JSON profil:** Tüm spec alanlarını export / import
- **Settings persistence:** Son spec, pencere geometrisi, son klasör QSettings'te otomatik saklanır

## Test paketi

```bash
.venv/bin/pytest -W error -m "not slow"   # 273 hızlı test (~28sn)
.venv/bin/pytest -W error                  # 277 test (fast + 4 slow integration, ~65sn)
.venv/bin/pytest -m gui                    # GUI + E2E widget testleri
```

Kapsam: utils, hardware tespiti (cross-OS), scheduler (3 codec × GPU/CPU/override × HDD/RAM), config (JSON profil + resume hash), extenders (5) + encoders (15) + filters (7) + presets (11), pipeline (resume / fail tolerance / paralel batch / worker exception / progress monotonluğu), CLI (argparse + list modes + error paths + --doctor + --reset-settings), GUI widgets (28), Meta compliance, error parsing, fast path eligibility (loop/freeze/black/image_card/intro_outro), thumbnail extraction, output validation, **E2E user flows** (drop-to-finish, retry, Meta mode, bulk retry, reset, status filter, extender requirements).

## CLI örnekleri

```bash
# 30dk freeze, TikTok preset, watermark + ses normalize
./run.sh --folder ~/Videos/reklamlar --add 30m --method freeze --preset tiktok \
         --audio-normalize --strip-metadata --watermark ~/logo.png

# Toplam 30dk, siyah ekran + IG Reels
./run.sh --folder ~/Videos --target 30m --method black --preset ig_reels

# Intro / outro (v0.12+ fast path otomatik devreye girer)
./run.sh --folder ~/Videos --add 10m --method intro_outro \
         --intro ~/clips/intro.mp4 --outro ~/clips/outro.mp4 --preset tiktok

# 16:9 → 9:16 dönüşüm + watermark
./run.sh --folder ~/Videos --add 15s --method freeze --preset tiktok \
         --aspect 9:16 --aspect-mode blur_pad

# Bitiş kartı + altyazı + renk
./run.sh --folder ~/Videos --add 5s --method image_card \
         --end-card ~/cta.png --preset tiktok \
         --subtitles ~/subs.srt --brightness 0.05 --saturation 1.2

# HEVC ile küçük dosya
./run.sh --folder ~/Videos --add 30m --codec hevc --preset yt_shorts

# Listeler ve teşhis
./run.sh --version
./run.sh --doctor                  # ffmpeg, encoder, RAM, GPU sağlık raporu
./run.sh --list-presets
./run.sh --list-methods
./run.sh --list-encoders
./run.sh --reset-settings          # GUI hatalı açılırsa QSettings'i temizle
./run.sh --folder ~/Videos --preflight-only
```

## Yeni özellik eklemek (Strategy + auto-discovery)

| Ne | Dosya | Base class |
|---|---|---|
| Yeni uzatma yöntemi | `core/extenders/yeni.py` | `ExtenderStrategy` |
| Yeni encoder | `core/encoders/yeni.py` | `EncoderBackend` |
| Yeni filter | `core/filters/yeni.py` | `Filter` |
| Yeni platform preset | `core/presets/yeni.py` | `PlatformPreset` |

Orkestrasyon kodunda hiçbir değişiklik gerekmez — registry'ler `__init_subclass__` ile otomatik dolar.

## Geliştirici dokümantasyonu

Codebase mimarisi, veri akışı, extension noktaları, threading modeli, hata yolları, status state machine, fast path implementation → **[ARCHITECTURE.md](ARCHITECTURE.md)**.

## Gereksinimler

- Python ≥ 3.11 (kaynaktan çalıştırma için; standalone binary'lerde gömülü)
- ffmpeg + ffprobe (donanım hızlandırma için codec destekli derleme; kaynaktan çalıştırmada otomatik indirilir)
- (Opsiyonel) GPU + driver — varsa scheduler otomatik kullanır

## Lisans

Kişisel kullanım.

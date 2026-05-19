# Video Extender — Mimari

Bu belge geliştiriciler için. Kullanıcı dokümantasyonu [README.md](README.md)'de.

## Genel yapı

Üç katman, tek yönlü bağımlılık:

```
┌─────────────────────────────────────────────────┐
│ GUI (PySide6)         CLI (argparse)            │
│ src/video_extender/   src/video_extender/cli.py │
│   gui/                                          │
└──────────────┬──────────────┬───────────────────┘
               ▼              ▼
       ┌──────────────────────────────┐
       │ Core (Qt'siz, test edilebilir)│
       │ src/video_extender/core/     │
       └──────────────┬───────────────┘
                      ▼
            ┌──────────────────┐
            │ ffmpeg, ffprobe  │
            │ (system binary)  │
            └──────────────────┘
```

- `core/` hiçbir Qt sembolüne dokunmaz; sadece stdlib + ffmpeg subprocess'i. Tüm iş mantığı burada.
- `gui/` ve `cli/` core'u tüketir, tersi olmaz.
- `core/` çıktı üretmez (print/notification yok); olayları callback / signal aracılığıyla yukarı verir.

## Veri akışı (tek bir batch)

```
1.  Folder picker veya CLI --folder
        │
        ▼
2.  utils.paths.discover_videos(folder, recursive)
        │   → list[Path]
        ▼
3.  core.probe.probe_file(path) for each
        │   ffprobe -show_streams -show_format
        │   → MediaInfo (width, height, fps, duration, codecs)
        ▼
4.  core.pipeline.build_jobs(sources, spec)
        │   → list[Job]   (probe failure → status=FAILED)
        ▼
5.  core.pipeline.BatchRunner(jobs, spec, folder)
        │
        ├── 5a. ensure_output_dir + plan output paths via safe_output_path
        │
        ├── 5b. Resume check: is_completed(state_path, source, spec_hash)?
        │       eşleşen jobs → SKIPPED
        │
        ├── 5c. scheduler.plan(n_pending, codec, encoder_override, max_parallel)
        │       → SchedulePlan(slots: tuple[WorkerSlot])
        │       her slot: kind=GPU|CPU, encoder=h264_nvenc|libx264|...,
        │                 threads, gpu_index, label
        │
        ├── 5d. ThreadPoolExecutor(max_workers=worker_count)
        │       her job → pool.submit(execute_job, slot)
        │
        │       execute_job:
        │         ┌────────────────────────────────────────────────┐
        │         │ FAST PATH attempt (core.fast_path):            │
        │         │   1. Eligibility: filter chain empty, source   │
        │         │      codec matches target, container is mp4-   │
        │         │      family, not CRF mode.                     │
        │         │   2. extender.build_fast_path() → FastPathPlan │
        │         │      (sequence of ffmpeg argv's; loop=1 cmd,   │
        │         │      black=2 cmds, freeze=3 cmds).            │
        │         │   3. Run all → validate output → SUCCESS.      │
        │         │   On any failure: fall through to full path.  │
        │         │                                                │
        │         │ FULL PATH (build_job_command):                 │
        │         │   extender.build_plan(media, target_duration)  │
        │         │     → ExtenderPlan (filtergraph, extra inputs) │
        │         │   filters.build_chain(spec)                    │
        │         │     → FilterChain (filter_complex segments)    │
        │         │   encoder.build_args(slot, preset_params)      │
        │         │     → EncoderArgs (-c:v ..., hw_init_args,     │
        │         │                    gpu_upload_filter)          │
        │         │   compose argv: hw_init + inputs +              │
        │         │                 -filter_complex + map +         │
        │         │                 encoder_args + -t target        │
        │         │                                                │
        │         │ Output validation (both paths):                │
        │         │   _validate_output() probes output with        │
        │         │   ffprobe: must exist, >1KB, parseable, video  │
        │         │   stream present, duration ±2% of target.      │
        │         │   Catches "ffmpeg returned 0 but output is     │
        │         │   truncated" — fast path that fails validation │
        │         │   silently retries via full path.              │
        │         └────────────────────────────────────────────────┘
        │         │
        │         ▼
        │       FFmpegRunner.run(argv, on_progress, stderr_log_path)
        │         │   subprocess.Popen + -progress pipe:1
        │         │   stdout: key=value progress events → ProgressEvent
        │         │   stderr: captured to log_dir/<output>.ffmpeg.log
        │         │
        │         ▼
        │       Job status: COMPLETED | FAILED | CANCELLED
        │       Completed → config.mark_completed(state_path, spec_hash)
        │
        ├── 5e. fut.result() — unhandled exception → job FAILED
        │
        └── 5f. Final sweep — herhangi non-terminal job → FAILED
                (defense-in-depth, "summary counts == len(jobs)" invariant)

6.  Result: each job has terminal status. GUI updates table,
    CLI prints summary, system notification.
```

## Dinamik optimizasyon katmanı

Pipeline yedi adaptif optimizasyon kullanır. **Hiçbiri hardcode değil**;
her biri runtime'da tespit edilen koşullara göre devreye girer ve
başarısız olursa sessizce eski yola düşer.

### Stream-copy fast path (`core/fast_path.py`)

`ExtenderStrategy`'ye opsiyonel `build_fast_path()` method'u eklendi.
Eğer extender bu method'u tanımlamışsa ve eligibility koşulları sağlanıyorsa
(filtersiz + source codec ↔ target codec eşleşmesi + mp4-family container +
CRF override yok), pipeline tüm encode yerine concat-copy yolunu seçer.

| Extender | Strateji | Tipik kazanç |
|---|---|---|
| `loop` | `ffmpeg -stream_loop -1 -c copy` (encode YOK) | 100x+ |
| `freeze` | last-frame extract → static tail encode → concat-copy | 30-100x |
| `black` | lavfi black tail → concat-copy | 30-100x |
| `image_card` | image-as-video tail + concat-copy | 3-10x |
| `intro_outro` (v0.12) | intro+outro encode-once cache + source stream-copy + concat-copy | 10-60x |

Fast path başarısız olursa (eligibility yok, ffmpeg fail, output validation
fail) pipeline otomatik full-encode yoluna düşer — fonksiyonalite garantili.

**intro_outro caching (v0.12.0)**: build_fast_path intro ve outro'yu yalnızca
ilk job'da encode eder ve `tmp_dir/intro_outro_cache/` altına kaydeder. Cache
anahtarı `(source_w, source_h, fps, audio_sr, target_codec, encoder, intro/outro
content hash)`. Sonraki jobs aynı intro+outro'yu cache'den okur; source ise her
job için stream-copy ile concat — encode yok. Batch sonunda tmp_dir temizlenir.

### Longest-job-first dispatch (`core/pipeline.py:_dispatch_pool`)

Jobs source duration'a göre desc sıralanır, slot'lar GPU-first sıralanır.
ThreadPoolExecutor FIFO submit eder → en uzun video en hızlı encoder'a düşer.
"Uzun CPU job batch sonunda tek başına çalışır" problemini elimine eder.

### Parallel ffprobe (`core/pipeline.py:build_jobs` + `gui/workers.py:ProbeThread`)

ThreadPoolExecutor 8-paralel ffprobe çalıştırır (her biri ~50ms metadata
read). 100 video için 30sn → 4sn. GUI'de `as_completed` ile sırayla emit
edilir (cancel responsive kalır).

### Resource-aware parallelism (`core/hardware.py` + `core/scheduler.py`)

İki yeni runtime probe:
- `free_ram_mb()`: Linux `/proc/meminfo`, macOS `vm_stat`, Windows
  `Get-CimInstance Win32_OperatingSystem`.
- `is_rotational_disk(path)`: Linux `/sys/block/.../queue/rotational`,
  macOS `diskutil -plist SolidState`, Windows `Get-PhysicalDisk MediaType`.

Scheduler bu sinyalleri okur:
- HDD source → CPU paralel cap = 2 (seek thrashing önlenir).
- Free RAM < N × 800 MB → cap = `free_ram / 800` (OOM önlenir).

Constraint'ler `scheduler.py` constants — call-site değişikliği olmadan
ayarlanabilir.

### Output integrity validation (`core/pipeline.py:_validate_output`)

Her encode (fast path veya full) tamamlandıktan sonra output'ta ffprobe
çalışır:
- Dosya mevcut + >1KB
- ffprobe parse edebilir
- Video stream var
- Duration target'ın ±%2'si içinde

ffmpeg occasionally returns 0 for truncated files (eksik moov atom);
validation bunu yakalayıp FAILED işaretler. Fast path validation fail
ederse silently full path'e retry yapılır.

### ffmpeg hata parser'ı (`core/errors.py`)

ffmpeg stderr ham + İngilizce. `parse_ffmpeg_failure(returncode, stderr)`
11 yaygın hata pattern'ini Türkçe mesaj + actionable çözüm önerisine
çevirir:

| Pattern | Mesaj | Öneri |
|---|---|---|
| OpenEncodeSessionEx fail | NVENC oturumu açılamadı | max-parallel azalt |
| nvenc driver too old | NVENC driver çok eski | Driver güncelle |
| VAAPI init | VAAPI başlatılamadı | `usermod -aG video` |
| QSV init | Intel QSV başlatılamadı | intel-media-driver yükle |
| No space left | Disk dolu | Çıktıda yer aç |
| Permission denied | Yazma izni yok | Çıktı izinlerini kontrol et |
| Unknown encoder | Encoder bulunamadı | Başka encoder dene |
| No such filter | Filter bulunamadı | ffmpeg derleme opsiyonları |
| moov atom not found | Source bozuk | Dosyayı yeniden indir |
| Out of memory | Bellek yetmedi | Paralel sayısı azalt |
| Filter graph parse | Filter zinciri bozuk | GitHub issue aç |

Eşleşmezse fallback: `ffmpeg exited N: <son 3 satır stderr>`.

### Meta Reklam Modu (`core/compliance.py`)

`JobSpec.meta_mode=True` olduğunda BatchRunner:
1. `_enforce_meta_mode_codec` — HEVC/AV1/VP9 → H.264 zorla rewrite
2. `_resolve_filters` — audio_normalize (-14 LUFS) + metadata_strip filter
   zinciri yokken bile eklenir
3. `build_job_command` — `-colorspace bt709 -color_primaries bt709
   -color_trc bt709` output'a damgalanır
4. `_apply_ffmpeg_result` — sonra `compliance.check_output(output_path)`
   ile re-probe: codec H.264, pixfmt yuv420p, audio AAC, fps ≤ 60.
   Fail varsa job FAILED, warning varsa job.error'a not düşülür ama
   completed sayılır.

Pre-encode: `MainWindow._maybe_show_meta_warnings()` source'ta low
resolution / non-standard aspect / too-long source / high fps varsa
bilgilendirme dialog'u gösterir (encode yine çalışır, sadece uyarı).

### Process priority (`core/ffmpeg.py:_nice_popen_kwargs`)

Her ffmpeg subprocess'i lowered priority ile başlar:
- Linux/macOS: `Popen(preexec_fn=os.nice(10))` — yalnızca forklanan child
  niced, Python parent normal kalır
- Windows: `Popen(creationflags=0x4000)` — BELOW_NORMAL_PRIORITY_CLASS

Sistem boştaysa ffmpeg yine tüm CPU'yu alır; interaktif task'lere karşı
kaybeder. Uzun batch'in tarayıcı/IDE'yi yavaşlatmasını engeller.

## Genişletme noktaları (Strategy pattern + auto-discovery)

Dört kategoride yeni davranış eklemek **tek bir dosya** yazmaktan ibaret. Her kategori bir ABC ve global registry kullanır; modül yüklenince `__init_subclass__` registry'ye otomatik kayıt yapar.

### Yeni uzatma yöntemi

`src/video_extender/core/extenders/yeni_yontem.py`:

```python
from video_extender.core.extenders.base import ExtenderPlan, ExtenderStrategy
from video_extender.utils.ffprobe_parser import MediaInfo

class YeniYontem(ExtenderStrategy):
    name = "yeni_yontem"           # registry key
    label = "Görünür isim"
    description = "Açıklama (GUI'de tooltip)"

    def build_plan(self, source, media, target_duration, *,
                   audio_fade_out_seconds=1.5, options=None) -> ExtenderPlan:
        # filtergraph üret
        return ExtenderPlan(
            source_input_args=("-stream_loop", "-1"),  # ihtiyaç varsa
            extra_inputs=(...),                         # ek -i input(lar)
            extra_input_args=(...,),                    # her ek input için prefix
            filtergraph="...",
            video_label="[vout]",
            audio_label="[aout]",
        )
```

`extenders/__init__.py`'ye import ekle, otomatik registry'ye düşer. GUI/CLI listelerinde görünür.

### Yeni encoder backend

`src/video_extender/core/encoders/yeni_encoder.py`:

```python
from video_extender.core.encoders.base import EncoderArgs, EncoderBackend

class YeniEncoder(EncoderBackend):
    name = "yeni_id"
    label = "Görünür isim"
    ffmpeg_encoder = "h264_xxx"      # ffmpeg encoder name
    kind = "gpu"                      # "gpu" | "cpu"
    codec = "h264"                    # "h264" | "hevc" | "av1" | "vp9"

    def build_args(self, *, bitrate_kbps, audio_bitrate_kbps, crf,
                   gpu_index, threads, extra=None) -> EncoderArgs:
        return EncoderArgs(
            video_args=("-c:v", "h264_xxx", "-b:v", f"{bitrate_kbps}k"),
            audio_args=("-c:a", "aac", "-b:a", f"{audio_bitrate_kbps}k"),
            container_args=("-movflags", "+faststart"),
            preferred_ext="mp4",
            hw_init_args=("-vaapi_device", "/dev/dri/renderD128"),  # GPU init args
            gpu_upload_filter="format=nv12,hwupload",                # son filtre
        )
```

Scheduler `codec` ve `kind`'a göre uygun GPU/CPU encoder'ı seçer. `hw_init_args` `-i` ÖNCESİNDE, `gpu_upload_filter` filter_complex SONUNDA otomatik enjekte edilir — pipeline halleder.

### Yeni filter

`src/video_extender/core/filters/yeni_filter.py`:

```python
from video_extender.core.filters.base import Filter, FilterFragment

class YeniFilter(Filter):
    name = "yeni_filter"
    label = "Görünür isim"

    def build(self, *, in_video, in_audio, next_input_index, options=None):
        suffix = in_video.strip("[]")
        out_label = f"[yeni_{suffix}]"
        seg = f"{in_video}some_filter=opt=value{out_label}"
        return FilterFragment(
            filter_segment=seg,
            new_video_label=out_label,           # video etiketini değiştir
            extra_inputs=(...,),                  # ekstra -i (e.g. watermark png)
            prefix_input_args=("-loop", "1"),     # her ekstra input için prefix
            output_metadata_args=(...,),          # -map_metadata gibi top-level
        )
```

Filter chain sıralı uygulanır. Bir önceki filter'ın `new_video_label`'ı sonraki filter'a `in_video` olarak geçer.

### Yeni platform preset

`src/video_extender/core/presets/yeni_platform.py`:

```python
from video_extender.core.presets.base import PlatformPreset, PresetParams

class YeniPlatform(PlatformPreset):
    name = "yeni_platform"
    label = "Yeni Platform"
    description = "..."
    params_low    = PresetParams(bitrate_kbps=3000, audio_bitrate_kbps=128,
                                 audio_lufs=-14.0, max_width=1080, max_height=1920, fps_cap=30.0)
    params_medium = PresetParams(bitrate_kbps=5000, audio_bitrate_kbps=128, audio_lufs=-14.0)
    params_high   = PresetParams(bitrate_kbps=8000, audio_bitrate_kbps=192, audio_lufs=-14.0)
```

GUI'deki preset combobox'ı registry'den otomatik dolduğu için, GUI kodunda değişiklik gerekmez.

## Threading modeli

| Thread | Sorumluluk |
|--------|------------|
| Main (Qt event loop) | GUI işle, signal'leri al, state güncelle |
| `ProbeThread` (QThread) | `ffprobe` çağrılarını seri halde yapar; her dosyadan sonra `isInterruptionRequested()` kontrol eder |
| `BatchThread` (QThread) | `BatchRunner.run()`'ı çağırır; pool'a job submit eder, finished/progress signal yayınlar |
| `ThreadPoolExecutor` worker'ları (BatchRunner içinde) | Her worker bir `execute_job` çalıştırır; her biri kendi `FFmpegRunner` örneğine sahip → cancel sırasında o tek subprocess'i öldürür |
| `FFmpegRunner._drain_stderr` (sub-thread) | ffmpeg subprocess'inin stderr'ını okur; ana thread stdout'tan progress okurken bloklamasın diye |

**Signal vs callback:** Core'un `on_progress` callback'leri Qt signal'lerini bilmez. `gui/workers.py` callback'i Qt signal emit eden bir lambda ile sarmalıyor.

## State

| Konum | İçerik | Yaşam süresi |
|-------|--------|---------------|
| `<source>/output/.video_extender_state.json` | `completed` jobs (source + output + spec_hash) ve `failed` jobs | Klasör bazında kalıcı |
| `<source>/output/logs/<output>.ffmpeg.log` | Her job için ffmpeg stderr | Klasör bazında kalıcı |
| QSettings (`~/.config/...` / Windows Registry / macOS plist) | Son window geometrisi, son spec, son folder | Kullanıcı bazında kalıcı |
| JSON profil dosyaları | Spec'i export/import | Manuel oluşturulur |

**Resume kararı:** `is_completed(state_path, source, spec, output)` —
`(source, spec_hash)` eşleşmesi varsa VE output dosyası diskte mevcutsa SKIPPED. Aksi durumda yeniden encode. `spec_hash` JobSpec'in tüm içerik-üreten alanlarını hash'ler; ufak ayar değişikliği farklı hash → re-run.

## Statü makinesi

```
PENDING  ──┬─→ PROBING ─→ QUEUED ─→ RUNNING ─┬─→ COMPLETED
           │                                  ├─→ FAILED
           │                                  └─→ CANCELLED
           └─→ SKIPPED (resume hit)
           └─→ FAILED (probe error in build_jobs)
```

`BatchRunner.run()` döndüğünde HER job mutlaka {COMPLETED, FAILED, CANCELLED, SKIPPED}'dan birinde. Aksi senaryo varsa final sweep zorla FAILED yapar.

## Hata yolları (production'da test'le sabitlenmiş)

- Probe failure (bozuk dosya, eksik moov atom vb.) → `build_jobs` FAILED job üretir
- ffmpeg returncode != 0 → execute_job FAILED + stderr tail in `job.error`
- ffmpeg SIGKILL (137) → log dosyası yine yazılır
- ffmpeg cancelled (kullanıcı X tuşu) → CANCELLED + "cancelled by user"
- Worker thread'inde unhandled Python exception → BatchRunner outer try-except FAILED yapar
- Non-terminal status sonu → final sweep FAILED'a çevirir
- Folder yok → CLI rc=2, GUI critical dialog
- GPU encoder listede ama init başarısız → scheduler atlar, CPU encoder kullanır

İlgili testler: `tests/test_pipeline.py` içindeki `TestFfmpegEncodeFailure`, `TestRealWorldStress`, `TestBatchRunner`.

## Test kategorileri

`pytest.ini` markers:
- (varsayılan) hızlı birim testler
- `@pytest.mark.integration` — gerçek ffmpeg çağırır
- `@pytest.mark.slow` — uzun süren scale/stress testleri (`-m "not slow"` ile atlanır)
- `@pytest.mark.gpu` — NVENC sahibi sistem gerektirir
- `@pytest.mark.gui` — PySide6 yüklü olmalı

`tests/conftest.py` her test için (autouse):
- QSettings'i tmp dizine yönlendirir (kullanıcı ayarlarına dokunmaz)
- QMessageBox modal'larını no-op stub'lar (offscreen Qt hang olmaz)
- `notify()` masaüstüne dispatch'i devre dışı (test'lerden gerçek bildirim sızmasın)
- `QT_QPA_PLATFORM=offscreen` set eder

Real video fixture'ları `ffmpeg lavfi` ile üretilir — placeholder/demo data değil, gerçek H.264 encoded dosya.

## Test stat

```
273 test (269 fast + 4 slow @pytest.mark.slow)
- tests/test_*.py birim testleri (filter, encoder, preset, hardware,
  scheduler, fast_path, errors, compliance)
- tests/test_fast_path.py — eligibility matrisi + per-extender plan
  (loop=1 cmd, black=2 cmds, freeze=3 cmds, image_card=2 cmds,
  intro_outro fast path eligibility)
- tests/test_hardware.py — _os_can_probe + dynamic resource probes
  (free_ram_mb, is_rotational_disk)
- tests/test_errors.py — ffmpeg stderr pattern matching (NVENC/VAAPI/
  QSV init, disk full, OOM, codec/filter not found, moov, ...)
- tests/test_compliance.py — Meta spec source check + output check +
  meta_mode override shape
- tests/test_pipeline.py @pytest.mark.integration uçtan uca ffmpeg
  (resume hash, fail tolerance, worker exception, summary invariants,
  fast path testler tarafından dolaylı doğrulanır, Meta Mode codec
  rewrite + filter injection)
- tests/test_stress.py @pytest.mark.slow 1080p 30s yük testleri
- tests/test_gui.py @pytest.mark.gui PySide6 widget'ları (28 test —
  picker, settings, presets, filters, video list, reset, auto-preset,
  meta toggle, compress toggle, profile persistence, ...)
- tests/test_e2e.py @pytest.mark.gui + integration — gerçek
  QApplication + ffmpeg + MainWindow user flows (drop-to-finish,
  retry, Meta Mode, bulk retry, reset, status filter, extender
  requirements validation)
- tests/test_cli.py argparse + main() + --version + --doctor +
  --reset-settings + --list-modes
- tests/test_notify.py subprocess-mock'lu notify davranışı
```

## Modül bağımlılık zinciri

```
utils.{logging, paths, duration, notify, ffprobe_parser}
   ↑
core.{hardware, ffmpeg, probe, job, config, preflight}
   ↑
core.extenders / encoders / filters / presets   (her birinin base + concrete'leri)
   ↑
core.scheduler, core.pipeline
   ↑
gui.workers ←── gui.widgets.* ←── gui.main_window
   ↑
cli.py, app.py
```

`utils/` ↓ olarak hiçbir şeye bağımlı değil (saf yardımcılar).
`core/extenders|encoders|filters|presets/` birbirinden bağımsız, sadece kendi base ABC'sine bağımlı.

## Dosya boyut özeti

```
src/   69 .py dosyası
tests/ 19 .py dosyası
```

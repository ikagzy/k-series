# K-Optimizer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Windows'ta CPU/RAM/GPU yükünü süreç bazında izleyen, güvenli süreçleri onayla kapatıp geri açabilen masaüstü uygulaması.

**Architecture:** `monitor` (psutil + WMI GPU sayaçları) bir `Snapshot` üretir; `classifier` her sürece `Level` verir; `cleaner` seçilen süreçleri kapatır ve `session.json`'a yazar, `restore()` ile geri açar. `cli` ve `ui` yalnızca bu üç katmanı çağırır, iş mantığı içermez.

**Tech Stack:** Python 3.11+, psutil, customtkinter, pytest. Opsiyonel: pynvml (kullanılmaz, ilk sürümde yok).

**Spec:** `docs/superpowers/specs/2026-10-23-k-optimizer-design.md`

## Global Constraints

- Python 3.11+, yalnızca Windows 10/11.
- Bağımlılıklar: `psutil`, `customtkinter`; test için `pytest`. Başka bağımlılık eklenmez.
- GPU verisi üretici bağımsız okunur (NVIDIA/AMD/Intel); GPU okunamazsa GPU alanları `None`, hiçbir yerde istisna fırlatılmaz.
- `protected` süreç listede görünmez ve `cleaner` tarafından da reddedilir (iki katmanlı).
- Emin olunamayan süreç `unknown` olur, asla `safe` olmaz.
- Yönetici izni gerektirmez; erişim reddedilen süreç atlanır ve sebep `"yetki gerekir"` yazılır.
- Her kapatma kullanıcı onayı ister (UI ve CLI'da `--yes` yoksa).
- Testler gerçek süreç kapatmaz, gerçek PowerShell çalıştırmaz.
- Oyun tespiti, Oyun Modu, servis/kayıt defteri, disk temizliği bu planda yok.

## Review Focus

1. Süreç snapshot ile kapatma arasında çıkmış: `close` hata vermeden `skipped` ("süreç yok") yazar.
2. PID yeniden kullanılmış (aynı pid, farklı `create_time`): `close` yanlış süreci öldürmez, `skipped` yazar.
3. Türkçe/yerelleştirilmiş Windows: GPU okuması sayaç adına değil WMI sınıf adına dayanır; WMI başarısızsa GPU alanları `None`.
4. Yolunda boşluk/Türkçe karakter olan exe: `restore` komut satırını liste olarak çalıştırır, string birleştirmez.
5. Bozuk veya eksik `session.json` / kullanıcı `known_apps.user.json`: çökmeden boş kabul edilir.

---

## Dosya yapısı

```
pyproject.toml
requirements.txt
src/k_optimizer/__init__.py
src/k_optimizer/__main__.py        # cli.main'i çağırır
src/k_optimizer/models.py          # Level, ProcInfo, GpuAdapter, Snapshot
src/k_optimizer/gpu.py             # WMI okuma + saf ayrıştırıcılar
src/k_optimizer/monitor.py         # snapshot()
src/k_optimizer/classifier.py      # KnownApps, classify()
src/k_optimizer/data/known_apps.json
src/k_optimizer/cleaner.py         # Cleaner, SessionStore
src/k_optimizer/cli.py             # scan / close / restore
src/k_optimizer/ui.py              # CustomTkinter arayüzü
tests/test_gpu.py  test_monitor.py  test_classifier.py  test_cleaner.py  test_cli.py
```

---

### Task 1: Proje iskeleti ve modeller

**Files:**
- Create: `pyproject.toml`, `requirements.txt`, `src/k_optimizer/__init__.py`, `src/k_optimizer/models.py`, `tests/test_models.py`

**Interfaces:**
- Produces (`models.py`):
  - `class Level(str, Enum)`: `PROTECTED="protected"`, `SAFE="safe"`, `UNKNOWN="unknown"`
  - `@dataclass(frozen=True) class ProcInfo`: `pid:int, name:str, exe:str|None, cmdline:tuple[str,...], create_time:float, cpu_percent:float, rss_bytes:int, gpu_percent:float|None, vram_bytes:int|None`
  - `@dataclass(frozen=True) class GpuAdapter`: `luid:str, utilization:float, dedicated_used_bytes:int|None`
  - `@dataclass(frozen=True) class Snapshot`: `cpu_percent:float, ram_used_bytes:int, ram_total_bytes:int, adapters:tuple[GpuAdapter,...], processes:tuple[ProcInfo,...]`

- [ ] **Step 1: `git init`, sanal ortam, `requirements.txt` (`psutil`, `customtkinter`, `pytest`) ve `pyproject.toml` (paket `k_optimizer`, `src` düzeni, `pytest` için `pythonpath = ["src"]`) oluştur; `pip install -r requirements.txt` çalıştır.**
- [ ] **Step 2: Failing test yaz** — `tests/test_models.py::test_level_values_and_procinfo_is_immutable`: `Level.SAFE.value == "safe"`; `ProcInfo(...)` oluşturulur; `p.pid = 5` `dataclasses.FrozenInstanceError` fırlatır.
- [ ] **Step 3: Çalıştır:** `pytest tests/test_models.py -v` → FAIL (`ModuleNotFoundError`).
- [ ] **Step 4: `models.py`'yi yukarıdaki imzalarla yaz.**
- [ ] **Step 5: Çalıştır:** `pytest tests/test_models.py -v` → PASS.
- [ ] **Step 6: Commit:** `git add -A && git commit -m "chore: project scaffold and models"`

---

### Task 2: GPU sayaç ayrıştırma ve okuma

**Files:**
- Create: `src/k_optimizer/gpu.py`, `tests/test_gpu.py`

**Interfaces:**
- Consumes: `GpuAdapter` (Task 1)
- Produces (`gpu.py`):
  - `parse_engine(samples: dict[str, float]) -> tuple[dict[int, float], dict[str, float]]` — `samples` anahtarı WMI `GPUEngine` örnek adı, değeri `UtilizationPercentage`. Dönüş: (pid→yüzde, luid→yüzde).
  - `parse_process_memory(samples: dict[str, int]) -> dict[int, int]` — `GPUProcessMemory` adı→`DedicatedUsage`; pid→bayt (aynı pid'in adaptörleri toplanır).
  - `parse_adapter_memory(samples: dict[str, int]) -> dict[str, int]` — `GPUAdapterMemory` adı→`DedicatedUsage`; luid→bayt.
  - `read_gpu() -> GpuReading | None`, `@dataclass(frozen=True) class GpuReading: per_pid_percent: dict[int,float]; per_pid_vram: dict[int,int]; adapters: tuple[GpuAdapter,...]`. Başarısızlıkta `None`.

Örnek adlar: motor `pid_1234_luid_0x00000000_0x0000A1B2_phys_0_eng_0_engtype_3D`; süreç belleği `pid_1234_luid_0x00000000_0x0000A1B2_phys_0`; adaptör belleği `luid_0x00000000_0x0000A1B2_phys_0`. Luid = `0x00000000_0x0000A1B2` kısmı.

- [ ] **Step 1: Failing testler** (`tests/test_gpu.py`):
  - `test_parse_engine_sums_engines_per_pid_and_caps_at_100`: aynı pid için iki motor 70+60 → `per_pid[1234] == 100.0`.
  - `test_parse_engine_adapter_utilization_is_max_engtype_sum`: luid için engtype 3D toplamı 40, VideoDecode toplamı 10 → adaptör 40.0.
  - `test_parse_engine_ignores_malformed_names`: `"garbage"` anahtarı atlanır, istisna yok.
  - `test_parse_process_memory_sums_adapters_per_pid`: aynı pid iki luid, 100+200 → 300.
  - `test_parse_adapter_memory_keyed_by_luid`.
  - `test_read_gpu_returns_none_when_powershell_fails`: `subprocess.run` monkeypatch ile `OSError` / sıfırdan farklı çıkış kodu / geçersiz JSON → `None`.
  - `test_read_gpu_builds_reading_from_json`: monkeypatch'li `subprocess.run` üç sınıfın JSON çıktısını döndürür → `GpuReading` beklenen sözlüklerle.
- [ ] **Step 2: Çalıştır** `pytest tests/test_gpu.py -v` → FAIL.
- [ ] **Step 3: Ayrıştırıcıları `re` ile yaz** (`pid_(\d+)_luid_(0x[0-9A-Fa-f]+_0x[0-9A-Fa-f]+)`, motor için `engtype_(\w+)`); eşleşmeyen ad atlanır.
- [ ] **Step 4: `read_gpu()`** tek `subprocess.run(["powershell","-NoProfile","-Command", ...], capture_output=True, text=True, timeout=10)` ile üç `Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_{GPUEngine,GPUProcessMemory,GPUAdapterMemory} | Select Name,UtilizationPercentage/DedicatedUsage | ConvertTo-Json` çalıştırır (tek obje gelirse listeye sar). Her türlü hata → `None`. Sınıf adları dil bağımsızdır; `Get-Counter` kullanma.
- [ ] **Step 5: Çalıştır** `pytest tests/test_gpu.py -v` → PASS.
- [ ] **Step 6: Commit:** `git add -A && git commit -m "feat: locale-independent GPU counter reader"`

---

### Task 3: Monitor

**Files:**
- Create: `src/k_optimizer/monitor.py`, `tests/test_monitor.py`

**Interfaces:**
- Consumes: `read_gpu() -> GpuReading | None` (Task 2), modeller (Task 1)
- Produces: `snapshot(read_gpu_fn=gpu.read_gpu) -> Snapshot`

- [ ] **Step 1: Failing testler:**
  - `test_snapshot_contains_own_process`: `snapshot(lambda: None)` içinde `os.getpid()` var; `ram_total_bytes > 0`; tüm süreçlerde `gpu_percent is None and vram_bytes is None`; `adapters == ()`.
  - `test_snapshot_merges_gpu_reading`: sahte `GpuReading` (`per_pid_percent={os.getpid(): 12.5}`, `per_pid_vram={os.getpid(): 1024}`, bir adaptör) → kendi sürecinde `gpu_percent == 12.5`, `vram_bytes == 1024`; GPU verisi olmayan süreçte `0.0`/`0` değil `None`'dan farklı: okuma başarılıysa eksik pid için `gpu_percent == 0.0`, `vram_bytes == 0`.
  - `test_snapshot_skips_processes_that_vanish_or_deny_access`: `psutil.process_iter` monkeypatch'li, biri `NoSuchProcess` biri `AccessDenied` fırlatır → diğerleri döner, istisna yok. Erişim reddedilen süreçte `exe=None`, `cmdline=()` ile yine listelenir.
- [ ] **Step 2: Çalıştır** → FAIL.
- [ ] **Step 3: `snapshot()`** `psutil.process_iter(["pid","name","exe","cmdline","create_time","memory_info"])` ile süreçleri okur; CPU yüzdesi için `process_iter`'in önbelleğe aldığı `Process.cpu_percent(None)` kullanılır (ilk çağrıda 0.0 olması kabul). `cpu_count` ile bölünür (0-100 aralığı). Sistem toplamı `psutil.cpu_percent(None)`, `psutil.virtual_memory()`.
- [ ] **Step 4: Çalıştır** → PASS.
- [ ] **Step 5: Commit:** `git add -A && git commit -m "feat: system and per-process snapshot"`

---

### Task 4: Classifier

**Files:**
- Create: `src/k_optimizer/classifier.py`, `src/k_optimizer/data/known_apps.json`, `tests/test_classifier.py`

**Interfaces:**
- Consumes: `ProcInfo`, `Level` (Task 1)
- Produces:
  - `class KnownApps`: `KnownApps.load(builtin: Path, user: Path | None) -> KnownApps`; `.is_safe(name: str) -> bool` (küçük harf karşılaştırma). Bozuk/eksik kullanıcı dosyası yok sayılır; bozuk yerleşik dosya `ValueError`.
  - `classify(p: ProcInfo, known: KnownApps, own_pids: frozenset[int]) -> Level`
  - `default_known_apps() -> KnownApps` (yerleşik dosya + `%APPDATA%\K-Optimizer\known_apps.user.json`)

`known_apps.json` biçimi: `{"safe": ["spotify.exe", "discord.exe", "onedrive.exe", "teams.exe", "msedgewebview2.exe", "steamwebhelper.exe", "epicgameslauncher.exe", "googledrivefs.exe", "dropbox.exe", "skype.exe", "slack.exe", "zoom.exe", "adobeupdateservice.exe", "ccleaner.exe"]}` (küçük başlar, 10-20 giriş).

Korumalı kurallar (sırayla, ilk eşleşen kazanır): `pid in own_pids`; `exe is None`; `exe` `C:\Windows\` altında (büyük/küçük harfsiz, `SystemRoot` ortam değişkeninden); ad şu kümede: `system, system idle process, registry, smss.exe, csrss.exe, wininit.exe, services.exe, lsass.exe, svchost.exe, winlogon.exe, explorer.exe, dwm.exe, fontdrvhost.exe, msmpeng.exe, nissrv.exe, securityhealthservice.exe, sihost.exe, ctfmon.exe, taskhostw.exe, runtimebroker.exe, searchhost.exe, startmenuexperiencehost.exe, shellexperiencehost.exe`. Sonra `known.is_safe(name)` → `SAFE`; aksi `UNKNOWN`.

- [ ] **Step 1: Failing testler:**
  - `test_system_dir_process_is_protected`: `exe=r"C:\Windows\System32\foo.exe"`, ad bilinen-güvenli listesinde olsa bile → `PROTECTED`.
  - `test_known_name_is_protected_even_outside_windows_dir`: `exe=r"D:\x\lsass.exe"` → `PROTECTED`.
  - `test_exe_none_is_protected`.
  - `test_own_pid_is_protected`.
  - `test_known_safe_app_is_safe`: `Discord.exe` (büyük harf) → `SAFE`.
  - `test_unknown_app_is_unknown_never_safe`: `random.exe` → `UNKNOWN`.
  - `test_known_apps_ignores_corrupt_user_file`: kullanıcı dosyasına `"{bozuk"` yazılır → yerleşik liste çalışır.
  - `test_known_apps_user_file_adds_names`.
- [ ] **Step 2: Çalıştır** → FAIL.
- [ ] **Step 3: Yaz** (sabit küme ve kural sırası yukarıdaki gibi).
- [ ] **Step 4: Çalıştır** → PASS.
- [ ] **Step 5: Commit:** `git add -A && git commit -m "feat: process classifier with known-apps whitelist"`

---

### Task 5: Cleaner

**Files:**
- Create: `src/k_optimizer/cleaner.py`, `tests/test_cleaner.py`

**Interfaces:**
- Consumes: `ProcInfo`, `Level` (Task 1); `classify` imzası (Task 4)
- Produces:
  - `@dataclass(frozen=True) class CloseReport: closed: tuple[ProcInfo,...]; skipped: tuple[tuple[ProcInfo,str],...]`
  - `@dataclass(frozen=True) class RestoreReport: started: tuple[str,...]; failed: tuple[tuple[str,str],...]` (ad, hata)
  - `class Cleaner(store_path: Path, classify: Callable[[ProcInfo], Level], get_process: Callable[[int], psutil.Process] = psutil.Process, launch: Callable[[list[str], str | None], None] = <subprocess.Popen sarmalayıcı, DETACHED_PROCESS>)`
    - `close(procs: Sequence[ProcInfo]) -> CloseReport`
    - `restore() -> RestoreReport`
    - `pending() -> tuple[ProcInfo,...]` (kayıtta bekleyenler; UI "Geri Al" düğmesi için)

Davranış: `close` her süreç için (1) `classify(p) == PROTECTED` ise `skipped` ("korumalı"); (2) `get_process(pid)`: `NoSuchProcess` → "süreç yok"; `create_time` eşleşmiyorsa → "süreç değişmiş"; (3) `terminate()`, 3 sn `wait`, `TimeoutExpired` ise `kill()`; `AccessDenied` → "yetki gerekir". Yalnızca gerçekten kapananlar `closed` olur ve `store_path` JSON'una eklenir (ad, exe, cmdline). `restore` kayıttaki her girdiyi `launch(list(cmdline), cwd=exe'nin klasörü)` ile açar, başarılıları kayıttan siler; `launch` hatası `failed`'e yazılır, kalanlara devam eder. `cmdline` boşsa `[exe]` kullanılır. Bozuk/eksik `store_path` boş kayıt sayılır.

- [ ] **Step 1: Failing testler** (sahte `get_process` ve `launch` ile):
  - `test_close_rejects_protected_process_without_touching_it`: `classify` → `PROTECTED`; `get_process` hiç çağrılmaz; `skipped` sebebi `"korumalı"`.
  - `test_close_terminates_and_records_closed_process`: sahte süreç `terminate` çağrılır; `closed` içinde; `pending()` aynı süreci döndürür.
  - `test_close_skips_vanished_process` (`NoSuchProcess`) → `"süreç yok"`.
  - `test_close_skips_reused_pid` (farklı `create_time`) → `"süreç değişmiş"`, `terminate` çağrılmaz.
  - `test_close_kills_when_terminate_times_out`.
  - `test_close_reports_access_denied` → `"yetki gerekir"`, kayıtta yok.
  - `test_restore_launches_recorded_commands_and_clears_store`: `launch` argümanı liste; boşluklu yol `r"C:\Program Files\App\a.exe"` tek eleman olarak geçer.
  - `test_restore_continues_after_launch_failure`: biri `OSError`, diğeri başarılı → `failed` 1, `started` 1.
  - `test_corrupt_store_is_treated_as_empty`.
- [ ] **Step 2: Çalıştır** → FAIL.
- [ ] **Step 3: Yaz** (kayıt atomik: geçici dosyaya yazıp `os.replace`).
- [ ] **Step 4: Çalıştır** → PASS.
- [ ] **Step 5: Commit:** `git add -A && git commit -m "feat: cleaner with reversible close and session log"`

---

### Task 6: CLI

**Files:**
- Create: `src/k_optimizer/cli.py`, `src/k_optimizer/__main__.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `snapshot`, `classify`, `default_known_apps`, `Cleaner`, `CloseReport`, `RestoreReport`
- Produces: `main(argv: list[str] | None = None, *, snapshot_fn=monitor.snapshot, cleaner: Cleaner | None = None) -> int` (çıkış kodu 0 başarı, 1 hata). Alt komutlar:
  - `scan`: `safe` ve `unknown` süreçleri RAM'e göre sıralı tablo olarak yazar (`level` sütunuyla); `protected` hiçbir zaman yazılmaz.
  - `close --pids 12,34 [--yes]`: `--yes` yoksa kaç süreç ve yaklaşık boşalacak RAM'i yazıp `input()` ile onay ister; reddedilirse 1. Ardından `CloseReport` özetini yazar.
  - `restore`: `RestoreReport` özetini yazar.
  - Kayıt yolu: `%APPDATA%\K-Optimizer\session.json`.

- [ ] **Step 1: Failing testler:**
  - `test_scan_never_prints_protected_processes` (sahte snapshot, `capsys`).
  - `test_close_without_yes_aborts_on_negative_answer`: `input` monkeypatch `"h"` → çıkış kodu 1, `Cleaner.close` çağrılmaz.
  - `test_close_with_yes_calls_cleaner_for_selected_pids_only`.
  - `test_close_unknown_pid_is_reported_not_crashing`: listede olmayan pid → mesaj, çıkış 1.
  - `test_restore_prints_summary`.
- [ ] **Step 2: Çalıştır** → FAIL.
- [ ] **Step 3: `argparse` ile yaz;** `__main__.py` `sys.exit(main())` çağırır.
- [ ] **Step 4: Çalıştır** `pytest -v` (tüm testler) → PASS.
- [ ] **Step 5: Elle doğrula:** `python -m k_optimizer scan` gerçek makinede çalışır, tablo ve (varsa) GPU sütunu görünür; çıktı "GPU kullanılamıyor" ise `Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine` komutunu elle çalıştırıp neden olduğunu raporla.
- [ ] **Step 6: Commit:** `git add -A && git commit -m "feat: scan/close/restore CLI"`

---

### Task 7: Arayüz

**Files:**
- Create: `src/k_optimizer/ui.py`; Modify: `src/k_optimizer/__main__.py` (argümansız çalışınca arayüzü açar, alt komut varsa CLI)

**Interfaces:**
- Consumes: `snapshot`, `classify`, `default_known_apps`, `Cleaner`
- Produces: `run() -> None`

Davranış: Arayüz iş mantığı içermez. İki sekmeli `customtkinter.CTkTabview`:
- *Canlı Yük*: CPU %, RAM (kullanılan/toplam) ve GPU adaptörlerinin yüzde/VRAM'i; altında süreç tablosu (ad, CPU, RAM, GPU, VRAM, seviye), `protected` olmayanlar, RAM'e göre sıralı. GPU `None` ise sütun "—".
- *Temizlik*: `safe` süreçler seçili, `unknown` süreçler seçilmemiş onay kutularıyla listelenir; "Kapat" onay penceresi (sayı ve boşalacak RAM) sonra `Cleaner.close`; sonuçta `skipped` sebepleriyle özet; "Geri Al" düğmesi `Cleaner.pending()` boşsa devre dışı, aksi `Cleaner.restore()`.
- Durum çubuğu: GPU verisi yoksa "GPU okunamıyor", herhangi bir süreç "yetki gerekir" döndüyse bunu belirtir.
- `snapshot()` arka plan iş parçacığında 2 sn aralıkla çalışır, sonuç `after()` ile UI iş parçacığına aktarılır; pencere kapanınca iş parçacığı durur.

- [ ] **Step 1: `ui.py`'yi yaz.**
- [ ] **Step 2: Elle doğrula:** `python -m k_optimizer` penceresi açılır; (a) canlı değerler 2 sn'de bir güncellenir, (b) `protected` süreç hiçbir listede yok, (c) gereksiz ama zararsız bir uygulama (ör. not defteri) "unknown" olarak seçilip kapatılır, "Geri Al" ile yeniden açılır, (d) pencere kapanınca süreç sonlanır.
- [ ] **Step 3: Commit:** `git add -A && git commit -m "feat: customtkinter UI"`

---

## Spec kapsam kontrolü

| Spec bölümü | Task |
|---|---|
| monitor (süreç, GPU, adaptör, `None` davranışı) | 2, 3 |
| classifier (protected/safe/unknown, beyaz liste, kullanıcı eklemesi) | 4 |
| cleaner (nazik kapat→zorla, kayıt, geri aç, korumalı reddi) | 5 |
| Cleaner arayüzden bağımsız, komut satırından çağrılabilir | 5, 6 |
| ui (Canlı Yük, Temizlik, durum çubuğu) | 7 |
| Onay, yönetici izni gerektirmeme, "yetki gerekir" | 5, 6, 7 |
| Testler (sahte süreç, sahte GPU çıktısı) | 2–6 |

**Spec'ten sapma:** classifier ilk sürümde imzalı yayıncı kontrolü yapmaz (ad ve yol yeterli, yayıncı doğrulaması imza API'si gerektirir); spec bu doğrultuda güncellendi. PyInstaller paketleme bu planın dışında, sonraki adım.

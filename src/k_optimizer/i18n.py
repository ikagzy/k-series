"""Turkish and English for K-Series and K-Optimizer. The source text is Turkish; `t()` swaps known phrases for
English when the interface language is English. Phrases are replaced longest first, so a long sentence wins over
the words in it. The language is chosen in K-Series' settings (%APPDATA%/K-Series/settings.json); K-Optimizer
follows it."""
import json
import locale
import os
import re
from pathlib import Path

LANGUAGES = (("tr", "Türkçe"), ("en", "English"))

_PAIRS = {
    "Ana Sayfa": "Home", "Ayarlar": "Settings", "Hızlı": "Fast", "Kapalı": "Off", "Yavaş": "Slow",
    "Kısayol yalnızca exe sürümünde oluşturulur.": "The shortcut can only be created from the exe version.",
    "Masaüstü kısayolu hazır; simgesi temayla birlikte değişir.": "Desktop shortcut ready; its icon follows the theme.",
    "Kısayol oluşturulamadı.": "Could not create the shortcut.",
    "Güncellemeler denetleniyor…": "Checking for updates…",
    ": yeni sürüm ": ": new version ", ": güncel": ": up to date", ": henüz yayın yok": ": no release yet",
    "K-Series yalnızca exe sürümünde güncellenebilir.": "K-Series can only be updated from the exe version.",
    " açık olduğu için otomatik güncelleme beklemede; elle güncelleyebilirsin.":
        " is open, so the automatic update is waiting; you can update it by hand.",
    "yüklü değil": "not installed",
    " şu an açık; güncelleme için nazikçe kapatılacak.\n\n":
        " is open right now; it will be closed politely for the update.\n\n",
    "İndirilsin ve kurulsun mu?": "Download and install it?", "İndirilsin ve yüklensin mi?": "Download and install it?",
    "Güncelleme": "Update",
    " indiriliyor… %": " downloading… %", " indiriliyor…": " downloading…", " kuruluyor…": " installing…",
    " kuruluyor, birkaç saniye içinde yeniden açılır.": " is being installed and reopens in a few seconds.",
    " hazır.": " is ready.", " kuruldu, yeniden başlatılıyor…": " was installed, restarting…",
    "Güncelleme beklenmedik bir hatayla durdu: ": "The update stopped with an unexpected error: ",
    "Tek çatı, tüm K ürünleri": "One roof for all K products",
    "Çalışıyor": "Running", "Bulunamadı": "Not found", "Güncelle": "Update", "Yükle": "Install",
    "Ürünler aranıyor": "Looking for products", "Ürünler": "Products",
    "Bu bilgisayarda algılanan K ürünleri": "K products found on this computer",
    "Yeni sürüm": "New version", "Yüklenebilir": "Can be installed", "Güncel": "Up to date", "Ayrıntı": "Details",
    "Yeniden tara": "Rescan", "Kısayol simgesini güncelle": "Update the shortcut icon",
    "Masaüstü kısayolu oluştur": "Create a desktop shortcut",
    "Kısayolun simgesi, K-Launcher'daki gibi seçtiğin temaya göre değişir.":
        "The shortcut's icon follows the theme you pick, as in K-Launcher.",
    "K-Series için yeni sürüm: ": "New version for K-Series: ", "Şu an v": "Currently v",
    "Aranıyor...": "Searching...", " yayınlandı": " released", "Sürüm": "Version",
    " (K-Series ile ortak)": " (shared with K-Series)", "Ayar klasörü": "Settings folder",
    "Klasörü aç": "Open folder", "Konum seç...": "Choose location...", "İndirme sayfası": "Download page",
    "Tema ve hareket, K-Launcher ile ortaktır": "Theme and motion are shared with K-Launcher",
    "TEMA": "THEME", "HAREKET HIZI": "MOTION SPEED", "DİL": "LANGUAGE",
    "GÜNCELLEMELER (GITHUB)": "UPDATES (GITHUB)", "Açılışta denetle": "Check on start",
    "Kendiliğinden kur": "Install automatically", "Şimdi denetle": "Check now", " deposu:": " repository:",
    "Değiştir": "Change", " başlatıldı.": " started.", "Başlatılamadı.": "Could not start.",
    "Tema ayar klasörüne yazılamadı (salt okunur olabilir).": "Could not write the theme to the settings folder (read-only?).",
    "Hareket ayarı yazılamadı.": "Could not write the motion setting.", "Ayar kaydedilemedi.": "Could not save the setting.",
    "Geçersiz depo adı. 'sahip/depo' biçiminde yaz.": "Invalid repository name. Write it as 'owner/repo'.",
    "Depo kaydedildi: ": "Repository saved: ", "Depo kaydedilemedi.": "Could not save the repository.",
    "Konum kaydedildi.": "Location saved.", "Konum kaydedilemedi.": "Could not save the location.",
    "GitHub deposu": "GitHub repository", "Uygulama": "Application",
    " güncellemeleri hangi depodan gelsin?\n(sahip/depo biçiminde, ör. ikagzy/k-launcher)":
        " updates should come from which repository?\n(as owner/repo, e.g. ikagzy/k-launcher)",
    # K-Optimizer
    " çekirdek": " cores", "okunamıyor": "unavailable",
    "Windows'un gereksiz yükünü temizle": "Clear Windows' unnecessary load",
    "🛡  Yönetici olarak aç": "🛡  Open as administrator", "↶  Geri Al": "↶  Undo", "Otomatik": "Auto",
    "her ": "every ", " sn": " s",
    " yavaşlatıldı": " slowed down", " · oto denge açık": " · auto balance on",
    " arka planda yavaşlatıldı": " slowed down in the background", "Otomatik denge: ": "Auto balance: ",
    "Otomatik denge: öncelikler eski haline getirildi": "Auto balance: priorities restored",
    " sürecin önceliği eski haline getirildi": " process priorities restored",
    "Otomatik CPU dengeleme kapatıldı · ": "Automatic CPU balancing turned off · ",
    "Otomatik CPU dengeleme açıldı: sistem yüklenince arka planda CPU yiyenler yavaşlatılır, ön plandaki uygulamaya dokunulmaz":
        "Automatic CPU balancing turned on: when the system is busy, background CPU hogs are slowed down; the app "
        "in front is never touched",
    "Windows bileşeni kapatıldı: ": "Windows component closed: ", "yetki gerekir": "needs permission",
    "bazıları için yönetici yetkisi gerekir": "some need administrator permission",
    "Düşürülecek veya kapatılacak gereksiz yük yok.": "There is no unnecessary load to lower or close.",
    "Otomatik RAM temizliği: ": "Automatic RAM cleaning: ", "RAM temizliği hata verdi: ": "RAM cleaning failed: ",
    " saniyede bir boştaki arka plan süreçlerinin belleği sıkıştırılır (hiçbir şey kapatılmaz).":
        " seconds the memory of idle background processes is compressed (nothing is closed).",
    "Otomatik RAM temizliği açık: her ": "Automatic RAM cleaning on: every ",
    "Otomatik RAM temizliği kapatıldı.": "Automatic RAM cleaning turned off.",
    " (ayar kaydedilemedi)": " (could not save the setting)", " saniye": " seconds",
    "Otomatik temizleme aralığı: her ": "Automatic cleaning interval: every ",
    "CPU önceliği": "CPU priority", "GPU önceliği": "GPU priority", " düşürüldü: ": " lowered: ",
    "Arka plan ": "Background ",
    "Ön plan uygulaması henüz bilinmiyor: önce oyuna/uygulamana geç, sonra K-Optimizer'a dönüp tekrar bas (hiçbir sürece dokunulmadı)":
        "The foreground app is not known yet: switch to your game or app first, then come back to K-Optimizer "
        "and press again (no process was touched)",
    "Ön planda GPU kullanan bir uygulama bulunamadı (oyundayken değil, K-Optimizer'a geçince son baktığın uygulamaya bakılır)":
        "No app using the GPU was found in the foreground (the app you were last in is checked when you switch "
        "to K-Optimizer, not while you are in the game)",
    "Ön plan GPU önceliği yükseltildi: ": "Foreground GPU priority raised: ",
    "bir sonraki açılışta yüksek performanslı GPU: ": "high-performance GPU on the next launch: ",
    "Geri açıldı: ": "Reopened: ", " uygulamanın GPU tercihi eski haline getirildi": " apps' GPU preference restored",
    " · açılamadı: ": " · could not reopen: ",
    "korumalı": "protected", "süreç değişmiş": "process changed", "süreç yok": "process gone",
    "başlatma komutu yok": "no start command", "zaten düşük": "already low", "zaten yüksek": "already high",
    "GPU önceliği okunamadı": "could not read the GPU priority",
    "çalışma kümeleri": "working sets", "sistem önbelleği": "system cache",
    "değiştirilmiş sayfalar": "modified pages", "düşük öncelikli bekleme listesi": "low-priority standby list",
    "bekleme listesi": "standby list", " MB RAM boşaldı (": " MB RAM freed (",
    " boşta süreç) · temizlenen: ": " idle processes) · cleaned: ", " · başarısız: ": " · failed: ",
    " · tam temizlik için yönetici olarak aç": " · open as administrator for a full clean",
    # product taglines
    "RAM, GPU ve CPU temizleyici": "RAM, GPU and CPU cleaner", "Oyun ve uygulama başlatıcı": "Game and app launcher",
    # update errors (updater.py)
    " (sahip/depo biçiminde olmalı)": " (must be owner/repo)", "Geçersiz GitHub deposu: ": "Invalid GitHub repository: ",
    "GitHub istek sınırına takıldı, biraz sonra yeniden dene.": "GitHub's rate limit was hit; try again in a moment.",
    "GitHub yanıtı alınamadı (": "No answer from GitHub (",
    "İnternete ulaşılamadı veya GitHub yanıt vermedi.": "No internet, or GitHub did not answer.",
    "Henüz yayınlanmış sürüm yok.": "No release has been published yet.",
    "İndirme adresi güvenli değil (yalnızca https GitHub adresleri kabul edilir).":
        "The download address is not safe (only https GitHub addresses are accepted).",
    "Bu sürümün SHA-256 doğrulama karması yok; güvenlik için kurulmadı.":
        "This release has no SHA-256 checksum; it was not installed, for safety.",
    "İndirme güvenli olmayan bir adrese yönlendirildi; durduruldu.": "The download was redirected to an unsafe address; stopped.",
    "İndirme tamamlanamadı (bağlantı veya disk hatası).": "The download could not finish (connection or disk error).",
    "İndirilen dosyanın SHA-256 karması uyuşmuyor; dosya silindi, kurulmadı.":
        "The downloaded file's SHA-256 does not match; it was deleted and not installed.",
    "K-Launcher kapanmadı. Çalışmanı kaydedip kapat, sonra güncellemeyi yeniden dene.":
        "K-Launcher did not close. Save your work and close it, then try the update again.",
    "Yeni K-Launcher başlatılamadı.": "The new K-Launcher could not be started.",
    "K-Optimizer kapanmadı. İşini kaydedip kapat, sonra güncellemeyi yeniden dene.":
        "K-Optimizer did not close. Save your work and close it, then try the update again.",
    "Mevcut K-Optimizer dosyası değiştirilemedi.": "The current K-Optimizer file could not be replaced.",
    "Yeni sürüm yerine konamadı; eski sürüm korundu.": "The new version could not be put in place; the old one was kept.",
    "K-Optimizer güncellendi ama yeniden başlatılamadı; elle aç.": "K-Optimizer was updated but could not restart; open it by hand.",
    "Çalışan K-Series dosyası değiştirilemedi.": "The running K-Series file could not be replaced.",
    "Yeni K-Series başlatılamadı; kapatıp elle aç.": "The new K-Series could not be started; close it and open it by hand.",
}


def _alt(key: str) -> str:
    """The key as a regex that cannot match in the middle of a longer word."""
    head = r"(?<!\w)" if key[0].isalnum() else ""
    tail = r"(?!\w)" if key[-1].isalnum() else ""
    return head + re.escape(key) + tail


_PATTERN = re.compile("|".join(_alt(k) for k in sorted(_PAIRS, key=len, reverse=True)))

_lang = "tr"


def system_default() -> str:
    try:
        code = (locale.getlocale()[0] or locale.getdefaultlocale()[0] or "")  # type: ignore[attr-defined]
    except (ValueError, AttributeError):
        code = ""
    return "tr" if code.lower().startswith(("tr", "turkish")) else "en"


def settings_path() -> Path:
    return Path(os.environ.get("APPDATA") or Path.home()) / "K-Series" / "settings.json"


def saved_language() -> str:
    """The language K-Series saved, else the system's."""
    try:
        code = json.loads(settings_path().read_text(encoding="utf-8")).get("language")
    except (OSError, ValueError, AttributeError):
        code = None
    return code if code in dict(LANGUAGES) else system_default()


def follow() -> bool:
    """Pick up a language change made in K-Series. True when the language changed."""
    before = _lang
    set_language(saved_language())
    return _lang != before


def set_language(code: str) -> None:
    global _lang
    _lang = code if code in dict(LANGUAGES) else "tr"


def current() -> str:
    return _lang


def t(text: str) -> str:
    """The text in the interface language (unknown text is returned as it is)."""
    if _lang == "tr" or not text:
        return text
    return _PATTERN.sub(lambda m: _PAIRS[m.group(0)], text)

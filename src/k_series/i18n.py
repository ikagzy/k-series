"""Turkish and English for K-Series. The source text is Turkish; `t()` swaps known phrases for English when the
interface language is English. Phrases are replaced longest first, so a long sentence wins over the words in it."""
import locale
import re

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
_ORDER = sorted(_PAIRS, key=len, reverse=True)
_PATTERN = re.compile("|".join(re.escape(k) for k in _ORDER))

_lang = "tr"


def system_default() -> str:
    try:
        code = (locale.getlocale()[0] or locale.getdefaultlocale()[0] or "")  # type: ignore[attr-defined]
    except (ValueError, AttributeError):
        code = ""
    return "tr" if code.lower().startswith(("tr", "turkish")) else "en"


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

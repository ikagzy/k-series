# K-Series — Tasarım Spec'i

Tarih: 2026-10-23

## Amaç

K-Launcher ve K-Optimizer'ı tek çatıda toplayan, SteelSeries GG gibi bir merkez uygulama. GG cihazları algılayıp kartlarda gösterir; K-Series kurulu K ürünlerini algılar, durumlarını gösterir, açar ve ortak ayarları (tema, hareket) yönetir.

**Kullanıcının söyledikleri:** tek çatı; K-Launcher ile aynı tasarım ve tema renkleri; tema ayarları doğrudan K-Launcher'dan alınacak; "SteelSeries'in klavye/mouse algılama driver'ı gibi".

## Kapsam

**Var:**
- Yan menülü tek pencere: Ana Sayfa, K-Optimizer, K-Launcher, Ayarlar.
- **Ürün algılama:** K-Launcher'ı bulur (çalışan süreç, kayıtlı yol, `%LOCALAPPDATA%\Programs\K-Launcher`, Program Files, masaüstü taraması), sürümünü exe'den okur, çalışıp çalışmadığını gösterir. K-Optimizer yerleşik modüldür.
- **K-Optimizer sayfası:** mevcut RAM/GPU/CPU göstergeleri, aynı mantık.
- **Ortak tema ayarları:** 7 K-Launcher paleti. Okuma ve yazma, K-Launcher'ın gerçek ayar klasörüne (`<KLauncher.exe klasörü>\Data\theme.txt`, `motion.txt`); eski sürümler için `%LOCALAPPDATA%\K-Launcher` ve `%APPDATA%\K-Launcher` yedek yollar. K-Series'te seçilen tema K-Launcher'ın bir sonraki açılışında geçerli olur.

**Yok:**
- K-Launcher arayüzünün kopyası veya içine gömülmesi (WPF şeffaf pencereler kırılgan). K-Launcher kendi penceresinde açılır.
- Oyun/uygulama tarama gibi K-Launcher özelliklerinin Python'da yeniden yazımı.
- K-Launcher'ın dil, parçacık, pencere solma ayarları.

## Düzeltilen varsayım

K-Optimizer şimdiye kadar temayı `%APPDATA%\K-Launcher\theme.txt` dosyasından okuyordu (`aurora`). Güncel K-Launcher ayarlarını exe'sinin yanındaki `Data` klasörüne yazıyor ve gerçek tema `amber-orange`. Okuma sırası artık: algılanan K-Launcher `Data` klasörü, `%LOCALAPPDATA%\K-Launcher`, `%APPDATA%\K-Launcher`.

## Mimari

Aynı depoda yeni paket `k_series`, `k_optimizer` modüllerini kullanır (tema, monitor, temizleyiciler). Ayrı exe: `K-Series.exe`.

- `k_optimizer/klauncher.py`: K-Launcher'ı bulma, ayar klasörleri, sürüm, çalışma durumu.
- `k_optimizer/theme.py`: paletler; ayarları algılanan K-Launcher klasöründen okur ve yazar.
- `k_optimizer/ui.py`: `OptimizerPanel` (bir Frame, her yerde kullanılabilir) ve ince `App` kabuğu.
- `k_series/products.py`: `Product` modeli ve algılama.
- `k_series/app.py`: pencere, yan menü, sayfalar.

## Güvenlik ve hata yönetimi

- Algılama arka plan iş parçacığında çalışır, arayüzü dondurmaz; bulunamayan ürün hata değil "Bulunamadı" durumudur.
- K-Launcher'ı yalnızca kullanıcı "Aç" dediğinde başlatır; hiçbir süreç otomatik kapatılmaz.
- Ayar yazma başarısız olursa (yetki, salt okunur) arayüzde söylenir, uygulama çökmez.
- Önizleme modu (`K_OPTIMIZER_PREVIEW=1`) tüm eylemleri kapatır.

## Test

Algılama ve tema yolları geçici klasörlerle test edilir; arayüz sayfaları elle ve ekran görüntüsüyle doğrulanır.

## Güncellemeler (GitHub Releases)

K-Series, K-Launcher ve K-Optimizer'ın güncellemelerini GitHub Releases'ten denetler ve kurar.

**Kaynak:** Her ürün için GitHub deposunun en son release'i (`/repos/{depo}/releases/latest`). Varsayılan depolar `ikagzy/k-launcher` ve `ikagzy/k-optimizer`; ayarlardan değiştirilebilir. Release henüz yoksa hata değil "yayın yok" durumudur.

**Varlıklar (asset):** K-Launcher için tek parça taşınabilir `KLauncher*.exe` (K-Launcher kendini kuran tek exe olarak dağıtılıyor); K-Optimizer için `K-Series*.exe` (K-Optimizer K-Series'in içinde yerleşiktir, bu yüzden K-Optimizer güncellemesi = K-Series güncellemesi).

**Güvenlik:**
- Yalnızca `https` ve GitHub alan adları (`github.com`, `*.githubusercontent.com`).
- Dosyanın SHA-256 karması zorunlu: release varlığının `digest` alanı veya yanındaki `<ad>.sha256` dosyası. Karma yoksa ya da uyuşmuyorsa indirilen dosya silinir ve kurulum yapılmaz.
- Kurulumdan önce kullanıcıdan onay alınır (sürümler ve notlar gösterilir). "Kendiliğinden kur" seçeneği varsayılan olarak kapalıdır.
- Çalışan K-Launcher zorla kapatılmaz: önce nazik kapatma istenir, kapanmazsa kullanıcıya söylenir.

**Kurulum:**
- K-Launcher: indirilen exe çalıştırılır; kendi başlatıcısı `%LOCALAPPDATA%\Programs\K-Launcher` içine kurar, yeniden açar ve taşınabilir kopyayı siler. Ayar (`Data`) klasörüne dokunulmaz.
- K-Series: çalışan exe yeniden adlandırılır (`.old`), yenisi yerine konur, başlatılır; `.old` sonraki açılışta silinir. Başarısızlıkta eski ad geri verilir.

**Test:** Ağ, dosya sistemi ve süreç işlemleri sahte nesnelerle test edilir; gerçek indirme yapılmaz.

## Güncelleme: K-Optimizer ayrı uygulama (2026-10-23)

Kullanıcı isteğiyle K-Optimizer K-Series'in içinden çıkarıldı. K-Series artık yalnızca bir merkez: K-Optimizer ve
K-Launcher iki ayrı ürün olarak algılanır (çalışan süreç, kayıtlı yol, K-Series'in yanındaki klasör,
`%LOCALAPPDATA%\Programs`, masaüstü taraması; yüzeysel kopya derin olandan önce gelir), "Aç" ile ayrı pencerede
açılır. Ürün kartlarında ve uygulama simgesinde K-Launcher'ın kendi hazır `ThemeIcons` simgeleri kullanılır (tema
başına bir `.ico`); kendi çizdiğim rozetler kaldırıldı. Ayarlar, tema ve hareket K-Launcher'la ortaktır.

Güncelleme akışları üçe çıktı: k-launcher, k-optimizer, k-series (her biri kendi `KLauncher*.exe`,
`K-Optimizer*.exe`, `K-Series*.exe` dosyası ve deposu). Kurulu olmayan K-Optimizer için "Yükle" sunulur; "Kendiliğinden
kur" yalnızca kurulu ürünleri günceller, ilk kurulumu hiçbir zaman kendiliğinden yapmaz.

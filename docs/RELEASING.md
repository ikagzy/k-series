# Yayınlama: GitHub'a ekle, etiketle, K-Series güncellesin

K-Series, ürünlerin en son **GitHub release**'ini denetler. Release'i elle hazırlamana gerek yok: kaynak kodu
GitHub'a koyup bir sürüm etiketi atınca GitHub Actions exe'yi senin yerine derler ve release'e ekler.

## Bir kerelik kurulum

**K-Optimizer / K-Series** (bu proje)
1. GitHub'da `k-optimizer` adında bir depo oluştur (başka ad istersen K-Series > Ayarlar > Güncellemeler'den
   "Değiştir" ile depoyu seç).
2. Bu klasör zaten bir git deposu. Uzak depoyu bağla ve it:
   ```
   git remote add origin https://github.com/ikagzy/k-series.git
   git push -u origin main
   ```
   `.github/workflows/release.yml` iş akışı depoyla birlikte gider.

**K-Launcher**
1. `docs/release-workflows/k-launcher-release.yml` dosyasını K-Launcher deposuna `.github/workflows/release.yml`
   olarak koy.
2. Dosyanın başındaki `CSPROJ` değerini, `KLauncher.csproj` o depoda hangi yoldaysa ona ayarla
   (depoda `Kagzy-Launcher-Source/` alt klasöründeyse `Kagzy-Launcher-Source/KLauncher.csproj`).

## Her yeni sürümde

```
git tag v1.1.0
git push origin v1.1.0
```

GitHub birkaç dakikada exe'yi derler, testleri çalıştırır (K-Series) ve release'i yayınlar. Etiket sürümü exe'nin
sürüm numarası olur (`v1.1.0` → `1.1.0`).

## K-Series'in beklediği dosyalar

K-Optimizer artık K-Series'in içinde değil, K-Launcher gibi ayrı bir uygulama. K-Series ikisini de algılar, "Aç"
ile açar, kurulu değilse ya da eskiyse GitHub'dan yükler/günceller.

| Ürün | Release dosyası | Kurulum |
|---|---|---|
| K-Launcher | `KLauncher.exe` (tek parça, self-contained) | K-Launcher'ın kendi kurulum mantığı: `%LOCALAPPDATA%\Programs\K-Launcher` |
| K-Optimizer | `K-Optimizer.exe` | Yerinde değiştirilir (eski kopya `.old`); yoksa `%LOCALAPPDATA%\Programs\K-Optimizer` |
| K-Series | `K-Series.exe` | Çalışan exe yeniden adlandırılır, yenisi yerine konur |

K-Optimizer ve K-Series aynı depodan (`ikagzy/k-series`) gelir; bir etiketle ikisinin exe'si de yayınlanır ve her
ürün kendi dosyasını seçer. Ayarlar'dan her ürünün deposunu ayrı seçebilirsin. Exe'lerin sürümü derleme sırasında
dosyaya gömülür (`tools/make_version.py`); K-Series kurulu K-Optimizer'ın sürümünü buradan okur.

Her dosyanın SHA-256 karması gerekir. GitHub bunu `digest` alanıyla kendisi üretir; iş akışları ayrıca
`<dosya>.sha256` da yükler. **Karması olmayan veya uyuşmayan dosya kurulmaz.**

## Güvenlik

- K-Series yalnızca `https` GitHub adreslerinden indirir, indirme yönlendirmesini de denetler.
- Kurulumdan önce onay sorar (sürümler ve notlar gösterilir). "Kendiliğinden kur" kapalı gelir.
- Açık olan K-Launcher zorla kapatılmaz; nazikçe kapanması istenir.
- İş akışları `actions/*` ve `softprops/action-gh-release` için ana sürüm etiketlerini kullanır. Daha sıkı
  güvenlik istersen bunları tam commit SHA'sına sabitle.

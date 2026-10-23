# K-Optimizer — Tasarım Spec'i

Tarih: 2026-10-23

## Amaç

Windows'ta RAM, CPU ve GPU'daki gereksiz yükü bulup kullanıcı onayıyla kaldıran, işlemleri geri alınabilir tutan bir masaüstü uygulaması. Oyunlarda ve diğer işlerde sistemin rahatlamasını sağlar.

**Başarı ölçütü:** Kullanıcı tek ekranda hangi süreçlerin CPU/RAM/GPU yediğini görür, güvenli olanları seçip kapatır, istediğinde hepsini geri açar. Sistem süreçlerine hiçbir zaman dokunulmaz.

## Kapsam

**Var:**
- Canlı CPU / RAM / GPU / VRAM izleme (genel ve süreç bazlı)
- Süreçleri risk seviyesine göre sınıflandırma
- Seçilen süreçleri kapatma ve geri açma
- NVIDIA, AMD ve Intel GPU desteği

**Yok (bilinçli olarak dışarıda):**
- Oyun tespiti ve Oyun Modu. Bunlar K-Launcher'a özeldir ([itzkagzy.itch.io/k-launcher](https://itzkagzy.itch.io/k-launcher)).
- Servis/kayıt defteri ayarları, disk temizliği, overclock, sıcaklık/fan sensörleri.

**Gelecek entegrasyon için tek kural:** Cleaner katmanı arayüzden bağımsız, içe aktarılabilir ve komut satırından çağrılabilir olur. K-Launcher ileride bu katmanı tetikleyebilir. Bunun için şimdi ek bir şey yazılmaz.

## Teknoloji

- Python 3.11+, `psutil`
- GPU: Windows performans sayaçları (PDH). `\GPU Engine(*)\Utilization Percentage`, `\GPU Process Memory(*)\Dedicated Usage`, `\GPU Adapter Memory(*)`. Sayaç adındaki `pid_NNN` ile süreç başına GPU yükü okunur. Üç üreticide de aynı çalışır.
- NVIDIA için isteğe bağlı `pynvml` (sıcaklık, güç). Yoksa uygulama normal çalışır.
- Arayüz: CustomTkinter
- Test: pytest
- Paketleme: PyInstaller ile .exe (sonraki adım)

## Bileşenler

Her bileşen tek bir iş yapar ve arayüzden bağımsız test edilir.

1. **monitor**: `snapshot()` çağrısı sistem toplamlarını ve süreç listesini (pid, ad, yol, CPU %, RAM, GPU %, VRAM) döndürür. GPU sayaçları okunamazsa GPU alanları `None` olur, hata fırlatmaz. Entegre ve ayrık GPU ayrı adaptör olarak listelenir.
2. **classifier**: Her sürece bir seviye verir.
   - `protected`: Windows sistem süreçleri, antivirüs, sürücüler, uygulamanın kendisi, kullanıcı oturumu için gerekli süreçler. Listede hiç görünmez, kapatılamaz.
   - `safe`: Bilinen arka plan uygulamaları (güncelleyiciler, launcher'lar, sohbet/bulut istemcileri). `data/known_apps.json` beyaz listesinden gelir.
   - `unknown`: Gösterilir, işaretlenebilir, varsayılan olarak seçili gelmez.
   Sınıflandırma ad ve dosya yoluna göre yapılır (imzalı yayıncı doğrulaması ilk sürümde yok). Emin olunamayan süreç `unknown` olur, asla `safe` olmaz.
3. **cleaner**: `close(processes)` önce süreci nazikçe kapatır (terminate), zaman aşımında zorla sonlandırır. Her kapatılan sürecin ad, yol ve komut satırını `session.json` kaydına yazar. `restore()` kayıttakileri yeniden başlatır. Korumalı bir süreç verilirse reddeder.
4. **ui**: Üç parça. *Canlı Yük* (toplam grafikler ve süreç tablosu), *Temizlik* (öneri listesi, seçim, "Kapat", "Geri Al"), durum çubuğu (GPU desteği, yetki uyarısı).

## Veri akışı

monitor → classifier → ui listesi → kullanıcı seçer → cleaner kapatır ve kaydeder → ui günceller. "Geri Al" kayıt dosyasından cleaner.restore() çağırır.

## Güvenlik ve hata yönetimi

- Korumalı süreç hem classifier'da hem cleaner'da ayrı ayrı engellenir (iki katmanlı).
- Kapatmadan önce her zaman kullanıcı onayı alınır; kaç süreç ve yaklaşık ne kadar RAM boşalacağı gösterilir.
- Yönetici izni olmadan çalışır. Erişim reddedilen süreçler atlanır ve "yetki gerekir" olarak işaretlenir.
- Geri açma, süreç artık başlatılamıyorsa hatayı listeler, diğerlerine devam eder.
- GPU sayaçları kullanılamıyorsa arayüz GPU sütununu "kullanılamıyor" gösterir.

## Test

- classifier: sahte süreç listeleriyle seviyelerin doğruluğu, bilinmeyenin asla `safe` çıkmaması.
- cleaner: sahte süreç nesneleriyle kapatma, kayıt ve geri açma; korumalı sürecin reddi. Gerçek süreç kapatılmaz.
- monitor: GPU sayaç çıktısı örnekleriyle ayrıştırma (`pid_NNN` eşleştirme, eksik sayaç durumu).
- Arayüz elle doğrulanır.

## Açık noktalar

Yok. Beyaz liste (`known_apps.json`) ilk sürümde küçük başlar, kullanıcı kendi eklemelerini yapabilir.

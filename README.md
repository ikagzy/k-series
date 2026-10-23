# K-Series

Windows için iki uygulama:

- **K-Optimizer**: RAM, CPU ve GPU yükünü azaltır. Hiçbir uygulamanı kapatmaz, yaptığı her değişiklik geri alınabilir.
- **K-Series**: K-Launcher ve K-Optimizer'ı tek yerden bulur, açar ve GitHub Releases üzerinden günceller. Tema ayarlarını K-Launcher ile paylaşır.

## Çalıştırma

```
pip install -r requirements.txt
set PYTHONPATH=src
python launcher.py            # K-Optimizer
python kseries_launcher.py    # K-Series
python -m pytest
```

## Yayınlama

Bkz. [docs/RELEASING.md](docs/RELEASING.md).

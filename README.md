# K-Series

Two apps for Windows:

- **K-Optimizer**: Reduces the load on RAM, GPU and CPU. Doesnt close any apps, if it does you can revert the changes.
- **K-Series**: It can find K-Launcher and K-Optimizer, can run and updates from GitHub releases. Shares the same Themes settings.

## Make it run

```
pip install -r requirements.txt
set PYTHONPATH=src
python launcher.py            # K-Optimizer
python kseries_launcher.py    # K-Series
python -m pytest
```

## Release

Bkz. [docs/RELEASING.md](docs/RELEASING.md).

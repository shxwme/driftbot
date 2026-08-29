# Drift Radar — personal edition

Lokalny monitor kalendarzy i publikacji driftingowych. Źródła są ręcznie kuratorowane w
`sources.yaml`, a poprzednie odczyty trafiają do `state.json`.

## Uruchomienie

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
py main.py --dry-run --bootstrap
```

Sekrety:

- `DISCORD_WEBHOOK_URL` — webhook Discorda;
- `YOUTUBE_API_KEY` — klucz YouTube Data API.

W PowerShell przed pełnym uruchomieniem ustaw je jednorazowo w bieżącej sesji:

```powershell
$env:DISCORD_WEBHOOK_URL = "..."
$env:YOUTUBE_API_KEY = "..."
& .\.venv\Scripts\python.exe main.py --bootstrap
```

Kanały YouTube wymagają klucza API; bez niego kalendarze nadal działają, a błędy kanałów są raportowane
bez usuwania poprawnego stanu kalendarzy.

Pierwsze właściwe uruchomienie wykonaj z `--bootstrap`, aby zasilić stan bez lawiny powiadomień.
Parser nie aktualizuje stanu źródła, jeśli pobranie lub parsowanie zakończy się błędem.
Do przebazowania istniejącego stanu bez wysyłania alertów służy `--no-notify`.
Źródła z `include_images: true` zapisują także adresy plakatów/kalendarzy obrazkowych. Ich zmiana jest
wykrywana, a workflow chmurowy automatycznie uruchamia Tesseract OCR i zapisuje odczytane daty.
Lokalnie wymagany jest zainstalowany program `tesseract`; jeśli go brakuje, źródło kończy się błędem
zamiast zapisać niepełne dane.

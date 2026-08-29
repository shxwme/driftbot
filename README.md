# Drift Radar — personal edition

Lokalny monitor kalendarzy i publikacji driftingowych. Źródła są ręcznie kuratorowane w
`sources.yaml`, a poprzednie odczyty trafiają do `state.json`.

## Co robi automatycznie

- co 5 minut sprawdza zaplanowane i trwające transmisje YouTube;
- około 10 minut przed startem wysyła czytelny alert Discord z bezpośrednim przyciskiem;
- po wykryciu statusu live może wysłać osobny alert `LIVE TERAZ`;
- pokazuje czas w `Europe/Warsaw`, względny czas Discorda oraz oznaczenie transmisji nocnych;
- trzy razy dziennie skanuje oficjalne kalendarze, w tym plakaty obsługiwane przez OCR;
- pomija zakończone transmisje i nie wysyła surowych dumpów danych.

## Uruchomienie

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
py main.py --dry-run --bootstrap --source-type all
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

## Tryby skanowania

```powershell
# Lekki polling transmisji
py main.py --source-type youtube

# Same strony kalendarzy i OCR
py main.py --source-type calendar

# Pełny przebieg
py main.py --source-type all
```

Ręczny digest można wysłać opcją `--digest-notification`. Alerty live nie wymagają ręcznego
uruchamiania — odpowiada za nie harmonogram GitHub Actions.

## Jakość i bezpieczeństwo

```powershell
pip install -r requirements-dev.txt
python -m unittest discover -s tests -p "test_*.py"
python -m ruff check . --exclude gitmeta
```

Sekrety muszą pozostać wyłącznie w GitHub Actions Secrets lub zmiennych środowiskowych. Repozytorium
nie zawiera klucza YouTube ani adresu webhooka. Dependabot raz w tygodniu sprawdza zależności Pythona
i używane akcje GitHub.

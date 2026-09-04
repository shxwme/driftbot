# Drift Radar

Samodzielna usługa Python → Discord. **Bez GitHub Actions.** GitHub przechowuje kod,
a program pracuje na osobnej maszynie Linux. Po wdrożeniu nie korzysta z komputera właściciela.

## Automatyczna praca

- YouTube co 5 minut, w niezależnym procesie od kalendarzy i OCR.
- Alert około 10 minut przed zaplanowanym live i osobny alert po wykryciu LIVE.
- Podsumowanie o 09:00 i 19:00 w Europe/Warsaw, bez ręcznej komendy.
- Kalendarze co 8 godzin; zmiany potwierdzonych przyszłych wydarzeń w jednym podsumowaniu.
- Fioletowe karty, przyciski prowadzące do transmisji, czas względny Discorda,
  oznaczenie **TEJ NOCY** i konkretne daty nocy z X na Y.
- Kanał organizatora nie jest przedstawiany jako potwierdzona transmisja.
- Brak starych surowych list. Zakończone wydarzenia i transmisje są pomijane.

To usługa wysyłająca webhooki, a nie aplikacja Discord z komendami slash.
Przyciski są linkami; nie wymagają połączenia Discord Gateway.
Alerty zależą od dostępności YouTube/Discorda i hosta. Polling nie gwarantuje
dokładnej sekundy ani odnalezienia każdej transmisji (zwłaszcza niepublicznej).

## Wiarygodność danych

Każdy obsługiwany kalendarz ma własny odczyt kart, tabel lub sekcji.
Numer rundy, termin, miejsce i źródło pochodzą z tego samego elementu.
Dat publikacji newsów ani archiwalnych dat nie zamieniamy na tegoroczne zawody.
Niejednoznaczne wpisy nie są publikowane; zmiana rozpoznawanego układu wywołuje błąd źródła.

Japonia: FDJ, FDJ2, FDJ3, D1GP, D1 LIGHTS oraz sześć regionów D1 NEXT są rozdzielone.
Kalendarz D1 może obejmować treningi i kilka rund we wspólnym weekendzie — UI to opisuje.
Dokładna godzina oglądania pochodzi z API transmisji, nie z daty weekendu.

OCR działa lokalnie na serwerze, bez płatnego API: Tesseract w dwóch ustawieniach segmentacji.
Dla źródeł obrazkowych publikowane są tylko zgodne odczyty z obu przebiegów,
bez zgadywania numeru rundy. To filtr ostrożności, **nie gwarancja bezbłędności OCR**.
Drift Kings porównuje plakat z wydzielonym opisem kalendarza; różnica zakresów
jest zapisana diagnostycznie, a publikowany zakres pochodzi z opisu wydarzenia.
Jego awaryjny odczyt przez r.jina.ai jest kopią strony, nie drugim niezależnym potwierdzeniem.

Stan testów i pokrycie: [raport walidacji](research/validation-2026-09-05.md).
Dalsze źródła: [research serii](research/series-2026-09-05.md).
Nie deklarujemy pokrycia wszystkich lig na świecie.

## Uruchomienie na serwerze

Wymagany Linux z Docker Engine i Compose. Sugerowany wariant: Oracle Always Free VM
z obrazem Ubuntu, w darmowym limicie. Dostępność VM i ciągłość usługi nie są gwarantowane.
Szczegóły alternatyw i ryzyka kosztów: [hosting](research/hosting-2026-09-05.md).

Na serwerze sklonuj repozytorium. Utwórz plik `.env` na podstawie `.env.example`
i wpisz dwa sekrety: `YOUTUBE_API_KEY` (Data API v3) oraz `DISCORD_WEBHOOK_URL`.
Nie wklejaj sekretów do repozytorium, logów ani publicznych wiadomości.
Sekretów GitHub nie da się odczytać z powrotem przy migracji.
Klucze ujawnione w rozmowie warto wcześniej wymienić.

```sh
docker compose build
# Kontrola pobierania bez Discorda i zapisów stanu:
docker compose run --rm driftbot python service.py --once --dry-run
# Start w tle; pierwszy odczyt kalendarzy bez zalewu powiadomień:
docker compose up -d
docker compose ps
docker compose logs --tail=80 driftbot
```

Wolumen `drift-data` przechowuje kalendarze, dane YouTube, limity i wysłane alerty.
Nie usuwaj go podczas aktualizacji. Nie uruchamiaj drugiej kopii na innym wolumenie:
lokalna blokada chroni tylko procesy używające tego samego dysku.
Aktualizacja: `git pull --ff-only`, potem `docker compose up -d --build`.
Przed aktualizacją i okresowo wykonuj kopię wolumenu poza VM.
Obraz działa jako użytkownik bez uprawnień root, nie wystawia portów, ma rotację logów.

Docker wznawia proces po awarii, o ile działa sam host i usługa Docker.
Healthcheck sprawdza świeżość obu procesów, ale status unhealthy sam nie restartuje kontenera.
Pojedyncze źródło może zawieść przy zdrowym procesie — szczegóły są w `source_health`
w plikach stanu. Nie są wymagane testy jednostkowe przy każdym produkcyjnym odczycie.

**Stan migracji 2026-09-05:** harmonogram GitHub wyłączony, workflow usunięty.
Nowego hosta jeszcze nie skonfigurowano. Do jego uruchomienia nie ma automatycznych powiadomień.
Kontenera nie zbudowano lokalnie (brak Dockera); wymagany test na docelowym serwerze.

## Trwałość i limity

Osobne pliki `calendar.json`, `youtube.json`, `digest.json` i health w katalogu danych.
Zapis jest atomowy. Awaria źródła nie kasuje ostatniego odczytu; podsumowania pomijają
nieświeże lub nieudane odczyty. Oczekująca aktualizacja kalendarza jest ponawiana
z aktualnymi danymi. Przy utracie odpowiedzi Discorda po przyjęciu wiadomości
możliwy jest duplikat — webhook nie zapewnia exactly-once.

YouTube: lista uploads (50 najnowszych) + paczki videos po 50; zapamiętujemy
wcześniej wykryte zaplanowane i trwające live oraz identyfikator playlisty.
Bez kosztownego search.list. Pięć aktywnych kanałów to zwykle około 2880 jednostek/dobę
plus pierwsze rozpoznanie kanałów i dodatkowe paczki śledzonych filmów.
Lokalny budżet domyślnie 8500 resetuje się o północy czasu Pacific.
To licznik tej instalacji, nie zużycie całego projektu Google; awaria przed zapisem
może zgubić ostatnie naliczenia. Nie stanowi blokady naliczania kosztów hostingu.

## Testy lokalne

Python 3.12+, Tesseract w PATH, strefy czasowe i zależności z repozytorium:

Na Windows wykrywana jest też standardowa instalacja Tesseract-OCR w Program Files.
Niestandardową lokalizację można podać przez zmienną `TESSERACT_CMD`.

```sh
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
python -m ruff check . --exclude gitmeta
python main.py --source-type calendar --bootstrap --no-notify
python tests/check_dates.py
```

Ostatnia kontrola zwraca 2 przy źródłach bez zweryfikowanych dat — nie oznacza to,
że należy je zgadywać. Ręczny odczyt zapisuje `data/state.json`; demon używa własnych,
oddzielnych plików. Historyczny główny `state.json` nie jest już wersjonowany ani używany.

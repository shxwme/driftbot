# Render Free + Supabase Free + cron-job.org

To wariant wykonywania zleconych zadań, nie płatny Background Worker.
Nie wymaga GitHub Actions ani stale włączonego komputera właściciela.

## Bezpieczeństwo i stan przygotowań

Migracja `supabase/migrations/202609050001_drift_runtime.sql` tworzy jedną tabelę
stanu z RLS i sześć funkcji. Dostęp mają wyłącznie uprawnienia serwerowe, nie anon
ani authenticated. Nie przechowuj kluczy API w tej tabeli.

Migrację wykonano 2026-09-05 w projekcie qbrpnutjhvgajjzqjcxr. Test na rzeczywistym
Postgresie potwierdził blokowanie drugiego właściciela, odrzucenie zapisu przez
starego właściciela, poprawne zakończenie i ponowne przejęcie. Testy wycofano
transakcyjnie; pozostało zero rekordów testowych. RLS i blokady anon potwierdzone.
38 testów Pythona przeszło. Pełne wdrożenie i test Discorda pozostają do wykonania.

## Render

Użyj `render.yaml` lub utwórz Web Service z publicznego repozytorium shxwme/driftbot:

- runtime Docker, Dockerfile w katalogu głównym;
- **Instance Type: Free**, region Frankfurt;
- Docker Command: `python cloud_web.py` (nie domyślny `service.py`);
- Health Check Path: `/healthz`;
- Auto Deploy: Off — aktualizacje świadomie po testach;
- bez dysku, płatnej bazy Render, Background Workera i dodatkowych instancji.

Zmienne środowiskowe wyłącznie w panelu Render:

| Nazwa | Wartość |
|---|---|
| SUPABASE_URL | `https://qbrpnutjhvgajjzqjcxr.supabase.co` |
| SUPABASE_SECRET_KEY | serwerowy `sb_secret_...` lub istniejący service_role JWT |
| CRON_SECRET | losowy sekret, minimum 32 znaki, wspólny tylko z cron-job.org |
| YOUTUBE_API_KEY | klucz YouTube Data API v3 |
| DISCORD_WEBHOOK_URL | aktualny webhook kanału |
| YOUTUBE_DAILY_BUDGET | `8500` |

Klucz serwerowy Supabase ma szerokie uprawnienia do projektu: używaj projektu
dedykowanego botowi. Nie zapisuj kluczy w repozytorium, URL-ach ani logach.
Nie można odzyskać wartości dawnych sekretów GitHub poprzez GitHub API.
Sekrety ujawnione wcześniej w wiadomościach zaleca się wymienić.

## cron-job.org

Po udanym deployu użyj rzeczywistego adresu HTTPS nadanego przez Render.
Każde zadanie: POST, nagłówek `Authorization: Bearer <CRON_SECRET>`, bez treści.
Nie umieszczaj tokena w adresie URL. Ustaw trzy zadania:

| Ścieżka | Częstotliwość | Praca |
|---|---|---|
| `/jobs/youtube` | co 5 minut | wszystkie aktywne kanały i alerty live |
| `/jobs/calendar` | co 2 minuty | jeden najdawniej sprawdzany kalendarz, jeśli wymaga odświeżenia |
| `/jobs/digest` | co 5 minut | podsumowanie raz o 09 i raz o 19 w Europe/Warsaw |

Kalendarze odświeżane są po 8 godzinach, błędne źródło ponawiane po 30 minutach.
Pierwsze przejście 29 źródeł przy rytmie 2 minuty trwa około godziny, dłużej przy
awariach. Brak przyszłych zweryfikowanych terminów nie jest zastępowany zgadywaniem.

Odpowiedź 202 oznacza **przyjęcie**, nie ukończenie. Stan ostatnich prac jest
dostępny pod `GET /status` z tym samym nagłówkiem. Sprawdzaj `last_ok`,
`last_finished` oraz świeżość; /healthz sprawdza tylko gotowość procesu/konfiguracji.
Po pierwszym uruchomieniu sprawdź status wszystkich trzech prac, logi Rendera,
stan w Supabase oraz rzeczywiste dostarczenie alertu na Discorda.

## Limity i awarie

Zadanie jest rezerwowane atomowo w bazie przed odpowiedzią 202. Usługa wykonuje je
w ograniczonym czasowo podprocesie. Ponowienie tego samego wywołania nie uruchamia
drugiej kopii. Po utracie procesu blokada wygasa: do 330 sekund dla YouTube,
570 dla kalendarza, 180 dla podsumowania. Kolejny cron może wtedy ponowić pracę.
Stan i wysłane alerty są zapisywane w Supabase, bez awaryjnego zapisu tylko lokalnie.
Wygaśnięty właściciel nie może zapisywać; przed wysyłką sprawdzana jest blokada.
Utrata odpowiedzi Discorda lub śmierć procesu między wysyłką a zapisem może mimo
tego powodować duplikat — nie obiecujemy exactly-once.

Zewnętrzne wywołania wykonują faktyczną pracę, nie sam keepalive. Start uśpionego
Rendera może przekroczyć limit 30 sekund cron-job.org; kolejne wywołanie ponawia
kontrolę. Dłuższy OCR odbywa się po przyjęciu zadania, ale restart Rendera może
go przerwać. Wynik nie jest bezwarunkową gwarancją punktualnych alertów.

Render Free ma 750 godzin współdzielonych przez workspace. Inna stale działająca
darmowa usługa w tym samym workspace może wyczerpać wspólny limit. Przy braku karty
wyczerpanie niektórych limitów skutkuje zawieszeniem. Jeśli karta jest już dodana,
sprawdź limity transferu/buildów i ustawienia wydatków przed startem — sam napis
Free przy instancji nie jest gwarancją braku wszystkich opłat dodatkowych.
Nie włączaj płatnych planów. Supabase Free: 500 MB bazy i 5 GB transferu;
stan jest przycinany do zdarzeń i niezbędnych metadanych, bez całych stron HTML.

Źródła: [Render Free](https://render.com/docs/free),
[Supabase](https://supabase.com/pricing), [cron-job FAQ](https://cron-job.org/en/faq/).

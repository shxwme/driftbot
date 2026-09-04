# Weryfikacja migracji — 5 września 2026

## Wynik i granice testu

Pełny rzeczywisty odczyt `main.py --source-type calendar --bootstrap --no-notify`:
29 źródeł kalendarzowych, 0 błędów pobierania/parsowania, 128 rekordów w 26 źródłach.
To rekordy wszystkich znalezionych sezonowych terminów, nie 128 przyszłych zawodów.
Formatter odrzuca zakończone wydarzenia. Są to potwierdzone odczyty oficjalnych stron,
nie niezależna gwarancja, że organizator nie zmieni lub błędnie nie opisze terminu.

Następnie uruchomiono skończony cykl całej usługi
`service.py --once --dry-run --source-type calendar`: 29 źródeł, 0 błędów,
kod zakończenia 0. Wcześniejszy test wykrył brak Tesseracta w PATH; dodano
wykrywanie standardowej instalacji Windows i opcję TESSERACT_CMD.
Po testach nie pozostawiono lokalnego bota działającego w tle.

27 testów automatycznych przeszło; Ruff bez uwag. Testy obejmują fałszywy dzień z
numeru rundy, jawny rok 2025 obok sezonu 2026, rozdzielenie kategorii FDJ, japońskie
zakresy i brak końcowego znaku 日, różne rundy jednego dnia, północ UTC→Warszawa,
wykluczanie zakończonych live, deduplikację po ponownym uruchomieniu,
ponowne powiadomienie po przejściu upcoming→live, błąd transportu i atomowy zapis,
limity długości Discorda, żądanie potwierdzenia dostarczenia i komponentów linkowych.

Nie wysyłano testowych wiadomości na kanał. Produkcyjne API YouTube nie zostało
ponownie sprawdzone kluczem — jego wywołania testowano z kontrolowanymi odpowiedziami.
Docker nie jest zainstalowany lokalnie: build i start kontenera wymagają walidacji
na docelowym hoście. Nie uruchomiono nowej usługi w chmurze.

## Sprawdzone przykłady

| Źródło | Odczyt / kontrola |
|---|---|
| [Drift Masters](https://dm.gp/seasons/drift-masters-2026/) | 7 rund; finał Runda 7: **11–12.09.2026**, nie 7 września |
| [FDJ / FDJ2 / FDJ3](https://formulad.jp/) | po 6 terminów; FDJ R5 5–6.09, FDJ2 R5 12–13.09, FDJ3 R4 20.09 |
| [D1GP](https://d1gp.co.jp/category/gp/2026-d1gp/) | 5 wspólnych weekendów rund; zakres obejmuje treningi |
| [D1 LIGHTS](https://d1gp.co.jp/category/lights/2026-d1-lights/) | 6 weekendów; grudzień 12–13.12, bez zgadywania rozdziału sesji |
| [D1 NEXT](https://d1gp.co.jp/category/d1div/2026-next/) | 6 regionów: 2+2+5+2+5+2 terminy |
| [Czech PRO / PRO2](https://www.drifting.cz/kalendar/) | po 6 terminów, osobne tabele klas; zawierają także oznaczone treningi |
| [Drift SM Finland](https://driftsm.fi/osakilpailut/) | PRO i PRO2 po 4; zakres 31.07–01.08 prawidłowo przekracza miesiąc |
| [DMCC](https://dmcc-series.com/calendrier/) | 5 rund; finał 5.09.2026 |
| [Rumunia FRAS](https://fras.ro/sport/drift/) | po 5 w PRO/Semi-PRO oraz OPEN/STREET; różne finały 3–4 i 24–25.10 |
| [Drift Kings](https://driftkings.com/dk26/) | 8 wpisów z treningiem i eventem specjalnym; opis październikowego weekendu 2–4.10 |
| [D1NZ](https://motorsport.org.nz/championships/d1nz/) | listopad 2025 zachowany jako 2025, nie przeniesiony do przyszłości |

Drift Kings: główna strona nie udostępniła rozpoznanego kalendarza w pierwszym
odczycie. Parser użył tekstowej kopii r.jina.ai strony organizatora; zapisuje
`retrieved_url`. OCR przetworzył plakat automatycznie. Zgodność jest częściowa:
plakat rozdziela 2–3.10 i 4.10, opis daje wspólny weekend. Ta różnica nie jest
ukrywana jako pełne potwierdzenie OCR. Publikowany jest opisany wspólny zakres.

## Źródła bez publikowanych dat

- PDS: odczytano cztery plakaty, ale dwa przebiegi OCR nie uzgodniły terminów.
  Brak automatycznego dopisywania cyfr lub zgadywania dat. Potrzebny lepszy odczyt obrazu.
- Baltic / Latvia: źródło wymaga adaptera oficjalnego arkusza, zamiast czytania samej otoczki HTML.
- Irish Drift Series: brak zatwierdzonego odczytu aktualnego kalendarza. Archiwum nie jest sezonem bieżącym.

Odkryte, ale **jeszcze nie zintegrowane**:

- [EDS / Ebisu Drift Series — Japonia](https://www.ebisu-circuit.com/race-event/2026/eds/youko2026-English.pdf):
  oficjalny PDF 2026 rozdziela 200/280 i Challenge oraz treningi. Wymaga adaptera PDF;
  nie należy łączyć dni zgłoszeń z datami zawodów. Ostatnia runda klas 200/280: 1.11,
  Challenge: 3.11; dni treningowe osobno.
- [MSC Challenge](https://msccha.jp/): widoczny kalendarz 2022; nie zweryfikowano 2026.
- [Danish Drift](https://danishdrift.dk/en/kalender/): kalendarz dynamicznie pobierany z Google Sheets.
- [Szwecja — SBF](https://www.sbf.se/sportgrenar/drifting/tavlingar-drifting-2026):
  kalendarz federacji do rozdzielenia na SM/JSM/RM.
- [Drift Spain — RFEDA](https://calendarios.rfeda.es/drift-spain/c/0):
  strukturalny kalendarz osadzony w stronie; daty całodniowe nie są godzinami live.

## Infrastruktura

GitHub workflow Drift Radar check jest wyłączony i usunięty z kodu. Historyczny
`state.json` usunięto wyłącznie z wersjonowania; lokalna kopia i historia Git pozostają.
Nie ruszano niepowiązanego folderu `assets`.

Nowa usługa ma niezależny polling YouTube i kalendarzy/OCR, prywatny trwały wolumen,
blokadę drugiej instancji na tym samym wolumenie (Linux), rotowane logi i healthcheck.
Nie wymaga otwarcia portów. Brak hostingu oznacza obecnie przerwę w powiadomieniach.

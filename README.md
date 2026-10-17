# GreenCraft v2

Automatycznie zarządzany, prywatnie projektowany modpack do normalnego grania.

## Architektura

- Prism Launcher
- Fabric
- packwiz / packwiz-installer
- `stable/` = jedyna wersja używana przez normalnego gracza
- `candidate/` = aktualizacje modów, konfiguracji lub Minecrafta w trakcie walidacji
- GitHub-hosted CI = zależności + dedicated-server smoke test
- lokalny RTX 4070 Ti validator = test Iris/shadera w prawdziwym renderingu

## Ważne

Repo może być publiczne, bo nie zawiera sekretów ani danych gracza.
Nie podpinaj do niego self-hosted GitHub Runnera. GPU test działa lokalnie przez `scripts/gpu_validate.ps1`.

`Distant Horizons` jest wyłączony w baseline v2.0 i może wrócić dopiero jako osobno zatwierdzony moduł.

Normalny klient czyta wyłącznie:

`stable/pack.toml`

## Automatyczne aktualizacje

Co sześć godzin `GreenCraft Candidate` rozwiązuje aktualne wersje modów,
zależności, shadera, tekstur i Fabric dla Minecrafta używanego przez stable.
Jeśli nie ma takich zmian, sprawdza najnowsze wydanie Minecrafta. Składniki
obecne w stable nie mogą zniknąć po cichu. Rozjazd zależności, brak zgodnego
wydania albo błąd API zatrzymuje publikację i uruchamia istniejący raport błędu.

Zmiana zawartości automatycznie zwiększa numer poprawki GreenCraft, np.
`26.3-2.0.1` → `26.3-2.0.2`. Brak zmian nie tworzy nowej wersji i nie resetuje
czasu oczekiwania ani wyniku testu istniejącego kandydata. `policy.pack_version`
jest początkowym numerem dla samodzielnego buildera; automat wylicza numer
z opublikowanego stable i poprzedniego candidate.

`greencraft-release.json` jest osobnym dokumentem stanu. Launcher lub monitor
może czytać go spod `stable/greencraft-release.json`, ale Packwiz nie instaluje
go i nie wymaga dla niego hasha. Wszystkie faktycznie instalowane pliki nadal
mają sprawdzane sumy kontrolne. Usunięcie dawnej lokalnej kopii tego JSON-a
przez Packwiz podczas migracji jest oczekiwane; źródłem stanu pozostaje repo.

CI sprawdza manifest, kompletność indeksu, metadane Modrinth, zależności i sumy
kontrolne pobranych plików, także tych przeznaczonych tylko dla klienta. Następnie
uruchamia serwer z przypiętą wersją Fabric. Dopiero komplet tych kontroli nadaje
status `READY_FOR_GPU`. Wyniki są powiązane z sumą kontrolną konkretnej paczki.

Zachowany jest test renderowania na prawdziwym GPU: uruchom istniejący skrót
`GreenCraft GPU Test` lub `scripts/gpu_validate.ps1` (Python 3.11+). Walidator
testuje adres konkretnego commita, a po sukcesie archiwizuje poprzednie stable
i publikuje przetestowaną paczkę. Jeśli repo zmieni się podczas testu, publikacja
zostaje zatrzymana. Nie ma wymuszonego nadpisywania historii.

**Publikacja stable nadal wymaga tego testu GPU.** GitHub-hosted CI sprawdza
automatycznie pobieranie, zgodność deklarowaną przez autorów i start serwera;
nie potwierdza działania Iris ani kompilacji shadera na RTX 4070 Ti.

Pliki `options.txt` i `config/iris.properties` nadal mają `preserve = true`,
więc główna instancja zachowuje ustawienia gracza. Ustawienia dedykowanej
instancji testowej są odświeżane z kandydata, żeby test używał jego plików grafiki.
Jeśli aktualizacja zmienia nazwę ZIP-a shadera lub tekstur, w głównej instancji
może być potrzebne ponowne wybranie paczki w menu — repo nie zawiera launchera,
który mógłby bezpiecznie migrować osobiste ustawienia gracza.

## Sprawdzanie zmian

```text
python -m unittest discover -s tests -v
python scripts/build_pack.py --self-test
python scripts/validate_pack.py --folder stable
python scripts/validate_pack.py --folder candidate
python scripts/validate_pack.py --folder stable --online
```

Workflow `GreenCraft Validation` wykonuje te kontrole dla PR, buduje świeżą
paczkę dla bieżącego Minecrafta i uruchamia test serwera. Nie publikuje zmian.
Archiwalne wydania są historycznymi migawkami i nie są modyfikowane migracją.

Opis decyzji i plan naprawy: [docs/updater-design.md](docs/updater-design.md).
Format indeksu: [dokumentacja Packwiz](https://packwiz.infra.link/reference/pack-format/index-toml/).
Metadane zgodności: [Modrinth API](https://docs.modrinth.com/api/operations/getversion/).

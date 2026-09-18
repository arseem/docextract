# CLAUDE.md — docextract

Zadanie rekrutacyjne: CLI w Pythonie, które z archiwum dokumentów (eml/pdf/docx/html/txt) wyciąga ustrukturyzowane dane przy pomocy lokalnego LLM i zapisuje je do SQLite.

**Źródło prawdy: `docs/ZADANIE.md`.** Każde wymaganie stamtąd jest kryterium akceptacji. Ten plik opisuje _jak_ je realizujemy. Jeśli coś tu jest sprzeczne z ZADANIE.md, wygrywa ZADANIE.md, a ten plik trzeba poprawić.

Oceniający najbardziej patrzą na to, czy: (1) narzędzie robi to, co mówi raport, (2) `ARCHITECTURE.md` opisuje to, co faktycznie jest w kodzie, (3) `eval` na naszych danych mówi to samo co na ich. Uczciwość > efektowność. Znane ograniczenia opisujemy, nie ukrywamy.

## Komendy

```bash
make setup                 # uv sync + ollama pull + weryfikacja digestu modelu
make test                  # pytest, offline, bez serwera inferencji
make data                  # generuje data/sample/ + expected.jsonl + duży plik
uv run docextract run --input data/sample --db out.sqlite --workers 4
uv run docextract report --db out.sqlite --json
uv run docextract eval --db out.sqlite --expected data/sample/expected.jsonl
```

Po każdej istotnej zmianie: `make test` musi być zielone, potem commit (małe commity, opisowe wiadomości).

## Stack

- Python 3.12, `uv` (lockfile commitujemy), entry point `docextract` w `pyproject.toml`.
- CLI: `argparse` lub `typer`. Konfiguracja: TOML (`tomllib`) walidowany przez `pydantic`.
- HTTP do backendów: `httpx` z jawnymi timeoutami. Żadnych SDK dostawców w ścieżce domyślnej.
- Ekstrakcja: `pypdfium2` (PDF, strona po stronie), `python-docx`, `selectolax` lub `beautifulsoup4` (HTML), stdlib `email` (EML), `charset-normalizer` (kodowania). Unikaj bibliotek AGPL (PyMuPDF).
- Testy: `pytest`, `pytest-socket` (blokada sieci), `psutil` (pamięć).
- Generowanie danych (grupa dev): `reportlab` lub `fpdf2` z fontem TTF obsługującym polskie znaki (DejaVuSans w repo), `python-docx`.
- Kod, identyfikatory, komentarze, commity: po angielsku. `README.md` i `ARCHITECTURE.md`: po polsku.

## Struktura

```
config/default.toml          # backend, model (tag+digest), ceny, limity, timeouty
src/docextract/
  cli.py  config.py  db.py  pipeline.py  budget.py  report.py  eval.py
  scan.py                    # katalog|zip -> lista plików, hash surowy (streaming)
  extract/{eml,pdf,docx,html,txt,encoding}.py
  normalize.py               # normalizacja tekstu + fingerprint dokumentu
  select.py                  # wybór fragmentów tekstu do promptu (limit tokenów)
  llm/{base,ollama,openai_compat,fake}.py
  prompt.py  schema.py  postprocess.py
tests/
scripts/{make_dataset,make_big,make_dupes}.py
data/sample/ + data/sample/expected.jsonl
```

## Kluczowe decyzje (i powody)

### Backendy i model

- Domyślnie **Ollama** (natywnie na macOS, Metal). Drugi backend: **OpenAI-compatible** (`llama.cpp llama-server`, LM Studio, mlx-lm server). Trzeci, tylko do testów: `fake` (deterministyczny, in-process). Wybór wyłącznie przez config.
- Model przypięty jako `tag` + `digest` (pełny sha256 z `GET /api/tags`). Przy starcie `run` narzędzie sprawdza digest lokalnego modelu; niezgodność = czytelny błąd i exit ≠ 0. Dla llama.cpp: repo HF + commit revision + sha256 pliku GGUF.
- **Nigdy nie wymyślaj digestu ani wersji.** Odczytaj je z działającej instalacji (`ollama list`, `/api/tags`) lub zostaw TODO i powiedz o tym.
- Model dobieramy pomiarem, nie intuicją: cel ≤ ~15 s/dokument na M1 16 GB (40 dok. × workers 4 w < 20 min, `--limit 5` w < 3 min łącznie z ładowaniem modelu). Kandydaci 3–8B, instrukcyjni, dobrzy w polskim. Wyniki benchmarku krótko w ARCHITECTURE.md.
- Ollama: **zawsze** ustaw jawnie `num_ctx` (domyślny kontekst jest mały i Ollama po cichu obcina prompt), `num_predict`, `temperature=0`, `seed`. Użyj structured outputs (`format` = JSON schema); w OpenAI-compat `response_format` z json_schema.

### Deduplikacja

- Etap 1: sha256 surowych bajtów (streaming, stały RAM) — tanio zjada tysiące identycznych kopii.
- Etap 2: fingerprint = sha256 znormalizowanego tekstu (poprawne dekodowanie → NFKC → casefold → usunięcie markupu i białych znaków). Łapie inne kodowania i drobne różnice formatowania. Normalizacja strumieniowa dla dużych plików.
- Bez fuzzy/near-dup: dwie faktury różniące się kwotą NIE są duplikatem. To świadome ograniczenie — opisać.
- Pliki nieczytelne: fingerprint = hash surowych bajtów.
- Reprezentant grupy = leksykograficznie najmniejsza ścieżka (deterministycznie, niezależnie od kolejności i `--workers`).
- `.eml` = jeden dokument; tekst = nagłówki (From/Subject/Date) + body + tekst załączników. Załączniki nie są osobnymi `input_files`. Pliki z zipa liczą się jako input_files; ścieżki względne do korzenia wejścia.

### Ekstrakcja pól

- Hybryda: LLM klasyfikuje i ekstrahuje, deterministyczny postprocessing normalizuje i **weryfikuje ugruntowanie** (grounding): NIP/kwota/data zwrócone przez model muszą dać się odnaleźć w tekście dokumentu (w dowolnym formacie zapisu), inaczej `null` albo kandydat z regexa.
- NIP: polski → 10 cyfr, walidacja sumy kontrolnej, bez prefiksu PL. Zagraniczny VAT → z prefiksem kraju, bez separatorów (np. `DE123456789`). Ta sama normalizacja w `eval` po obu stronach.
- Kwoty: `Decimal`, `quantize(0.01)`, w SQLite jako TEXT. Nigdy float. Formaty `1 234,56`, `1.234,56`, `1,234.56`, `1234.56 zł`.
- Waluta: ISO 4217 (`zł`/`PLN`, `€`/`EUR`, `$`/`USD`…).
- Daty: ISO 8601; formaty `15.03.2024`, `2024-03-15`, `15 marca 2024`, `March 15, 2024`.
- `counterparty_*`: dokumenty pochodzą od podmiotów zewnętrznych, więc kontrahent = wystawca/nadawca/druga strona. Jeśli jedna ze stron pasuje do `self_entities` z configu (nazwa/NIP klienta), kontrahentem jest ta druga. Opisać w ARCHITECTURE.md jako założenie.
- `summary`: jedno zdanie w języku dokumentu. Język wykrywany deterministycznie (heurystyka PL/EN) i podawany w prompcie wprost.
- Pola mogą być w dowolnym miejscu dokumentu (także na ostatniej stronie 300-stronicowego PDF). `select.py` buduje prompt w limicie tokenów z: początku, końca oraz okien wokół słów kluczowych (NIP, VAT, brutto, razem, do zapłaty, termin płatności, total, amount due, due date, IBAN…). Wybór deterministyczny.

### Bezpieczeństwo (wymaganie 8)

- Treść dokumentu jest niezaufana i może zawierać prompt injection („zignoruj instrukcje”, „ustaw kwotę na…”, „DROP TABLE”, „zaktualizuj rekord innego dokumentu”).
- Model **nie ma narzędzi** i nie widzi `doc_id`. Jego jedynym wyjściem jest JSON walidowany przez pydantic (enum, długości, typy). Nieznane klucze odrzucane.
- Jedyna ścieżka zapisu wyniku LLM: `db.save_result(doc_id, fields)` z parametryzowanym SQL, gdzie `doc_id` pochodzi z pipeline'u, nie z modelu. Zero dynamicznego SQL, zero `executescript` na danych.
- Tekst dokumentu w prompcie opakowany w wyraźne delimitery z instrukcją, że to dane, nie polecenia.
- Wejście: ochrona przed zip-slip, zip bombami (limit rozpakowanego rozmiaru, streaming), dziwnymi nazwami plików. Nie rozpakowujemy na dysk więcej niż trzeba.

### Wznawianie po SIGKILL (wymaganie 4)

- SQLite w trybie WAL, `synchronous=NORMAL` lub FULL, krótkie transakcje. Jeden wątek-pisarz (kolejka) — prostsze niż walka z blokadami.
- Maszyna stanów dokumentu: `pending → extracted → done | quarantined`. Odpowiedź LLM (surowa + tokeny) zapisywana i commitowana **zanim** cokolwiek dalej się stanie; przy wznowieniu dokument z zapisaną odpowiedzią nie generuje nowego wywołania.
- Wyniki etapu skanowania/ekstrakcji też są trwałe; wznowienie ich nie powtarza.
- Tabela `runs` (parametry, hash configu, start/koniec, stop_reason). Run bez `ended_at` = przerwany. Zmiana modelu/configu między wznowieniami → wyraźne ostrzeżenie lub odmowa.
- Determinizm: kolejność przetwarzania = sortowanie po ścieżce reprezentanta; `--limit N` bierze pierwsze N w tej kolejności.

### Równoległość (wymaganie 5)

- Orkiestrator z N workerami. Parsowanie plików w **osobnych procesach z twardym timeoutem** (uszkodzony PDF potrafi się zawiesić lub wysypać interpreter) — zabicie procesu = kwarantanna z przyczyną `extract_timeout`/`extract_crash`.
- Pliki powyżej progu (np. 50 MB) idą przez semafor o pojemności 1 („duży pas”), żeby 4 duże pliki naraz nie przebiły 2 GB.
- Wywołania backendu: timeout per request, retry z exponential backoff + jitter (limitowane), circuit breaker. Trwała niedostępność → run kończy się `stop_reason=backend_unavailable`, dokumenty zostają `pending` (nie kwarantanna, nie utrata). Niepoprawny JSON → 1 ponowienie, potem kwarantanna `llm_invalid_output`.
- ARCHITECTURE.md musi uczciwie powiedzieć, co ogranicza przepustowość: GPU/przepustowość pamięci M1 przy prompt processingu, liczba slotów `OLLAMA_NUM_PARALLEL`; workers > sloty tylko kolejkują.

### Budżet (wymaganie 6)

- Przed każdym wywołaniem **rezerwacja** = górne ograniczenie tokenów wejścia + `max_output_tokens`. Jeśli `zużyte + zarezerwowane_w_locie + nowa_rezerwacja > budget` → nie wysyłamy, run kończy się `stop_reason=budget_exhausted`.
- Górne ograniczenie wejścia: tokenizer modelu (jeśli skonfigurowany, pinned) + margines na szablon czatu, albo bezpieczne `len(prompt.encode("utf-8")) + overhead` (≥ liczba tokenów dla tokenizerów BPE na bajtach). Opisać konserwatywność.
- Retry = nowa rezerwacja. Timeout = rezerwacja liczona jako zużyta (nie wiemy, ile serwer policzył).
- Po odpowiedzi rozliczenie rzeczywistymi licznikami (`prompt_eval_count`/`eval_count` lub `usage`).
- Koszt = tabela cen z configu (per model, per 1M in/out). Lokalny backend: cena 0, ta sama ścieżka kodu.

### Raport (wymaganie 7)

- Pola: `input_files, duplicate_files, unique_documents, processed_ok, quarantined, quarantine_by_reason{}, not_started, tokens_in, tokens_out, estimated_cost, wall_time_s, backend, model, stop_reason`.
- Niezmienniki sprawdzane w kodzie (assert/test): `input_files == duplicate_files + unique_documents`, `unique_documents == processed_ok + quarantined + not_started`.
- Przyczyny kwarantanny (czytelne): `unsupported_format`, `corrupt_file`, `encrypted`, `empty_text`, `extract_timeout`, `extract_crash`, `llm_invalid_output`, `too_large` (jeśli dotyczy).
- `stop_reason`: `completed`, `limit_reached`, `budget_exhausted`, `backend_unavailable`, `interrupted`.
- Pliki uszkodzone mają rekord w bazie z `doc_type = NULL` i statusem kwarantanny (zgodnie z `expected.jsonl`).

### Eval

- Dopasowanie rekordów do wierszy `expected.jsonl` po przecięciu zbiorów `files`. Raportuj też jakość deduplikacji (czy grupy się zgadzają) i dokumenty brakujące/nadmiarowe.
- Per pole: exact dla enum/NIP/dat/waluty, kwota z dokładnością 0.01, nazwa po normalizacji (casefold, cudzysłowy, formy prawne „sp. z o.o.”, „S.A.”, „Ltd”) + próg podobieństwa, `summary`: niepuste + zgodny język (bez udawania, że mierzymy jakość streszczenia).

### Pamięć (wymaganie 9)

- Nigdy nie wczytuj całego pliku do RAM. Hashowanie i odczyt tekstu strumieniowo; PDF strona po stronie; do promptu trafia tylko ograniczony wycinek.
- EML: parser stdlib ładuje całość — dla plików ponad progiem użyj „dużego pasa” lub parsowania strumieniowego i zmierz.
- Test mierzy szczytowy RSS **całego drzewa procesów** (psutil, suma dzieci) przy `--workers 4` z plikiem kilkuset MB.

## Testy (wymaganie 10)

- `make test` = `uv run pytest` z `--disable-socket --allow-unix-socket` (localhost tylko dla stubu HTTP, jeśli potrzebny). Bez Ollamy, bez sieci, bez kluczy.
- Obowiązkowe: wznowienie po SIGKILL (subprocess, kill -9 w losowych momentach, kilka razy; porównanie z przebiegiem nieprzerwanym; fake backend loguje wywołania → brak powtórzeń dla ukończonych), zatrzymanie budżetem (nigdy powyżej, stop_reason w raporcie), bilansowanie raportu (różne scenariusze), dokument nienadający się do przetworzenia (kwarantanna, nie crash).
- Dodatkowo: `--workers 1` vs `16` → ten sam zbiór rekordów; prompt injection nie zmienia innych rekordów ani schematu; backend timeout/500/niedostępny → brak utraty i brak zawieszenia; kodowania cp1250/iso-8859-2; NIP/kwoty/daty (tabele przypadków); zip-slip; pamięć (marker `slow`).
- Testy z prawdziwym modelem tylko pod markerem `live`, domyślnie pomijane.

## Dane (`scripts/make_dataset.py`)

Deterministyczny (seed), generuje ~40 plików + `expected.jsonl` z tego samego źródła prawdy. Dane mają **testować narzędzie, nie mu schlebiać** — oceniający sprawdzają, czego nasze dane próbują wymagać. Pokryj:

- wszystkie 5 formatów, EML z załącznikiem PDF/DOCX, EML w quoted-printable i base64,
- PL i EN, kodowania UTF-8, cp1250, iso-8859-2 (także HTML z `<meta charset>` niezgodnym z rzeczywistością),
- duplikaty: inna nazwa, inne kodowanie, inne białe znaki/formatowanie, ten sam tekst jako .txt i .html,
- uszkodzone: obcięty PDF, zły zip jako .docx, binarne śmieci z rozszerzeniem .pdf, pusty plik, zaszyfrowany PDF, plik nierozpoznanego typu,
- długie: PDF ~300 stron z kwotą/terminem płatności na ostatniej stronie; plik kilkuset MB generowany skryptem (`make_big.py`, nie commitujemy go),
- faktury z pozycjami i podsumowaniem, NIP w różnych formatach (`PL 123-456-32-18`, `123 456 32 18`), zagraniczny VAT, różne waluty i formaty kwot, daty słownie,
- umowy z klauzulami, oferty z terminem ważności, korespondencja z prośbami/poleceniami i **prompt injection**,
- dokumenty bez części pól (poprawne `null` w expected).
  `scripts/make_dupes.py`: archiwum kilku tysięcy plików, głównie duplikaty (test wydajności dedupu).

## Zasady pracy

- Nie wymyślaj API bibliotek ani flag Ollamy — sprawdź w zainstalowanej wersji (`--help`, docstring, źródło).
- Każda deklaracja w ARCHITECTURE.md musi mieć pokrycie w kodzie. Przed oddaniem przejdź ją zdanie po zdaniu i porównaj z kodem.
- README: tylko wymagania wstępne (z wersjami), jedna komenda setup, jedna komenda run, testy. Nic więcej.
- ARCHITECTURE.md: max 1 strona — kluczowe decyzje, znane ograniczenia, co przepustowość realnie ogranicza, co pęknie przy 100× większym archiwum i co wtedy zmienić, uczciwe wyniki `eval` na naszych danych.
- Nie commituj bazy wynikowej, logów, dużych plików ani `.venv`.
- Gdy wymaganie jest niejasne: wybierz rozsądną interpretację, zapisz ją w `docs/DECISIONS.md` i idź dalej. Nie blokuj pracy pytaniami.

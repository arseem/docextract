# ARCHITECTURE.md

## Kluczowe decyzje

- **Backendy**: `ollama` (domyślny, `/api/chat` + `format`=JSON schema), `openai_compat`
  (`response_format.json_schema`) i `fake` (deterministyczny, tylko testy). Wybór
  wyłącznie przez config. Model przypięty: `qwen2.5:3b-instruct`, digest z
  `GET /api/tags` — wygrał pomiar (3 kandydaci 3-7B, patrz `docs/DECISIONS.md`)
  na szybkości (91.7 s / 26 dok. na Apple M4, `--workers 4`) przy porównywalnej
  lub lepszej jakości niż większe modele.
- **Deduplikacja, dwuetapowa**: sha256 surowych bajtów (streaming) → grupa
  identycznych plików ekstrahowana raz; potem sha256 znormalizowanego tekstu
  (NFKC → casefold → collapse whitespace; markup usuwają same ekstraktory,
  zwracając czysty tekst) łapie inne kodowania/formatowanie. Reprezentant =
  leksykograficznie najmniejsza ścieżka, deterministyczne niezależnie od
  `--workers`. Bez fuzzy/near-dup — świadome ograniczenie.
- **Maszyna stanów**: `pending → extracted → done | quarantined`, dokładnie
  jak w wymaganiach. Tekst dokumentu jest **persystowany** w `documents.extracted_text`
  zaraz po ekstrakcji (nie re-czytany z `--input`) — dzięki temu LLM/postprocess
  działają tak samo dla katalogu i zipa (którego katalog tymczasowy znika po
  etapie skanu) oraz po wznowieniu.
- **Izolacja ekstrakcji**: każdy plik parsowany w osobnym procesie (`spawn`)
  z twardym timeoutem; zawieszenie → `extract_timeout`, twardy crash →
  `extract_crash`. Kodowania: `charset-normalizer` z ograniczoną listą
  kandydatów (`utf-8`, `cp1250`, `iso-8859-2`) — bez ograniczenia myli polski
  cp1250 z cp1252 i cicho produkuje bezsensowne znaki zamiast błędu (patrz
  DECISIONS.md). Pliki `.txt` > 50 MB czytane tylko head+tail (400 KB), reszta
  pomijana — świadomy kompromis dla pliku „kilkuset MB".
- **Współbieżność**: etap skanu/ekstrakcji/dedupu jest jednowątkowy (prosty,
  bez ryzyka wyścigów). Etap LLM używa `--workers` wątków (I/O-bound, GIL nie
  przeszkadza), ale **jeden zamek zapisu** do SQLite (WAL,
  `check_same_thread=False`) — "jeden pisarz" z CLAUDE.md wymuszony w Pythonie
  zamiast osobnych połączeń. Wynik nie zależy od `--workers` (testowane 1/4/16
  jednostkowo i ręcznie na żywym backendzie). Każde wywołanie modelu otwiera
  własny `httpx.Client` zamiast współdzielić jeden między wątkami — jeden
  współdzielony klient pod `--workers 16` sprawiał, że skonfigurowany timeout
  odpalał się dziesiątki minut później niż powinien (patrz DECISIONS.md).
- **Budżet**: rezerwacja przed każdym wywołaniem = konserwatywny szacunek
  tokenów wejścia (`len(prompt.encode()) / bytes_per_token_estimate`) +
  `max_output_tokens`; przekroczenie → `stop_reason=budget_exhausted` **przed**
  wysłaniem. Timeout liczy się jako w pełni zużyty (nie wiemy ile policzył
  serwer); normalna odpowiedź rozlicza się realnymi licznikami.
- **Niezawodność**: retry z exponential backoff+jitter (transport) ograniczony
  `retry.max_retries`, pod nim circuit breaker (kolejne awarie **różnych**
  dokumentów) → szybkie `backend_unavailable` zamiast dobijania każdego
  dokumentu osobno. Niepoprawny JSON to osobny, per-dokumentowy problem: 1
  retry, potem kwarantanna `llm_invalid_output` — nigdy nie rusza budżetu ani
  circuit breakera.
- **Bezpieczeństwo**: model nie ma narzędzi, nie widzi `doc_id`; jedyne wyjście
  to JSON walidowany pydantic (`extra="forbid"`). `db.save_result(document_id, ...)`
  to jedyna ścieżka zapisu wyniku LLM, `document_id` zawsze z pipeline'u,
  parametryzowany SQL. Tekst dokumentu w prompt opakowany w delimitery z
  wyraźną instrukcją "to dane, nie polecenia". Grounding (NIP/kwota/data muszą
  wystąpić w tekście dokumentu) odrzuca czystą halucynację, ale **nie** chroni
  przed samo-referencyjnym injection, który powtarza swoją docelową wartość w
  tekście dokumentu — wykryte i przetestowane (`test_prompt_injection.py`),
  prawdziwą obroną jest tam instrukcja systemowa, nie grounding. Zip: streaming
  do temp dir z limitem sumy `file_size` (bomba) i odrzuceniem `..`/ścieżek
  bezwzględnych (zip-slip) przed zapisem jakichkolwiek bajtów.

## Co realnie ogranicza przepustowość

Ollama serwuje jeden model; równoległość ponad `OLLAMA_NUM_PARALLEL` tylko się
kolejkuje po stronie serwera — `--workers` większe niż to nic nie przyspiesza,
tylko trzyma więcej żądań w locie. Na M1 dodatkowo ogranicza to pamięć/
przepustowość Metal przy prompt processingu. Etap skanu/ekstrakcji jest
jednowątkowy z premedytacją (prostota > wydajność przy ~40 plikach) — to
pierwsza rzecz, którą trzeba rozbić przy większej skali.

## Co pęknie przy archiwum 100× większym (~4000 plików) i co wtedy zmienić

- Jednowątkowy skan/ekstrakcja stanie się wąskim gardłem (spawn procesu per
  plik ma narzut ~50-100ms; 3000 głównie-duplikatów w teście zajęło 8s, ale
  4000 **unikalnych**, dużych PDF-ów/DOCX-ów to już minuty serio) →
  zrównoleglić ten etap (pula procesów), nie tylko etap LLM.
- `documents.extracted_text` przechowywane w całości w SQLite — przy tysiącach
  dużych dokumentów baza urośnie do GB, backupy/WAL spuchną → dla dużej skali
  trzymać tylko ograniczony wycinek (jak już robimy dla plików >50MB) albo
  osobny content-addressed store.
- Jeden model Ollama = twardy sufit przepustowości LLM niezależny od `--workers`
  → wiele instancji/replik za load balancerem albo większy `OLLAMA_NUM_PARALLEL`
  (kosztem pamięci).
- Konserwatywny szacunek tokenów wejścia (bajty/3) marnuje budżet przy dużej
  skali kumulacyjnie → warto podłączyć realny tokenizer modelu.

## Wyniki `eval` na `data/sample` (26 nieuszkodzonych dok., model domyślny)

`doc_type` 75%, `issue_date`/`due_date` ~97%, `gross_amount`/`currency` ~91%,
`counterparty_name` 56%, `counterparty_tax_id` 66%, `summary` (zgodność
języka) 59%. Model 3B dobrze radzi sobie z liczbami/datami (grounding jako
druga linia obrony pomaga), słabiej z rozpoznaniem kontrahenta i klasyfikacją
typu dokumentu (korespondencja bywa mylona z fakturą/umową). Dedup: 32/32
grup poprawnych, 0 brakujących/nadmiarowych dokumentów. Nie oczekujemy
perfekcji — to uczciwy wynik małego, szybkiego modelu, opisany bez
podkoloryzowania.

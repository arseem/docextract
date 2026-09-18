# Decyzje projektowe

Zapis nieoczywistych interpretacji wymagań z `docs/ZADANIE.md`, podjętych bez
blokowania pracy na pytaniach.

## Zakres `--budget`

`--budget N` ogranicza łączne zużycie tokenów **jednego uruchomienia procesu**
(jednego wiersza w tabeli `runs`), nie sumy historycznej po wielu
wznowieniach. Jeśli przebieg zatrzymał się `budget_exhausted`, kolejne
uruchomienie z tym samym `--budget` dostaje świeży licznik — użytkownik sam
decyduje, czy podnieść limit. `report` pokazuje tokeny/koszt/`stop_reason`
najnowszego wiersza `runs`, natomiast liczba plików/dokumentów w raporcie
odzwierciedla cały stan bazy (bo dedup i status dokumentu przechodzą przez
wznowienia).

## Status `extracted` w bilansie raportu

Dokument w stanie `extracted` (odpowiedź LLM zapisana, postprocessing jeszcze
nie zacommitowany — możliwe tylko chwilę po SIGKILL) liczy się w raporcie
jako `not_started`, razem z `pending`. Postprocessing jest deterministyczny i
bezkosztowy (bez I/O do modelu), więc przy normalnym zakończeniu przebiegu
nie powinien tam zostać żaden dokument.

## Backend `--config` bez sekcji

Nieznane klucze w configu są odrzucane (`pydantic extra="forbid"`) — literówka
w TOML ma być błędem walidacji, nie cichym fallbackiem na wartość domyślną.

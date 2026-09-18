# docextract

## Wymagania wstępne

- Python 3.12 (zarządzany przez `uv`, patrz `.python-version`)
- [uv](https://docs.astral.sh/uv/) >= 0.12
- [Ollama](https://ollama.com) >= 0.34, uruchomiony (`ollama serve`) — backend domyślny.
  Alternatywnie dowolny serwer zgodny z OpenAI API (np. `llama.cpp llama-server`,
  LM Studio) — patrz `backend.kind = "openai_compat"` w `config/default.toml`.

## Setup

```
make setup
```

Wykonuje `uv sync`, pobiera domyślny model (`ollama pull qwen2.5:3b-instruct`,
~2 GB) i weryfikuje jego digest wobec tego przypiętego w `config/default.toml`.

## Uruchomienie

```
uv run docextract run --input data/sample --db out.sqlite --workers 4
uv run docextract report --db out.sqlite --json
uv run docextract eval --db out.sqlite --expected data/sample/expected.jsonl
```

## Testy

```
make test
```

Uruchamia `pytest` bez dostępu do sieci i bez działającego serwera inferencji
(HTTP do backendów jest testowane przez mockowanie `httpx`, nie żywy serwer).
Testy oznaczone `slow` (pamięć na pliku kilkuset MB) i `live` (żywy model) są
pomijane domyślnie.

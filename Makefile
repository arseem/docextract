.PHONY: setup test data run report eval clean

setup:
	uv sync
	uv run python scripts/verify_model.py || true

test:
	uv run pytest --disable-socket --allow-unix-socket

data:
	uv run python scripts/make_dataset.py
	@echo "Committed dataset regenerated in data/sample/."
	@echo "For the memory/performance tests, also run (not committed, see .gitignore):"
	@echo "  uv run python scripts/make_big.py     # multi-hundred-MB file"
	@echo "  uv run python scripts/make_dupes.py   # few-thousand-file dedup archive"

clean:
	rm -f out.sqlite out.sqlite-wal out.sqlite-shm
	rm -rf data/dupes data/big

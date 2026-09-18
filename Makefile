.PHONY: setup test data run report eval clean

setup:
	uv sync
	uv run python scripts/verify_model.py || true

test:
	uv run pytest --disable-socket --allow-unix-socket

data:
	uv run python scripts/make_dataset.py
	uv run python scripts/make_dupes.py
	@echo "make_big.py skipped by default (generates a multi-hundred-MB file); run explicitly:"
	@echo "  uv run python scripts/make_big.py"

clean:
	rm -f out.sqlite out.sqlite-wal out.sqlite-shm
	rm -rf data/dupes data/big

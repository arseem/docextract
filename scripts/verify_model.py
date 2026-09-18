"""Verify the model pinned in config/default.toml is actually available,
with the expected digest. Run by `make setup` after `ollama pull`."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from docextract.config import DEFAULT_CONFIG_PATH, load_config  # noqa: E402
from docextract.llm.base import LLMError  # noqa: E402
from docextract.llm.factory import build_backend  # noqa: E402


def main() -> int:
    config = load_config(DEFAULT_CONFIG_PATH)
    if config.backend.kind == "fake":
        print("backend=fake, nothing to verify")
        return 0

    tag, digest = config.active_model_identity()
    if tag == "TODO" or digest == "TODO":
        print(
            f"backend={config.backend.kind}: model tag/digest not pinned in "
            "config/default.toml - see README for setup instructions"
        )
        return 1

    backend = build_backend(config)
    try:
        backend.verify_model_available()
    except LLMError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(f"OK: backend={config.backend.kind} model={tag}@{digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

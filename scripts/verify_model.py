"""Verify the model pinned in config/default.toml is actually available.

Milestone 1 placeholder: real digest verification against a running backend
is wired up in milestone 8, once a model has been benchmarked and pinned.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from docextract.config import DEFAULT_CONFIG_PATH, load_config  # noqa: E402


def main() -> int:
    config = load_config(DEFAULT_CONFIG_PATH)
    tag, digest = config.active_model_identity()
    if config.backend.kind == "fake":
        print("backend=fake, nothing to verify")
        return 0
    if tag == "TODO" or digest == "TODO":
        print(
            f"backend={config.backend.kind}: model tag/digest not pinned yet "
            "(milestone 8 TODO) - skipping verification"
        )
        return 0
    print(f"backend={config.backend.kind} model={tag}@{digest}: TODO wire up live check")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

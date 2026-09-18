from __future__ import annotations

import argparse
import json
import sys

from . import db, pipeline
from .config import DEFAULT_CONFIG_PATH, load_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="docextract")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="Process an input archive into a SQLite DB")
    p_run.add_argument("--input", required=True, help="Directory or zip archive")
    p_run.add_argument("--db", required=True, help="Output SQLite file")
    p_run.add_argument("--workers", type=int, default=1)
    p_run.add_argument("--limit", type=int, default=None)
    p_run.add_argument("--budget", type=int, default=None)
    p_run.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))

    p_report = sub.add_parser("report", help="Print a report for a DB")
    p_report.add_argument("--db", required=True)
    p_report.add_argument("--json", action="store_true")

    p_eval = sub.add_parser("eval", help="Compare a DB against expected.jsonl")
    p_eval.add_argument("--db", required=True)
    p_eval.add_argument("--expected", required=True)

    return parser


def cmd_run(args: argparse.Namespace) -> int:
    from .llm.base import LLMError

    if args.workers < 1:
        print("error: --workers must be >= 1", file=sys.stderr)
        return 2
    config = load_config(args.config)
    try:
        with db.open_db(args.db) as conn:
            pipeline.run(
                conn,
                input_path=args.input,
                config=config,
                workers=args.workers,
                limit=args.limit,
                budget=args.budget,
            )
    except LLMError as e:
        print(f"error: {e}", file=sys.stderr)
        return 3
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from . import report as report_mod

    with db.open_db(args.db) as conn:
        report = report_mod.compute_report(conn)
    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        for key, value in report.items():
            print(f"{key}: {value}")
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    from . import eval as eval_mod

    with db.open_db(args.db) as conn:
        result = eval_mod.run_eval(conn, args.expected)
    print(json.dumps(result, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {"run": cmd_run, "report": cmd_report, "eval": cmd_eval}
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())

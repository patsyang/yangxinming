from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import load_config
from .bundle import run_query_bundle
from .code import run_code
from .errors import KnowledgeKitError
from .init import run_init
from .ingest import run_ingest
from .lint import run_lint, validate_structure
from .search import run_query
from .update import run_update


def emit_json(payload: dict) -> None:
    data = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    sys.stdout.buffer.write(data.encode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="knowledge_kit")
    parser.add_argument(
        "--config",
        default=argparse.SUPPRESS,
        help="Path to knowledge_kit.config.json or a directory containing it.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    query_parser = subparsers.add_parser("query")
    query_parser.add_argument("--config", default=argparse.SUPPRESS)
    query_parser.add_argument("query", nargs="+")
    query_parser.add_argument("-k", "--knowledge")
    query_parser.add_argument("--all", action="store_true")
    query_parser.add_argument("--semantic-plan")

    query_bundle_parser = subparsers.add_parser("query-bundle")
    query_bundle_parser.add_argument("--config", default=argparse.SUPPRESS)
    query_bundle_parser.add_argument("query", nargs="+")
    query_bundle_parser.add_argument("-k", "--knowledge")
    query_bundle_parser.add_argument("--all", action="store_true")
    query_bundle_parser.add_argument("--semantic-plan")

    update_parser = subparsers.add_parser("update")
    update_parser.add_argument("--config", default=argparse.SUPPRESS)
    update_parser.add_argument("-k", "--knowledge", required=False)
    update_parser.add_argument("--task", required=True)
    update_parser.add_argument("--content")

    ingest_parser = subparsers.add_parser("ingest")
    ingest_parser.add_argument("--config", default=argparse.SUPPRESS)
    ingest_parser.add_argument("-k", "--knowledge", required=True)
    ingest_parser.add_argument("--src", required=True)

    init_parser = subparsers.add_parser("init")
    init_parser.add_argument("--config", default=argparse.SUPPRESS)
    init_parser.add_argument("-k", "--knowledge", required=True)

    lint_parser = subparsers.add_parser("lint")
    lint_parser.add_argument("--config", default=argparse.SUPPRESS)
    lint_parser.add_argument("-k", "--knowledge")
    lint_parser.add_argument("--all", action="store_true")

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--config", default=argparse.SUPPRESS)
    validate_parser.add_argument("-k", "--knowledge")

    code_parser = subparsers.add_parser("code")
    code_parser.add_argument("--config", default=argparse.SUPPRESS)
    code_parser.add_argument("-k", "--knowledge", required=True)
    code_parser.add_argument("--mode", choices=["from-zero", "update"], default=None)
    code_parser.add_argument("--stage", choices=["auto", "inventory", "plan", "plan-verify", "evidence", "analyze", "verify", "handoff"], default="auto")
    code_parser.add_argument("--resume")
    code_parser.add_argument("--repo")
    code_parser.add_argument("--batch")
    code_parser.add_argument("--remote", action="store_true")
    code_parser.add_argument("--depth", choices=["light", "standard", "deep"], default=None)
    code_parser.add_argument("--max-rounds", type=int, default=None)
    code_parser.add_argument("--output-json", action="store_true")
    code_parser.add_argument("task", nargs="*")

    args = parser.parse_args(argv)
    try:
        config = load_config(config_path=getattr(args, "config", None))
        if args.command == "query":
            payload = run_query(
                config,
                " ".join(args.query),
                knowledge_id=args.knowledge,
                all_enabled=args.all,
                semantic_plan=load_semantic_plan_arg(args.semantic_plan),
            )
        elif args.command == "query-bundle":
            payload = run_query_bundle(
                config,
                " ".join(args.query),
                knowledge_id=args.knowledge,
                all_enabled=args.all,
                semantic_plan=load_semantic_plan_arg(args.semantic_plan),
            )
        elif args.command == "update":
            payload = run_update(config, args.knowledge, args.task, content=args.content)
        elif args.command == "ingest":
            payload = run_ingest(config, args.knowledge, args.src)
        elif args.command == "init":
            payload = run_init(config, args.knowledge)
        elif args.command == "lint":
            payload = run_lint(config, knowledge_id=args.knowledge, all_enabled=args.all)
        elif args.command == "validate":
            payload = validate_structure(config, knowledge_id=args.knowledge)
        else:
            payload = run_code(
                config,
                args.knowledge,
                mode=args.mode,
                stage=args.stage,
                resume=args.resume,
                repo=args.repo,
                batch=args.batch,
                remote=args.remote,
                depth=args.depth,
                max_rounds=args.max_rounds,
                task=" ".join(args.task),
            )
    except KnowledgeKitError as exc:
        emit_json({"status": "failed", "error": exc.code, "message": str(exc)})
        return 2
    except Exception as exc:  # noqa: BLE001
        emit_json({"status": "failed", "error": type(exc).__name__, "message": str(exc)})
        return 1
    emit_json(payload)
    return 0


def load_semantic_plan_arg(path: str | None) -> dict | None:
    if not path:
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import shutil
from pathlib import Path

from .config import KitConfig
from .runtime import append_ledger, new_run_id, now_iso, write_run_artifact
from .workflow_contract import CLI_LIMITATIONS, INGEST_REGISTRATION_KIND, RELATION_DECISION_SKELETON


def run_ingest(config: KitConfig, knowledge_id: str, source: str) -> dict:
    root = config.require_write_root(knowledge_id)
    source_path = Path(source).expanduser().resolve()
    if not source_path.exists() or not source_path.is_file():
        from .errors import SourceRequired

        raise SourceRequired(f"source_required:{source}")
    run_id = new_run_id("ingest")
    root.raw_dir.mkdir(parents=True, exist_ok=True)
    raw_root = root.raw_dir.resolve()
    if source_path.is_relative_to(raw_root):
        raw_target = source_path
        copied = False
    else:
        raw_target_dir = root.raw_dir / "imports"
        raw_target_dir.mkdir(parents=True, exist_ok=True)
        raw_target = unique_path(raw_target_dir / source_path.name)
        shutil.copy2(source_path, raw_target)
        copied = True
    raw_rel = raw_target.relative_to(root.path).as_posix()
    payload = {
        "run_id": run_id,
        "kind": INGEST_REGISTRATION_KIND,
        "operation": "INGEST",
        "cli_role": "source_registration_only",
        "knowledge_target": root.id,
        "actual_knowledge_root": str(root.path),
        "source": {
            "input_path": str(source_path),
            "raw_path": raw_rel,
            "copied": copied,
        },
        "karpathy_alignment": {
            "operations": ["INGEST"],
            "why": ["CLI 只把来源放入目标 raw/；正式 source/concept/entity/overview/index/log 维护由 agent 执行。"],
        },
        "wiki_artifact_summary": {"add": [], "update": [], "structural": []},
        "ingest_next_steps": [
            "read_source_from_raw",
            "write_source_summary",
            "create_or_update_concept_pages",
            "create_or_update_entity_pages",
            "update_cross_references",
            "update_overview_if_needed",
            "update_index",
            "append_log",
            "decide_relations_rebuild_or_noop",
            "handoff_to_verifier",
        ],
        "relations_decision": RELATION_DECISION_SKELETON,
        "blockers": {"values": ["codex_agent_required_for_full_karpathy_ingest"]},
        "limitations": CLI_LIMITATIONS,
        "created_at": now_iso(),
    }
    artifact = write_run_artifact(config.runs_dir, run_id, "ingest-registration.json", payload)
    append_ledger(config.state_dir, {"run_id": run_id, "kind": INGEST_REGISTRATION_KIND, "artifact": str(artifact), "created_at": payload["created_at"]})
    return payload


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    counter = 2
    while True:
        candidate = parent / f"{stem}-{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1

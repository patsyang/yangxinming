from __future__ import annotations

import json
from knowledge_kit.config import KitConfig
from knowledge_kit.workflow_contract import (
    KCODE_CONTINUATION_POLICY,
    KCODE_HUMAN_READABLE_OUTPUT_LANGUAGE,
    KCODE_LANGUAGE_POLICY,
    KCODE_REQUIRES_LLM_KIND,
    KCODE_RUN_KIND,
)

from .coverage_contract import AGENTIC_CODING_COVERAGE_CONTRACT
from .diff import write_diff
from .evidence import batch_slug, collect_evidence, load_plan, select_batch
from .git_inventory import collect_inventory, write_latest_snapshot, write_repo_map
from .handoff import generate_handoff
from .repo_map import build_repo_map
from .verify import verify_batch, verify_plan
from .workspace import CodeRunError, code_stage_command, codex_next_step, create_run, mark_stage, require_run


def run_code(
    config: KitConfig,
    knowledge_id: str,
    *,
    mode: str | None = None,
    stage: str = "auto",
    resume: str | None = None,
    repo: str | None = None,
    batch: str | None = None,
    remote: bool = False,
    depth: str | None = None,
    max_rounds: int | None = None,
    task: str = "",
) -> dict:
    if stage == "auto":
        run = create_run(config, knowledge_id, mode=mode, depth=depth, max_rounds=max_rounds, task=task)
        inventory_payload = stage_inventory(run, remote=remote, repo_filter=repo)
        plan_payload = stage_plan(run)
        return {
            "kind": KCODE_RUN_KIND,
            "status": "requires_llm",
            "continuation_policy": KCODE_CONTINUATION_POLICY,
            "run_id": run.run_id,
            "run_dir": str(run.run_dir),
            "inventory": inventory_payload,
            "next": plan_payload,
            "codex_next_step": plan_payload["codex_next_step"],
        }
    if stage == "inventory":
        run = create_run(config, knowledge_id, mode=mode, depth=depth, max_rounds=max_rounds, task=task)
        payload = stage_inventory(run, remote=remote, repo_filter=repo)
        return {
            "kind": KCODE_RUN_KIND,
            "status": "completed",
            "stage": "inventory",
            "run_id": run.run_id,
            "run_dir": str(run.run_dir),
            "next_command": code_stage_command(run, "plan"),
            **payload,
        }
    run = require_run(config, knowledge_id, resume)
    if stage == "plan":
        return stage_plan(run)
    if stage == "plan-verify":
        return verify_plan(run)
    if stage == "evidence":
        return stage_evidence(run, batch)
    if stage == "analyze":
        return stage_analyze(run, batch)
    if stage == "verify":
        return verify_batch(run, batch)
    if stage == "handoff":
        return generate_handoff(run)
    raise CodeRunError(f"invalid_code_stage:{stage}")


def stage_inventory(run, *, remote: bool, repo_filter: str | None) -> dict:
    inventory = collect_inventory(run, remote=remote, repo_filter=repo_filter)
    diff = write_diff(run, inventory["snapshot"])
    write_latest_snapshot(run, inventory["snapshot"])
    repo_map = build_repo_map(inventory["repos"], run.workspace)
    write_repo_map(run, repo_map)
    return {
        "artifacts": {
            "submodules": "inventory/submodules.json",
            "snapshot": "inventory/snapshot.json",
            "diff": "inventory/diff.json",
            "repo_map": "inventory/repo-map.json",
        },
        "repo_count": len(inventory["repos"]),
        "repo_changes": len(diff.get("repo_changes", [])),
    }


def stage_plan(run) -> dict:
    plan_dir = run.run_dir / "plan"
    plan_dir.mkdir(parents=True, exist_ok=True)
    planner_input = {
        "schema_version": "kcode.planner_input.v1",
        "run": "run.json",
        "inventory": {
            "submodules": "inventory/submodules.json",
            "snapshot": "inventory/snapshot.json",
            "diff": "inventory/diff.json",
            "repo_map": "inventory/repo-map.json",
        },
        "task": run.task,
        "mode": run.mode,
        "depth": run.depth,
        "human_readable_output_language": KCODE_HUMAN_READABLE_OUTPUT_LANGUAGE,
        "language_policy": KCODE_LANGUAGE_POLICY,
        "coverage_contract": AGENTIC_CODING_COVERAGE_CONTRACT,
        "required_outputs": ["analysis-plan.md", "analysis-plan.json", "coverage-ledger.json"],
    }
    target = plan_dir / "planner-input.json"
    target.write_text(json.dumps(planner_input, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    mark_stage(run, "plan", "requires_llm", {"planner_input": "plan/planner-input.json"})
    next_step = codex_next_step(
        run,
        stage="plan",
        agent="kcode-planner",
        prompt="prompts/kcode-planner.md",
        input_path="plan/planner-input.json",
        expected_outputs=["plan/analysis-plan.md", "plan/analysis-plan.json", "plan/coverage-ledger.json"],
        after_outputs_stage="plan-verify",
    )
    return {
        "kind": KCODE_REQUIRES_LLM_KIND,
        "status": "requires_llm",
        "continuation_policy": KCODE_CONTINUATION_POLICY,
        "run_id": run.run_id,
        "run_dir": str(run.run_dir),
        "agent": "kcode-planner",
        "prompt": "prompts/kcode-planner.md",
        "input": "plan/planner-input.json",
        "human_readable_output_language": KCODE_HUMAN_READABLE_OUTPUT_LANGUAGE,
        "language_policy": KCODE_LANGUAGE_POLICY,
        "expected_outputs": ["plan/analysis-plan.md", "plan/analysis-plan.json", "plan/coverage-ledger.json"],
        "after_writing_outputs_command": next_step["after_writing_outputs_command"],
        "codex_next_step": next_step,
    }


def stage_evidence(run, batch_id: str | None) -> dict:
    payload = collect_evidence(run, batch_id)
    return {
        "kind": KCODE_RUN_KIND,
        "status": "completed",
        "stage": "evidence",
        "run_id": run.run_id,
        "run_dir": str(run.run_dir),
        "batch_id": payload["batch"].get("batch_id"),
        "evidence": payload["batch_dir"].joinpath("evidence.json").relative_to(run.run_dir).as_posix(),
        "next_command": code_stage_command(run, "analyze", batch_id=str(payload["batch"].get("batch_id") or "")),
    }


def stage_analyze(run, batch_id: str | None) -> dict:
    plan = load_plan(run)
    batch = select_batch(plan, batch_id)
    slug = batch_slug(batch)
    batch_dir = run.run_dir / "batches" / slug
    batch_dir.mkdir(parents=True, exist_ok=True)
    analyzer_input = {
        "schema_version": "kcode.analyzer_input.v1",
        "run": "run.json",
        "batch": {"batch_id": batch.get("batch_id"), "plan_ref": f"plan/analysis-plan.json:batches[{plan.get('batches', []).index(batch)}]"},
        "evidence": f"batches/{slug}/evidence.json",
        "coverage_ledger": "plan/coverage-ledger.json",
        "human_readable_output_language": KCODE_HUMAN_READABLE_OUTPUT_LANGUAGE,
        "language_policy": KCODE_LANGUAGE_POLICY,
        "coverage_contract": AGENTIC_CODING_COVERAGE_CONTRACT,
        "required_outputs": ["analysis.md", "findings.jsonl"],
    }
    target = batch_dir / "analyzer-input.json"
    target.write_text(json.dumps(analyzer_input, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    mark_stage(run, "analyze", "requires_llm", {f"batch_{batch.get('batch_id')}_analyzer_input": target.relative_to(run.run_dir).as_posix()})
    expected_outputs = [f"batches/{slug}/analysis.md", f"batches/{slug}/findings.jsonl"]
    next_step = codex_next_step(
        run,
        stage="analyze",
        agent="kcode-analyzer",
        prompt="prompts/kcode-analyzer.md",
        input_path=target.relative_to(run.run_dir).as_posix(),
        expected_outputs=expected_outputs,
        after_outputs_stage="verify",
        batch_id=str(batch.get("batch_id") or ""),
    )
    return {
        "kind": KCODE_REQUIRES_LLM_KIND,
        "status": "requires_llm",
        "continuation_policy": KCODE_CONTINUATION_POLICY,
        "run_id": run.run_id,
        "run_dir": str(run.run_dir),
        "agent": "kcode-analyzer",
        "prompt": "prompts/kcode-analyzer.md",
        "input": target.relative_to(run.run_dir).as_posix(),
        "human_readable_output_language": KCODE_HUMAN_READABLE_OUTPUT_LANGUAGE,
        "language_policy": KCODE_LANGUAGE_POLICY,
        "expected_outputs": expected_outputs,
        "after_writing_outputs_command": next_step["after_writing_outputs_command"],
        "codex_next_step": next_step,
    }

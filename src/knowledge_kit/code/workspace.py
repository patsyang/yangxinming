from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from knowledge_kit.config import KitConfig
from knowledge_kit.errors import ConfigError, KnowledgeKitError
from knowledge_kit.workflow_contract import KCODE_CONTRACT_REFS, KCODE_HUMAN_READABLE_OUTPUT_LANGUAGE, KCODE_LANGUAGE_POLICY

from .models import CodeRun, CodeWorkspace

DEFAULT_EXCLUDES = (
    "**/.git/**",
    "**/node_modules/**",
    "**/.venv/**",
    "**/dist/**",
    "**/build/**",
    "**/target/**",
    "**/__pycache__/**",
)

STAGES = ("inventory", "plan", "plan_verification", "evidence", "analyze", "verify", "handoff")


class CodeRunError(KnowledgeKitError):
    code = "code_run_error"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def make_run_id(knowledge_id: str) -> str:
    return f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{knowledge_id}"


def resolve_workspace(config: KitConfig, knowledge_id: str) -> CodeWorkspace:
    root = config.require_write_root(knowledge_id)
    code_config = config.data.get("code", {})
    workspaces = code_config.get("workspaces", {}) if isinstance(code_config, dict) else {}
    raw_workspace = workspaces.get(knowledge_id, {}) if isinstance(workspaces, dict) else {}
    if raw_workspace and not isinstance(raw_workspace, dict):
        raise ConfigError(f"invalid_code_workspace:{knowledge_id}")

    configured_root = raw_workspace.get("workspace_root")
    if configured_root:
        workspace_root = Path(str(configured_root)).expanduser().resolve()
    elif root.path.name == "knowledge":
        workspace_root = root.path.parent.resolve()
    else:
        workspace_root = root.path.resolve()

    runs_relative = str(code_config.get("runs_dir", "state/kcode-runs")) if isinstance(code_config, dict) else "state/kcode-runs"
    runs_dir = (root.path / runs_relative).resolve()
    include_globs = tuple(str(item) for item in raw_workspace.get("include_globs", ["**/*"]))
    exclude_globs = tuple(str(item) for item in raw_workspace.get("exclude_globs", DEFAULT_EXCLUDES))
    return CodeWorkspace(
        knowledge_id=knowledge_id,
        knowledge_root=root.path,
        workspace_root=workspace_root,
        repos_dir=str(raw_workspace.get("repos_dir", "repos")),
        submodule_mode=bool(raw_workspace.get("submodule_mode", True)),
        include_globs=include_globs,
        exclude_globs=exclude_globs,
        runs_dir=runs_dir,
    )


def resolve_defaults(config: KitConfig, mode: str | None, depth: str | None, max_rounds: int | None) -> tuple[str, str, int]:
    code_config = config.data.get("code", {})
    if not isinstance(code_config, dict):
        code_config = {}
    resolved_mode = mode or str(code_config.get("default_mode", "update"))
    resolved_depth = depth or str(code_config.get("default_depth", "standard"))
    resolved_rounds = int(max_rounds if max_rounds is not None else code_config.get("default_max_rounds", 2))
    if resolved_mode not in {"from-zero", "update"}:
        raise ConfigError(f"invalid_code_mode:{resolved_mode}")
    if resolved_depth not in {"light", "standard", "deep"}:
        raise ConfigError(f"invalid_code_depth:{resolved_depth}")
    return resolved_mode, resolved_depth, resolved_rounds


def create_run(
    config: KitConfig,
    knowledge_id: str,
    *,
    mode: str | None,
    depth: str | None,
    max_rounds: int | None,
    task: str,
) -> CodeRun:
    workspace = resolve_workspace(config, knowledge_id)
    resolved_mode, resolved_depth, resolved_rounds = resolve_defaults(config, mode, depth, max_rounds)
    run_id = make_run_id(knowledge_id)
    run_dir = workspace.runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    run = CodeRun(run_id, run_dir, workspace, resolved_mode, resolved_depth, resolved_rounds, task)
    (run_dir / "input.md").write_text((task or "").strip() + "\n", encoding="utf-8")
    save_run(run, initial_run_payload(run))
    return run


def load_run(config: KitConfig, knowledge_id: str, run_id: str) -> CodeRun:
    workspace = resolve_workspace(config, knowledge_id)
    run_dir = workspace.runs_dir / run_id
    run_path = run_dir / "run.json"
    if not run_path.exists():
        raise CodeRunError(f"code_run_missing:{run_id}")
    payload = json.loads(run_path.read_text(encoding="utf-8"))
    if payload.get("knowledge_id") != knowledge_id:
        raise CodeRunError(f"code_run_knowledge_mismatch:{run_id}")
    return CodeRun(
        run_id=run_id,
        run_dir=run_dir,
        workspace=workspace,
        mode=str(payload.get("mode", "update")),
        depth=str(payload.get("depth", "standard")),
        max_rounds=int(payload.get("max_rounds", 2)),
        task=str(payload.get("task", "")),
    )


def require_run(config: KitConfig, knowledge_id: str, run_id: str | None) -> CodeRun:
    if not run_id:
        raise CodeRunError("code_run_required")
    return load_run(config, knowledge_id, run_id)


def initial_run_payload(run: CodeRun) -> dict:
    now = utc_now()
    return {
        "schema_version": "kcode.run.v1",
        "run_id": run.run_id,
        "knowledge_id": run.workspace.knowledge_id,
        "knowledge_root": str(run.workspace.knowledge_root),
        "workspace_root": str(run.workspace.workspace_root),
        "mode": run.mode,
        "depth": run.depth,
        "max_rounds": run.max_rounds,
        "task": run.task,
        "created_at": now,
        "updated_at": now,
        "stage_status": {stage: "pending" for stage in STAGES},
        "artifacts": {},
    }


def load_run_payload(run: CodeRun) -> dict:
    return json.loads((run.run_dir / "run.json").read_text(encoding="utf-8"))


def save_run(run: CodeRun, payload: dict) -> None:
    payload["updated_at"] = utc_now()
    (run.run_dir / "run.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def mark_stage(run: CodeRun, stage: str, status: str, artifacts: dict[str, str] | None = None) -> None:
    payload = load_run_payload(run)
    payload.setdefault("stage_status", {})[stage] = status
    if artifacts:
        payload.setdefault("artifacts", {}).update(artifacts)
    save_run(run, payload)


def relative_artifact(run: CodeRun, path: Path) -> str:
    return path.relative_to(run.run_dir).as_posix()


def code_stage_command(run: CodeRun, stage: str, *, batch_id: str | None = None) -> str:
    command = f"python -m knowledge_kit code -k {run.workspace.knowledge_id} --stage {stage} --resume {run.run_id}"
    if batch_id:
        command += f" --batch {batch_id}"
    return command


def codex_next_step(run: CodeRun, *, stage: str, agent: str, prompt: str, input_path: str, expected_outputs: list[str], after_outputs_stage: str, batch_id: str | None = None) -> dict:
    payload = {
        "schema_version": "kcode.codex_next_step.v1",
        "status": "requires_llm",
        "completion_state": "not_complete",
        "must_continue": True,
        "final_answer_allowed": False,
        "requires_llm_must_be_resolved_by": "current_session_or_named_kcode_agent",
        "contract_refs": KCODE_CONTRACT_REFS,
        "must_read_contract_refs_before_writing_outputs": True,
        "run_id": run.run_id,
        "run_dir": str(run.run_dir),
        "stage": stage,
        "agent": agent,
        "prompt": prompt,
        "absolute_prompt": str((Path.cwd() / prompt).resolve()),
        "input": input_path,
        "absolute_input": str((run.run_dir / input_path).resolve()),
        "expected_outputs": expected_outputs,
        "absolute_expected_outputs": [str((run.run_dir / item).resolve()) for item in expected_outputs],
        "after_writing_outputs_command": code_stage_command(run, after_outputs_stage, batch_id=batch_id),
        "continue_until": "handoff_completed_or_verifier_loop_blocked",
        "do_not_final_answer_at_requires_llm": True,
        "required_actions": [
            "读取 prompt 和 input 指向的文件。",
            "按 agent 角色生成 expected_outputs 指向的全部文件；所有人读内容必须使用中文。",
            "写入文件后执行 after_writing_outputs_command。",
            "如果命令再次返回 status=requires_llm，继续按新的 codex_next_step 执行；不得把 requires_llm 当作最终回答。",
            "只有 handoff completed 或 verifier loop 达到 agent-level blocker 时才允许结束本次 /k code。",
        ],
        "human_readable_output_language": KCODE_HUMAN_READABLE_OUTPUT_LANGUAGE,
        "language_policy": KCODE_LANGUAGE_POLICY,
    }
    next_step_path = run.run_dir / "codex-next-step.json"
    payload["next_step_artifact"] = next_step_path.relative_to(run.run_dir).as_posix()
    payload["absolute_next_step_artifact"] = str(next_step_path.resolve())
    next_step_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    run_payload = load_run_payload(run)
    run_payload.setdefault("artifacts", {})["codex_next_step"] = payload["next_step_artifact"]
    run_payload["current_codex_next_step"] = payload["next_step_artifact"]
    save_run(run, run_payload)
    return payload

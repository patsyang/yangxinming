from __future__ import annotations

import json

from .git_inventory import run_git
from .models import CodeRun
from .workspace import mark_stage


def write_diff(run: CodeRun, current_snapshot: dict) -> dict:
    baseline = load_baseline(run)
    repo_changes = []
    baseline_by_path = {repo["path"]: repo for repo in baseline.get("repos", [])} if baseline else {}
    for repo in current_snapshot.get("repos", []):
        previous = baseline_by_path.get(repo["path"])
        previous_commit = previous.get("commit", "") if previous else ""
        current_commit = repo.get("commit", "")
        changed_files = changed_files_between(run, repo["path"], previous_commit, current_commit) if previous_commit and current_commit and previous_commit != current_commit else []
        if run.mode == "from-zero" or previous_commit != current_commit or changed_files:
            repo_changes.append(
                {
                    "repo_id": repo["repo_id"],
                    "previous_commit": previous_commit,
                    "current_commit": current_commit,
                    "changed_files": changed_files,
                }
            )
    payload = {
        "schema_version": "kcode.diff.v1",
        "mode": run.mode,
        "baseline_snapshot": baseline.get("snapshot_id") if baseline else None,
        "current_snapshot": current_snapshot.get("snapshot_id"),
        "repo_changes": repo_changes,
    }
    target = run.run_dir / "inventory" / "diff.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    mark_stage(run, "inventory", "completed", {"diff": "inventory/diff.json"})
    return payload


def load_baseline(run: CodeRun) -> dict | None:
    if run.mode == "from-zero":
        return None
    path = run.workspace.knowledge_root / "state" / "kcode" / "latest-snapshot.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def changed_files_between(run: CodeRun, repo_path: str, previous_commit: str, current_commit: str) -> list[str]:
    repo_root = run.workspace.workspace_root / repo_path
    if not (repo_root / ".git").exists():
        return []
    code, stdout, _ = run_git(["-C", str(repo_root), "diff", "--name-only", previous_commit, current_commit], run.workspace.workspace_root)
    if code != 0:
        return []
    return [f"{repo_path}/{line.strip()}" for line in stdout.splitlines() if line.strip()]

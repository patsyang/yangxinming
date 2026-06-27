from __future__ import annotations

import configparser
import json
import subprocess
from pathlib import Path

from .models import CodeRun
from .repo_map import iter_repo_files, language_summary
from .workspace import mark_stage, relative_artifact


def run_git(args: list[str], cwd: Path) -> tuple[int, str, str]:
    try:
        result = subprocess.run(["git", *args], cwd=str(cwd), check=False, capture_output=True, text=True, encoding="utf-8", errors="replace")
    except OSError as exc:
        return 127, "", str(exc)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def parse_gitmodules(workspace_root: Path) -> list[dict]:
    path = workspace_root / ".gitmodules"
    if not path.exists():
        repos_dir = workspace_root / "repos"
        if repos_dir.exists():
            return [{"name": item.name, "path": f"repos/{item.name}", "url": ""} for item in sorted(repos_dir.iterdir()) if item.is_dir()]
        return []
    parser = configparser.ConfigParser()
    parser.read(path, encoding="utf-8")
    repos: list[dict] = []
    for section in parser.sections():
        if not section.startswith("submodule "):
            continue
        name = section.split('"', 2)[1] if '"' in section else section.replace("submodule ", "").strip()
        repos.append({"name": name, "path": parser.get(section, "path", fallback=""), "url": parser.get(section, "url", fallback="")})
    return [item for item in repos if item["path"]]


def maybe_update_submodules(run: CodeRun, remote: bool) -> dict:
    workspace = run.workspace.workspace_root
    if not run.workspace.submodule_mode:
        return {"status": "skipped", "reason": "submodule_mode_false"}
    if not (workspace / ".git").exists() or not (workspace / ".gitmodules").exists():
        return {"status": "skipped", "reason": "not_git_submodule_workspace"}
    args = ["submodule", "update", "--recursive"]
    if remote:
        args.insert(2, "--remote")
    else:
        args.insert(2, "--init")
    code, stdout, stderr = run_git(args, workspace)
    return {"status": "completed" if code == 0 else "failed", "returncode": code, "stdout": stdout, "stderr": stderr}


def collect_inventory(run: CodeRun, *, remote: bool, repo_filter: str | None = None) -> dict:
    inventory_dir = run.run_dir / "inventory"
    inventory_dir.mkdir(parents=True, exist_ok=True)
    update_result = maybe_update_submodules(run, remote)
    parsed_repos = filter_repos(parse_gitmodules(run.workspace.workspace_root), repo_filter)
    repos = [enrich_repo(run, item) for item in parsed_repos]
    submodules = {
        "schema_version": "kcode.submodules.v1",
        "workspace_root": str(run.workspace.workspace_root),
        "submodule_update": update_result,
        "submodules": repos,
    }
    snapshot = build_snapshot(run, repos)
    (inventory_dir / "submodules.json").write_text(json.dumps(submodules, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (inventory_dir / "snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown_snapshot(run, snapshot)
    mark_stage(
        run,
        "inventory",
        "completed",
        {
            "submodules": "inventory/submodules.json",
            "snapshot": "inventory/snapshot.json",
        },
    )
    return {"repos": repos, "submodules": submodules, "snapshot": snapshot}


def filter_repos(repos: list[dict], repo_filter: str | None) -> list[dict]:
    if not repo_filter:
        return repos
    normalized = repo_filter.replace("\\", "/").strip()
    return [repo for repo in repos if repo.get("name") == normalized or repo.get("path") == normalized or repo.get("path", "").endswith(f"/{normalized}")]


def write_latest_snapshot(run: CodeRun, snapshot: dict) -> None:
    latest_dir = run.workspace.knowledge_root / "state" / "kcode"
    latest_dir.mkdir(parents=True, exist_ok=True)
    (latest_dir / "latest-snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def enrich_repo(run: CodeRun, item: dict) -> dict:
    repo_root = run.workspace.workspace_root / item["path"]
    branch = ""
    commit = ""
    if repo_root.exists():
        _, branch, _ = run_git(["-C", str(repo_root), "branch", "--show-current"], run.workspace.workspace_root)
        _, commit, _ = run_git(["-C", str(repo_root), "rev-parse", "HEAD"], run.workspace.workspace_root)
    return {
        "name": item["name"],
        "path": item["path"],
        "absolute_path": str(repo_root.resolve()),
        "url": item.get("url", ""),
        "branch": branch or "(detached)" if commit else "",
        "commit": commit,
        "short_commit": commit[:7] if commit else "",
        "status": "initialized" if repo_root.exists() else "missing",
    }


def build_snapshot(run: CodeRun, repos: list[dict]) -> dict:
    snapshot_repos: list[dict] = []
    for repo in repos:
        repo_root = run.workspace.workspace_root / repo["path"]
        files = iter_repo_files(repo_root, repo["path"], run.workspace) if repo_root.exists() else []
        snapshot_repos.append(
            {
                "repo_id": repo["name"],
                "path": repo["path"],
                "branch": repo.get("branch", ""),
                "commit": repo.get("commit", ""),
                "remote": repo.get("url", ""),
                "tracked_files": len(files),
                "language_summary": language_summary(repo_root, repo["path"], run.workspace) if repo_root.exists() else {},
            }
        )
    return {"schema_version": "kcode.snapshot.v1", "snapshot_id": run.run_id, "repos": snapshot_repos}


def write_markdown_snapshot(run: CodeRun, snapshot: dict) -> None:
    rows = ["# Submodule Snapshot", "", "| Path | Branch | Commit | Remote |", "| --- | --- | --- | --- |"]
    for repo in snapshot["repos"]:
        rows.append(f"| `{repo['path']}` | `{repo.get('branch', '')}` | `{repo.get('commit', '')}` | `{repo.get('remote', '')}` |")
    (run.run_dir / "inventory" / "submodule-snapshot.md").write_text("\n".join(rows) + "\n", encoding="utf-8")


def write_repo_map(run: CodeRun, repo_map: dict) -> None:
    target = run.run_dir / "inventory" / "repo-map.json"
    target.write_text(json.dumps(repo_map, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    mark_stage(run, "inventory", "completed", {"repo_map": relative_artifact(run, target)})

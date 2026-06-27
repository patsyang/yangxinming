from __future__ import annotations

import fnmatch
from pathlib import Path

from .models import CodeWorkspace

LANGUAGE_BY_SUFFIX = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".cs": "csharp",
    ".php": "php",
    ".rb": "ruby",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".json": "json",
    ".xml": "xml",
    ".md": "markdown",
}

DEPENDENCY_NAMES = {
    "package.json",
    "pnpm-lock.yaml",
    "pom.xml",
    "build.gradle",
    "requirements.txt",
    "pyproject.toml",
    "go.mod",
}

CONFIG_NAMES = {
    "application.yml",
    "application.yaml",
    ".env.example",
    "settings.py",
}

ENTRYPOINT_PATTERNS = (
    "@RequestMapping",
    "@GetMapping",
    "@PostMapping",
    "@PutMapping",
    "@DeleteMapping",
    "FastAPI(",
    "@app.route",
    "APIRouter(",
    "app.get(",
    "app.post(",
    "router.get(",
    "router.post(",
    "http.HandleFunc",
)


def language_for(path: Path) -> str:
    return LANGUAGE_BY_SUFFIX.get(path.suffix.lower(), "other")


def is_excluded(relative: str, workspace: CodeWorkspace) -> bool:
    normalized = relative.replace("\\", "/")
    return any(fnmatch.fnmatch(normalized, pattern) for pattern in workspace.exclude_globs)


def iter_repo_files(repo_root: Path, repo_path: str, workspace: CodeWorkspace) -> list[str]:
    git_files = run_git_ls_files(repo_root)
    if git_files:
        candidates = git_files
    else:
        candidates = [
            item.relative_to(repo_root).as_posix()
            for item in repo_root.rglob("*")
            if item.is_file()
        ]
    result: list[str] = []
    for item in sorted(candidates):
        full_relative = f"{repo_path}/{item}".replace("\\", "/")
        if not is_excluded(full_relative, workspace):
            result.append(item)
    return result


def run_git_ls_files(repo_root: Path) -> list[str]:
    import subprocess

    if not (repo_root / ".git").exists():
        return []
    try:
        result = subprocess.run(["git", "-C", str(repo_root), "ls-files"], check=False, capture_output=True, text=True, encoding="utf-8", errors="replace")
    except OSError:
        return []
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def language_summary(repo_root: Path, repo_path: str, workspace: CodeWorkspace) -> dict[str, int]:
    summary: dict[str, int] = {}
    for item in iter_repo_files(repo_root, repo_path, workspace):
        language = language_for(Path(item))
        summary[language] = summary.get(language, 0) + 1
    return dict(sorted(summary.items()))


def build_repo_map(repos: list[dict], workspace: CodeWorkspace) -> dict:
    mapped: list[dict] = []
    for repo in repos:
        repo_path = str(repo["path"])
        repo_root = workspace.workspace_root / repo_path
        files = iter_repo_files(repo_root, repo_path, workspace) if repo_root.exists() else []
        dependency_files = [f"{repo_path}/{item}" for item in files if Path(item).name in DEPENDENCY_NAMES or Path(item).suffix == ".csproj"]
        config_files = [
            f"{repo_path}/{item}"
            for item in files
            if Path(item).name in CONFIG_NAMES or Path(item).name.startswith("config.") or Path(item).name.startswith("settings.")
        ]
        entrypoints = detect_entrypoints(repo_root, repo_path, files)
        mapped.append(
            {
                "repo_id": repo["name"],
                "path": repo_path,
                "language_summary": language_summary(repo_root, repo_path, workspace) if repo_root.exists() else {},
                "entrypoints": entrypoints,
                "config_files": config_files[:50],
                "dependency_files": dependency_files[:50],
                "domain_terms": [],
                "candidate_modules": candidate_modules(repo_path, files),
            }
        )
    return {"schema_version": "kcode.repo_map.v1", "repos": mapped}


def detect_entrypoints(repo_root: Path, repo_path: str, files: list[str]) -> list[dict]:
    entrypoints: list[dict] = []
    for relative in files:
        suffix = Path(relative).suffix.lower()
        if suffix not in {".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".cs"}:
            continue
        path = repo_root / relative
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for index, line in enumerate(lines, start=1):
            if any(pattern in line for pattern in ENTRYPOINT_PATTERNS):
                entrypoints.append(
                    {
                        "kind": "entrypoint",
                        "file": f"{repo_path}/{relative}",
                        "line": index,
                        "symbol": nearest_symbol(lines, index),
                    }
                )
                break
        if len(entrypoints) >= 100:
            break
    return entrypoints


def nearest_symbol(lines: list[str], line_number: int) -> str:
    for index in range(line_number - 1, max(-1, line_number - 20), -1):
        line = lines[index].strip()
        for marker in ("class ", "def ", "function ", "func "):
            if marker in line:
                return line.split(marker, 1)[1].split("(", 1)[0].split("{", 1)[0].strip()
    return ""


def candidate_modules(repo_path: str, files: list[str]) -> list[dict]:
    modules: dict[str, set[str]] = {}
    for item in files:
        parts = Path(item).parts
        if len(parts) < 2:
            continue
        key = "/".join(parts[:2])
        modules.setdefault(key, set()).add(f"{repo_path}/{item}")
    result = []
    for index, (module, paths) in enumerate(sorted(modules.items())[:30], start=1):
        result.append({"module_id": f"module-{index:03d}", "paths": sorted(paths)[:20], "signals": []})
    return result

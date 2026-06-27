from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CodeWorkspace:
    knowledge_id: str
    knowledge_root: Path
    workspace_root: Path
    repos_dir: str
    submodule_mode: bool
    include_globs: tuple[str, ...]
    exclude_globs: tuple[str, ...]
    runs_dir: Path


@dataclass(frozen=True)
class CodeRun:
    run_id: str
    run_dir: Path
    workspace: CodeWorkspace
    mode: str
    depth: str
    max_rounds: int
    task: str

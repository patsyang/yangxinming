from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ConfigError, KnowledgeDisabled, KnowledgeNotFound, KnowledgeReadOnly, WriteTargetRequired

CONFIG_FILE = "knowledge_kit.config.json"
CONFIG_ENV_VAR = "KNOWLEDGE_KIT_CONFIG"
ROOT_ENV_VAR = "KNOWLEDGE_KIT_ROOT"
VALID_MODES = {"read_only", "read_write"}


@dataclass(frozen=True)
class KnowledgeRoot:
    id: str
    name: str
    path: Path
    enabled: bool
    mode: str
    priority: int = 0

    @property
    def raw_dir(self) -> Path:
        return self.path / "raw"

    @property
    def wiki_dir(self) -> Path:
        return self.path / "wiki"

    @property
    def relations_dir(self) -> Path:
        return self.path / "relations"

    @property
    def state_dir(self) -> Path:
        return self.path / "state"


@dataclass(frozen=True)
class KitConfig:
    root: Path
    data: dict[str, Any]
    knowledge_roots: list[KnowledgeRoot]

    def enabled_roots(self) -> list[KnowledgeRoot]:
        return sorted((item for item in self.knowledge_roots if item.enabled), key=lambda item: -item.priority)

    def get(self, knowledge_id: str) -> KnowledgeRoot:
        for item in self.knowledge_roots:
            if item.id == knowledge_id:
                return item
        raise KnowledgeNotFound(f"knowledge_not_found:{knowledge_id}")

    def require_query_root(self, knowledge_id: str) -> KnowledgeRoot:
        root = self.get(knowledge_id)
        if not root.enabled:
            raise KnowledgeDisabled(f"knowledge_disabled:{knowledge_id}")
        return root

    def require_write_root(self, knowledge_id: str | None) -> KnowledgeRoot:
        if not knowledge_id:
            raise WriteTargetRequired("write_target_required")
        root = self.require_query_root(knowledge_id)
        if root.mode != "read_write":
            raise KnowledgeReadOnly(f"knowledge_read_only:{knowledge_id}")
        return root

    @property
    def runs_dir(self) -> Path:
        configured = self.data.get("output", {}).get("runs_dir", "output/knowledge-runs")
        return self.root / configured

    @property
    def state_dir(self) -> Path:
        configured = self.data.get("output", {}).get("state_dir", "state")
        return self.root / configured

    @property
    def query_candidate_limit(self) -> int:
        query_config = self.data.get("query", {})
        return int(query_config.get("candidate_limit", 80))

    @property
    def query_evidence_budget(self) -> int:
        return int(self.data.get("query", {}).get("evidence_budget", 8))

    @property
    def query_exhaustive_evidence_budget(self) -> int:
        return int(self.data.get("query", {}).get("exhaustive_evidence_budget", 30))


def project_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for path in [current, *current.parents]:
        if (path / CONFIG_FILE).exists():
            return path
    return current


def resolve_config_path(start: Path | None = None, config_path: str | Path | None = None) -> Path:
    if config_path is not None:
        candidate = Path(config_path).expanduser()
        if candidate.is_dir():
            candidate = candidate / CONFIG_FILE
        return candidate.resolve()

    env_config = os.environ.get(CONFIG_ENV_VAR, "").strip()
    if env_config:
        candidate = Path(env_config).expanduser()
        if candidate.is_dir():
            candidate = candidate / CONFIG_FILE
        return candidate.resolve()

    env_root = os.environ.get(ROOT_ENV_VAR, "").strip()
    if env_root:
        return (Path(env_root).expanduser() / CONFIG_FILE).resolve()

    return (project_root(start) / CONFIG_FILE).resolve()


def load_config(start: Path | None = None, config_path: str | Path | None = None) -> KitConfig:
    config_path = resolve_config_path(start=start, config_path=config_path)
    root = config_path.parent
    if not config_path.exists():
        raise ConfigError(f"config_missing:{config_path}")
    data = json.loads(config_path.read_text(encoding="utf-8"))
    raw_roots = data.get("knowledge_roots")
    if not isinstance(raw_roots, list):
        raise ConfigError("knowledge_roots_must_be_list")
    roots: list[KnowledgeRoot] = []
    seen: set[str] = set()
    for raw in raw_roots:
        if not isinstance(raw, dict):
            raise ConfigError("knowledge_root_must_be_object")
        knowledge_id = str(raw.get("id", "")).strip()
        if not knowledge_id:
            raise ConfigError("knowledge_id_required")
        if knowledge_id in seen:
            raise ConfigError(f"duplicate_knowledge_id:{knowledge_id}")
        seen.add(knowledge_id)
        mode = str(raw.get("mode", "")).strip()
        if mode not in VALID_MODES:
            raise ConfigError(f"invalid_mode:{knowledge_id}:{mode}")
        roots.append(
            KnowledgeRoot(
                id=knowledge_id,
                name=str(raw.get("name") or knowledge_id),
                path=Path(str(raw.get("path", ""))).expanduser().resolve(),
                enabled=bool(raw.get("enabled", False)),
                mode=mode,
                priority=int(raw.get("priority", 0)),
            )
        )
    return KitConfig(root=root, data=data, knowledge_roots=roots)


def validate_config(config: KitConfig) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    for root in config.knowledge_roots:
        if not root.enabled:
            continue
        if not root.path.exists():
            issues.append({"severity": "major", "knowledge": root.id, "code": "knowledge_path_missing", "path": str(root.path)})
            continue
        for relative in ["raw", "wiki", "wiki/index.md", "wiki/schema.md", "wiki/log.md", "wiki/overview.md", "relations", "state"]:
            target = root.path / relative
            if not target.exists():
                issues.append({"severity": "major", "knowledge": root.id, "code": "required_path_missing", "path": str(target)})
    return issues

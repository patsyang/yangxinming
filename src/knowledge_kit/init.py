from __future__ import annotations

import json
from pathlib import Path

from .config import KitConfig
from .errors import ConfigError
from .lint import validate_structure
from .runtime import append_ledger, new_run_id, now_iso, write_run_artifact
from .workflow_contract import INIT_SCAFFOLD_KIND, RELATION_FILE_NAMES

DIRECTORIES = [
    "raw",
    "wiki",
    "wiki/concepts",
    "wiki/entities",
    "wiki/sources",
    "wiki/queries",
    "relations",
    "state",
]

CODE_DIRECTORIES = [
    "wiki/entities/code",
    "wiki/entities/code/features",
    "wiki/entities/code/modules",
    "wiki/sources/code",
    "wiki/sources/code/kcode-runs",
]

BASE_SCHEMA = """# Schema

本知识库遵循 Karpathy Wiki 结构。

## 页面类型

- `concept`: 抽象概念、术语和稳定分类。
- `entity`: 具体对象、产品能力、模块、功能、系统组件或数据对象。
- `source`: 原始来源的结构化摘要，不复制全文。
- `query`: 值得沉淀的跨页面查询综合。
- `overview`: 跨来源高层综合。

## 通用规则

- 正式事实必须可追溯到 `sources`、source 页或明确的维护材料。
- 更新既有对象时优先原位更新，不创建平行页面。
- 每次正式变更必须同步判断 `wiki/index.md`、`wiki/log.md`、`wiki/overview.md` 和 `relations/`。
- `raw/` 是来源真源，`state/` 是运行状态，不是正文知识。
"""

CODE_SCHEMA_FIXED_SECTIONS = """
### 固定章节

`feature_implementation` 和 `coding_playbook` 正式页面必须使用以下二级标题，便于 `/k query` 稳定抽取 Agentic Coding 和 PRD 设计证据：

- `## 现有实现`
- `## 代码定位`
- `## 实现链`
- `## 复用边界`
- `## 改动点`
- `## 暂不应改动`
- `## 数据/权限/运行约束`
- `## 测试/验证路径`
- `## PRD 设计影响`
- `## 缺口与继续探索`
"""

CODE_SCHEMA_APPENDIX = """
## Code Knowledge

当 knowledge 配置了 code workspace 或维护材料来自 `/k code` handoff 时，正式代码知识必须沉淀为可查询的 wiki 页面，不能把 `state/kcode-runs/**` artifact 原样复制成正文。

### 目录约定

- `wiki/sources/code/kcode-runs/<run_id>/<shard>.md`: KCode handoff source summary。
- `wiki/entities/code/features/<module-or-domain>/<slug>.md`: 代码功能、业务能力或 feature implementation。
- `wiki/entities/code/modules/<repo-or-module>.md`: 仓库、模块、运行组件或 code map。

### 知识层级

- `code_map`: 只能写导航、仓库职责、模块边界、入口线索和后续探索提示。
- `feature_implementation`: 必须写现有实现、代码定位、实现链、数据/权限/运行约束、PRD 设计影响、缺口与继续探索。
- `coding_playbook`: 必须额外写复用边界、改动点、暂不应改动、数据约束、运行约束、测试/验证路径。

### 代码知识页必备内容

- 现有实现。
- 代码定位：仓库相对路径、类名、函数名、endpoint、配置名或测试入口；这些标识保持原文。
- 复用边界和改动点。
- 数据、权限、运行时或部署约束。
- 测试/验证路径。
- PRD 设计影响。
- 缺口与继续探索。

带 `blocking_gaps` 的 KCode finding 不能写成当前事实，只能进入缺口或阻断项。
""" + CODE_SCHEMA_FIXED_SECTIONS

WIKI_FILES = {
    "wiki/schema.md": BASE_SCHEMA,
    "wiki/index.md": "# 索引\n\n",
    "wiki/log.md": "# 日志\n\n",
    "wiki/overview.md": "# 总览\n\n",
}

RELATION_FILES = {
    "relation-graph.json": {"nodes": [], "edges": []},
    "requirement-map.json": {},
    "alias-lookup.json": {},
}


def run_init(config: KitConfig, knowledge_id: str) -> dict:
    root = config.require_write_root(knowledge_id)
    run_id = new_run_id("init")
    created: list[str] = []
    existing: list[str] = []
    updated: list[str] = []

    ensure_directory(root.path, root.path, created, existing)
    for relative in directories_for(config, knowledge_id):
        ensure_directory(root.path / relative, root.path, created, existing)

    for relative, content in wiki_files_for(config, knowledge_id).items():
        ensure_file(root.path / relative, root.path, content, created, existing)
    if is_code_knowledge(config, knowledge_id):
        ensure_code_schema_appendix(root.path / "wiki" / "schema.md", root.path, updated)

    for name in RELATION_FILE_NAMES:
        content = json.dumps(RELATION_FILES[name], ensure_ascii=False, indent=2) + "\n"
        ensure_file(root.relations_dir / name, root.path, content, created, existing)

    validation = validate_structure(config, knowledge_id=knowledge_id)
    payload = {
        "run_id": run_id,
        "kind": INIT_SCAFFOLD_KIND,
        "operation": "INIT",
        "cli_role": "knowledge_root_scaffold",
        "knowledge_target": root.id,
        "actual_knowledge_root": str(root.path),
        "created": created,
        "existing": existing,
        "updated": updated,
        "overwritten": [],
        "validation": validation,
        "created_at": now_iso(),
    }
    artifact = write_run_artifact(config.runs_dir, run_id, "init-scaffold.json", payload)
    append_ledger(config.state_dir, {"run_id": run_id, "kind": INIT_SCAFFOLD_KIND, "artifact": str(artifact), "created_at": payload["created_at"]})
    return payload


def ensure_directory(path: Path, root: Path, created: list[str], existing: list[str]) -> None:
    if path.exists() and not path.is_dir():
        raise ConfigError(f"init_path_conflict:{relative_to_root(path, root)}")
    if path.exists():
        existing.append(relative_to_root(path, root))
        return
    path.mkdir(parents=True, exist_ok=True)
    created.append(relative_to_root(path, root))


def ensure_file(path: Path, root: Path, content: str, created: list[str], existing: list[str]) -> None:
    if path.exists() and not path.is_file():
        raise ConfigError(f"init_path_conflict:{relative_to_root(path, root)}")
    if path.exists():
        existing.append(relative_to_root(path, root))
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    created.append(relative_to_root(path, root))


def ensure_code_schema_appendix(path: Path, root: Path, updated: list[str]) -> None:
    if not path.exists() or not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    next_text = text.rstrip()
    if "## Code Knowledge" not in text:
        next_text += "\n\n" + CODE_SCHEMA_APPENDIX.lstrip()
    elif "### 固定章节" not in text:
        next_text += "\n\n" + CODE_SCHEMA_FIXED_SECTIONS.lstrip()
    next_text = next_text.replace(
        "`feature_implementation`: 必须写当前实现、代码定位、实现链、数据/权限/运行约束、PRD 设计影响、缺口与继续探索。",
        "`feature_implementation`: 必须写现有实现、代码定位、实现链、数据/权限/运行约束、PRD 设计影响、缺口与继续探索。",
    )
    next_text = next_text.replace("- 当前实现。", "- 现有实现。")
    if next_text != text.rstrip():
        path.write_text(next_text + "\n", encoding="utf-8")
        updated.append(relative_to_root(path, root))


def relative_to_root(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return "."


def directories_for(config: KitConfig, knowledge_id: str) -> list[str]:
    values = list(DIRECTORIES)
    if is_code_knowledge(config, knowledge_id):
        values.extend(item for item in CODE_DIRECTORIES if item not in values)
    return values


def wiki_files_for(config: KitConfig, knowledge_id: str) -> dict[str, str]:
    files = dict(WIKI_FILES)
    if is_code_knowledge(config, knowledge_id):
        files["wiki/schema.md"] = BASE_SCHEMA.rstrip() + "\n\n" + CODE_SCHEMA_APPENDIX.lstrip()
    return files


def is_code_knowledge(config: KitConfig, knowledge_id: str) -> bool:
    code_config = config.data.get("code", {})
    workspaces = code_config.get("workspaces", {}) if isinstance(code_config, dict) else {}
    return isinstance(workspaces, dict) and knowledge_id in workspaces

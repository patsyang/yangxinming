from __future__ import annotations

import re

from .query_intent import MODULE_CANONICAL, canonical_module
from .wiki import IndexEntry

CODE_REPOSITORY_MAP_HINTS = {
    "repository-map",
    "repo-map",
    "product-code-index",
    "code-index",
    "仓库导航",
    "仓库地图",
    "仓库总图",
    "仓库入口",
    "code_map",
    "代码地图",
    "产品功能到代码仓库",
    "产品能力到代码仓库",
    "产品能力到 repo",
    "产品能力到repo",
    "产品功能到 repo",
    "产品功能到repo",
    "产品代码索引",
    "功能到代码",
    "repo 和入口映射",
    "repo/入口映射",
}


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
def repo_wiki_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    return normalized if normalized.startswith("wiki/") else f"wiki/{normalized}"


def index_path_from_repo(repo_path: str) -> str:
    normalized = repo_path.replace("\\", "/")
    return normalized.removeprefix("wiki/")


def page_role(path: str) -> str:
    normalized = path.replace("\\", "/").removeprefix("wiki/")
    if normalized.startswith("sources/"):
        return "source"
    if "/data-dictionary/" in normalized:
        return "data_dictionary"
    if "/regulation/requirements/" in normalized:
        return "regulation_requirement"
    if "/solution/" in normalized:
        return "solution"
    if "/features/" in normalized:
        return "feature"
    if "/modules/" in normalized:
        return "module"
    if normalized.startswith("concepts/"):
        return "concept"
    if normalized.startswith("queries/"):
        return "query"
    return "unknown"


def is_code_feature_path(path: str) -> bool:
    normalized = path.replace("\\", "/").removeprefix("wiki/")
    return normalized.startswith("entities/code/features/")


def is_code_module_path(path: str) -> bool:
    normalized = path.replace("\\", "/").removeprefix("wiki/")
    return normalized.startswith("entities/code/modules/")


def is_code_repository_map(candidate: dict) -> bool:
    path = str(candidate.get("path", "")).replace("\\", "/").lower()
    title = str(candidate.get("title", "")).lower()
    summary = str(candidate.get("summary", "")).lower()
    if not is_code_module_path(path):
        return False
    haystack = " ".join([path, title, summary])
    return any(hint.lower() in haystack for hint in CODE_REPOSITORY_MAP_HINTS)


def module_from_path(path: str, module_aliases: dict[str, str] | None = None) -> str | None:
    modules = modules_from_path(path, module_aliases)
    return modules[0] if modules else None


def modules_from_path(path: str, module_aliases: dict[str, str] | None = None) -> list[str]:
    normalized = path.replace("\\", "/").removeprefix("wiki/")
    parts = normalized.split("/")
    modules: list[str] = []
    for part in parts:
        module = canonical_module(part, module_aliases)
        if module and module not in modules:
            modules.append(module)
    fallback = canonical_module(parts[-1], module_aliases) if parts else None
    if fallback and fallback not in modules:
        modules.append(fallback)
    return modules


def modules_from_entry(entry: IndexEntry, module_aliases: dict[str, str] | None = None) -> list[str]:
    values = [
        *modules_from_path(entry.path, module_aliases),
        *modules_from_text(entry.title, module_aliases),
        *modules_from_text(entry.summary, module_aliases),
    ]
    return _unique(values)


def modules_from_text(value: str, module_aliases: dict[str, str] | None = None) -> list[str]:
    modules: list[str] = []
    lowered = value.lower()
    aliases = module_aliases if module_aliases is not None else MODULE_CANONICAL
    for key, module in aliases.items():
        if re.search(rf"(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])", lowered) and module not in modules:
            modules.append(module)
    return modules


def page_type_for_role(role: str) -> str:
    if role == "source":
        return "source"
    if role == "concept":
        return "concept"
    if role == "query":
        return "query"
    return "entity"


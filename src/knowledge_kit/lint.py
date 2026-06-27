from __future__ import annotations

import re
from pathlib import Path

from .config import KitConfig, KnowledgeRoot, validate_config
from .frontmatter import parse_frontmatter
from .wiki import IndexEntry, iter_wiki_pages, parse_index, wikilink_targets
from .workflow_contract import MECHANICAL_LINT_KIND, RELATION_FILE_NAMES, STRUCTURE_VALIDATION_KIND

CODE_FEATURE_REQUIRED_HEADINGS = [
    "现有实现",
    "代码定位",
    "实现链",
    "复用边界",
    "改动点",
    "暂不应改动",
    "数据/权限/运行约束",
    "测试/验证路径",
    "PRD 设计影响",
    "缺口与继续探索",
]


def validate_structure(config: KitConfig, knowledge_id: str | None = None) -> dict:
    if knowledge_id:
        root = config.get(knowledge_id)
        scoped = KitConfig(root=config.root, data=config.data, knowledge_roots=[root])
        issues = validate_config(scoped)
    else:
        issues = validate_config(config)
    return {
        "kind": STRUCTURE_VALIDATION_KIND,
        "karpathy_lint": False,
        "passed": not issues,
        "issues": issues,
    }


def lint_one(root: KnowledgeRoot, *, is_code_knowledge: bool = False) -> dict:
    issues: list[dict] = []
    if not root.enabled:
        return {"knowledge": root.id, "kind": MECHANICAL_LINT_KIND, "mechanical_lint_only": True, "skipped": True, "reason": "knowledge_disabled", "issues": []}
    for required in [root.raw_dir, root.wiki_dir, root.relations_dir, root.state_dir]:
        if not required.exists():
            issues.append({"severity": "major", "code": "required_path_missing", "path": str(required)})
    pages = iter_wiki_pages(root)
    by_stem = {page.path.stem: page for page in pages}
    by_title = {page.title: page for page in pages}
    for page in pages:
        if page.path.name in {"index.md", "log.md", "schema.md", "overview.md"}:
            continue
        text = page.path.read_text(encoding="utf-8", errors="replace")
        meta, body = parse_frontmatter(text)
        for field in ["title", "type", "created", "updated", "sources"]:
            if field not in meta:
                issues.append({"severity": "minor", "code": "frontmatter_field_missing", "path": page.repo_path, "field": field})
        if is_thin_source_summary(page.repo_path, str(meta.get("type") or ""), body):
            issues.append({"severity": "minor", "code": "source_summary_too_thin", "path": page.repo_path})
        lint_code_knowledge_page(root, page.repo_path, meta, body, issues)
        for target in wikilink_targets(text):
            normalized = target.split("|", 1)[0].strip()
            target_stem = Path(normalized).stem
            if target_stem not in by_stem and normalized not in by_title:
                issues.append({"severity": "minor", "code": "broken_wikilink", "path": page.repo_path, "target": target})
    index_path = root.wiki_dir / "index.md"
    index_text = index_path.read_text(encoding="utf-8", errors="replace") if index_path.exists() else ""
    for page in pages:
        if page.path.name in {"index.md", "log.md", "schema.md", "overview.md"}:
            continue
        rel_to_wiki = page.path.relative_to(root.wiki_dir).as_posix()
        if rel_to_wiki not in index_text:
            issues.append({"severity": "minor", "code": "index_entry_missing", "path": page.repo_path})
    for name in RELATION_FILE_NAMES:
        if not (root.relations_dir / name).exists():
            issues.append({"severity": "minor", "code": "relation_file_missing", "path": f"relations/{name}"})
    if is_code_knowledge:
        lint_code_knowledge_readiness(root, pages, index_text, issues)
    return {
        "knowledge": root.id,
        "kind": MECHANICAL_LINT_KIND,
        "mechanical_lint_only": True,
        "skipped": False,
        "passed": not issues,
        "checked_subset": [
            "required_paths",
            "frontmatter_fields",
            "broken_wikilinks",
            "index_coverage",
            "relation_files_present",
            "source_summary_thinness",
            "code_knowledge_fixed_sections",
            "code_knowledge_readiness",
            "code_feature_source_trace",
            "code_feature_source_summary_exists",
        ],
        "not_checked_by_cli": [
            "contradictions",
            "stale_claims",
            "missing_concepts",
            "data_gaps",
            "semantic_thin_pages",
        ],
        "issues": issues,
    }


def is_thin_source_summary(repo_path: str, page_type: str, body: str) -> bool:
    if page_type != "source" and not repo_path.startswith("wiki/sources/"):
        return False
    if "## Source Snapshot" not in body or "## Outline" not in body:
        return False
    summary = section_text(body, "Summary")
    return len(summary.strip()) < 80


def lint_code_knowledge_page(root: KnowledgeRoot, repo_path: str, meta: dict, body: str, issues: list[dict]) -> None:
    if not repo_path.startswith("wiki/entities/code/features/"):
        return
    for heading in CODE_FEATURE_REQUIRED_HEADINGS:
        if f"## {heading}" not in body:
            issues.append({"severity": "minor", "code": "code_feature_required_section_missing", "path": repo_path, "section": heading})
            continue
        text = section_text(body, heading)
        if code_feature_section_is_placeholder(text):
            issues.append({"severity": "minor", "code": "code_feature_section_not_substantive", "path": repo_path, "section": heading})
    if not has_code_locator(section_text(body, "代码定位")):
        issues.append({"severity": "minor", "code": "code_feature_code_locator_missing", "path": repo_path})
    sources = meta.get("sources")
    if not has_kcode_source_summary(sources):
        issues.append({"severity": "minor", "code": "code_feature_source_trace_missing", "path": repo_path})
    else:
        for missing in missing_kcode_source_summaries(root, sources):
            issues.append({"severity": "minor", "code": "code_feature_source_summary_missing", "path": repo_path, "source": missing})


def lint_code_knowledge_readiness(root: KnowledgeRoot, pages: list, index_text: str, issues: list[dict]) -> None:
    schema_path = root.wiki_dir / "schema.md"
    schema_text = schema_path.read_text(encoding="utf-8", errors="replace") if schema_path.exists() else ""
    if "Code Knowledge" not in schema_text:
        issues.append({"severity": "major", "code": "code_schema_missing", "path": "wiki/schema.md"})
    code_pages = [
        page
        for page in pages
        if page.repo_path.startswith("wiki/entities/code/features/") or page.repo_path.startswith("wiki/entities/code/modules/")
    ]
    if not code_pages:
        issues.append({"severity": "major", "code": "code_knowledge_pages_missing", "path": "wiki/entities/code"})
    code_index_hits = [page for page in code_pages if page.path.relative_to(root.wiki_dir).as_posix() in index_text]
    if code_pages and not code_index_hits:
        issues.append({"severity": "major", "code": "code_knowledge_index_missing", "path": "wiki/index.md"})
    lint_code_index_summaries(root, code_pages, issues)


def lint_code_index_summaries(root: KnowledgeRoot, code_pages: list, issues: list[dict]) -> None:
    entries_by_path: dict[str, IndexEntry] = {entry.path.replace("\\", "/"): entry for entry in parse_index(root)}
    for page in code_pages:
        if not page.repo_path.startswith("wiki/entities/code/features/"):
            continue
        rel_to_wiki = page.path.relative_to(root.wiki_dir).as_posix()
        entry = entries_by_path.get(rel_to_wiki)
        if entry is None:
            continue
        if not has_code_locator(entry.summary):
            issues.append(
                {
                    "severity": "minor",
                    "code": "code_feature_index_summary_not_actionable",
                    "path": f"wiki/{rel_to_wiki}",
                }
            )


def has_code_locator(body: str) -> bool:
    patterns = [
        r"\b[\w./-]+\.(?:java|kt|js|jsx|ts|tsx|vue|py|go|xml|yml|yaml|json|sql)\b",
        r"`/[A-Za-z0-9_$:{}./-]+`",
        r"\b[A-Z][A-Za-z0-9_]*(?:Controller|Service|Repository|Mapper|Dao|Client|DTO|Dto|Entity|Config)\b",
    ]
    return any(re.search(pattern, body) for pattern in patterns)


def has_kcode_source_summary(value: object) -> bool:
    if not isinstance(value, list):
        return False
    for item in value:
        normalized = str(item).replace("\\", "/").lstrip("/")
        if normalized.startswith("wiki/sources/code/kcode-runs/") or normalized.startswith("sources/code/kcode-runs/"):
            return True
    return False


def missing_kcode_source_summaries(root: KnowledgeRoot, value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    missing: list[str] = []
    for item in value:
        normalized = str(item).replace("\\", "/").lstrip("/")
        if not (normalized.startswith("wiki/sources/code/kcode-runs/") or normalized.startswith("sources/code/kcode-runs/")):
            continue
        if not frontmatter_source_exists(root, normalized):
            missing.append(normalized)
    return missing


def frontmatter_source_exists(root: KnowledgeRoot, normalized: str) -> bool:
    if normalized.startswith("wiki/"):
        candidate = root.path / normalized
    elif normalized.startswith("sources/"):
        candidate = root.wiki_dir / normalized
    else:
        return False
    try:
        candidate.resolve().relative_to(root.path.resolve())
    except ValueError:
        return False
    return candidate.exists() and candidate.is_file()


def code_feature_section_is_placeholder(text: str) -> bool:
    stripped = re.sub(r"(?m)^\s*[-*]\s*", "", text or "")
    normalized = re.sub(r"\s+", "", stripped)
    if not normalized:
        return True
    placeholders = [
        "待补充",
        "未提供",
        "当前handoff未提供",
        "不得写入",
        "不得声称",
        "不得从目录结构自行推断",
        "需要继续探索后再确定",
    ]
    if any(item.lower() in normalized.lower() for item in placeholders):
        return True
    return bool(re.search(r"(?<![A-Za-z0-9_/.-])(?:TODO|TBD)(?![A-Za-z0-9_/.-])", stripped, flags=re.IGNORECASE))


def section_text(body: str, heading: str) -> str:
    marker = f"## {heading}"
    start = body.find(marker)
    if start == -1:
        return ""
    start += len(marker)
    next_heading = body.find("\n## ", start)
    if next_heading == -1:
        return body[start:].strip()
    return body[start:next_heading].strip()


def run_lint(config: KitConfig, knowledge_id: str | None = None, all_enabled: bool = False) -> dict:
    if knowledge_id:
        roots = [config.require_query_root(knowledge_id)]
    else:
        roots = config.enabled_roots()
    code_roots = code_knowledge_ids(config)
    results = [lint_one(root, is_code_knowledge=root.id in code_roots) for root in roots]
    issues = [issue for result in results for issue in result.get("issues", [])]
    return {
        "kind": MECHANICAL_LINT_KIND,
        "mechanical_lint_only": True,
        "karpathy_lint": False,
        "passed": not issues,
        "results": results,
    }


def code_knowledge_ids(config: KitConfig) -> set[str]:
    code_config = config.data.get("code", {})
    workspaces = code_config.get("workspaces", {}) if isinstance(code_config, dict) else {}
    if not isinstance(workspaces, dict):
        return set()
    return {str(item) for item in workspaces}

from __future__ import annotations

from .query_pages import (
    is_code_feature_path,
    is_code_module_path,
    is_code_repository_map,
    modules_from_entry,
    page_role,
    page_type_for_role,
    repo_wiki_path,
)
from .wiki import IndexEntry


def score_signals(query_intent: dict, entry: IndexEntry, module_aliases: dict[str, str] | None = None) -> list[str]:
    signals: list[str] = []
    modules = modules_from_entry(entry, module_aliases)
    requested_modules = query_intent.get("modules", [])
    if requested_modules and any(module in requested_modules for module in modules):
        signals.append("module_match")
    if modules and requested_modules and not any(module in requested_modules for module in modules):
        signals.append("module_mismatch")
    role = page_role(entry.path)
    signals.append(f"role:{role}")
    if query_intent.get("wants_code_navigation") and is_code_module_path(entry.path):
        signals.append("code_map_preferred")
    if query_intent.get("wants_code_knowledge") and not query_intent.get("wants_code_navigation") and is_code_feature_path(entry.path):
        signals.append("code_feature_preferred")
    return signals


def candidate_from_entry(score: float, entry: IndexEntry, query_intent: dict, module_aliases: dict[str, str] | None = None) -> dict:
    repo_path = repo_wiki_path(entry.path)
    role = page_role(entry.path)
    modules = modules_from_entry(entry, module_aliases)
    module = modules[0] if modules else None
    return {
        "path": repo_path,
        "title": entry.title,
        "type": page_type_for_role(role),
        "page_role": role,
        "module": module or "",
        "modules": modules,
        "index_summary": entry.summary,
        "score": round(score, 2),
        "signals": score_signals(query_intent, entry, module_aliases),
        "intent_fit": intent_fit(role, query_intent),
        "module_fit": module_fit(modules, query_intent),
        "source_policy": source_policy(role, query_intent),
        "selection_status": "candidate",
        "source": "index.md",
    }


def intent_fit(role: str, query_intent: dict) -> str:
    if role == "module" and query_intent.get("wants_code_navigation"):
        return "navigation_primary"
    if role == "source":
        return "requested" if query_intent.get("wants_source") else "provenance_only"
    if role == "data_dictionary":
        return "requested" if query_intent.get("wants_data_dictionary") else "supporting"
    if role == "regulation_requirement":
        return "requested" if query_intent.get("wants_regulation") else "out_of_intent"
    return "primary"


def module_fit(candidate_modules: list[str] | str | None, query_intent: dict) -> str:
    modules = query_intent.get("modules", [])
    if not modules:
        return "not_requested"
    normalized = candidate_modules
    if isinstance(normalized, str):
        normalized_modules = [normalized] if normalized else []
    else:
        normalized_modules = [str(item) for item in (normalized or []) if str(item)]
    if not normalized_modules:
        return "neutral"
    return "same_module" if any(module in modules for module in normalized_modules) else "module_mismatch"


def source_policy(role: str, query_intent: dict) -> str:
    if role != "source":
        return "normal"
    return "requested" if query_intent.get("wants_source") else "provenance_only"


def code_map_fallback_candidates(candidates: list[dict]) -> list[dict]:
    module_maps = [
        item
        for item in candidates
        if item.get("page_role") == "module" and is_code_module_path(str(item.get("path", "")))
    ]
    repository_maps = [item for item in module_maps if is_code_repository_map(item)]
    return repository_maps or module_maps


def primary_allowed(candidate: dict, query_intent: dict, mode: str, include_source: bool, include_cross_module: bool) -> bool:
    role = candidate.get("page_role")
    if role == "source" and not (include_source or query_intent.get("wants_source")):
        return False
    if role == "regulation_requirement" and not (query_intent.get("wants_regulation") or mode == "exhaustive"):
        return False
    modules = query_intent.get("modules", [])
    candidate_modules = candidate_module_values(candidate)
    if len(modules) == 1 and candidate_modules and not candidate_matches_modules(candidate, modules) and not (include_cross_module or query_intent.get("wants_cross_module") or mode == "exhaustive"):
        return False
    return True


def candidate_module_values(candidate: dict) -> list[str]:
    modules = candidate.get("modules")
    if isinstance(modules, list):
        values = [str(item) for item in modules if str(item)]
    else:
        values = []
    module = str(candidate.get("module") or "")
    if module and module not in values:
        values.append(module)
    return values


def candidate_matches_modules(candidate: dict, modules: list[str]) -> bool:
    values = candidate_module_values(candidate)
    return bool(values and any(module in modules for module in values))


def primary_rank(candidate: dict, query_intent: dict) -> tuple[float, float, str]:
    role = candidate.get("page_role", "unknown")
    priority = {
        "feature": 0,
        "module": 1,
        "data_dictionary": 2,
        "concept": 3,
        "solution": 4,
        "regulation_requirement": 5,
        "source": 6,
        "unknown": 7,
    }.get(role, 7)
    if role == "source" and query_intent.get("wants_source"):
        priority = -1
    if role == "data_dictionary" and query_intent.get("wants_data_dictionary"):
        priority = -1
    if role == "module" and query_intent.get("wants_code_navigation") and is_code_module_path(str(candidate.get("path", ""))):
        priority = -1
    if role == "feature" and query_intent.get("wants_code_knowledge") and is_code_feature_path(str(candidate.get("path", ""))):
        priority = -0.5
    return (priority, -float(candidate.get("score", 0.0)), str(candidate.get("path")))

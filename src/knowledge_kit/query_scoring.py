from __future__ import annotations

from .query_intent import (
    canonical_module,
    tokens,
    wants_code_navigation,
    wants_data_dictionary,
    wants_runtime_boundary,
    wants_source_page,
)
from .query_pages import is_code_feature_path, is_code_module_path
from .wiki import IndexEntry


RUNTIME_BOUNDARY_PAGE_HINTS = {
    "运行时",
    "消费边界",
    "运行时边界",
    "运行时消费",
    "执行链",
    "执行端",
    "缺口",
    "runtime",
    "consumer",
}


def score_index_entry(query: str, entry: IndexEntry, *, prefer_code_knowledge: bool = False, module_aliases: dict[str, str] | None = None) -> float:
    lowered_query = query.lower()
    query_tokens = tokens(query)
    title = entry.title.lower()
    path = entry.path.lower()
    summary = entry.summary.lower()
    score = 0.0
    if lowered_query and lowered_query in title:
        score += 12
    elif lowered_query and lowered_query in summary:
        score += 6
    for token in query_tokens:
        token_lower = token.lower()
        if not token_lower:
            continue
        if token_lower in title:
            score += 5
        if token_lower in summary:
            score += 2
        if token_lower in path:
            score += 0.8 if canonical_module(token, module_aliases) else 1.2
    if "/features/" in path or "features/" in path:
        score += 4.0
    if "/modules/" in path:
        score += 0.4
    if prefer_code_knowledge:
        if wants_code_navigation(query) and is_code_module_path(path):
            score += 14.0
        elif wants_code_navigation(query) and is_code_feature_path(path):
            score -= 8.0
        elif is_code_feature_path(path):
            score += 10.0
        elif is_code_module_path(path):
            score += 2.0
        if wants_runtime_boundary(query) and is_code_feature_path(path):
            boundary_text = " ".join([title, summary, path])
            if any(hint.lower() in boundary_text for hint in RUNTIME_BOUNDARY_PAGE_HINTS):
                score += 28.0
    elif is_code_feature_path(path):
        score -= 4.0
    elif is_code_module_path(path):
        score -= 2.0
    if path.startswith("sources/") and not wants_source_page(query):
        score -= 20.0
    if "data-dictionary" in path and not wants_data_dictionary(query):
        score -= 3.0
    return score

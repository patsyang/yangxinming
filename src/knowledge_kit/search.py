from __future__ import annotations

from pathlib import Path

from .config import KitConfig, KnowledgeRoot
from .query_intent import (
    code_query_topic_terms,
    detect_query_intent,
    has_configured_code_workspace,
    is_code_knowledge_root,
)
from .query_pages import (
    index_path_from_repo,
    is_code_feature_path,
    is_code_module_path,
    is_code_repository_map,
    modules_from_path,
    page_role,
)
from .query_candidates import (
    candidate_from_entry,
    candidate_matches_modules,
    candidate_module_values,
    code_map_fallback_candidates,
    primary_allowed,
    primary_rank,
    score_signals,
)
from .query_modules import infer_module_aliases
from .query_scoring import score_index_entry
from .runtime import append_ledger, new_run_id, now_iso, write_run_artifact
from .semantic_plan import build_semantic_plan, collection_scope, is_collection_plan, is_entity_attribute_plan
from .wiki import WikiPage, extract_page_links, parse_index, read_wiki_page, resolve_page_link
from .workflow_contract import CLI_LIMITATIONS, QUERY_MECHANISM, QUERY_READ_PLAN_KIND


DEFAULT_CANDIDATE_LIMIT = 80
DEFAULT_EVIDENCE_BUDGET = 8
DEFAULT_RELATIONSHIP_EXPANSION_LIMIT = 12
FOCUSED_CODE_FEATURE_PRIMARY_LIMIT = 3
FOCUSED_CODE_FEATURE_SCORE_GAP = 15.0
FOCUSED_CODE_FEATURE_SCORE_RATIO = 0.65


def selected_query_roots(config: KitConfig, knowledge_id: str | None) -> list[KnowledgeRoot]:
    if knowledge_id:
        return [config.require_query_root(knowledge_id)]
    return config.enabled_roots()


def query_one(
    root: KnowledgeRoot,
    query: str,
    limit: int | None = None,
    evidence_budget: int | None = None,
    mode: str = "focused",
    include_source: bool = False,
    include_cross_module: bool = False,
    semantic_plan: dict | None = None,
    code_knowledge_root: bool = False,
) -> dict:
    candidate_limit = limit or DEFAULT_CANDIDATE_LIMIT
    evidence_limit = evidence_budget or DEFAULT_EVIDENCE_BUDGET
    index_entries = parse_index(root)
    module_aliases = infer_module_aliases(index_entries)
    query_intent = detect_query_intent(query, module_aliases)
    if code_knowledge_root:
        query_intent["wants_code_knowledge"] = True
    semantic_plan = build_semantic_plan(query, query_intent, semantic_plan)
    scored_entries = []
    for entry in index_entries:
        score = score_index_entry(
            query,
            entry,
            prefer_code_knowledge=bool(query_intent.get("wants_code_knowledge")),
            module_aliases=module_aliases,
        )
        if score <= 0:
            continue
        scored_entries.append((score, entry))
    scored_entries.sort(key=lambda item: (-item[0], item[1].path))
    candidate_entries = scored_entries[:candidate_limit]

    index_hits = [
        {
            "title": entry.title,
            "path": entry.path,
            "summary": entry.summary,
            "score": round(score, 2),
            "signals": score_signals(query_intent, entry, module_aliases),
            "source": "wiki/index.md",
        }
        for score, entry in candidate_entries
    ]
    candidates = [candidate_from_entry(score, entry, query_intent, module_aliases) for score, entry in candidate_entries]
    primary_candidates = select_primary_candidates(candidates, query_intent, mode, include_source, include_cross_module, semantic_plan=semantic_plan)
    consulted: list[str] = ["wiki/index.md"] if (root.wiki_dir / "index.md").exists() else []
    relationship_expansion, related_candidates = expand_relationships(root, primary_candidates, consulted, module_aliases)
    candidates = merge_candidates(candidates, related_candidates)
    selected_evidence = select_evidence(
        candidates,
        primary_candidates,
        relationship_expansion,
        query_intent,
        evidence_limit,
        mode,
        include_source,
        include_cross_module,
        semantic_plan=semantic_plan,
    )
    coverage_proof = build_coverage_proof(candidates, selected_evidence, semantic_plan)
    selected_paths = {item["path"] for item in selected_evidence}
    for candidate in candidates:
        candidate["selection_status"] = "selected" if candidate["path"] in selected_paths else "omitted"
    omitted_candidates = [
        omitted_candidate(candidate, selected_paths, query_intent, mode)
        for candidate in candidates
        if candidate["path"] not in selected_paths and candidate.get("source") == "index.md"
    ]
    related_wikilinks = [
        {
            "from": item["from"],
            "target": item["target"],
            "resolved_path": item["resolved_path"],
            "status": item["status"],
        }
        for item in relationship_expansion
    ]
    return {
        "operation": "QUERY",
        "knowledge": root.id,
        "knowledge_id": root.id,
        "name": root.name,
        "actual_knowledge_root": str(root.path),
        "enabled": root.enabled,
        "mode": root.mode,
        "index_path": "wiki/index.md",
        "index_consulted": (root.wiki_dir / "index.md").exists(),
        "query_intent": query_intent,
        "module_aliases_source": "wiki/index.md",
        "module_aliases": sorted(set(module_aliases.values())),
        "semantic_plan": semantic_plan,
        "retrieval_policy": {
            "candidate_limit": candidate_limit,
            "evidence_budget": evidence_limit,
            "mode": mode,
            "include_source": include_source,
            "include_cross_module": include_cross_module,
            "raw_reads": "forbidden",
        },
        "index_hits": index_hits,
        "candidate_pages": candidates,
        "candidate_page_paths": [item["path"] for item in candidates],
        "relationship_expansion": relationship_expansion,
        "related_wikilinks": related_wikilinks,
        "selected_evidence": selected_evidence,
        "selected_evidence_paths": [item["path"] for item in selected_evidence],
        "coverage_proof": coverage_proof,
        "omitted_candidates": omitted_candidates,
        "consulted_pages": unique(consulted),
        "query_mechanism": QUERY_MECHANISM,
        "read_plan_only": True,
        "limitations": CLI_LIMITATIONS,
    }


def select_primary_candidates(
    candidates: list[dict],
    query_intent: dict,
    mode: str,
    include_source: bool,
    include_cross_module: bool,
    semantic_plan: dict | None = None,
) -> list[dict]:
    if not candidates:
        return []
    seed_limit = 1 if mode == "focused" else 5 if mode == "exhaustive" else 3
    pool = [item for item in candidates if primary_allowed(item, query_intent, mode, include_source, include_cross_module)]
    if is_entity_attribute_plan(semantic_plan):
        owners = entity_attribute_owner_candidates(pool or candidates, query_intent)
        if owners:
            return owners[:seed_limit]
    if (
        is_collection_plan(semantic_plan)
        and not collection_scope(semantic_plan)
        and query_intent.get("wants_code_knowledge")
    ):
        fallback_maps = code_map_fallback_candidates(candidates)
        if fallback_maps:
            fallback_maps.sort(key=lambda item: primary_rank(item, query_intent))
            return fallback_maps[:1]
    if query_intent.get("wants_code_navigation"):
        code_maps = [item for item in pool if item.get("page_role") == "module" and is_code_module_path(str(item.get("path", "")))]
        if code_maps:
            pool = code_maps
    if (
        mode == "focused"
        and query_intent.get("wants_code_knowledge")
        and not query_intent.get("wants_code_navigation")
        and not code_query_topic_terms(str(query_intent.get("query") or ""))
    ):
        code_maps = [item for item in pool if item.get("page_role") == "module" and is_code_module_path(str(item.get("path", "")))]
        if code_maps:
            code_maps.sort(key=lambda item: primary_rank(item, query_intent))
            return code_maps[:1]
    modules = query_intent.get("modules", [])
    if len(modules) == 1 and not include_cross_module and not query_intent.get("wants_cross_module"):
        same_module = [item for item in pool if candidate_matches_modules(item, modules)]
        if same_module:
            pool = same_module
        elif query_intent.get("wants_code_knowledge"):
            fallback_maps = code_map_fallback_candidates(candidates) or code_map_fallback_candidates(pool)
            if fallback_maps:
                fallback_maps.sort(key=lambda item: primary_rank(item, query_intent))
                return fallback_maps[:1]
    if is_collection_plan(semantic_plan):
        owner_pages = collection_owner_candidates(pool, semantic_plan)
        if owner_pages:
            return owner_pages[:1]
    if mode == "focused" and query_intent.get("wants_code_knowledge") and not query_intent.get("wants_code_navigation"):
        topic_matched_features = [
            item
            for item in pool
            if item.get("page_role") == "feature"
            and is_code_feature_path(str(item.get("path", "")))
            and code_feature_candidate_covers_query_topic(item, query_intent)
        ]
        if topic_matched_features:
            topic_matched_paths = {item.get("path") for item in topic_matched_features}
            pool = [
                item
                for item in pool
                if item.get("page_role") != "feature"
                or not is_code_feature_path(str(item.get("path", "")))
                or item.get("path") in topic_matched_paths
            ]
    if not pool:
        pool = candidates
    pool.sort(key=lambda item: primary_rank(item, query_intent))
    selected = pool[:seed_limit]
    if mode == "focused" and query_intent.get("wants_code_knowledge") and not query_intent.get("wants_code_navigation"):
        selected = expand_focused_code_feature_primaries(pool, selected, query_intent)
    return selected


def collection_owner_candidates(candidates: list[dict], semantic_plan: dict | None) -> list[dict]:
    scope = collection_scope(semantic_plan)
    if not scope:
        return []
    owners = [
        item
        for item in candidates
        if item.get("page_role") == "module"
        and candidate_matches_modules(item, [scope])
    ]
    owners.sort(key=lambda item: (-float(item.get("score", 0.0)), str(item.get("path"))))
    return owners


def entity_attribute_owner_candidates(candidates: list[dict], query_intent: dict) -> list[dict]:
    modules = query_intent.get("modules", [])
    pool = [
        item
        for item in candidates
        if item.get("page_role") in {"feature", "concept", "query"}
        and (not modules or candidate_matches_modules(item, modules))
    ]
    if not pool:
        pool = [
            item
            for item in candidates
            if item.get("page_role") in {"feature", "concept", "query"}
        ]
    if query_intent.get("wants_code_knowledge"):
        code_features = [
            item
            for item in pool
            if item.get("page_role") == "feature" and is_code_feature_path(str(item.get("path", "")))
        ]
        if code_features:
            pool = code_features
    pool.sort(key=lambda item: primary_rank(item, query_intent))
    return pool


def expand_focused_code_feature_primaries(pool: list[dict], selected: list[dict], query_intent: dict) -> list[dict]:
    feature_pool = [
        item
        for item in pool
        if item.get("page_role") == "feature" and is_code_feature_path(str(item.get("path", "")))
    ]
    if not feature_pool or not selected:
        return selected
    top_score = float(feature_pool[0].get("score", 0.0))
    if top_score <= 0:
        return selected
    expanded = list(selected)
    selected_paths = {item.get("path") for item in expanded}
    for candidate in feature_pool:
        if len(expanded) >= FOCUSED_CODE_FEATURE_PRIMARY_LIMIT:
            break
        if candidate.get("path") in selected_paths:
            continue
        score = float(candidate.get("score", 0.0))
        if top_score - score > FOCUSED_CODE_FEATURE_SCORE_GAP:
            continue
        if score < top_score * FOCUSED_CODE_FEATURE_SCORE_RATIO:
            continue
        if not code_feature_candidate_covers_query_topic(candidate, query_intent):
            continue
        expanded.append(candidate)
        selected_paths.add(candidate.get("path"))
    return expanded


def code_feature_candidate_covers_query_topic(candidate: dict, query_intent: dict) -> bool:
    topic_terms = code_query_topic_terms(str(query_intent.get("query") or ""))
    if not topic_terms:
        return True
    text = " ".join(
        [
            str(candidate.get("title") or ""),
            str(candidate.get("index_summary") or ""),
            str(candidate.get("path") or ""),
        ]
    ).lower()
    return any(term.lower() in text for term in topic_terms)



def expand_relationships(root: KnowledgeRoot, primary_candidates: list[dict], consulted: list[str], module_aliases: dict[str, str] | None = None) -> tuple[list[dict], list[dict]]:
    expansions: list[dict] = []
    related_candidates: list[dict] = []
    seen_links: set[tuple[str, str]] = set()
    for candidate in primary_candidates:
        page = read_wiki_page(root, index_path_from_repo(candidate["path"]))
        if page is None:
            continue
        consulted.append(page.repo_path)
        for link in extract_page_links(page.body):
            if len(expansions) >= DEFAULT_RELATIONSHIP_EXPANSION_LIMIT:
                break
            key = (page.repo_path, link.target)
            if key in seen_links:
                continue
            seen_links.add(key)
            resolved = resolve_page_link(root, page, link)
            expansion = {
                "from": page.repo_path,
                "target": link.target,
                "label": link.label,
                "link_type": link.link_type,
                "anchor": link.anchor or "",
                "resolved_path": resolved.repo_path if resolved is not None else "",
                "status": "resolved" if resolved is not None else "broken",
                "reason": "explicit_link_from_primary_evidence",
            }
            expansions.append(expansion)
            if resolved is None:
                continue
            related_candidates.append(candidate_from_page(resolved, candidate, expansion, module_aliases))
    return expansions, related_candidates


def candidate_from_page(page: WikiPage, source_candidate: dict, expansion: dict, module_aliases: dict[str, str] | None = None) -> dict:
    role = page_role(page.repo_path)
    modules = modules_from_path(page.repo_path, module_aliases)
    module = modules[0] if modules else None
    return {
        "path": page.repo_path,
        "title": page.title,
        "type": page.page_type,
        "page_role": role,
        "module": module or "",
        "modules": modules,
        "index_summary": page.summary,
        "score": round(float(source_candidate.get("score", 0.0)) * 0.75, 2),
        "signals": ["explicit_link_from_primary_evidence", f"role:{role}"],
        "intent_fit": "linked",
        "module_fit": "linked",
        "source_policy": "linked_provenance" if role == "source" else "normal",
        "selection_status": "candidate",
        "source": f"{expansion['link_type']}:{expansion['from']}",
    }


def merge_candidates(index_candidates: list[dict], related_candidates: list[dict]) -> list[dict]:
    merged: list[dict] = []
    seen: set[str] = set()
    for item in [*index_candidates, *related_candidates]:
        path = item["path"]
        if path in seen:
            continue
        seen.add(path)
        merged.append(item)
    return merged


def select_evidence(
    candidates: list[dict],
    primary_candidates: list[dict],
    relationship_expansion: list[dict],
    query_intent: dict,
    evidence_budget: int,
    mode: str,
    include_source: bool,
    include_cross_module: bool,
    semantic_plan: dict | None = None,
) -> list[dict]:
    if is_collection_plan(semantic_plan):
        return select_collection_evidence(candidates, primary_candidates, semantic_plan, evidence_budget)
    if is_entity_attribute_plan(semantic_plan):
        return select_entity_attribute_evidence(
            candidates,
            primary_candidates,
            relationship_expansion,
            query_intent,
            evidence_budget,
        )
    selected: list[dict] = []
    by_path = {item["path"]: item for item in candidates}
    for candidate in primary_candidates:
        add_selected(selected, candidate, "primary", "top_relevant_primary_page", evidence_budget)
    for expansion in relationship_expansion:
        resolved_path = expansion.get("resolved_path")
        if not resolved_path or resolved_path not in by_path:
            continue
        candidate = by_path[resolved_path]
        role = "provenance" if candidate.get("page_role") == "source" and not query_intent.get("wants_source") else "supporting"
        add_selected(selected, candidate, role, "explicit_link_from_primary_evidence", evidence_budget)
    if mode in {"balanced", "exhaustive"}:
        for candidate in candidates:
            if len(selected) >= evidence_budget:
                break
            if any(item["path"] == candidate["path"] for item in selected):
                continue
            if evidence_allowed(candidate, query_intent, mode, include_source, include_cross_module):
                add_selected(selected, candidate, "supporting", "additional_ranked_candidate", evidence_budget)
    if query_intent.get("wants_code_knowledge"):
        module_candidates = [
            candidate
            for candidate in candidates
            if candidate.get("page_role") == "module" and is_code_module_path(str(candidate.get("path", "")))
        ]
        repository_maps = [candidate for candidate in module_candidates if is_code_repository_map(candidate)]
        fallback_pool = repository_maps or module_candidates
        for candidate in fallback_pool:
            if len(selected) >= evidence_budget:
                break
            if any(item["path"] == candidate["path"] for item in selected):
                continue
            add_selected(selected, candidate, "supporting", "code_map_fallback_for_exploration", evidence_budget)
            break
    return selected


def select_entity_attribute_evidence(
    candidates: list[dict],
    primary_candidates: list[dict],
    relationship_expansion: list[dict],
    query_intent: dict,
    evidence_budget: int,
) -> list[dict]:
    selected: list[dict] = []
    by_path = {item["path"]: item for item in candidates}
    owners = entity_attribute_owner_candidates(primary_candidates, query_intent) or entity_attribute_owner_candidates(candidates, query_intent)
    for candidate in owners:
        add_selected(selected, candidate, "primary", "entity_attribute_owner_page", evidence_budget)
        break
    for expansion in relationship_expansion:
        resolved_path = expansion.get("resolved_path")
        if not resolved_path or resolved_path not in by_path:
            continue
        candidate = by_path[resolved_path]
        role = "provenance" if candidate.get("page_role") == "source" and not query_intent.get("wants_source") else "supporting"
        add_selected(selected, candidate, role, "explicit_link_from_primary_evidence", evidence_budget)
    if query_intent.get("wants_code_knowledge"):
        module_candidates = [
            candidate
            for candidate in candidates
            if candidate.get("page_role") == "module" and is_code_module_path(str(candidate.get("path", "")))
        ]
        repository_maps = [candidate for candidate in module_candidates if is_code_repository_map(candidate)]
        fallback_pool = repository_maps or module_candidates
        for candidate in fallback_pool:
            add_selected(selected, candidate, "supporting", "code_map_fallback_for_exploration", evidence_budget)
            break
    return selected


def select_collection_evidence(candidates: list[dict], primary_candidates: list[dict], semantic_plan: dict | None, evidence_budget: int) -> list[dict]:
    selected: list[dict] = []
    scope = collection_scope(semantic_plan)
    owners = collection_owner_candidates(candidates, semantic_plan)
    if owners:
        for candidate in owners:
            add_selected(selected, candidate, "primary", "collection_owner_page", evidence_budget)
    else:
        for candidate in primary_candidates:
            reason = "collection_owner_page" if candidate.get("page_role") == "module" else "top_relevant_primary_page"
            add_selected(selected, candidate, "primary", reason, evidence_budget)
    members = collection_member_candidates(candidates, semantic_plan)
    for candidate in members:
        add_selected(selected, candidate, "supporting", "collection_member_evidence", evidence_budget)
    if not any(item.get("page_role") == "module" and (not scope or item.get("module") == scope) for item in selected):
        for candidate in collection_owner_candidates(candidates, semantic_plan):
            add_selected(selected, candidate, "supporting", "collection_owner_fallback", evidence_budget)
    return selected


def collection_member_candidates(candidates: list[dict], semantic_plan: dict | None) -> list[dict]:
    scope = collection_scope(semantic_plan)
    if not scope:
        return []
    members = [
        item
        for item in candidates
        if item.get("page_role") == "feature"
        and candidate_matches_modules(item, [scope])
    ]
    members.sort(key=lambda item: (-float(item.get("score", 0.0)), str(item.get("path"))))
    return members


def build_coverage_proof(candidates: list[dict], selected_evidence: list[dict], semantic_plan: dict | None) -> dict:
    if not is_collection_plan(semantic_plan):
        return {}
    owners = collection_owner_candidates(candidates, semantic_plan)
    members = collection_member_candidates(candidates, semantic_plan)
    selected_paths = {item.get("path") for item in selected_evidence}
    member_paths = unique([str(item.get("path")) for item in members if item.get("path")])
    owner_paths = unique([str(item.get("path")) for item in owners if item.get("path")])
    return {
        "operator": semantic_plan.get("operator", ""),
        "subject_scope": collection_scope(semantic_plan),
        "collection": semantic_plan.get("target_collection", {}),
        "owner_pages": owner_paths,
        "member_paths": member_paths,
        "evidence_member_paths": [path for path in member_paths if path in selected_paths],
        "complete": bool(owner_paths and member_paths),
        "sources": ["wiki/index.md", "collection_owner_page", "explicit_links_from_owner_page"],
    }


def add_selected(selected: list[dict], candidate: dict, evidence_role: str, reason: str, evidence_budget: int) -> None:
    if len(selected) >= evidence_budget:
        return
    if any(item["path"] == candidate["path"] for item in selected):
        return
    selected.append(
        {
            "path": candidate["path"],
            "title": candidate["title"],
            "type": candidate["type"],
            "page_role": candidate.get("page_role", ""),
            "module": candidate.get("module", ""),
            "score": candidate.get("score", 0.0),
            "evidence_role": evidence_role,
            "selection_reason": reason,
        }
    )


def evidence_allowed(candidate: dict, query_intent: dict, mode: str, include_source: bool, include_cross_module: bool) -> bool:
    role = candidate.get("page_role")
    if role == "source" and not (include_source or query_intent.get("wants_source") or mode == "exhaustive"):
        return False
    if role == "regulation_requirement" and not (query_intent.get("wants_regulation") or mode == "exhaustive"):
        return False
    modules = query_intent.get("modules", [])
    candidate_modules = candidate_module_values(candidate)
    if len(modules) == 1 and candidate_modules and not candidate_matches_modules(candidate, modules) and not (include_cross_module or query_intent.get("wants_cross_module") or mode == "exhaustive"):
        return False
    return True


def omitted_candidate(candidate: dict, selected_paths: set[str], query_intent: dict, mode: str) -> dict:
    path = candidate["path"]
    role = candidate.get("page_role")
    candidate_modules = candidate_module_values(candidate)
    module = candidate_modules[0] if candidate_modules else None
    reason = "not_selected_for_focused_evidence" if mode == "focused" else "evidence_budget_or_lower_rank"
    modules = query_intent.get("modules", [])
    if len(modules) == 1 and candidate_modules and not candidate_matches_modules(candidate, modules) and not query_intent.get("wants_cross_module"):
        reason = "module_mismatch"
    elif role == "source" and not query_intent.get("wants_source"):
        reason = "source_page_not_requested"
    elif role == "regulation_requirement" and not query_intent.get("wants_regulation"):
        reason = "regulation_intent_not_requested"
    elif role == "data_dictionary" and not query_intent.get("wants_data_dictionary") and path not in selected_paths:
        reason = "data_dictionary_not_requested"
    return {
        "path": path,
        "title": candidate.get("title", ""),
        "score": candidate.get("score", 0.0),
        "page_role": role or "",
        "module": module or "",
        "reason": reason,
    }


def unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.replace("\\", "/")
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def build_query_read_plan(
    config: KitConfig,
    query: str,
    knowledge_id: str | None = None,
    all_enabled: bool = False,
    limit: int | None = None,
    run_id: str | None = None,
    created_at: str | None = None,
    candidate_limit: int | None = None,
    evidence_budget: int | None = None,
    mode: str = "focused",
    include_source: bool = False,
    include_cross_module: bool = False,
    semantic_plan: dict | None = None,
) -> dict:
    max_candidates = candidate_limit or limit or config.query_candidate_limit
    max_evidence = evidence_budget or (config.query_exhaustive_evidence_budget if mode == "exhaustive" else config.query_evidence_budget)
    roots = selected_query_roots(config, knowledge_id)
    results = [
        query_one(
            root,
            query,
            max_candidates,
            evidence_budget=max_evidence,
            mode=mode,
            include_source=include_source,
            include_cross_module=include_cross_module,
            semantic_plan=semantic_plan,
            code_knowledge_root=bool(knowledge_id and (has_configured_code_workspace(config, root) or is_code_knowledge_root(root))),
        )
        for root in roots
    ]
    return {
        "run_id": run_id or new_run_id("query"),
        "kind": QUERY_READ_PLAN_KIND,
        "operation": "QUERY",
        "query": query,
        "scope": "all" if all_enabled or not knowledge_id else knowledge_id,
        "selected_knowledge_roots": [
            {
                "id": root.id,
                "name": root.name,
                "path": str(root.path),
                "enabled": root.enabled,
                "mode": root.mode,
                "priority": root.priority,
                **code_workspace_metadata(config, root),
            }
            for root in roots
        ],
        "retrieval_policy": {
            "candidate_limit": max_candidates,
            "evidence_budget": max_evidence,
            "mode": mode,
            "include_source": include_source,
            "include_cross_module": include_cross_module,
            "raw_reads": "forbidden",
        },
        "per_knowledge_read_plans": results,
        "read_plan_only": True,
        "cli_role": "deterministic_assistant_for_codex_karpathy_query",
        "limitations": CLI_LIMITATIONS,
        "created_at": created_at or now_iso(),
    }


def code_workspace_metadata(config: KitConfig, root: KnowledgeRoot) -> dict:
    if not has_configured_code_workspace(config, root) and not is_code_knowledge_root(root):
        return {}
    code_config = config.data.get("code", {})
    workspaces = code_config.get("workspaces", {}) if isinstance(code_config, dict) else {}
    raw_workspace = workspaces.get(root.id, {}) if isinstance(workspaces, dict) else {}
    if raw_workspace and not isinstance(raw_workspace, dict):
        raw_workspace = {}
    configured_root = raw_workspace.get("workspace_root") if isinstance(raw_workspace, dict) else None
    if configured_root:
        workspace_root = Path(str(configured_root)).expanduser().resolve()
    elif root.path.name == "knowledge":
        workspace_root = root.path.parent.resolve()
    else:
        workspace_root = root.path.resolve()
    repos_dir = str(raw_workspace.get("repos_dir", "repos")) if isinstance(raw_workspace, dict) else "repos"
    repos_path = Path(repos_dir)
    repos_root = repos_path if repos_path.is_absolute() else workspace_root / repos_path
    return {
        "code_workspace": {
            "workspace_root": str(workspace_root),
            "repos_dir": repos_dir,
            "repos_root": str(repos_root.resolve()),
            "submodule_mode": bool(raw_workspace.get("submodule_mode", True)) if isinstance(raw_workspace, dict) else True,
            "command_cwd": str(workspace_root),
        }
    }


def run_query(
    config: KitConfig,
    query: str,
    knowledge_id: str | None = None,
    all_enabled: bool = False,
    limit: int | None = None,
    candidate_limit: int | None = None,
    evidence_budget: int | None = None,
    mode: str = "focused",
    include_source: bool = False,
    include_cross_module: bool = False,
    semantic_plan: dict | None = None,
) -> dict:
    run_id = new_run_id("query")
    payload = build_query_read_plan(
        config,
        query,
        knowledge_id=knowledge_id,
        all_enabled=all_enabled,
        limit=limit,
        candidate_limit=candidate_limit,
        evidence_budget=evidence_budget,
        mode=mode,
        include_source=include_source,
        include_cross_module=include_cross_module,
        semantic_plan=semantic_plan,
        run_id=run_id,
    )
    artifact = write_run_artifact(config.runs_dir, run_id, "query-read-plan.json", payload)
    append_ledger(config.state_dir, {"run_id": run_id, "kind": QUERY_READ_PLAN_KIND, "artifact": str(artifact), "created_at": payload["created_at"]})
    return payload

from __future__ import annotations

import json

from .config import KitConfig, KnowledgeRoot
from .code_exploration import (
    build_code_exploration,
    query_codex_next_step,
)
from .frontmatter import parse_frontmatter
from .runtime import append_ledger, new_run_id, now_iso, write_run_artifact
from .query_terms import query_topic_terms
from .search import build_query_read_plan
from .semantic_review import build_semantic_review, query_semantic_review_next_step
from .sufficiency import SEMANTIC_GAP_CODES, evaluate_sufficiency
from .query_profiles import (
    answer_requirements_for,
    code_knowledge_plans,
    code_knowledge_quality_gaps,
    collapse_subject_missing_gaps,
    first_non_empty,
    profile_evidence_gaps,
)
from .wiki import read_wiki_page
from .workflow_contract import (
    QUERY_BUNDLE_POLICY,
    QUERY_EVIDENCE_BUNDLE_KIND,
)


def run_query_bundle(
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
    run_id = new_run_id("query-bundle")
    created_at = now_iso()
    effective_evidence_budget = evidence_budget
    if effective_evidence_budget is None and mode == "exhaustive":
        effective_evidence_budget = config.query_exhaustive_evidence_budget
    read_plan = build_query_read_plan(
        config,
        query,
        knowledge_id=knowledge_id,
        all_enabled=all_enabled,
        limit=limit,
        candidate_limit=candidate_limit,
        evidence_budget=effective_evidence_budget,
        mode=mode,
        include_source=include_source,
        include_cross_module=include_cross_module,
        semantic_plan=semantic_plan,
        run_id=f"{run_id}-plan",
        created_at=created_at,
    )
    per_knowledge_bundles = []
    evidence_pages = []
    gaps = []
    semantic_sufficiency = []
    for plan in read_plan["per_knowledge_read_plans"]:
        root = config.require_query_root(plan["knowledge_id"])
        bundle = build_knowledge_bundle(root, plan)
        sufficiency = evaluate_sufficiency(plan.get("semantic_plan", {}), bundle["evidence_pages"], bundle.get("coverage_proof", {}))
        apply_bundle_gaps(bundle, sufficiency["gaps"])
        bundle["sufficiency"] = sufficiency
        per_knowledge_bundles.append(bundle)
        evidence_pages.extend(bundle["evidence_pages"])
        gaps.extend(bundle["gaps"])
        semantic_sufficiency.append(sufficiency)
    answer_requirements = answer_requirements_for(query, read_plan)
    code_gaps = code_knowledge_quality_gaps(read_plan, evidence_pages, query=query)
    gaps.extend(code_gaps)
    apply_code_quality_gaps(per_knowledge_bundles, read_plan, code_gaps)
    gaps.extend(profile_evidence_gaps(answer_requirements, evidence_pages, query=query))
    gaps = collapse_subject_missing_gaps(gaps)
    quality = bundle_quality(evidence_pages, gaps)
    code_exploration = build_code_exploration(read_plan, code_knowledge_plans(read_plan), evidence_pages, query_topic_terms(query), gaps, answer_requirements)
    semantic_review = build_semantic_review(read_plan, per_knowledge_bundles, evidence_pages, gaps, quality, answer_requirements)
    codex_next_step = query_codex_next_step(code_exploration)
    if semantic_review.get("enabled"):
        if codex_next_step:
            attach_semantic_review_to_code_next_step(codex_next_step, semantic_review)
        elif semantic_review.get("required_before_final"):
            codex_next_step = query_semantic_review_next_step(semantic_review)
    query_status = query_bundle_status(codex_next_step)
    citations = [f"{page['knowledge_id']}:{page['path']}" for page in evidence_pages]
    payload = {
        "run_id": run_id,
        "kind": QUERY_EVIDENCE_BUNDLE_KIND,
        "status": query_status["status"],
        "completion_state": query_status["completion_state"],
        "continuation_policy": query_status["continuation_policy"],
        "operation": "QUERY",
        "query": query,
        "scope": read_plan["scope"],
        "selected_knowledge_roots": read_plan["selected_knowledge_roots"],
        "retrieval_policy": read_plan.get("retrieval_policy", {}),
        "read_plan": read_plan,
        "per_knowledge_bundles": per_knowledge_bundles,
        "semantic_plan": first_non_empty([plan.get("semantic_plan", {}) for plan in read_plan.get("per_knowledge_read_plans", [])]),
        "semantic_plans": [plan.get("semantic_plan", {}) for plan in read_plan.get("per_knowledge_read_plans", [])],
        "coverage_proof": first_non_empty([bundle.get("coverage_proof", {}) for bundle in per_knowledge_bundles]),
        "coverage_proofs": [bundle.get("coverage_proof", {}) for bundle in per_knowledge_bundles],
        "sufficiency": {
            "passed": not any(not item.get("passed") for item in semantic_sufficiency),
            "results": semantic_sufficiency,
        },
        "evidence_pages": evidence_pages,
        "citations": citations,
        "gaps": gaps,
        "quality": quality,
        "semantic_review": semantic_review,
        "code_exploration": code_exploration,
        **({"codex_next_step": codex_next_step} if codex_next_step else {}),
        "answer_requirements": answer_requirements,
        "policy": QUERY_BUNDLE_POLICY,
        "forbidden_paths": QUERY_BUNDLE_POLICY["forbidden_paths"],
        "read_plan_only": False,
        "cli_role": "restricted_evidence_gateway_for_codex_karpathy_query",
        "created_at": created_at,
    }
    artifact = write_run_artifact(config.runs_dir, run_id, "query-evidence-bundle.json", payload)
    append_ledger(config.state_dir, {"run_id": run_id, "kind": QUERY_EVIDENCE_BUNDLE_KIND, "artifact": str(artifact), "created_at": created_at})
    return payload


def query_bundle_status(codex_next_step: dict) -> dict:
    if codex_next_step:
        status = str(codex_next_step.get("status") or "requires_followup")
        if status == "requires_code_exploration":
            required_next_step = "execute_code_exploration"
            continue_as = "current_session"
        elif status == "requires_semantic_review":
            required_next_step = "perform_semantic_review"
            continue_as = "current_session"
        else:
            required_next_step = "follow_codex_next_step"
            continue_as = "current_session"
        return {
            "status": status,
            "completion_state": "not_complete",
            "continuation_policy": {
                "query_evidence_bundle_is_final": False,
                "slash_command_must_continue": True,
                "continue_as": continue_as,
                "required_next_step": required_next_step,
                "final_answer_allowed": False,
            },
        }
    return {
        "status": "ready_for_answer",
        "completion_state": "complete",
        "continuation_policy": {
            "query_evidence_bundle_is_final": True,
            "slash_command_must_continue": False,
            "final_answer_allowed": True,
        },
    }




def attach_semantic_review_to_code_next_step(codex_next_step: dict, semantic_review: dict) -> None:
    codex_next_step["semantic_review"] = semantic_review
    if not semantic_review.get("required_before_final"):
        return
    codex_next_step["pre_code_semantic_review_required"] = True
    codex_next_step["execution_sequence"] = [
        "perform_semantic_review_or_refined_query",
        "execute_code_exploration",
        "read_entrypoint_code",
        "trace_implementation_chain",
        "write_code_verification_result",
        "run_code_verification_quality_gate",
    ]
    semantic_actions = [
        "先完成 semantic_review：判断 evidence_pages 是否语义对题；必要时按 retry_policy 生成 refined query 并重新执行 query-bundle。",
        "semantic_review 不是终态：若仍存在 code_exploration.execution_policy.must_execute_before_final=true，必须继续执行代码探索，不能只输出语义复核或探索计划。",
    ]
    existing_actions = [str(item) for item in codex_next_step.get("required_actions", []) if str(item)]
    codex_next_step["required_actions"] = semantic_actions + existing_actions


def apply_code_quality_gaps(per_knowledge_bundles: list[dict], read_plan: dict, code_gaps: list[dict]) -> None:
    if not code_gaps:
        return
    code_knowledge_ids = {str(plan.get("knowledge_id") or "") for plan in code_knowledge_plans(read_plan)}
    for bundle in per_knowledge_bundles:
        if str(bundle.get("knowledge_id") or "") not in code_knowledge_ids:
            continue
        existing = {
            json.dumps(gap, sort_keys=True, ensure_ascii=False)
            for gap in bundle.get("gaps", [])
        }
        for gap in code_gaps:
            key = json.dumps(gap, sort_keys=True, ensure_ascii=False)
            if key in existing:
                continue
            bundle.setdefault("gaps", []).append(gap)
            existing.add(key)
        bundle["quality"] = bundle_quality(bundle.get("evidence_pages", []), bundle.get("gaps", []))


def apply_bundle_gaps(bundle: dict, gaps: list[dict]) -> None:
    if not gaps:
        return
    existing = {
        json.dumps(gap, sort_keys=True, ensure_ascii=False)
        for gap in bundle.get("gaps", [])
    }
    for gap in gaps:
        key = json.dumps(gap, sort_keys=True, ensure_ascii=False)
        if key in existing:
            continue
        bundle.setdefault("gaps", []).append(gap)
        existing.add(key)
    bundle["quality"] = bundle_quality(bundle.get("evidence_pages", []), bundle.get("gaps", []))


def build_knowledge_bundle(root: KnowledgeRoot, plan: dict) -> dict:
    evidence_pages = []
    gaps = []
    selected_by_path = {item["path"]: item for item in plan.get("selected_evidence", [])}
    for repo_path in evidence_repo_paths(plan):
        if not repo_path.startswith("wiki/"):
            gaps.append({"knowledge_id": root.id, "code": "forbidden_non_wiki_path", "path": repo_path})
            continue
        page = read_wiki_page(root, repo_path.removeprefix("wiki/"))
        if page is None:
            gaps.append({"knowledge_id": root.id, "code": "planned_page_missing", "path": repo_path})
            continue
        content = page.path.read_text(encoding="utf-8", errors="replace")
        meta, _body = parse_frontmatter(content)
        frontmatter_sources = meta.get("sources") if isinstance(meta.get("sources"), list) else []
        evidence_pages.append(
            {
                "knowledge_id": root.id,
                "path": page.repo_path,
                "title": page.title,
                "type": page.page_type,
                "page_role": selected_by_path.get(repo_path, {}).get("page_role", ""),
                "module": selected_by_path.get(repo_path, {}).get("module", ""),
                "evidence_role": selected_by_path.get(repo_path, {}).get("evidence_role", "supporting"),
                "selection_reason": selected_by_path.get(repo_path, {}).get("selection_reason", ""),
                "frontmatter_sources": frontmatter_sources,
                "frontmatter_source_statuses": frontmatter_source_statuses(root, frontmatter_sources),
                "content": content,
                "source": "wiki",
            }
        )
    for link in plan.get("relationship_expansion", plan.get("related_wikilinks", [])):
        if link.get("status") == "broken":
            gaps.append(
                {
                    "knowledge_id": root.id,
                    "code": "broken_wikilink",
                    "from": str(link.get("from") or ""),
                    "target": str(link.get("target") or ""),
                }
            )
    if not evidence_pages:
        gaps.append({"knowledge_id": root.id, "code": "no_evidence_pages", "path": "wiki/index.md"})
    return {
        "knowledge_id": root.id,
        "actual_knowledge_root": str(root.path),
        "query_intent": plan.get("query_intent", {}),
        "semantic_plan": plan.get("semantic_plan", {}),
        "retrieval_policy": plan.get("retrieval_policy", {}),
        "coverage_proof": plan.get("coverage_proof", {}),
        "evidence_pages": evidence_pages,
        "citations": [f"{root.id}:{page['path']}" for page in evidence_pages],
        "gaps": gaps,
        "quality": bundle_quality(evidence_pages, gaps),
        "policy": QUERY_BUNDLE_POLICY,
    }


def evidence_repo_paths(plan: dict) -> list[str]:
    ordered = []
    selected_paths = plan.get("selected_evidence_paths") or []
    for path in selected_paths:
        ordered.append(str(path))
    seen: set[str] = set()
    unique = []
    for path in ordered:
        normalized = path.replace("\\", "/")
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
    return unique


def frontmatter_source_statuses(root: KnowledgeRoot, sources: list[str]) -> list[dict]:
    result: list[dict] = []
    for item in sources:
        normalized = str(item).replace("\\", "/").lstrip("/")
        result.append(
            {
                "path": normalized,
                "exists": frontmatter_source_exists(root, normalized),
            }
        )
    return result


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




def bundle_quality(evidence_pages: list[dict], gaps: list[dict]) -> dict:
    profile_gap_codes = {
        "profile_no_evidence_pages",
        "profile_required_section_missing",
        "profile_code_feature_evidence_missing",
        "profile_code_feature_source_trace_missing",
        "profile_code_feature_source_summary_missing",
        "profile_query_topic_not_covered",
        "profile_query_subject_missing",
        "query_topic_not_covered",
        "query_module_not_covered",
    }
    if not evidence_pages:
        confidence = "low"
    elif any(gap.get("code") in profile_gap_codes or gap.get("code") in SEMANTIC_GAP_CODES for gap in gaps):
        confidence = "low"
    elif any(page.get("evidence_role") == "primary" for page in evidence_pages) and not gaps:
        confidence = "high"
    else:
        confidence = "medium"
    return {
        "confidence": confidence,
        "conflicts": [],
        "gaps": gaps,
    }

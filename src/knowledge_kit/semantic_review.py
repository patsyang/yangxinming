from __future__ import annotations

from .sufficiency import SEMANTIC_GAP_CODES
from .workflow_contract import QUERY_CONTRACT_REFS


SEMANTIC_REVIEW_GAP_CODES = {
    "no_evidence_pages",
    "profile_no_evidence_pages",
    "profile_code_feature_evidence_missing",
    "profile_query_topic_not_covered",
    "profile_query_subject_missing",
    "query_topic_not_covered",
    "query_module_not_covered",
    *SEMANTIC_GAP_CODES,
}


def query_semantic_review_next_step(semantic_review: dict) -> dict:
    return {
        "schema_version": "query.semantic_review_next_step.v1",
        "status": "requires_semantic_review",
        "must_continue": True,
        "final_answer_allowed": False,
        "contract_refs": QUERY_CONTRACT_REFS,
        "must_read_contract_refs_before_final": True,
        "required_output_block": "语义复核结果",
        "semantic_review": semantic_review,
        "instructions": [
            "先复核 evidence_pages 是否语义对题；不得把 candidate_pages、omitted_candidates 或 semantic_review 当事实证据。",
            "如果 evidence_pages 语义不对题，按 semantic_review.retry_policy 生成更精确查询并重新执行 query-bundle。",
            "如果复核后仍不足，只能报告缺口、候选方向和下一步查询/代码探索，不能写成已确认结论。",
        ],
    }


def build_semantic_review(
    read_plan: dict,
    per_knowledge_bundles: list[dict],
    evidence_pages: list[dict],
    gaps: list[dict],
    quality: dict,
    answer_requirements: dict,
) -> dict:
    reason_codes = semantic_review_reason_codes(read_plan, evidence_pages, gaps, quality)
    enabled = bool(reason_codes)
    active_profiles = set(answer_requirements.get("active_profiles") or [])
    gap_codes = {str(gap.get("code") or "") for gap in gaps}
    requires_followup_profile = bool(active_profiles.intersection({"agentic_coding", "prd_design_from_code"}))
    requires_semantic_coverage = bool(gap_codes.intersection(SEMANTIC_GAP_CODES))
    required_before_final = bool(enabled and quality.get("confidence") == "low" and (requires_followup_profile or requires_semantic_coverage))
    return {
        "schema_version": "query.semantic_review.v1",
        "enabled": enabled,
        "required_before_final": required_before_final,
        "not_evidence": True,
        "language": "zh-CN",
        "purpose": "让当前 LLM 复核候选召回是否语义对题，并在低置信或主题未覆盖时先重试或转入代码探索。",
        "reason_codes": reason_codes,
        "review_scope": semantic_review_scope(read_plan, per_knowledge_bundles, evidence_pages),
        "instructions": [
            "只把 evidence_pages 和允许的 coverage_proof 当作 wiki 事实来源。",
            "检查 selected_evidence 是否覆盖用户问题中的业务对象、动作、模块、约束和回答 profile。",
            "candidate_pages、omitted_candidates 和 index_hits 只能用于发现可能漏选的页面或生成 refined_query，不能作为最终事实引用。",
            "若 evidence_pages 语义偏题或过泛，先按 retry_policy 生成 1-3 个更精确查询并重新执行 query-bundle。",
            "若代码知识库给出了 code_exploration，语义复核后仍需按 code_exploration 回代码验证现状，不能只停在 wiki。",
        ],
        "allowed_actions": [
            "judge_evidence_alignment",
            "derive_refined_queries",
            "rerun_query_bundle_with_refined_query",
            "execute_code_exploration_when_available",
            "report_gap_when_still_insufficient",
        ],
        "retry_policy": semantic_review_retry_policy(read_plan),
        "result_contract": {
            "output_block": "语义复核结果",
            "fields": [
                "alignment",
                "missing_query_facets",
                "selected_evidence_decision",
                "refined_queries",
                "rerun_commands",
                "remaining_gaps",
            ],
            "final_answer_policy": "required_before_final=true 时，必须先完成语义复核或重试；仍不足时只能报告缺口和下一步，不得输出已确认答案。",
        },
        "answer_requirement_integration": {
            "active_profiles": answer_requirements.get("active_profiles", []),
            "must_keep_separate_from_evidence": True,
            "facts_must_still_come_from": answer_requirements.get("must_use_only", "evidence_pages"),
        },
    }


def semantic_review_reason_codes(read_plan: dict, evidence_pages: list[dict], gaps: list[dict], quality: dict) -> list[str]:
    reasons: list[str] = []
    if quality.get("confidence") == "low":
        reasons.append("low_confidence")
    if not evidence_pages:
        reasons.append("no_evidence_pages")
    for gap in gaps:
        code = str(gap.get("code") or "")
        if code in SEMANTIC_REVIEW_GAP_CODES and code not in reasons:
            reasons.append(code)
    if any(plan.get("query_intent", {}).get("wants_code_knowledge") for plan in read_plan.get("per_knowledge_read_plans", [])):
        if "code_knowledge_query" not in reasons:
            reasons.append("code_knowledge_query")
    return reasons


def semantic_review_scope(read_plan: dict, per_knowledge_bundles: list[dict], evidence_pages: list[dict]) -> dict:
    return {
        "selected_evidence": [
            {
                "knowledge_id": str(page.get("knowledge_id") or ""),
                "path": str(page.get("path") or ""),
                "title": str(page.get("title") or ""),
                "page_role": str(page.get("page_role") or ""),
                "module": str(page.get("module") or ""),
                "evidence_role": str(page.get("evidence_role") or ""),
                "selection_reason": str(page.get("selection_reason") or ""),
            }
            for page in evidence_pages
        ],
        "top_candidates": semantic_review_candidates(read_plan, "candidate_pages", limit=16),
        "omitted_candidates": semantic_review_candidates(read_plan, "omitted_candidates", limit=12),
        "semantic_plans": [plan.get("semantic_plan", {}) for plan in read_plan.get("per_knowledge_read_plans", [])],
        "bundle_gaps": [
            {
                "knowledge_id": str(bundle.get("knowledge_id") or ""),
                "gaps": bundle.get("gaps", []),
            }
            for bundle in per_knowledge_bundles
        ],
    }


def semantic_review_candidates(read_plan: dict, field: str, *, limit: int) -> list[dict]:
    result: list[dict] = []
    for plan in read_plan.get("per_knowledge_read_plans", []):
        knowledge_id = str(plan.get("knowledge_id") or "")
        for item in plan.get(field, []):
            if len(result) >= limit:
                return result
            result.append(
                {
                    "knowledge_id": knowledge_id,
                    "path": str(item.get("path") or ""),
                    "title": str(item.get("title") or ""),
                    "page_role": str(item.get("page_role") or ""),
                    "module": str(item.get("module") or ""),
                    "score": item.get("score", 0),
                    "selection_status": str(item.get("selection_status") or ""),
                    "selection_reason": str(item.get("selection_reason") or item.get("omit_reason") or ""),
                    "signals": item.get("signals", []),
                }
            )
    return result


def semantic_review_retry_policy(read_plan: dict) -> dict:
    return {
        "max_refined_queries": 3,
        "same_scope_required": True,
        "command_templates": semantic_review_retry_commands(read_plan),
        "stop_conditions": [
            "新 bundle 的 evidence_pages 语义覆盖用户问题",
            "新 bundle 返回 requires_code_exploration 且可进入代码验证",
            "连续 refined_query 仍无证据，此时报告 gap 和下一步维护建议",
        ],
    }


def semantic_review_retry_commands(read_plan: dict) -> list[str]:
    roots = [str(root.get("id") or "") for root in read_plan.get("selected_knowledge_roots", []) if str(root.get("id") or "")]
    if len(roots) == 1:
        return [f'python -m knowledge_kit query-bundle -k {roots[0]} "<refined_query>"']
    if read_plan.get("scope") == "all_enabled" or len(roots) > 1:
        return ['python -m knowledge_kit query-bundle --all "<refined_query>"']
    return ['python -m knowledge_kit query-bundle "<refined_query>"']

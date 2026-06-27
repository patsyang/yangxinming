from __future__ import annotations

import re

from .semantic_plan import COUNT_COLLECTION, is_collection_plan, is_entity_attribute_plan


SEMANTIC_GAP_CODES = {
    "semantic_plan_missing",
    "subject_unresolved",
    "collection_owner_missing",
    "collection_boundary_missing",
    "collection_members_missing",
    "collection_coverage_incomplete",
    "single_member_page_insufficient_for_count",
    "entity_owner_missing",
    "attribute_topic_missing",
    "attribute_values_missing",
}


def evaluate_sufficiency(semantic_plan: dict, evidence_pages: list[dict], coverage_proof: dict | None) -> dict:
    gaps: list[dict] = []
    if not semantic_plan:
        return {"passed": True, "operator": "", "gaps": []}
    operator = str(semantic_plan.get("operator") or "")
    if is_entity_attribute_plan(semantic_plan):
        return evaluate_entity_attribute_sufficiency(semantic_plan, evidence_pages)
    if not is_collection_plan(semantic_plan):
        return {"passed": True, "operator": operator, "gaps": []}
    proof = coverage_proof or {}
    owner_pages = proof.get("owner_pages") if isinstance(proof.get("owner_pages"), list) else []
    member_paths = proof.get("member_paths") if isinstance(proof.get("member_paths"), list) else []
    if not semantic_plan.get("subjects"):
        gaps.append({"code": "subject_unresolved", "severity": "major", "operator": operator})
    if not owner_pages:
        gaps.append({"code": "collection_owner_missing", "severity": "major", "operator": operator})
    if not member_paths:
        gaps.append({"code": "collection_members_missing", "severity": "major", "operator": operator})
    if operator == COUNT_COLLECTION and len(evidence_pages) == 1 and evidence_pages[0].get("page_role") == "feature":
        gaps.append(
            {
                "code": "single_member_page_insufficient_for_count",
                "severity": "major",
                "operator": operator,
                "path": evidence_pages[0].get("path", ""),
            }
        )
    if member_paths and not proof.get("complete"):
        gaps.append({"code": "collection_coverage_incomplete", "severity": "major", "operator": operator})
    return {
        "passed": not gaps,
        "operator": operator,
        "gaps": gaps,
    }


def evaluate_entity_attribute_sufficiency(semantic_plan: dict, evidence_pages: list[dict]) -> dict:
    operator = str(semantic_plan.get("operator") or "")
    gaps: list[dict] = []
    owner_pages = [
        page
        for page in evidence_pages
        if page.get("evidence_role") == "primary"
        and page.get("page_role") in {"feature", "concept", "query", "unknown"}
    ]
    if not owner_pages:
        gaps.append({"code": "entity_owner_missing", "severity": "major", "operator": operator})
        return {"passed": False, "operator": operator, "gaps": gaps}

    attribute = semantic_plan.get("target_attribute") if isinstance(semantic_plan.get("target_attribute"), dict) else {}
    terms = [str(item) for item in attribute.get("terms", []) if str(item)] or [str(attribute.get("name") or "")]
    combined_content = "\n".join(str(page.get("content") or "") for page in owner_pages)
    if terms and not any(term.lower() in combined_content.lower() for term in terms):
        gaps.append({"code": "attribute_topic_missing", "severity": "major", "operator": operator})
    if not attribute_values_likely_present(combined_content):
        gaps.append({"code": "attribute_values_missing", "severity": "major", "operator": operator})
    return {
        "passed": not gaps,
        "operator": operator,
        "gaps": gaps,
    }


def attribute_values_likely_present(content: str) -> bool:
    if re.search(r"`[A-Za-z][A-Za-z0-9_./:-]{2,}`", content):
        return True
    if re.search(r"(?m)^\s*[-*]\s+\S+", content):
        return True
    if re.search(r"(?m)^\s*\d+\.\s+\S+", content):
        return True
    if re.search(r"(?m)^\|.+\|$", content):
        return True
    return False


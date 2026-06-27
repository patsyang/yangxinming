from __future__ import annotations

import re

from .code_exploration import code_verification_required
from .query_terms import evidence_covers_query_topic, query_topic_terms
from .semantic_plan import is_collection_plan
from .workflow_contract import (
    QUERY_AGENTIC_CODING_REQUIREMENTS,
    QUERY_ANSWER_REQUIREMENTS,
    QUERY_PRD_DESIGN_REQUIREMENTS,
)
AGENTIC_CODING_QUERY_HINTS = {
    "agentic coding",
    "coding",
    "代码",
    "实现",
    "新增",
    "字段",
    "筛选",
    "导出",
    "审批",
    "想改",
    "想做",
    "要改",
    "改动",
    "修改",
    "改造",
    "闭合",
    "定位",
    "开发",
    "编码",
    "复用",
    "边界",
    "运行时",
    "生效",
    "下发",
    "配置",
    "约束",
    "测试",
    "验证",
    "controller",
    "service",
    "repository",
}

PRD_DESIGN_QUERY_HINTS = {"prd", "产品设计", "功能设计", "补齐"}
PROFILE_SECTION_MARKERS = {
    "agentic_coding": {
        "现有实现": ["现有实现", "当前实现", "当前状态"],
        "代码定位": ["代码定位", "代码位置", "相关代码", "证据:"],
        "复用边界": ["复用边界", "复用点", "可复用"],
        "改动点": ["改动点", "修改点", "变更点"],
        "约束": ["约束", "数据约束", "权限", "运行约束"],
        "测试/验证路径": ["测试/验证路径", "验证入口", "测试", "验证路径"],
        "缺口与继续探索": ["缺口与继续探索", "缺口", "探索提示", "下一步探索"],
    },
    "prd_design_from_code": {
        "已有能力": ["已有能力", "现有能力", "当前能力", "现有实现", "当前实现", "当前状态"],
        "设计可继承部分": ["设计可继承部分", "可继承", "可复用设计", "复用边界", "复用点", "可复用"],
        "设计受限边界": ["设计受限边界", "受限边界", "数据/权限/运行约束", "暂不应改动", "约束"],
        "需要新增或澄清": ["需要新增或澄清", "需新增", "需澄清", "缺口与继续探索", "探索提示"],
        "实现影响": ["实现影响", "改动影响", "技术影响", "PRD 设计影响", "设计影响", "改动点"],
        "缺口": ["缺口", "未知", "待探索", "缺口与继续探索"],
    },
}


def collapse_subject_missing_gaps(gaps: list[dict]) -> list[dict]:
    if not any(gap.get("code") == "profile_query_subject_missing" for gap in gaps):
        return gaps
    return [gap for gap in gaps if gap.get("code") != "subject_unresolved"]


def first_non_empty(items: list[dict]) -> dict:
    for item in items:
        if item:
            return item
    return {}


def answer_requirements_for(query: str, read_plan: dict) -> dict:
    requirements = {
        **QUERY_ANSWER_REQUIREMENTS,
        "active_profiles": [],
        "profile_requirements": {},
        "missing_policy": "mark_unknown_or_gap_do_not_infer_beyond_evidence_pages",
    }
    active_profiles = requirements["active_profiles"]
    profile_requirements = requirements["profile_requirements"]
    if wants_semantic_coverage_answer(read_plan):
        requirements["must_use_only"] = "evidence_pages_and_coverage_proof"
    if is_code_knowledge_scope(read_plan):
        requirements["code_exploration_policy"] = {
            "available": True,
            "not_evidence": True,
            "source_field": "code_exploration",
            "allowed_usage": "next_code_verification_plan_only",
            "must_not_cite_as_fact": True,
            "must_show_when_agentic_coding_or_prd_design": True,
        }
    if wants_code_navigation_answer(read_plan):
        requirements["required_answer_blocks"] = required_answer_blocks(requirements)
        return requirements
    if wants_agentic_coding_answer(query, read_plan):
        active_profiles.append("agentic_coding")
        profile_requirements["agentic_coding"] = QUERY_AGENTIC_CODING_REQUIREMENTS
    if wants_prd_design_answer(query, read_plan):
        active_profiles.append("prd_design_from_code")
        profile_requirements["prd_design_from_code"] = QUERY_PRD_DESIGN_REQUIREMENTS
    if is_code_knowledge_scope(read_plan) and active_profiles:
        requirements["must_use_only"] = "evidence_pages_coverage_proof_and_executed_code_exploration"
        requirements["allowed_answer_sources"] = [
            "evidence_pages",
            "coverage_proof",
            "executed_code_exploration",
        ]
        requirements["missing_policy"] = "mark_unknown_or_gap_do_not_infer_beyond_allowed_answer_sources"
    requirements["required_answer_blocks"] = required_answer_blocks(requirements)
    return requirements


def wants_semantic_coverage_answer(read_plan: dict) -> bool:
    return any(is_collection_plan(plan.get("semantic_plan", {})) for plan in read_plan.get("per_knowledge_read_plans", []))


def wants_code_navigation_answer(read_plan: dict) -> bool:
    for plan in read_plan.get("per_knowledge_read_plans", []):
        intent = plan.get("query_intent", {})
        if intent.get("wants_code_navigation") or "code_navigation_query" in intent.get("intents", []):
            return True
    return False


def required_answer_blocks(answer_requirements: dict) -> list[dict]:
    blocks: list[dict] = []
    for section in answer_requirements.get("required_sections", []):
        blocks.append({"section": section, "source": "base", "required": True})
    seen = {item["section"] for item in blocks}
    for profile in answer_requirements.get("active_profiles", []):
        profile_requirements = answer_requirements.get("profile_requirements", {}).get(profile, {})
        for section in profile_requirements.get("required_sections", []):
            if section in seen:
                continue
            seen.add(section)
            blocks.append(
                {
                    "section": section,
                    "source": profile,
                    "required": True,
                    "missing_policy": "写入缺口或未知，不得用推测补齐。",
                }
            )
    if answer_requirements.get("code_exploration_policy", {}).get("available") and "代码探索计划" not in seen:
        seen.add("代码探索计划")
        blocks.append(
            {
                "section": "代码探索计划",
                "source": "code_exploration",
                "required": True,
                "missing_policy": "只可列出 code_exploration 中的 workspace、repo_targets、code_anchors、suggested_rg；不得作为事实证据引用。",
            }
        )
    if code_verification_required(answer_requirements) and "代码验证结果" not in seen:
        seen.add("代码验证结果")
        blocks.append(
            {
                "section": "代码验证结果",
                "source": "executed_code_exploration",
                "required": True,
                "missing_policy": "必须先按 code_exploration.execution_policy 执行有界代码探索；列出命令、关键命中路径、代码事实和仍需继续探索的缺口。不得用未执行的探索计划代替。",
            }
        )
    return blocks




def profile_evidence_gaps(answer_requirements: dict, evidence_pages: list[dict], *, query: str = "") -> list[dict]:
    gaps: list[dict] = []
    active_profiles = answer_requirements.get("active_profiles") or []
    if not active_profiles:
        return gaps
    if not evidence_pages:
        return [
            {
                "code": "profile_no_evidence_pages",
                "profile": profile,
                "severity": "major",
            }
            for profile in active_profiles
        ]
    code_profiles = {"agentic_coding", "prd_design_from_code"}
    active_code_profiles = [profile for profile in active_profiles if profile in code_profiles]
    if query and active_code_profiles and not query_topic_terms(query):
        return [
            {
                "code": "profile_query_subject_missing",
                "profile": profile,
                "severity": "major",
                "reason": "code_or_prd_query_has_no_specific_business_topic",
            }
            for profile in active_code_profiles
        ]
    if any(profile in code_profiles for profile in active_profiles) and not has_code_feature_evidence(evidence_pages):
        for profile in active_profiles:
            if profile in code_profiles:
                gaps.append(
                    {
                        "code": "profile_code_feature_evidence_missing",
                        "profile": profile,
                        "severity": "major",
                        "expected_path_prefix": "wiki/entities/code/features/",
                    }
                )
    code_feature_pages = code_feature_evidence_pages(evidence_pages)
    if active_code_profiles:
        topic_terms = query_topic_terms(query)
        if code_feature_pages and not evidence_covers_query_topic(topic_terms, code_feature_pages):
            for profile in active_code_profiles:
                gaps.append(
                    {
                        "code": "profile_query_topic_not_covered",
                        "profile": profile,
                        "severity": "major",
                        "topic_terms": topic_terms[:12],
                        "reason": "selected_code_feature_page_does_not_cover_query_specific_topic",
                    }
                )
        for page in code_feature_pages:
            if not has_kcode_source_summary(page.get("frontmatter_sources")):
                for profile in active_code_profiles:
                    gaps.append(
                        {
                            "code": "profile_code_feature_source_trace_missing",
                            "profile": profile,
                            "path": page.get("path", ""),
                            "severity": "major",
                            "expected_source_prefix": "wiki/sources/code/kcode-runs/",
                        }
                    )
                continue
            if not has_existing_kcode_source_summary(page.get("frontmatter_source_statuses")):
                for profile in active_code_profiles:
                    gaps.append(
                        {
                            "code": "profile_code_feature_source_summary_missing",
                            "profile": profile,
                            "path": page.get("path", ""),
                            "severity": "major",
                            "expected_source_prefix": "wiki/sources/code/kcode-runs/",
                        }
                    )
    for profile in active_profiles:
        sections = answer_requirements.get("profile_requirements", {}).get(profile, {}).get("required_sections", [])
        markers_by_section = PROFILE_SECTION_MARKERS.get(profile, {})
        if profile in code_profiles and code_feature_pages:
            for page in code_feature_pages:
                for section in sections:
                    markers = markers_by_section.get(section, [section])
                    if not page_section_is_substantive(page, section, markers):
                        gaps.append(
                            {
                                "code": "profile_required_section_missing",
                                "profile": profile,
                                "section": section,
                                "path": page.get("path", ""),
                                "severity": "major",
                                "expected_markers": markers,
                                "reason": "code_feature_page_section_missing_or_not_actionable",
                            }
                        )
            continue
        content = "\n".join(str(page.get("content", "")) for page in evidence_pages)
        for section in sections:
            markers = markers_by_section.get(section, [section])
            if not any(marker in content for marker in markers):
                gaps.append(
                    {
                        "code": "profile_required_section_missing",
                        "profile": profile,
                        "section": section,
                        "severity": "major",
                        "expected_markers": markers,
                    }
                )
                continue
    return gaps


def code_knowledge_quality_gaps(read_plan: dict, evidence_pages: list[dict], *, query: str = "") -> list[dict]:
    gaps: list[dict] = []
    code_plans = code_knowledge_plans(read_plan)
    if not code_plans:
        return gaps
    if any(plan.get("query_intent", {}).get("wants_code_navigation") for plan in code_plans):
        return gaps
    code_feature_pages = code_feature_evidence_pages(evidence_pages)
    topic_terms = query_topic_terms(query)
    if code_feature_pages and topic_terms and not evidence_covers_query_topic(topic_terms, code_feature_pages):
        gaps.append(
            {
                "code": "query_topic_not_covered",
                "severity": "major",
                "topic_terms": topic_terms[:12],
                "reason": "selected_code_feature_pages_do_not_cover_query_topic",
            }
        )
    for plan in code_plans:
        modules = [str(item) for item in plan.get("query_intent", {}).get("modules", []) if str(item)]
        if not modules:
            continue
        selected_modules = {
            str(page.get("module") or "")
            for page in evidence_pages
            if str(page.get("path", "")).replace("\\", "/").startswith("wiki/entities/code/features/")
        }
        if selected_modules and any(module in selected_modules for module in modules):
            continue
        gaps.append(
            {
                "code": "query_module_not_covered",
                "severity": "major",
                "modules": modules,
                "reason": "query_requested_module_but_selected_code_feature_pages_do_not_match_module",
            }
        )
    return gaps



def code_knowledge_plans(read_plan: dict) -> list[dict]:
    roots = {
        str(root.get("id") or ""): root
        for root in read_plan.get("selected_knowledge_roots", [])
        if root_is_code_knowledge(root)
    }
    plans = []
    for plan in read_plan.get("per_knowledge_read_plans", []):
        if str(plan.get("knowledge_id") or "") in roots and plan.get("query_intent", {}).get("wants_code_knowledge"):
            plans.append(plan)
    return plans


def has_code_feature_evidence(evidence_pages: list[dict]) -> bool:
    return bool(code_feature_evidence_pages(evidence_pages))


def code_feature_evidence_pages(evidence_pages: list[dict]) -> list[dict]:
    pages: list[dict] = []
    for page in evidence_pages:
        path = str(page.get("path", "")).replace("\\", "/")
        if path.startswith("wiki/entities/code/features/"):
            pages.append(page)
    return pages


def has_kcode_source_summary(value: object) -> bool:
    if not isinstance(value, list):
        return False
    for item in value:
        normalized = str(item).replace("\\", "/").lstrip("/")
        if normalized.startswith("wiki/sources/code/kcode-runs/") or normalized.startswith("sources/code/kcode-runs/"):
            return True
    return False


def has_existing_kcode_source_summary(value: object) -> bool:
    if not isinstance(value, list):
        return False
    for item in value:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path", "")).replace("\\", "/").lstrip("/")
        if not item.get("exists"):
            continue
        if path.startswith("wiki/sources/code/kcode-runs/") or path.startswith("sources/code/kcode-runs/"):
            return True
    return False


def section_is_substantive(code_feature_pages: list[dict], section: str, markers: list[str]) -> bool:
    for page in code_feature_pages:
        if page_section_is_substantive(page, section, markers):
            return True
    return False


def page_section_is_substantive(page: dict, section: str, markers: list[str]) -> bool:
    sections = markdown_sections(str(page.get("content", "")))
    for heading, body in sections.items():
        if not heading_matches(heading, markers):
            continue
        text = normalize_section_body(body)
        if section == "代码定位":
            return has_code_locator(text)
        return len(text) >= 12 and not looks_like_placeholder(text)
    return False


def markdown_sections(text: str) -> dict[str, str]:
    matches = list(re.finditer(r"(?m)^##\s+(.+?)\s*$", text))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        heading = match.group(1).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[heading] = text[start:end].strip()
    return sections


def heading_matches(heading: str, markers: list[str]) -> bool:
    normalized = heading.strip().lower()
    return any(marker.lower() in normalized or normalized in marker.lower() for marker in markers)


def normalize_section_body(text: str) -> str:
    cleaned = re.sub(r"`([^`]+)`", r"\1", text)
    cleaned = re.sub(r"\[[^\]]+\]\([^)]+\)", "", cleaned)
    cleaned = re.sub(r"(?m)^\s*[-*]\s*", "", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def looks_like_placeholder(text: str) -> bool:
    placeholders = [
        "未提供",
        "不得写入",
        "不得声称",
        "不得从目录结构自行推断",
        "只能写需要继续探索",
    ]
    return any(item in text for item in placeholders)


def has_code_locator(text: str) -> bool:
    patterns = [
        r"\b[\w./-]+\.(?:java|kt|js|jsx|ts|tsx|vue|py|go|xml|yml|yaml|json|sql)\b",
        r"/[A-Za-z0-9_$:{}./-]+",
        r"\b[A-Z][A-Za-z0-9_]*(?:Controller|Service|Repository|Mapper|Dao|Client|DTO|Dto|Entity|Config)\b",
    ]
    return any(re.search(pattern, text) for pattern in patterns)


def wants_agentic_coding_answer(query: str, read_plan: dict) -> bool:
    lowered = query.lower()
    if any(hint in lowered for hint in AGENTIC_CODING_QUERY_HINTS):
        return True
    return is_code_knowledge_scope(read_plan) and any(hint in lowered for hint in {"如何", "怎么", "需求", "功能", "设计"})


def wants_prd_design_answer(query: str, read_plan: dict) -> bool:
    lowered = query.lower()
    if any(hint in lowered for hint in PRD_DESIGN_QUERY_HINTS):
        return True
    if is_code_knowledge_scope(read_plan) and any(hint in lowered for hint in {"需求", "功能", "产品", "设计", "方案"}):
        return True
    return any(hint in lowered for hint in AGENTIC_CODING_QUERY_HINTS) and "设计" in lowered


def is_code_knowledge_scope(read_plan: dict) -> bool:
    return bool(code_knowledge_plans(read_plan))


def root_is_code_knowledge(root: dict) -> bool:
    if isinstance(root.get("code_workspace"), dict):
        return True
    identity = f"{root.get('id', '')} {root.get('name', '')}".lower()
    return "code" in identity or "代码" in f"{root.get('id', '')} {root.get('name', '')}"


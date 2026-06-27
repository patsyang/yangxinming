from __future__ import annotations


SEMANTIC_PLAN_SCHEMA_VERSION = "knowledge_kit.semantic_plan.v1"

DESCRIBE_ENTITY = "DESCRIBE_ENTITY"
LIST_COLLECTION = "LIST_COLLECTION"
LIST_ENTITY_ATTRIBUTE = "LIST_ENTITY_ATTRIBUTE"
COUNT_COLLECTION = "COUNT_COLLECTION"
COMPARE_ENTITIES = "COMPARE_ENTITIES"
TRACE_FLOW = "TRACE_FLOW"
LOOKUP_ATTRIBUTE = "LOOKUP_ATTRIBUTE"
LOCATE_IMPLEMENTATION = "LOCATE_IMPLEMENTATION"
SYNTHESIZE_DESIGN = "SYNTHESIZE_DESIGN"

COUNT_HINTS = {"几个", "多少", "一共", "总共", "数量", "count", "how many"}
LIST_HINTS = {"有哪些", "哪些", "列表", "清单", "列出", "所有", "全部", "list"}
APPLICATION_HINTS = {"应用", "app", "application"}
CAPABILITY_HINTS = {"能力", "功能", "feature", "capability"}
PRODUCT_ATTRIBUTE_HINTS = {
    "类型",
    "状态",
    "字段",
    "场景",
    "节点",
    "枚举",
    "消息",
    "messageType",
    "taskType",
    "routeName",
    "入口",
    "权限",
    "角色",
    "接口",
    "表",
}
CODE_ATTRIBUTE_HINTS = {
    "messageType",
    "taskType",
    "routeName",
}
ENTITY_ATTRIBUTE_HINTS = PRODUCT_ATTRIBUTE_HINTS | CODE_ATTRIBUTE_HINTS
IMPLEMENTATION_OVERRIDE_HINTS = {
    "哪些代码",
    "改哪些",
    "改动点",
    "怎么改",
    "新增",
    "导出",
    "筛选",
    "改造",
    "修改",
    "运行时",
    "生效",
    "下发",
    "配置",
}
CODE_IMPLEMENTATION_ACTION_HINTS = {
    "新增",
    "字段",
    "筛选",
    "导出",
    "审批",
    "改造",
    "修改",
    "运行时",
    "生效",
    "下发",
    "配置",
}


def build_semantic_plan(query: str, query_intent: dict, provided_plan: dict | None = None) -> dict:
    if provided_plan:
        return normalize_semantic_plan(provided_plan)
    return infer_semantic_plan(query, query_intent)


def infer_semantic_plan(query: str, query_intent: dict) -> dict:
    operator = infer_operator(query, query_intent)
    modules = [str(item) for item in query_intent.get("modules", []) if str(item)]
    subject = {"text": modules[0], "type": "module", "canonical_id": modules[0]} if len(modules) == 1 else {}
    plan = {
        "schema_version": SEMANTIC_PLAN_SCHEMA_VERSION,
        "planner": "deterministic_protocol_fallback",
        "operator": operator,
        "answer_shape": answer_shape_for_operator(operator),
        "subjects": [subject] if subject else [],
        "target_collection": {},
        "required_evidence": [],
        "sufficiency_rules": [],
    }
    if operator in {LIST_COLLECTION, COUNT_COLLECTION}:
        member_type = infer_member_type(query)
        plan["target_collection"] = {
            "member_type": member_type,
            "member_role": "feature",
            "relation": "contained_by_module",
            "scope": subject.get("canonical_id", "") if subject else "",
        }
        plan["required_evidence"] = [
            "collection_owner_page",
            "complete_member_list_or_coverage_proof",
        ]
        plan["sufficiency_rules"] = [
            "must_have_collection_boundary",
            "must_have_member_set",
            "must_not_answer_count_from_single_member_page",
        ]
    elif operator == LIST_ENTITY_ATTRIBUTE:
        plan["target_attribute"] = infer_target_attribute(query)
        plan["required_evidence"] = [
            "entity_owner_page",
            "attribute_values_or_topic_coverage",
        ]
        plan["sufficiency_rules"] = [
            "must_have_entity_owner_page",
            "must_cover_attribute_topic",
            "must_have_attribute_values",
        ]
    return plan


def normalize_semantic_plan(plan: dict) -> dict:
    normalized = dict(plan)
    normalized.setdefault("schema_version", SEMANTIC_PLAN_SCHEMA_VERSION)
    normalized.setdefault("planner", "provided")
    normalized.setdefault("operator", DESCRIBE_ENTITY)
    normalized.setdefault("answer_shape", answer_shape_for_operator(str(normalized["operator"])))
    normalized.setdefault("subjects", [])
    normalized.setdefault("target_collection", {})
    normalized.setdefault("target_attribute", {})
    normalized.setdefault("required_evidence", [])
    normalized.setdefault("sufficiency_rules", [])
    return normalized


def infer_operator(query: str, query_intent: dict | None = None) -> str:
    lowered = query.lower()
    if query_intent and query_intent.get("wants_code_knowledge"):
        if "哪些代码" in query or "改哪些" in query or "改动点" in query or "怎么改" in query:
            return LOCATE_IMPLEMENTATION
        if "如何实现" in query or "怎么实现" in query or "如何设计" in query:
            return DESCRIBE_ENTITY
        if is_entity_attribute_list_query(query):
            return LIST_ENTITY_ATTRIBUTE
        if any(hint in query for hint in CODE_IMPLEMENTATION_ACTION_HINTS):
            return LOCATE_IMPLEMENTATION
    if any(hint in lowered for hint in COUNT_HINTS):
        return COUNT_COLLECTION
    if is_entity_attribute_list_query(query):
        return LIST_ENTITY_ATTRIBUTE
    if any(hint in lowered for hint in LIST_HINTS):
        return LIST_COLLECTION
    return DESCRIBE_ENTITY


def answer_shape_for_operator(operator: str) -> str:
    if operator == COUNT_COLLECTION:
        return "count"
    if operator in {LIST_COLLECTION, LIST_ENTITY_ATTRIBUTE}:
        return "list"
    if operator == COMPARE_ENTITIES:
        return "comparison"
    if operator == TRACE_FLOW:
        return "trace"
    if operator == LOCATE_IMPLEMENTATION:
        return "implementation_location"
    return "descriptive"


def infer_member_type(query: str) -> str:
    lowered = query.lower()
    if any(hint in lowered for hint in APPLICATION_HINTS):
        return "application"
    if any(hint in lowered for hint in CAPABILITY_HINTS):
        return "capability"
    return "member"


def is_entity_attribute_list_query(query: str) -> bool:
    lowered = query.lower()
    has_list_hint = any(hint.lower() in lowered for hint in LIST_HINTS)
    if not has_list_hint:
        return False
    if any(hint.lower() in lowered for hint in IMPLEMENTATION_OVERRIDE_HINTS):
        return False
    has_attribute_hint = any(hint.lower() in lowered for hint in ENTITY_ATTRIBUTE_HINTS)
    if not has_attribute_hint:
        return False
    has_collection_hint = any(hint.lower() in lowered for hint in APPLICATION_HINTS | CAPABILITY_HINTS)
    return not has_collection_hint


def infer_target_attribute(query: str) -> dict:
    lowered = query.lower()
    matched = [hint for hint in ENTITY_ATTRIBUTE_HINTS if hint.lower() in lowered]
    if not matched:
        return {}
    matched.sort(key=lambda value: (-len(value), value))
    return {
        "name": matched[0],
        "terms": matched,
        "owner_role": "feature",
    }


def is_collection_plan(plan: dict | None) -> bool:
    return bool(plan and plan.get("operator") in {LIST_COLLECTION, COUNT_COLLECTION})


def is_entity_attribute_plan(plan: dict | None) -> bool:
    return bool(plan and plan.get("operator") == LIST_ENTITY_ATTRIBUTE)


def collection_scope(plan: dict | None) -> str:
    if not plan:
        return ""
    collection = plan.get("target_collection") if isinstance(plan.get("target_collection"), dict) else {}
    scope = str(collection.get("scope") or "")
    if scope:
        return scope
    subjects = plan.get("subjects") if isinstance(plan.get("subjects"), list) else []
    for subject in subjects:
        if not isinstance(subject, dict):
            continue
        value = str(subject.get("canonical_id") or "")
        if value:
            return value
    return ""

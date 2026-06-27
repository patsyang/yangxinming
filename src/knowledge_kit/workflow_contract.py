from __future__ import annotations

KARPATHY_OPERATIONS = ("INIT", "INGEST", "QUERY", "LINT")
RELATION_FILE_NAMES = ("relation-graph.json", "requirement-map.json", "alias-lookup.json")

QUERY_READ_PLAN_KIND = "query_read_plan"
QUERY_EVIDENCE_BUNDLE_KIND = "query_evidence_bundle"
MAINTENANCE_PREFLIGHT_KIND = "maintenance_preflight_package"
INGEST_REGISTRATION_KIND = "ingest_registration"
INIT_SCAFFOLD_KIND = "init_scaffold"
MECHANICAL_LINT_KIND = "mechanical_lint"
STRUCTURE_VALIDATION_KIND = "structure_validation"
KCODE_RUN_KIND = "kcode_run"
KCODE_REQUIRES_LLM_KIND = "kcode_requires_llm"
KCODE_HUMAN_READABLE_OUTPUT_LANGUAGE = "zh-CN"
KCODE_LANGUAGE_POLICY = {
    "human_readable_fields": KCODE_HUMAN_READABLE_OUTPUT_LANGUAGE,
    "applies_to": [
        "LLM 写入的 Markdown 正文",
        "LLM 写入的 JSON/JSONL 中 title/current_state/design_implications/detail/summary/notes/required_repairs 等人读字段",
        "handoff Markdown",
        "knowledge-manager 维护后的 wiki Markdown 正文",
    ],
    "preserve_original_identifiers": [
        "schema id",
        "JSON field name",
        "knowledge_level",
        "coverage_claims item/status",
        "file path",
        "code symbol",
        "command",
        "API endpoint",
        "class name",
        "function name",
        "enum value",
    ],
}
KCODE_CONTINUATION_POLICY = {
    "requires_llm_is_final": False,
    "slash_command_must_continue": True,
    "continue_until": "handoff_completed_or_verifier_loop_blocked",
    "human_readable_output_language": KCODE_HUMAN_READABLE_OUTPUT_LANGUAGE,
    "language_policy": KCODE_LANGUAGE_POLICY,
}

QUERY_CONTRACT_REFS = [
    "contracts/k/command-contract.md",
    "contracts/k/query-workflow.md",
]
QUERY_CODE_EXPLORATION_CONTRACT_REFS = [
    *QUERY_CONTRACT_REFS,
    "contracts/k/query-code-exploration.md",
]
KCODE_CONTRACT_REFS = [
    "contracts/k/command-contract.md",
    "contracts/k/code-workflow.md",
]
KU_CONTRACT_REFS = [
    "contracts/k/command-contract.md",
    "contracts/k/update-workflow.md",
    ".trae/agents/knowledge-manager.md",
]
KU_CONTINUATION_POLICY = {
    "maintenance_preflight_package_is_final": False,
    "slash_command_must_continue": True,
    "continue_as": "knowledge-manager",
    "continue_until": "wiki_maintenance_verified_or_agent_blocked",
    "human_readable_output_language": KCODE_HUMAN_READABLE_OUTPUT_LANGUAGE,
    "language_policy": KCODE_LANGUAGE_POLICY,
}

QUERY_MECHANISM = "karpathy_query_index_first_read_plan"
QUERY_BUNDLE_POLICY = {
    "allowed_roots": ["wiki"],
    "forbidden_roots": ["raw", "relations", "state"],
    "forbidden_paths": ["raw/**"],
    "direct_scan": "forbidden",
}

QUERY_ANSWER_REQUIREMENTS = {
    "must_use_only": "evidence_pages",
    "required_sections": ["答案", "引用", "置信度", "冲突", "缺口"],
    "citation_format": "<knowledge_id>:<wiki_path>",
    "forbidden_citation_sources": ["index_hits", "candidate_pages", "omitted_candidates"],
}

QUERY_AGENTIC_CODING_REQUIREMENTS = {
    "profile": "agentic_coding",
    "required_sections": ["现有实现", "代码定位", "复用边界", "改动点", "约束", "测试/验证路径", "缺口与继续探索"],
    "must_extract": [
        "current_implementation_state",
        "code_paths_symbols_or_components",
        "reuse_boundary",
        "change_points",
        "data_permission_runtime_constraints",
        "test_or_manual_verification_entrypoints",
        "missing_knowledge_and_next_exploration_targets",
    ],
    "must_mark_unknown": True,
}

QUERY_PRD_DESIGN_REQUIREMENTS = {
    "profile": "prd_design_from_code",
    "required_sections": ["已有能力", "设计可继承部分", "设计受限边界", "需要新增或澄清", "实现影响", "缺口"],
    "must_extract": [
        "existing_capabilities",
        "design_reuse_from_current_implementation",
        "constraints_from_current_code",
        "new_or_uncertain_requirements",
        "implementation_impact_for_product_design",
        "knowledge_gaps",
    ],
    "must_mark_unknown": True,
}

CLI_LIMITATIONS = {
    "model_synthesis": "not_performed_by_cli",
    "wiki_body_maintenance": "not_performed_by_cli",
    "query_filing": "not_performed_by_cli",
    "karpathy_lint": "not_performed_by_cli",
}

RELATION_DECISION_SKELETON = {
    "action": "undecided",
    "allowed_actions": ["rebuild", "noop"],
    "triggers": [],
    "files": list(RELATION_FILE_NAMES),
    "decided_by": "codex_knowledge_manager_agent_after_wiki_changes",
}

MANAGER_OUTPUT_FIELDS = [
    "task_classification",
    "knowledge_target",
    "karpathy_alignment",
    "preflight_query_policy",
    "wiki_artifact_summary",
    "wiki_reconciliation",
    "relations_decision",
    "source_trace",
    "blockers",
    "verifier_handoff",
    "quality_loop",
]

VERIFIER_OUTPUT_FIELDS = [
    "passed",
    "confidence",
    "issues",
    "suggestions",
    "verification_scope",
]

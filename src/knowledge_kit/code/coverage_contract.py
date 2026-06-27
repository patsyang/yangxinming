from __future__ import annotations


AGENTIC_CODING_COVERAGE_CONTRACT: dict = {
    "contract_id": "kcode.agentic_coding.v1",
    "purpose": [
        "support_agentic_coding_against_current_code",
        "support_prd_design_from_current_implementation",
        "support_repository_exploration_when_formal_knowledge_is_insufficient",
    ],
    "knowledge_levels": [
        {
            "level": "code_map",
            "allowed_claims": [
                "repository purpose",
                "module boundaries",
                "entrypoints",
                "navigation hints",
            ],
            "not_allowed_as": "feature_implementation_or_coding_playbook",
        },
        {
            "level": "feature_implementation",
            "required_layers": [
                "user_surface_or_calling_entrypoint",
                "frontend_route_or_page_when_present",
                "api_client_or_external_interface_when_present",
                "backend_controller_or_message_handler_when_present",
                "service_or_domain_logic",
                "repository_mapper_dao_or_external_dependency",
                "domain_model_dto_schema_or_persistent_fields",
                "permission_config_feature_flag_or_runtime_wiring_when_present",
                "tests_fixtures_or_manual_verification_path_when_present",
            ],
        },
        {
            "level": "coding_playbook",
            "required_claims": [
                "where_to_change",
                "what_to_reuse",
                "what_not_to_change_without_extra_exploration",
                "data_contract_constraints",
                "runtime_or_deployment_constraints",
                "test_or_verification_entrypoints",
            ],
        },
    ],
    "gap_policy": {
        "blocking_gaps": [
            "missing_required_layer_for_claimed_feature_implementation",
            "missing_code_path_for_claimed_change_point",
            "missing_data_contract_for_claimed_business_or_design_behavior",
            "missing_permission_or_runtime_wiring_for_claimed_available_behavior",
            "missing_test_or_verification_path_for_coding_playbook",
            "evidence_only_supports_code_map_but_finding_claims_feature_or_coding_support",
        ],
        "non_blocking_gaps": [
            "adjacent_optional_path_not_needed_for_current_claim",
            "test_depth_unknown_but_no_coding_playbook_claim",
            "historical_context_unknown_but_current_code_claim_is_supported",
        ],
        "exploration_hints": [
            "where_an_agent_should_continue_searching_if_user_asks_to_modify_this_area",
            "candidate_files_or_symbols_not_required_for_current_verified_claim",
        ],
    },
}


VALID_KNOWLEDGE_LEVELS = {"code_map", "feature_implementation", "coding_playbook"}
VALID_COVERAGE_STATUSES = {"covered", "not_applicable", "blocking_gap"}

REQUIREMENTS_BY_LEVEL = {
    "code_map": [
        "repository purpose",
        "module boundaries",
        "entrypoints",
        "navigation hints",
    ],
    "feature_implementation": [
        "user_surface_or_calling_entrypoint",
        "frontend_route_or_page_when_present",
        "api_client_or_external_interface_when_present",
        "backend_controller_or_message_handler_when_present",
        "service_or_domain_logic",
        "repository_mapper_dao_or_external_dependency",
        "domain_model_dto_schema_or_persistent_fields",
        "permission_config_feature_flag_or_runtime_wiring_when_present",
        "tests_fixtures_or_manual_verification_path_when_present",
    ],
    "coding_playbook": [
        "where_to_change",
        "what_to_reuse",
        "what_not_to_change_without_extra_exploration",
        "data_contract_constraints",
        "runtime_or_deployment_constraints",
        "test_or_verification_entrypoints",
    ],
}

CODING_CONTEXT_FIELDS_BY_CLAIM = {
    "where_to_change": "change_points",
    "what_to_reuse": "reuse_points",
    "what_not_to_change_without_extra_exploration": "do_not_change_without_extra_exploration",
    "data_contract_constraints": "data_contracts",
    "runtime_or_deployment_constraints": "runtime_constraints",
    "test_or_verification_entrypoints": "verification_entrypoints",
}

CODING_CONTEXT_REQUIRED_FIELDS = list(CODING_CONTEXT_FIELDS_BY_CLAIM.values())


def requirements_for_level(level: str) -> list[str]:
    return REQUIREMENTS_BY_LEVEL.get(level, [])

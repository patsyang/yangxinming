from __future__ import annotations


def code_exploration_steps() -> list[dict]:
    return [
        {
            "step": "locate_candidate_files",
            "action": "先用文件名/路径搜索缩小候选仓库和模块，不要先读全仓库正文。",
        },
        {
            "step": "search_relevant_symbols_and_terms",
            "action": "在候选仓库内搜索业务词、英文代码别名、接口路径、controller/service/repository/job/runner 等线索。",
        },
        {
            "step": "trace_implementation_chain",
            "action": "沿前端页面/API -> controller -> service -> repository/mapper -> runtime consumer/job/runner -> tests 追链。",
        },
        {
            "step": "report_verified_code_findings",
            "action": "最终把代码验证结果和 wiki 证据分开呈现，引用具体代码路径；不把探索计划本身当事实。",
        },
    ]


def code_exploration_loop() -> dict:
    return {
        "schema_version": "query.code_exploration_loop.v1",
        "purpose": "turn_query_bundle_navigation_into_verified_code_findings",
        "stop_rule": "只有 completion_criteria 满足，或明确记录每个缺失项和下一步更精确命令后，才允许输出最终回答。",
        "phases": [
            {
                "id": "discover_candidate_files",
                "goal": "把 wiki/code_map 线索收敛为候选代码文件列表。",
                "inputs": ["codex_next_step.commands", "code_exploration.repo_targets", "code_exploration.code_anchors"],
                "actions": [
                    "在 command_cwd 或 workspace_commands[].command_cwd 下执行首轮 rg 命令。",
                    "保留与查询主题、code_map_matches、repo_targets、code_anchors 同时相关的候选文件。",
                    "如果首轮命中太宽，优先用 code_anchors 中的类名、API 文件、页面路径或 endpoint 追加更精确的 rg。",
                ],
                "output": "candidate_files_with_reason",
            },
            {
                "id": "read_entrypoints",
                "goal": "读取候选入口代码，而不是只返回文件名。",
                "actions": [
                    "优先读取页面/API 模块、controller/resource/rest、router、job/runner、service 中最相关的 2-6 个文件。",
                    "每个文件只读取必要窗口；用 rg -n 定位类名、方法名、endpoint、service 调用和 mapper/repository 调用后再读邻近片段。",
                    "记录每个入口为什么相关，以及它提供了现有实现、请求/响应字段、权限或运行时线索中的哪一类证据。",
                ],
                "output": "read_entrypoints_with_code_paths",
            },
            {
                "id": "trace_implementation_chain",
                "goal": "沿入口追到实现链和数据/权限/运行时约束。",
                "actions": [
                    "从前端 API 追到后端 endpoint/controller，再追到 service/repository/mapper/model/config/runtime consumer。",
                    "搜索已读代码中的方法名、DTO/model、mapper id、endpoint path、常量名和表/字段名。",
                    "如果找不到运行时消费者、权限判断、测试入口或数据落库点，记录为缺口，并给出下一条更精确 rg 命令。",
                ],
                "output": "implementation_chain_constraints_and_gaps",
            },
            {
                "id": "identify_reuse_change_and_verification",
                "goal": "把代码事实转换为 Agentic Coding / PRD 可用上下文。",
                "actions": [
                    "列出可复用的页面/API/controller/service/repository/model/config。",
                    "列出需要改动或新增的入口、字段、接口、服务、mapper、权限或测试。",
                    "列出现有约束和测试/手工验证路径；没有证据时写未知，不用推测补齐。",
                ],
                "output": "reuse_change_boundary_and_verification_path",
            },
            {
                "id": "synthesize_code_verification_result",
                "goal": "生成最终回答中的“代码验证结果”。",
                "actions": [
                    "按 verification_report_template.sections 输出。",
                    "引用本地代码路径作为代码事实来源，并和 wiki evidence_pages 结论分开。",
                    "逐项对照 completion_criteria；未满足项必须写缺口和下一步命令。",
                ],
                "output": "代码验证结果",
            },
        ],
        "generic_command_templates": {
            "locate_symbol": 'rg -n -i "<symbol_or_endpoint_or_term>" <candidate_repo_or_file> -g "*.java" -g "*.js" -g "*.ts" -g "*.vue" -g "*.xml" -g "*.sql"',
            "list_related_tests": 'rg --files <candidate_repo> | rg -i "(test|spec|it|e2e|controller|service|mapper)"',
            "find_lines_in_candidate_file": 'rg -n -i "<class_or_method_or_endpoint_or_field>" "<candidate_file>"',
            "read_file_window_powershell": '$start=[Math]::Max(1,<line>-40); $end=<line>+80; $i=0; Get-Content -LiteralPath "<candidate_file>" | ForEach-Object { $i++; if ($i -ge $start -and $i -le $end) { "${i}:$_" } }',
            "trace_symbol_in_repo": 'rg -n -i "<method_or_class_or_mapper_or_dto>" <candidate_repo_or_file> -g "*.java" -g "*.js" -g "*.ts" -g "*.vue" -g "*.xml" -g "*.sql"',
            "read_file_window": "先用 find_lines_in_candidate_file 定位行号，再用 read_file_window_powershell 读取命中行附近窗口；继续用 trace_symbol_in_repo 追 service/repository/mapper/test。",
        },
    }


def code_trace_requirements() -> list[dict]:
    return [
        {
            "key": "candidate_entrypoints",
            "required": True,
            "expected_evidence": "前端页面/API 模块、router、controller/resource/rest endpoint 或 CLI/job 入口之一。",
        },
        {
            "key": "implementation_chain",
            "required": True,
            "expected_evidence": "从入口继续追到 service/repository/mapper/model/config/runtime consumer 中至少一层；不能只停在文件名命中。",
        },
        {
            "key": "runtime_data_permission_constraints",
            "required": True,
            "expected_evidence": "列出已读代码中能确认的数据字段、租户/权限/运行时消费约束；未找到时写未知和下一步命令。",
        },
        {
            "key": "reuse_and_change_boundary",
            "required": True,
            "expected_evidence": "说明哪些现有类/接口/配置可复用，哪些改动点仍需进一步读代码确认。",
        },
        {
            "key": "test_or_manual_verification",
            "required": True,
            "expected_evidence": "测试类、接口手工验证入口、页面操作路径或构建/单测命令；未找到时写缺口。",
        },
        {
            "key": "prd_design_projection",
            "required": True,
            "expected_evidence": "当 active_profiles 包含 prd_design_from_code 时，必须把代码事实投影为可继承设计、设计受限边界、实现影响、需要新增或澄清；没有代码证据的设计点写未知。",
        },
    ]


def code_verification_result_contract(answer_requirements: dict) -> dict:
    active_profiles = list(answer_requirements.get("active_profiles") or [])
    contract = {
        "schema_version": "query.code_verification_result_contract.v1",
        "language": "zh-CN",
        "output_block": "代码验证结果",
        "citation_policy": "每条代码事实必须引用本地代码路径；未知项写 unknown，不得由 code_exploration 计划或 wiki 证据推断。",
        "required_contexts": [
            {
                "name": "agentic_coding_context",
                "required_when_profile": "agentic_coding",
                "fields": [
                    {"key": "existing_implementation", "description": "已读代码能确认的现有实现现状；没有证据写 unknown。"},
                    {"key": "code_locations", "description": "候选入口、关键类/函数/endpoint/API 文件/页面/mapper/test 路径。"},
                    {"key": "implementation_chain", "description": "入口到 service/repository/mapper/model/config/runtime consumer/test 的已确认链路或缺口。"},
                    {"key": "reuse_boundary", "description": "可复用的页面/API/controller/service/repository/model/config/测试及不可复用原因。"},
                    {"key": "change_points", "description": "为满足用户需求可能需要新增或修改的位置；只写代码证据能支撑的点。"},
                    {"key": "constraints", "description": "已确认的数据字段、状态、租户、权限、运行时消费、配置或兼容性约束。"},
                    {"key": "verification_path", "description": "可执行测试、手工接口验证、页面验证路径或未找到测试时的缺口。"},
                    {"key": "gaps_and_next_commands", "description": "未确认事实、不能下结论的点和下一步更精确 rg/读取命令。"},
                ],
            },
            {
                "name": "coding_execution_plan",
                "required_when_profile": "agentic_coding",
                "fields": [
                    {"key": "pre_edit_checks", "description": "改代码前必须确认的代码事实、缺口和阻断条件；未确认时写 gap 和下一步命令。"},
                    {"key": "files_to_edit", "description": "基于已读代码证据可以编辑的候选文件、符号和改动原因；不能把未读文件列为已确认编辑目标。"},
                    {"key": "safe_edit_boundary", "description": "本次需求允许改动的模块、接口、字段、配置和测试边界，以及明确不应改动的位置。"},
                    {"key": "implementation_steps", "description": "按前端、后端、数据/mapper、权限/配置、测试组织的具体改动步骤；每步引用支撑代码路径或写 gap。"},
                    {"key": "validation_commands", "description": "完成改动后应执行的测试、构建、lint 或手工接口/页面验证命令；无法确定时写 gap 和下一步命令。"},
                    {"key": "rollback_or_risk_notes", "description": "可能影响已有行为的风险、回滚点、兼容性注意事项和仍需人工确认的内容。"},
                ],
            },
        ],
        "unknown_policy": "缺少已读代码证据时，该字段值必须写 unknown 或 gap，并给出下一步命令；不得用常识、candidate pages 或 code_map 计划补事实。",
    }
    if "prd_design_from_code" in active_profiles:
        contract["required_contexts"].append(
            {
                "name": "prd_design_projection",
                "required_when_profile": "prd_design_from_code",
                "fields": [
                    {"key": "inherited_design", "description": "PRD 可以直接继承的现有对象、页面、流程、接口、字段、状态或权限模型。"},
                    {"key": "restricted_design_boundary", "description": "受现有代码限制的设计边界，包括不能承诺的运行时能力、数据范围、权限范围或兼容性要求。"},
                    {"key": "implementation_impact", "description": "若按该需求落地，需要影响的前端、后端、数据、配置、测试或迁移面。"},
                    {"key": "new_or_clarify", "description": "PRD 仍需新增、澄清或验证的业务规则和技术前提。"},
                    {"key": "design_gaps_and_next_commands", "description": "当前代码证据不足以支撑的设计点和下一步代码探索命令。"},
                ],
            }
        )
    return contract


def code_verification_quality_gate(answer_requirements: dict) -> dict:
    active_profiles = list(answer_requirements.get("active_profiles") or [])
    pass_conditions = [
        {"key": "commands_executed", "required": True, "check": "代码验证结果记录了实际执行的命令和 cwd；没有执行时不得 final。"},
        {"key": "local_code_paths_cited", "required": True, "check": "每条已确认代码事实至少引用一个本地代码路径；wiki path 不能替代代码路径。"},
        {"key": "entrypoint_read", "required": True, "check": "至少读取过一个候选入口或实现文件片段；不能只列 rg 命中文件名。"},
        {"key": "chain_or_gap_recorded", "required": True, "check": "实现链至少确认一跳，或明确写出未追到链路和下一步命令。"},
        {"key": "constraints_or_gap_recorded", "required": True, "check": "数据/权限/运行约束有代码证据，或明确写 unknown/gap 和下一步命令。"},
        {"key": "verification_or_gap_recorded", "required": True, "check": "测试/手工验证路径有代码证据，或明确写未找到和下一步命令。"},
        {"key": "result_contract_filled", "required": True, "check": "按 result_contract 填写 agentic_coding_context 和 coding_execution_plan；PRD 场景还要填写 prd_design_projection。"},
        {"key": "coding_execution_plan_or_gap_recorded", "required": True, "check": "必须给出基于已读代码证据的 files_to_edit、safe_edit_boundary、implementation_steps、validation_commands，或明确写 gap 和下一步命令。"},
    ]
    if "prd_design_from_code" in active_profiles:
        pass_conditions.append(
            {"key": "prd_projection_or_gap_recorded", "required": True, "check": "PRD 设计投影必须明确可继承设计、受限边界、实现影响、需新增/澄清，或写设计缺口和下一步命令。"}
        )
    return {
        "schema_version": "query.code_verification_quality_gate.v1",
        "language": "zh-CN",
        "applies_to_output_block": "代码验证结果",
        "final_answer_allowed_when": "所有 pass_conditions 满足；若不满足，只能输出不足与下一步探索，不能写成已确认代码结论。",
        "pass_conditions": pass_conditions,
        "blocking_fail_conditions": [
            {"key": "only_query_bundle_or_code_exploration", "description": "只复述 query_evidence_bundle、code_exploration、code_map_matches 或 suggested_rg，没有执行代码命令。"},
            {"key": "only_file_list_without_reading", "description": "只列出 rg 命中文件，没有读取关键代码片段。"},
            {"key": "facts_without_local_code_citations", "description": "把实现事实写成已确认，但没有本地代码路径引用。"},
            {"key": "uses_wiki_or_code_map_as_code_fact", "description": "用 wiki evidence、candidate page、code_map 或探索计划替代实际代码事实。"},
            {"key": "missing_required_context_fields", "description": "未按 result_contract 填写必需上下文字段，也没有写 unknown/gap 和下一步命令。"},
        ],
        "self_check_output": {
            "required": True,
            "section": "代码验证质量门",
            "format": "列出 pass/fail 项；若 fail，说明阻断原因和下一步命令。",
        },
    }


def code_verification_result_skeleton(answer_requirements: dict) -> dict:
    active_profiles = list(answer_requirements.get("active_profiles") or [])
    skeleton = {
        "schema_version": "query.code_verification_result_skeleton.v1",
        "language": "zh-CN",
        "markdown_block": "代码验证结果",
        "fill_policy": "所有已确认事实必须引用本地代码路径；无法确认的字段写 unknown 或 gap，并给出 next_commands。",
        "wiki_evidence_assessment": {
            "alignment": "unknown",
            "refined_queries_executed": [],
            "remaining_wiki_gaps": [],
            "policy": "只记录 wiki evidence 是否对题和剩余缺口；不得把 wiki/code_map 当作已验证代码事实。",
        },
        "executed_commands": [{"cwd": "", "command": "", "result_summary": ""}],
        "read_code_paths": [{"path": "", "line_refs": "", "why_relevant": ""}],
        "agentic_coding_context": {
            "existing_implementation": {"value": "unknown", "code_citations": [], "gaps": []},
            "code_locations": {"value": [], "code_citations": [], "gaps": []},
            "implementation_chain": {"value": [], "code_citations": [], "gaps": []},
            "reuse_boundary": {"value": "unknown", "code_citations": [], "gaps": []},
            "change_points": {"value": [], "code_citations": [], "gaps": []},
            "constraints": {"value": [], "code_citations": [], "gaps": []},
            "verification_path": {"value": "unknown", "code_citations": [], "gaps": []},
            "gaps_and_next_commands": [],
        },
        "coding_execution_plan": {
            "pre_edit_checks": [],
            "files_to_edit": [],
            "safe_edit_boundary": "unknown",
            "implementation_steps": [],
            "validation_commands": [],
            "rollback_or_risk_notes": [],
        },
        "quality_gate_self_check": [
            {"key": "commands_executed", "status": "fail", "evidence_or_gap": ""},
            {"key": "entrypoint_read", "status": "fail", "evidence_or_gap": ""},
            {"key": "local_code_paths_cited", "status": "fail", "evidence_or_gap": ""},
            {"key": "chain_or_gap_recorded", "status": "fail", "evidence_or_gap": ""},
            {"key": "constraints_or_gap_recorded", "status": "fail", "evidence_or_gap": ""},
            {"key": "verification_or_gap_recorded", "status": "fail", "evidence_or_gap": ""},
        ],
    }
    if "prd_design_from_code" in active_profiles:
        skeleton["prd_design_projection"] = {
            "inherited_design": {"value": "unknown", "code_citations": [], "gaps": []},
            "restricted_design_boundary": {"value": "unknown", "code_citations": [], "gaps": []},
            "implementation_impact": {"value": "unknown", "code_citations": [], "gaps": []},
            "new_or_clarify": [],
            "design_gaps_and_next_commands": [],
        }
        skeleton["quality_gate_self_check"].append(
            {"key": "prd_projection_or_gap_recorded", "status": "fail", "evidence_or_gap": ""}
        )
    return skeleton


def code_verification_report_template(answer_requirements: dict) -> dict:
    active_profiles = list(answer_requirements.get("active_profiles") or [])
    sections = [
        {"section": "已执行命令", "required": True, "content": "列出实际执行的命令、执行 cwd、命中数量或无命中结果。"},
        {"section": "候选入口", "required": True, "content": "列出已读取的前端页面/API 模块、router、controller/resource/rest endpoint、job/runner 等入口路径和符号。"},
        {"section": "实现链", "required": True, "content": "按入口 -> service -> repository/mapper/model/config/runtime consumer/test 的顺序列出已确认链路；未追到的环节写缺口。"},
        {"section": "运行/数据/权限约束", "required": True, "content": "列出代码中确认的数据字段、状态、租户、权限、运行时消费或配置约束；没有证据写未知。"},
        {"section": "复用边界与改动点", "required": True, "content": "说明可复用的类、接口、页面、配置、测试，以及仍需新增或修改的位置。"},
        {"section": "测试/验证路径", "required": True, "content": "列出测试类、接口手工验证入口、页面操作路径或构建/单测命令；未找到写缺口。"},
    ]
    if "prd_design_from_code" in active_profiles:
        sections.append(
            {"section": "PRD 设计投影", "required": True, "content": "把代码事实投影为已有能力、设计可继承部分、设计受限边界、实现影响、需要新增或澄清；没有代码证据的设计点写未知。"}
        )
    sections.append(
        {"section": "缺口与下一步探索", "required": True, "content": "列出仍未确认的链路、约束、测试和下一步更精确命令；不得把未读代码当事实。"}
    )
    return {
        "schema_version": "query.code_verification_report_template.v1",
        "language": "zh-CN",
        "required_block": "代码验证结果",
        "active_profiles": active_profiles,
        "sections": sections,
        "citation_policy": "代码事实引用本地代码路径；wiki 结论引用 <knowledge_id>:<wiki_path>；两者分开标注。",
    }


def code_verification_completion_criteria(answer_requirements: dict) -> dict:
    active_profiles = list(answer_requirements.get("active_profiles") or [])
    required_evidence = [
        {"key": "executed_commands", "minimum": 1, "description": "至少执行并记录一条实际代码探索命令；无命中也必须记录。"},
        {"key": "read_entrypoint_or_candidate", "minimum": 1, "description": "至少读取一个候选入口或候选实现文件的片段，不能只列文件名。"},
        {"key": "implementation_chain_or_gap", "minimum": 1, "description": "至少确认一段入口到下一层实现的链路，或明确写出未追到链路及下一步命令。"},
        {"key": "constraints_or_gap", "minimum": 1, "description": "至少确认一个数据/权限/运行约束，或明确写未知和继续探索路径。"},
        {"key": "verification_path_or_gap", "minimum": 1, "description": "至少确认一个测试/手工验证入口，或明确写未找到和下一步命令。"},
    ]
    if "prd_design_from_code" in active_profiles:
        required_evidence.append(
            {"key": "prd_projection_or_gap", "minimum": 1, "description": "必须把已读代码事实投影到 PRD 设计，或明确说明因缺少代码证据只能列为设计缺口。"}
        )
    return {
        "schema_version": "query.code_verification_completion_criteria.v1",
        "final_answer_allowed_after_code_exploration": True,
        "required_evidence": required_evidence,
        "insufficient_evidence_policy": "如果未满足 required_evidence，不能把当前代码验证写成已确认结论；必须继续执行更精确命令，或在代码验证结果中只报告不足与下一步探索。",
    }

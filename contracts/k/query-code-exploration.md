# /k query Code Exploration Contract

代码知识库的 `wiki` 是高价值索引和已验证结论层，不是穷尽代码事实库。涉及 Agentic Coding、PRD 设计或实际改代码时，即使 `quality.confidence=high`，也应按 `code_exploration` 回到代码 workspace 确认当前实现。

## 触发条件

当 bundle 顶层或 next step 出现以下任一信号时，当前会话不得 final：

- `status=requires_code_exploration`
- `completion_state=not_complete`
- `continuation_policy.slash_command_must_continue=true`
- `codex_next_step.status=requires_code_exploration`
- `codex_next_step.final_answer_allowed=false`
- `code_exploration.execution_policy.must_execute_before_final=true`

必须进入 `codex_next_step.command_cwd` 或各 `codex_next_step.workspace_commands[].command_cwd`，执行 `codex_next_step.commands` 或等价更精确 `rg` 命令，读取关键代码片段，补齐“代码验证结果”。

## 边界

- `code_exploration.not_evidence=true` 表示它不是事实证据，不得作为最终引用来源。
- `repo_targets`、`code_anchors`、`suggested_rg` 只是首轮探索入口。
- `selection_reason=evidence_code_map_match` 只表示来自 code_map 表格行，仍必须读代码后才能形成事实。
- `repo_target_status=snapshot_fallback` 时，repo 只是候选清单，必须先搜索再收敛。
- 不得扫描非 `code_exploration.workspaces` 指定的代码 workspace。
- 不得把 `code_exploration` 或 code_map 直接写成当前实现事实。

## 探索循环

执行顺序：

1. 发现候选文件。
2. 读取入口代码。
3. 沿前端/API/controller/service/repository/mapper/runtime/test 追实现链。
4. 识别数据、权限、租户、运行时、配置和持久化约束。
5. 识别复用边界、改动点、暂不应改动范围。
6. 找测试、构建、lint、接口或页面手工验证路径。
7. 按 `verification_result_skeleton` 与 `result_contract` 输出“代码验证结果”。

`exploration_loop.generic_command_templates` 是命中后的通用读取模板：先定位类名、方法、endpoint、字段行号，再读取文件窗口，再追 symbol 到 service/repository/mapper/test。

## 结果合同

“代码验证结果”必须包含：

- `wiki_evidence_assessment`
- `executed_commands`
- `read_code_paths`
- `agentic_coding_context.existing_implementation`
- `agentic_coding_context.code_locations`
- `agentic_coding_context.implementation_chain`
- `agentic_coding_context.reuse_boundary`
- `agentic_coding_context.change_points`
- `agentic_coding_context.constraints`
- `agentic_coding_context.verification_path`
- `agentic_coding_context.gaps_and_next_commands`
- `coding_execution_plan.pre_edit_checks`
- `coding_execution_plan.files_to_edit`
- `coding_execution_plan.safe_edit_boundary`
- `coding_execution_plan.implementation_steps`
- `coding_execution_plan.validation_commands`
- `coding_execution_plan.rollback_or_risk_notes`

PRD 场景还必须包含：

- `prd_design_projection.inherited_design`
- `prd_design_projection.restricted_design_boundary`
- `prd_design_projection.implementation_impact`
- `prd_design_projection.new_or_clarify`
- `prd_design_projection.design_gaps_and_next_commands`

所有已确认事实必须引用本地代码路径；无法确认的字段写 `unknown`、`gap` 和下一步命令。

## quality_gate / Quality Gate

最终回答必须追加 `代码验证质量门` 自检，并说明是否满足以下要求。

以下情况阻断 final：

- 只复述 bundle。
- 只列文件名但未读代码。
- 缺本地代码路径引用。
- 把 wiki/code_map 当代码事实。
- 未填 `result_contract` 必需字段。
- 未记录实际执行命令。

触发阻断时，只能报告不足和下一步命令，不能写成已确认代码结论。

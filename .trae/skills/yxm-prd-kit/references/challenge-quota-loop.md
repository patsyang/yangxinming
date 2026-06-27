# Challenge Quota Loop

Challenge Quota Loop 防止 PRD 讨论只走线性阶段、问题过少或问题集中在单一视角。它不鼓励机械凑数；只有绑定真实用户 turn receipt 且已回灌的问题才计入有效问题。

## 配置

过程文件可以包含配置区。没有配置时使用 wf 默认值。

```text
## PRD Kit Configuration
| key | value | updated_by | updated_at | reason |
| --- | --- | --- | --- | --- |
| challenge_quota.target_total | 200 | default | 2026-05-20 | default quality bar |
| challenge_quota.stage_policy | proportional | default | 2026-05-03 | 按总数比例分摊 |
| challenge_quota.perspective_policy | proportional | default | 2026-05-03 | 按总数比例分摊 |
```

用户可以随时用自然语言显式调整 `challenge_quota.target_total`。LLM 负责解析意图并更新配置；runtime 只读取配置和校验结果。调低配额不会自动放行，仍要重新计算阶段覆盖、视角覆盖、open issue 和 repair loop。不得引入“最低可用配额”作为默认或推荐目标，避免把默认质量门从 200 误降为较低数值。

## 有效问题

有效问题必须同时满足：

- 用户已回答或明确确认修复假设，且该回答绑定到 host 生成的 `user_turn` receipt。
- 用户没有判定该问题无效。
- 问题不是同类问题换话术。
- 问题记录了阶段、视角、类别、影响章节、为什么重要和回灌位置。
- 回答已经回灌到事实、边界、对象、状态、关键业务流程、验收、风险或排除项。

用户说“不算”“无效”“没价值”“不是这个问题”时，该问题必须标记为 `invalidated`，不计数，并换视角重新提问。用户指出上一轮问题本身错误、口径不成立、验收不可执行、不是目标 PRD 应包含内容，或正在质疑模型提问/产物错误时，该轮只能记录为 `acceptance_type=repair` 或 `invalidated`，不得计入 quota；修复后必须重新提出新的有效问题。

## Effective Challenge Ledger

```text
## Effective Challenge Ledger
| challenge_id | stage | perspective | category | question | why_matters | affected_section | answer_summary | answer_status | acceptance_type | user_acceptance_ref | invalidation_reason | quality_score | backfill_location | asked_at | answered_at |
```

计数条件：

- `user_acceptance_ref` 指向真实存在的 host `user_turn` receipt，格式为 `user_turn:<receipt_id>`
- `answer_status=answered` 或 `answer_status=confirmed`
- `acceptance_type=answer` 或 `acceptance_type=accept`
- `invalidation_reason` 为空、`-` 或 `无`
- `backfill_location` 非空
- `quality_score` 达到 wf/runtime 定义的最低分

`acceptance_type` 取值：

- `answer`：用户回答了该问题，回答内容已回灌。
- `accept`：用户明确认可该问题/结论，认可内容已回灌。
- `repair`：用户在纠错、反质疑、指出上一轮问题或产物错误；可保留 `user_acceptance_ref` 作为修复证据，但不得计数。

## 默认分布

默认 `target_total=200` 时，runtime 会按以下阶段分布基线等比例重算；这些 baseline 是比例权重，不是固定阶段阈值。

| stage | baseline |
| --- | ---: |
| W1_value_alignment | 6 |
| W2_scenario_roles | 6 |
| W3_function_architecture | 8 |
| W4_pages_and_flows | 8 |
| W5_object_state_audit | 8 |
| W6_requirement_acceptance | 8 |
| W7_prd_gate | 4 |
| W9_formal_prd_output | 2 |

默认视角分布基线如下；用户调整总数后按比例重算。

| perspective | baseline |
| --- | ---: |
| 客户一线使用者 | 8 |
| 客户安全/合规/管理者 | 8 |
| 产品经理 | 8 |
| CTO/架构负责人 | 6 |
| 研发实现者 | 6 |
| QA/测试 | 6 |
| CEO/商业负责人 | 6 |
| 交付/客户成功 | 2 |

## Challenge Quota Summary

过程文件可以包含汇总，便于人类阅读。runtime 以 Effective Challenge Ledger 为准重新计算。

```text
## Challenge Quota Summary
| dimension | key | required | accepted | invalidated | remaining | status |
```

## 阻断规则

- W10 前总有效问题数未达到 `target_total`，阻断。
- 当前阶段退出前，本阶段有效问题数未达到按比例要求，阻断。
- W10 前任一必需视角未达到按比例要求，阻断。
- `invalidated` 问题不得计数。
- 存在 `user_acceptance_ref` 但 receipt 不存在，阻断。
- 存在 `user_acceptance_ref` 但缺少回灌位置，阻断。


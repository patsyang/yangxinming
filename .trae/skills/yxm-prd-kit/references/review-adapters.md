# Review Adapter Layer

Review Adapter Layer 用于把其他 Skill 的高价值审查方法纳入 prd-kit，但不把 prd-kit 变成多 Skill 强制流水线。默认不触发 adapter；只有当前阶段存在明确阻塞问题，且 adapter 输出能回灌到 PRD 事实、边界、对象、流程、状态、验收、风险或排除项时才触发。

## 模式

| 模式 | 含义 | 使用边界 |
| --- | --- | --- |
| lens | 在当前 prd-kit 会话内使用来源 Skill 的问题框架和输出契约 | 不切换 command，不创建外部会话 |
| handoff | 在当前项目内读取另一个 Skill 的规则完成独立评审 | 不要求派发凭证；失败必须暴露，不能写成通过 |
| evidence | 消费外部证据产物 | 必须记录 evidence provenance；需要 knowledge 事实时走 `/k query` 的 evidence bundle |
| mechanism_borrowed | 只借鉴流程机制 | 不调用来源 Skill，不把来源 Skill 的业务结论当证据 |

## Adapter Registry

| 阶段 | source_adapter | 模式 | 触发条件 | 必须输出 | 回灌位置 | 非目标 |
| --- | --- | --- | --- | --- | --- | --- |
| W1/W3/W5 | first-principles-decomposer | lens | 范围过大、对象边界混乱、方案复杂度高于目标 | 事实/假设/偏好/约束拆分，最小可验证路径 | 范围与边界、核心对象、状态机 | 不做技术架构重写 |
| W10 | plan-ceo-review | handoff | W9 完成后进入 CEO/创始人视角评审 | passed/changes_requested、回灌阶段、final_release_status | CEO 评审记录、修复计划 | 不复制 plan-ceo-review 内部逻辑 |
| 任意 | karpathy-wiki | evidence | 需要稳定知识事实或既有能力证据 | `/k query` evidence bundle provenance、事实摘录、适用边界 | 已确认事实、风险依赖 | 不直接读取外部 knowledge root |
| W1-W6/W9/W10 | grill-with-docs | lens | 新增核心术语、术语混用、对象边界不清、状态或动作含义变化、用户未显式对齐但阶段准备推进，或 W10 quota/CEO/用户反馈暴露概念错误 | 标准术语、冲突术语、一个最高价值对齐问题、场景压力测试结论、回灌位置 | 领域语言账本、概念对齐检查点、质疑账本、冲突账本、用户模型账本、关键业务流程账本、核心对象模型、状态机、验收标准、Repair Loop Ledger | 不新增外部文档产物，不切换 workflow，不创建外部会话 |

## Adapter Review Ledger

过程文件可包含以下账本。没有触发 adapter 时可以不存在，但一旦存在必须使用稳定字段。

```text
## Adapter Review Ledger
| issue_id | stage | source_adapter | adapter_mode | trigger | severity | status | blocking_stage | conclusion | target_ledger | waiver_id | evidence_provenance | updated_at |
```

字段约束：

- `issue_id` 唯一且稳定，例如 `AR-001`。
- `adapter_mode` 只能是 `lens`、`handoff`、`evidence`、`mechanism_borrowed`。
- `severity` 只能是 `low`、`medium`、`high`、`critical`。
- `status` 只能是 `open`、`resolved`、`waived`、`superseded`。
- `blocking_stage` 必须是 W0-W10 的合法阶段之一；`high/critical + open` 到达该阶段时阻断推进。
- `evidence` 必须记录 `evidence_provenance`。
- `waived` 必须记录 `waiver_id`，并能在 Adapter Waiver Ledger 中找到。

## Adapter Waiver Ledger

```text
## Adapter Waiver Ledger
| waiver_id | stage_or_section | waived_item | user_quote | risk | expiry_condition | updated_at |
```

waiver 只能豁免明确项，不能一键关闭整个质疑机制。用户驳回某个问题只关闭该问题，不自动形成 waiver。

## Deep Adapter 限制

deep adapter 指满足任一条件的 adapter：

- 产生 high/critical 结论。
- 产生阻断性账本项。
- 要求独立真实重读、证据查询或 handoff。

每轮最多触发一个 deep adapter。若多个 adapter 同时命中，优先选择能消除当前阶段阻断项的 adapter，其余写入候选质疑或假设账本。



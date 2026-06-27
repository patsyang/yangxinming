# Challenge-Driven PRD Loop

这个 Skill 的核心价值不是更快写 PRD，而是持续质疑 PRD，发现矛盾，逼近真实边界，并把用户回答沉淀成研发、测试、交付可以消费的事实。

## 每轮循环

1. 识别变化：本轮输入新增、推翻、收窄或确认了什么。
2. 概念对齐：抽取本轮新增、变更或冲突的核心概念，先对照领域语言账本、用户模型账本、关键业务流程账本、核心对象模型、状态机和用户明确否定内容。
3. 概念质疑：如果存在 high-impact 概念偏差，优先生成概念对齐问题，并说明影响对象/流程/状态/验收、判断错误风险和回灌位置。
4. 对照事实：检查已确认事实、工作假设、排除项、用户明确否定内容是否被冲突。
5. 生成候选质疑：至少 3 个，覆盖当前阶段和跨阶段风险。
6. 排序：按影响度、不确定性、返工成本、阻塞程度、用户回答成本排序。
7. 决策：只问 1 个最高价值问题；低风险缺口写成显式假设并继续。输出给用户的待确认问题必须包含必要性、1 个短模拟场景和建议口径；模拟场景只用于解释问题触发条件，不得扩展新需求或作为未确认事实回灌。建议口径默认 1 个推荐方案；只有存在两个合理产品方案时，才给 A/B 两个选项，并明确“接受”采用默认推荐项。
8. 有效计数：用户回答且接受的问题才写入 Effective Challenge Ledger 并计数；用户判无效时标记 invalidated 并重新提问；用户纠错、反质疑或指出上一轮问题/产物错误时只能记录为 `acceptance_type=repair` 或 invalidated，不得计数。
9. 视角轮换：按 `reviewer-perspectives.md` 切换客户、产品、技术、测试、CEO、交付等视角，避免同类问题换话术。
10. 业务建模：涉及用户时更新用户模型；涉及业务闭环时更新关键业务流程账本。
11. Adapter 判断：如果当前阻断项能被 Review Adapter 明确改善，按 `review-adapters.md` 选择最多 1 个 deep adapter，并记录触发原因。
12. Repair 判断：后置阶段发现前置根因时，按 `root-cause-repair-loop.md` 回退 root_stage，禁止顺手修复和自动补跑后续阶段；W10 quota/CEO/用户反馈暴露的概念问题必须记录 found_stage=W10_plan_ceo_review、root_stage 和回灌位置。
13. 回灌：把回答、假设或 adapter 结论落到具体 PRD 章节、过程文件账本和验收标准。
14. 门禁：如果存在高严重级别未关闭质疑、未处理冲突、quota 未达标、用户模型/关键业务流程不完整、high-impact 概念冲突、open repair issue 或 high/critical open adapter 阻断项，不允许进入 W7、W9、W10。

## 问题排序

优先问同时满足这些条件的问题：

- 不回答会改变核心对象、流程、状态或验收标准。
- 后续再改会造成明显返工。
- 当前阶段无法用低风险假设推进。
- 用户能用简短答案消除关键不确定性。

避免问：

- 只为了补齐形式的背景问题。
- 用户已经回答过的问题。
- 与当前阶段无关且不会阻塞下一阶段的问题。
- 能从上下文直接推断且风险低的问题。

## 账本写入

过程文件必须包含以下账本。

```text
## 质疑账本
| ID | 阶段 | 质疑类型 | 问题 | 风险 | 影响范围 | 严重级别 | 状态 | 结论 | 回灌位置 |

## 假设账本
| ID | 阶段 | 假设 | 成立条件 | 风险 | 是否需用户确认 | 回灌位置 |

## 冲突账本
| ID | 发现时间 | 冲突内容 | 涉及章节 | 处理结论 | 状态 |

## 语义反思记录
| 时间 | 阶段 | 结论 | 必须修复项 | 已处理 |

## PRD Kit Configuration
| key | value | updated_by | updated_at | reason |

## Effective Challenge Ledger
| challenge_id | stage | perspective | category | question | why_matters | affected_section | answer_summary | answer_status | acceptance_type | user_acceptance_ref | invalidation_reason | quality_score | backfill_location | asked_at | answered_at |

## Challenge Quota Summary
| dimension | key | required | accepted | invalidated | remaining | status |

## 用户模型账本

### U-001 <用户类型>
- 用户定义：
- 所属组织/租户：
- 使用入口：
- 业务目标：
- 能看到什么：
- 能创建什么：
- 能修改什么：
- 能删除/终止什么：
- 能执行的关键动作：
- 明确不能做什么：
- 与其他用户的关系：
- 数据边界：
- 审计/留痕字段：
- 涉及的关键业务流程：
- 待确认问题：

## 关键业务流程账本

### BF-001 <流程名称>
- 业务目标：
- 参与用户：
- 用户关系：
- 触发条件：
- 业务前置条件：
- 关键业务判断：
- 主路径：
- 分支与例外：
- 业务结果：
- 失败/中止后果：
- 涉及对象与状态：
- 数据/证据来源：
- 与其他流程关系：
- 验收映射：
- 待确认问题：

## Repair Loop Ledger
| issue_id | found_stage | root_stage | root_cause_type | affected_stages | severity | repair_question_id | user_acceptance | repair_status | current_repair_stage | rerun_policy | root_stage_revalidated_at | status |

## Stage Revalidation Ledger
| repair_issue_id | stage | new_challenge_count_after_reopen | exit_criteria_status | exit_evidence | next_stage |

## Adapter Review Ledger
| issue_id | stage | source_adapter | adapter_mode | trigger | severity | status | blocking_stage | conclusion | target_ledger | waiver_id | evidence_provenance | updated_at |

## Adapter Waiver Ledger
| waiver_id | stage_or_section | waived_item | user_quote | risk | expiry_condition | updated_at |

## 真实重读记录
| 时间 | 阶段 | artifact | path | 结论 | status |

## W9 章节语义质疑覆盖记录
| 章节 | challenge_id | source_adapter | 结论 | status | waiver_id |

## 领域语言账本
| term_id | 阶段 | 标准术语 | 定义 | 避免用词 | 概念类型 | 所属对象/流程 | 影响章节 | 用户确认 | user_turn_ref | 回灌位置 | 状态 |

## 概念对齐检查点
| stage | 新增概念 | 变更概念 | 冲突概念 | 最高风险概念 | 对齐问题ID | user_turn_ref | exit_status | blocker |
```

`状态` 推荐值：`open`、`answered`、`resolved_by_assumption`、`deferred`、`rejected`、`converted_to_requirement`、`closed`。

`严重级别` 推荐值：`low`、`medium`、`high`、`critical`。

## 回灌要求

每个被回答的问题必须至少回灌到一个位置：

- 已确认事实
- 工作假设
- 范围与边界
- 核心对象模型
- 状态机设计
- 页面与流程
- 需求清单
- 验收标准
- 风险与依赖
- Out of Scope

如果无法回灌，说明这个问题不值得问。

如果用户明确说问题“不算”“无效”“不是这个问题”，该问题必须标记为 invalidated，不计入 quota，不得换话术重复计数。若用户是在质疑模型上一轮提问、指出问题口径错误、指出验收不可执行或要求修正产物，该轮必须标记为 `acceptance_type=repair` 或 invalidated，只能进入修复记录，不得作为有效 challenge 计数。

## 概念对齐问题格式

```text
我需要先确认一个会影响 <对象/流程/状态/验收> 的概念：你这里说的“<原词>”，是指 <候选定义A>，还是 <候选定义B>？
如果判断错，后续 <章节/阶段> 会按错误对象继续展开；确认后我会统一写入 <领域语言账本/核心对象模型/状态机/验收标准>。
```

W10 quota 补问、CEO 评审或用户反馈暴露的概念问题必须按 backfill grill 处理：Effective Challenge Ledger 可记录 `stage=W10_plan_ceo_review`，但 `backfill_location` 必须指向根因阶段章节，Repair Loop Ledger 必须记录 `found_stage=W10_plan_ceo_review` 和真实 `root_stage`。

## 关键业务流程要求

关键业务流程不是创建、编辑、删除、查询的功能流程模板。它必须从业务目标、参与用户、用户关系、关键业务判断、业务结果、失败/中止后果、对象状态和验收映射出发。页面与按钮只能作为落地补充。

## Repair 要求

后置阶段发现前置根因时，必须定位 root_stage 并回退。修复后停留在 root_stage 继续深挖；只有 root_stage 重新满足退出条件后，才能逐阶段进入下一阶段。

## Adapter 回灌规则

adapter 结论不能直接替代 PRD 结论，必须回灌到至少一个账本或 PRD 章节。`handoff` 在当前项目内读取目标 Skill 的规则执行，不要求派发凭证；`evidence` 必须记录证据来源；`mechanism_borrowed` 只能记录机制执行结果，不能产生来源 Skill 的业务判断。

如果 adapter 只会增加治理文字、不能回答当前阻断问题，不触发。



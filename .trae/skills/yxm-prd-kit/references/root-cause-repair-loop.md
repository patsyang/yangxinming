# Root-Cause Repair Loop

Root-Cause Repair Loop 防止后置阶段发现问题后被模型顺手修改、自动补跑或自证闭环。

## 原则

- 后置阶段发现的问题必须先定位 `root_stage`。
- high/critical 问题不得顺手修改，必须问用户或让用户确认修复假设。
- 修复后停留在 `root_stage` 继续深挖，不自动执行后续阶段。
- `repair_applied` 不等于 `closed`。
- root_stage 重新满足退出条件后，才允许进入下一阶段。
- 禁止从 repair stage 直接跳回 found stage。

## Repair Loop Ledger

```text
## Repair Loop Ledger
| issue_id | found_stage | root_stage | root_cause_type | affected_stages | severity | repair_question_id | user_acceptance | repair_status | current_repair_stage | rerun_policy | root_stage_revalidated_at | status |
```

字段约束：

- `found_stage` 是发现问题的阶段。
- `root_stage` 是根因所属阶段。
- `affected_stages` 列出受影响阶段，使用逗号分隔。
- `repair_question_id` 必须能关联到 Effective Challenge Ledger。
- `user_acceptance` 必须是 `answered`、`confirmed`、`waived` 或 `rejected` 之一。
- `repair_status` 推荐值：`open`、`root_stage_identified`、`waiting_user`、`accepted_by_user`、`repair_applied`、`root_stage_reopened`、`root_stage_revalidated`、`closed`、`invalidated`。
- `rerun_policy` 必须是 `stepwise_from_root_stage`，表示只能逐阶段推进。

## Stage Revalidation Ledger

```text
## Stage Revalidation Ledger
| repair_issue_id | stage | new_challenge_count_after_reopen | exit_criteria_status | exit_evidence | next_stage |
```

修复后必须在 root_stage 继续深挖。`new_challenge_count_after_reopen` 必须大于 0，不能只改文字就出关。

## 状态机

```text
open
→ root_stage_identified
→ waiting_user
→ accepted_by_user
→ repair_applied
→ root_stage_reopened
→ root_stage_revalidated
→ closed
```

如果用户说“不算、无效、不是这个问题”，进入 `invalidated`，必须重新定位或重新提问。

## 禁止

- 禁止 W9 发现 W5 问题后直接修改 W9 文案并关闭。
- 禁止修复 root_stage 后自动补跑后续阶段。
- 禁止把 verifier 通过当作用户接受。
- 禁止 high/critical 问题没有用户回答就标记 resolved。


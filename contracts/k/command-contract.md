# /k Command Contract

`/k` 是 knowledge 操作统一入口。第一个参数必须是 action：`query`、`code`、`update`、`ingest`、`init`、`lint` 或 `validate`。

## 不变量

- 使用 `-k <knowledge_id>` 作为显式 knowledge 目标短参数。
- 查询可以面向一个 enabled knowledge，也可以面向全部 enabled knowledge。
- 任何写入 action 必须指定且只能指定一个 writable knowledge。
- 不得写入 disabled 或 read_only knowledge。
- 不得生成跨 knowledge 关系文件。
- 不得把正式知识正文迁移进 `knowledge_kit` 仓库。
- Python CLI 只提供确定性辅助输出；PowerShell CLI 不直接调用模型，也不独立完成最终综合、维护判断、INGEST 判断或完整 LINT。

## 非终态信号

- `requires_code_exploration`、`requires_semantic_review`、`requires_llm`、`requires_agent` 都不是完成态。
- `completion_state=not_complete`、`final_answer_allowed=false`、`must_continue=true`、`continuation_policy.slash_command_must_continue=true` 是强制续跑信号。
- 当前 Codex 会话必须读取 next-step artifact、contract refs 和 task package，执行对应后续动作；不得把 CLI JSON、预检包或探索计划当最终回答。

## Contract Refs

- General: `contracts/k/command-contract.md`
- Query: `contracts/k/query-workflow.md`
- Query code exploration: `contracts/k/query-code-exploration.md`
- KCode: `contracts/k/code-workflow.md`
- Update: `contracts/k/update-workflow.md`
- Ingest: `contracts/k/ingest-workflow.md`
- Lint/validate: `contracts/k/lint-validate-workflow.md`

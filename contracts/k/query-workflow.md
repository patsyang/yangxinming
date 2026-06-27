# /k query Workflow

`/k query` 对一个或多个 enabled knowledge 执行 Karpathy QUERY。必须先运行：

```powershell
python -m knowledge_kit query-bundle "问题"
python -m knowledge_kit query-bundle -k <knowledge_id> "问题"
python -m knowledge_kit query-bundle --all "问题"
```

`python -m knowledge_kit query ...` 只用于调试 read plan，不是 `/k query` 最终入口。

## 单库 QUERY

每个 selected knowledge 内必须：

1. 先读 `wiki/index.md`。
2. 从 index 条目的标题、路径、摘要产生候选。
3. 由 CLI 生成受限 `query_evidence_bundle`，输出候选页、语义计划、模块/意图判断、页面链接扩展和 `evidence_pages`。
4. 对集合类问题使用 `semantic_plan`、`coverage_proof` 和 `sufficiency`；回答数量、列表或覆盖性时只能基于集合 owner 页、成员证据或 coverage proof。
5. 对实体属性列表问题使用 `LIST_ENTITY_ATTRIBUTE`；例如“某能力支持哪些类型/状态/字段/场景”应选中对应 feature/entity owner 页，不得强制退回 module code_map 的 `collection_owner_page`。
6. Codex 只基于 `evidence_pages` 与允许的 `coverage_proof` 综合 wiki 证据结论，引用 `<knowledge_id>:<wiki_path>`。
7. 标注 bundle `quality.confidence`、冲突和缺口。
8. 只有指定单个 `-k` 且答案值得沉淀时，才按 query filing 写入该 knowledge；未指定单库目标或多库查询不归档。

禁止全文扫库、直接扫描所有正文、读取 `raw/`、读取非 selected knowledge root，或把 CLI 输出当最终答案。

## Bundle 字段边界

- `evidence_pages` 是 wiki 事实证据来源。
- `coverage_proof` 只在 `answer_requirements.must_use_only=evidence_pages_and_coverage_proof` 时用于集合数量、列表和覆盖性判断。
- `LIST_ENTITY_ATTRIBUTE` 的事实来源仍是 `evidence_pages`；它不使用 `coverage_proof` 证明集合完整性。
- `index_hits`、`candidate_pages`、`omitted_candidates` 只用于判断召回覆盖、排除原因和潜在缺口，不得作为事实引用。
- `semantic_review` 是 LLM 复核任务包，不是事实证据。
- `code_exploration` 是代码探索计划，不是事实证据；详见 `contracts/k/query-code-exploration.md`。

## Semantic Review

当 `semantic_review.required_before_final=true`、`codex_next_step.status=requires_semantic_review` 或 `codex_next_step.pre_code_semantic_review_required=true`：

1. 先复核 `evidence_pages` 是否语义对题。
2. 如不对题，按 `semantic_review.retry_policy.command_templates` 生成 refined query 并重新执行 `query-bundle`。
3. 复核结果仍不能作为事实引用；最终事实仍只能来自 `evidence_pages`、允许的 `coverage_proof` 和已执行代码探索。

当 `semantic_review.required_before_final=true` 与 `codex_next_step.status=requires_code_exploration` 同时出现时，必须按 `codex_next_step.execution_sequence` 先复核或 refined query，再执行代码探索；不能停在语义复核，也不得把语义复核结果当最终回答。

## 最终回答

最终回答必须包含：

1. 答案：只基于 `evidence_pages` 综合 wiki 证据结论；如允许使用 `coverage_proof`，仅用于集合数量、列表和覆盖性判断。
2. 引用：实际使用的 `<knowledge_id>:<wiki_path>`。
3. 置信度：bundle `quality.confidence`；如 Codex 下调，说明原因。
4. 冲突：无则写“未发现”。
5. 缺口：无则写“未发现”。
6. 若 `answer_requirements.required_answer_blocks` 非空，必须按 block 顺序追加或合并 profile 要求；证据不足写“缺口”或“未知”。
7. 若执行了代码探索，必须追加“代码验证结果”，且代码事实引用本地代码路径。

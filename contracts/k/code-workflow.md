# /k code Workflow

`/k code` 为一个明确指定的代码 knowledge 生成代码理解 handoff。目标是支撑 Agentic Coding 和 PRD 设计：Agent 读知识库后应能定位当前实现、判断复用边界、找到改动点、理解数据/权限/运行时约束，并知道下一步该探索哪些代码。

## 契约

- `-k` 必填，单次运行只面向一个 enabled、read_write knowledge。
- Python runner 只执行确定性工作。
- planner、analyzer、semantic verifier 由 Codex 读取对应 prompt 和 task package 后执行。
- handoff 生成后停止，由用户人工检查后手动触发 `knowledge-manager-agent.toml`。
- 中间 stage、repair loop 和 verifier loop 不要求用户确认。
- Verifier 不判断主观“足不足以回答问题”，只验证 `coverage_contract` 是否满足。
- 浅层目录扫描只能生成 code-map 导航，不能冒充 feature/coding 知识。

## CLI Stages

```powershell
python -m knowledge_kit code -k <knowledge_id> --stage inventory --mode from-zero
python -m knowledge_kit code -k <knowledge_id> --stage plan --resume <run_id>
python -m knowledge_kit code -k <knowledge_id> --stage plan-verify --resume <run_id>
python -m knowledge_kit code -k <knowledge_id> --stage evidence --resume <run_id> --batch <batch_id>
python -m knowledge_kit code -k <knowledge_id> --stage analyze --resume <run_id> --batch <batch_id>
python -m knowledge_kit code -k <knowledge_id> --stage verify --resume <run_id> --batch <batch_id>
python -m knowledge_kit code -k <knowledge_id> --stage handoff --resume <run_id>
```

## 自动执行

默认 `/k code -k <knowledge_id> ...` 必须自动推进到 handoff。`requires_llm` 是内部续跑信号，不是完成状态。不得停在 `plan: requires_llm`、`analyze: requires_llm` 或 `verify: requires_llm`。

每次 CLI 返回 `status=requires_llm` 时，必须读取 `codex-next-step.json` 的 `prompt`、`input`、`expected_outputs`、`after_writing_outputs_command`、`contract_refs` 和语言策略。写入 expected outputs 后复跑对应 CLI stage。若再次返回 `requires_llm`，继续循环，直到 handoff completed 或 verifier loop 达到 agent-level blocker。

执行流程：

1. inventory，记录 `run_id`。
2. plan。
3. planner 写 `plan/analysis-plan.md`、`plan/analysis-plan.json`、`plan/coverage-ledger.json`。
4. plan-verify。
5. verifier 写 `verifier/plan-verification.json`，必要时 repair。
6. 对每个 batch 执行 `evidence -> analyze -> verify`。
7. analyzer 写 `batches/<batch>/analysis.md` 和 `findings.jsonl`。
8. semantic verifier 写 `semantic-verification.json`。
9. verification 未通过时写 repair，必要时扩展 evidence，再 analyze/verify。
10. 有 `blocking_gaps` 的 finding 不得进入 handoff。
11. 所有 planned batch 都有非空 `verified-findings.jsonl` 后执行 handoff。
12. handoff 若返回 `handoff_unverified_batches`，继续处理未验证 batch，不能把已有分片当最终 handoff。

## 证据深度

- evidence 不使用固定行数窗口或固定文件预算作为理解边界。
- 从 batch seed files 出发，沿 import、HTTP endpoint、controller/service/repository/mapper/dao/model/config/test 等实现链展开，直到 worklist 没有新增代码文件。
- 跨仓库功能链必须由 planner 在 batch `repo_ids` 中显式包含相关仓库。
- `evidence.json` 必须写 `closure` 元数据：seed files、展开策略、followed reference kinds、file count、reference count、停止原因。
- feature/coding finding 必须有闭合证据链；否则继续扩展 evidence，或写入 `blocking_gaps` 并退出 handoff 候选。

## 输出语言

所有 LLM 写入的 Markdown、JSON/JSONL 人读字段必须是中文。schema id、JSON 字段名、`knowledge_level`、`coverage_claims.item/status`、文件路径、代码标识、命令、API endpoint、英文类名/函数名保持原样。

最终产物：

- `state/kcode-runs/<run_id>/handoff/index.md`
- `handoff/manifest.json`
- `handoff/handoff-quality.json`
- `handoff/shards/*.md`
- `handoff/page-blueprints/*.md`
- `handoff/knowledge-manager-request.md`

# /k update Workflow

`/k update` 对一个明确指定的外部 knowledge 执行 knowledge-manager 维护机制。CLI 只生成 deterministic preflight package，不写正式 wiki。

## 契约

- `-k` 必填。
- 目标必须 enabled 且 read_write。
- 单次命令只能写一个 knowledge。
- 所有路径解析到 selected knowledge root。
- 不允许把多库查询汇总结果当作单库写入证据。

## Karpathy 维护流程

1. 先执行 preflight QUERY：`wiki/index.md -> 命中页面 -> wikilinks`。
2. 执行 `wiki_reconciliation`。
3. 决定 `create | update | merge | delete | block`。
4. 真实修改 source/concept/entity/query/overview/index/log。
5. 判断 relations decision：`rebuild | noop`。
6. 调用 verifier handoff。

不得用单个记录页、运行 artifact 或 CLI 输出冒充维护完成。

## requires_agent 续跑

`maintenance_preflight_package` 不是完成态。CLI 返回 `status=requires_agent` 或 `continuation_policy.slash_command_must_continue=true` 时，必须读取 `ku-next-step.json` 的 `preflight_artifact`、`agent_config`、`input_materials`、`contract_refs` 和语言策略。

当前主会话必须使用 `.trae/agents/knowledge-manager.md` 作为唯一 knowledge-manager 角色合同，启动 knowledge-manager sub agent。正式 wiki/source summary/index/log/overview/relations 的写入只能由该 sub agent 执行。

不得只运行 CLI 后停止；CLI 产物只能作为 knowledge-manager sub agent 的输入材料。

最终回答不得停在 `maintenance_preflight_package`、`codex_agent_required_for_wiki_maintenance`、`CLI 仅完成维护预检` 或仅列出下一步；只有正式 wiki 已维护并完成 verifier handoff，才算 `/k update` 完成。

## KCode Handoff 输入

如果维护请求指向 `/k code` 生成的 `handoff/index.md`、`handoff/shards/*.md`、`handoff/knowledge-manager-request.md` 或 `handoff/manifest.json`：

- 必须执行 preflight QUERY 和 `wiki_reconciliation`。
- 必须读取 `handoff/manifest.json`、`handoff-quality.json`、handoff shards、verified-findings、analysis、evidence、source-summary-blueprints、page-blueprints。
- 如果质量门缺失或 `passed=false`，本轮阻断，不写正式 wiki。
- 只能写入已验证且无 `blocking_gaps` 的 finding。
- 不得把 `state/kcode-runs/**` artifact 原样复制成正式 wiki 正文。
- 必须建立或更新 `wiki/sources/code/kcode-runs/<run_id>/<shard>.md` source summary。
- source summary 只承载来源范围、追溯路径、已验证 finding 索引、非阻断缺口和候选正式页，不得冒充 feature 页。
- 正式代码 feature 页必须使用固定二级标题：`现有实现`、`代码定位`、`实现链`、`复用边界`、`改动点`、`暂不应改动`、`数据/权限/运行约束`、`测试/验证路径`、`PRD 设计影响`、`缺口与继续探索`。
- 固定章节必须有实质内容，不能只有标题或占位语；`代码定位` 必须包含仓库相对路径、类名、函数名、endpoint、配置名或测试入口之一。
- 每个正式 feature 页必须独立支撑 Agentic Coding / PRD 设计查询，不得把必要章节拆散到多页后依赖 query-bundle 拼接通过。
- frontmatter `sources` 必须指向对应 source summary。
- 如果 `wiki/schema.md` 缺少 Code Knowledge 约定，必须作为 structural update 一起补齐。

## 验收

写入后必须运行：

```powershell
python -m knowledge_kit lint -k <knowledge_id>
```

KCode 写入后还必须读取 `handoff/manifest.json` 的 `acceptance_query` 和 `acceptance_commands` 并执行。feature/coding handoff 的 query-bundle 至少选中一个 `wiki/entities/code/features/**` evidence page，且不得出现：

- `profile_no_evidence_pages`
- `profile_code_feature_evidence_missing`
- `profile_code_feature_source_trace_missing`
- `profile_code_feature_source_summary_missing`
- `profile_required_section_missing`
- `profile_query_topic_not_covered`

code_map-only handoff 必须选中 `wiki/entities/code/modules/**` 导航页，并给出可继续探索的 repo/入口线索。

verifier handoff 必须检查代码引用完整性、`coding_context` 是否落入正式页面、`blocking_gaps` 是否未写成事实、index 是否可召回、schema 是否包含 Code Knowledge 约定。

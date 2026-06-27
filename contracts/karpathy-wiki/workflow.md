# Karpathy Wiki 机制合同（多 knowledge 适配版）

本文件是原 Karpathy Wiki `SKILL.md` 与 `references/operations.md` 的中文移植版。唯一语义改动是路径适配：所有 `raw/`、`wiki/`、`relations/`、`state/` 都解析到**当前选中的外部 knowledge root** 下。

`knowledge_kit` 不实现第二套搜索或维护机制。Agent 对话触发是模型执行层；Python CLI 只做确定性辅助、路径解析、校验、source registration、运行记录和 read plan，不替代模型完成综合、ingest 判断、maintenance 判断或 verifier 判断。

## 决策树

```text
当前选中的外部 knowledge root 是否已有 wiki/？
├─ 没有，且用户要求 init wiki/start wiki → 执行 INIT
├─ 有 →
│  ├─ raw/ 有未进入 log.md 的新来源 → 执行 INGEST
│  ├─ 用户询问 knowledge 领域问题 → 执行 QUERY
│  ├─ 用户要求 lint/health check/find gaps → 执行 LINT
│  └─ 用户粘贴内容或 URL 要加入知识库 → 先保存到 raw/，再执行 INGEST
```

## 当前选中的外部 knowledge root 结构

```text
raw/                    # 不可变来源材料，由用户或 CLI source registration 放入
wiki/
  index.md              # 内容目录：每个页面的链接和摘要
  log.md                # 追加式操作日志
  schema.md             # wiki 约定，随项目演进
  overview.md           # 跨来源高层综合
  concepts/             # 概念页
  entities/             # 实体页
  sources/              # 每个来源一页摘要
  queries/              # 值得沉淀的查询综合
relations/              # 从 wiki 派生的最小机器关系层
state/                  # 权威机器状态，不是正文知识
```

## Operations

### INIT

1. 在当前选中的外部 knowledge root 下创建 `raw/`、`wiki/`、`relations/`、`state/` 结构。
2. 写入默认 `wiki/schema.md`。
3. 创建空的 `wiki/index.md` 与 `wiki/log.md`。
4. 创建 `wiki/overview.md` 占位页。
5. 如果 `raw/` 已有来源，立即对这些来源执行 INGEST。
6. 在 Codex 项目中，不创建宿主特定控制面文件；`wiki/schema.md` 是 schema 真源。

### INGEST

1. 读取当前选中 knowledge 的 `raw/` 中的新来源，记录格式、标题、来源路径。
2. 提取主要论点、事实、实体、概念、数据点、值得保留的引用，以及与既有 wiki 的冲突。
3. 如处于交互流程，先向用户说明 3-5 个关键 takeaway 并确认强调点。
4. 写入 `wiki/sources/<canonical-source-path>.md`，做结构化摘要，不复制全文。
5. 创建或更新 `wiki/concepts/` 下的重要概念页。
6. 创建或更新 `wiki/entities/` 下的重要实体页。
7. 更新被触达页面之间的 wikilinks 与反向交叉引用。
8. 如果新来源改变全局理解，更新 `wiki/overview.md`。
9. 更新 `wiki/index.md`，覆盖所有新增和改动页面。
10. 追加 `wiki/log.md`：`## [YYYY-MM-DD] ingest | Source Title`。
11. 判断 `relations/` 是 `rebuild` 还是 `noop`；source、feature、link 变化通常触发 rebuild。
12. 调用 verifier。一次来源通常会触达 10-15 个 wiki 页面。

### QUERY

1. 先读当前选中 knowledge 的 `wiki/index.md`，只能通过目录条目的标题、路径、摘要找到相关页面。
2. 再读命中页面。
3. 继续读命中页面中的相关 wikilinks。
4. 基于已读取 wiki 页面综合回答，引用 wiki 页面路径。
5. 明确标注置信度：多来源支持、单来源支持、冲突、缺口。
6. 判断是否 query filing：
   - 跨多个页面形成新的稳定综合 → 可写入 `wiki/queries/`。
   - 简单查找 → 不归档。
   - 揭示新的连接 → 归档并补充相关交叉引用。
7. 如果归档，写入 query 页，更新 `wiki/index.md`。
8. 追加 `wiki/log.md`：`## [YYYY-MM-DD] query | Question summary`。

禁止用全文扫库、直接读取所有 wiki 正文、单页记录或运行 artifact 替代 Karpathy QUERY。CLI `query` 只能输出 deterministic read plan，最终综合由 Codex 执行。

### LINT

1. 读取所有 wiki 页面，建立当前知识图景。
2. 检查 contradictions、stale claims、orphan pages、missing concepts、broken links、data gaps、thin pages。
3. 能修复的由 Codex 直接修复：过期结论、缺失交叉引用、明显缺失的概念 stub。
4. 不能修复的输出 review items：需要新来源、人类判断或业务确认的问题。
5. 建议后续来源和后续问题。
6. 追加 `wiki/log.md`：`## [YYYY-MM-DD] lint | Summary of findings`。
7. 判断 `relations/` 是 `rebuild` 还是 `noop`，必要时移交 verifier。

CLI `lint` 只做机械检查子集，不等同完整 Karpathy LINT。

## Page Conventions

每个正式 wiki 页面必须有 YAML frontmatter：

```yaml
---
title: Page Title
type: concept | entity | source | query | overview
tags: [tag1, tag2]
created: YYYY-MM-DD
updated: YYYY-MM-DD
sources: [raw/filename.md]
---
```

- 列表值必须可解析，优先使用 JSON-compatible list。
- product module 的具体能力优先进入 `entities/product/features/<MODULE>/...`，除非来源只描述抽象概念。
- source 页使用从 raw 路径派生的 canonical source path，不创建仅标点或省略分隔符不同的平行 source 页。
- product feature knowledge 不维护用户可见功能编号；不要生成新的业务编号或空编号列。
- `legacy_id` 只作为 wiki 内部稳定身份；命中既有对象时原位更新。
- 使用 `[[wikilinks]]` 做页面交叉引用。
- 每个页面开头用 1-2 句摘要说明核心内容。
- 正文中的事实必须能追溯到 source 页或 raw 来源。

## Code Knowledge Conventions

当维护材料来自 `/k code` handoff 时，它是经过 verifier 的代码知识维护材料，不是正式 wiki 正文。knowledge-manager 必须把它转成可查询的 Karpathy Wiki 页面，而不是把 `state/kcode-runs/**` 文件原样搬进 wiki。

- KCode source 页可写入 `wiki/sources/code/kcode-runs/<run_id>/<shard>.md`，frontmatter `sources` 可记录 `state/kcode-runs/<run_id>/handoff/...`、`analysis.md`、`evidence.json` 等 artifact 路径。
- 代码能力或功能实现优先写入 `wiki/entities/code/features/<module-or-domain>/<slug>.md`；代码模块、仓库或运行组件优先写入 `wiki/entities/code/modules/<repo-or-module>.md`。
- `code_map` 只能写导航、仓库职责、模块边界、入口线索和后续探索提示；不得写成“可直接编码”的结论。
- `feature_implementation` 和 `coding_playbook` 正式 feature 页面必须使用固定二级标题：`## 现有实现`、`## 代码定位`、`## 实现链`、`## 复用边界`、`## 改动点`、`## 暂不应改动`、`## 数据/权限/运行约束`、`## 测试/验证路径`、`## PRD 设计影响`、`## 缺口与继续探索`。
- `coding_playbook` 页面中的复用边界、改动点、暂不应改动、数据/权限/运行约束和测试/验证路径必须来自 KCode `coding_context` 或带 evidence refs 的 finding。
- 每条代码定位必须保留仓库相对路径、类/函数/接口/endpoint 等代码标识；不要翻译路径、类名、函数名、API endpoint。
- 如果 handoff 或 verified findings 中出现 `blocking_gaps`，不得把对应 finding 写入正式知识页；只能记录为缺口或阻断项。
- index 摘要必须包含用户后续会搜索的能力名、模块名、关键代码路径或 endpoint 线索，确保 `/k query` 能召回。

## Index.md Format

按类别组织。每个条目：

```markdown
- [Page Title](path.md) — one-line summary (N sources, YYYY-MM-DD)
```

示例：

```markdown
# Wiki Index

## Overview
- [Overview](overview.md) — High-level synthesis (updated 2026-04-04)

## Concepts
- [Attention Mechanisms](concepts/attention.md) — Self-attention, cross-attention, and variants (3 sources, 2026-04-03)

## Entities
- [GPT-4](entities/gpt-4.md) — Multimodal model, capabilities and limitations (2 sources, 2026-04-02)

## Sources
- [Attention Is All You Need](sources/attention-is-all-you-need.md) — Original transformer paper (2026-04-01)

## Queries
- [How does attention scale?](queries/attention-scaling.md) — Comparison of attention variants by compute cost (2026-04-03)
```

## Log.md Format

追加式日志，每条可被 `^## \[` 解析：

```markdown
## [2026-04-04] ingest | New Research Paper
- Source: raw/new-paper.pdf
- Pages created: concepts/new-idea.md
- Pages updated: overview.md, concepts/related.md, entities/author.md
- Total pages touched: 8

## [2026-04-03] query | How does X compare to Y?
- Pages consulted: concepts/x.md, concepts/y.md
- Answer filed: queries/x-vs-y.md

## [2026-04-02] lint | Weekly health check
- Issues found: 2 orphan pages, 1 broken link
- Fixed: all resolved
```

## 多 Knowledge 分发规则

- `/k query` 默认查询所有 `enabled=true` 的 knowledge。
- `/k query -k <id>` 只查询指定 knowledge。
- `/k update`、`/k ingest` 和任何写入 action 必须指定单个 `-k <id>`。
- 写入目标必须 `enabled=true` 且 `mode=read_write`。
- 不允许一次写多个 knowledge。
- 多库查询等于对每个 knowledge 分别执行完整 Karpathy QUERY，再由 Codex 汇总。
- 多库只影响“哪些库参与查询/哪个库被写入”，不改变单库内 INIT / INGEST / QUERY / LINT。
- 不生成跨库关系文件；关系层只在单个 selected knowledge root 内派生。

## Key Rules

- LLM 写入和维护 wiki；用户提供来源和问题。
- `raw/` 是来源真源，不对已有 raw 来源做破坏性修改。
- 每次正式 Karpathy 操作都必须考虑 `index.md`、`log.md`、`overview.md` 和 `relations/`。
- 好的查询答案会沉淀回 wiki；探索应复利。
- 维护、更新、删除、清理前必须先执行 QUERY。
- 显式维护前必须执行 `wiki_reconciliation`：`legacy_id -> canonical path -> title/alias candidate`。
- 命中既有知识对象时必须原位更新；不存在匹配对象时才允许新增。
- 不得自创第二套 wiki 语义，不得用 runtime 输出当权威正文知识，不得绕过 verifier。

---
name: yxm-prd-kit
description: 非 Agent 应用 PRD 协作 Skill。用于通过 /prd-kit 设计、质疑、回灌和产出非 Agent 应用 PRD；每轮维护过程文件、阶段账本、质疑账本、假设账本、冲突账本、语义反思记录，并在 W7/W9/W10 前执行结构与语义门禁。
---

# PRD Kit

使用本 Skill 时，先读取 `references/prd-kit.wf`，再按需读取引用文件。

## 每轮固定动作

1. 输出 `[PRD工作流] stage=<current_stage>; artifact=<process_file|formal_prd>; gate=<blocked|pass|reviewing|passed>; next=<next_stage|none>; blocker=<none|最高优先级阻断项>`。
2. 执行 `Challenge-Driven PRD Loop`：识别本轮输入改变了什么，挑战已有判断，生成候选质疑，只问最高价值问题或写明低风险假设。所有用户可见的待确认问题都必须包含“必要性”、1 个短“模拟场景”和“建议口径”。
3. 执行 `Concept Alignment Loop`：抽取本轮新增、变更或冲突的核心概念；对影响对象、状态、动作、权限、业务流程或验收口径的概念优先提出 1 个对齐问题；用户确认后写入 `领域语言账本` 和 `概念对齐检查点`。`blocker` 优先暴露 high/critical 概念冲突。
4. 执行 `Challenge Quota Loop` 和 `Perspective Rotation Loop`：只有已回答或已确认、已回灌、质量达标且非无效的问题才计入可配置 quota；默认 `challenge_quota.target_total=200`，用户可随时调整。`user_acceptance_ref` 只作为人工追溯字段，不依赖外部回合凭证。
5. 执行 `Business Scenario Loop`：凡涉及用户必须明确用户类型、能力边界、数据边界和用户关系；关键业务流程必须围绕业务闭环建模，不写成功能流程模板。
6. 按 `Review Adapter Layer` 判断是否需要引入额外审查 lens。默认不触发 adapter；只有它能回答当前阻塞问题时才触发，并写入 Adapter Review Ledger。
7. 若后置阶段发现前置根因，执行 `Root-Cause Repair Loop`：定位 root_stage，回退后停留在 root_stage 继续深挖，禁止自动补跑后续阶段或顺手闭环。W10 quota 补问或 CEO 评审暴露的概念问题必须使用 backfill grill 回灌 root_stage，禁止只在 W10 本地闭环。
8. 更新过程文件中的 `Workflow State`、`Stage Ledger`、`质疑账本`、`假设账本`、`冲突账本`、`语义反思记录`，必要时更新 quota、用户模型、关键业务流程、概念对齐、repair、adapter 和 W9 readiness 账本。
9. 阶段推进前运行 `executors/prd_kit_runtime.py check-status`；进入 W7/W9/W10 前不得存在未关闭高严重级别质疑、未处理冲突、高严重级别 adapter 阻断项、未闭合 repair issue 或 high/critical 概念冲突。
10. 正式 PRD 输出前运行 `executors/prd_kit_runtime.py check-formal-prd`，并确认 quota、用户模型、关键业务流程、概念对齐、repair、W9 语义反思、真实重读和章节级 challenge 覆盖已通过。
11. W11 仅在 W10 `yxm-plan-ceo-review` passed 后执行；读取 `references/engineering-prd-template.md`，基于最新正式 PRD 和过程文件生成带时间戳的研发版 PRD。研发版 PRD 是派生产物，不覆盖正式 PRD，也不覆盖历史研发版 PRD；W11 不做新概念讨论，只消费已确认的过程文件和正式 PRD。

## 引用文件

- `references/challenge-framework.md`：每轮质疑循环、问题排序、账本写入规则。每轮都要遵循。
- `references/stage-challenge-bank.md`：W0-W10 分阶段问题库。进入或回退阶段时读取对应阶段。
- `references/question-quality-rubric.md`：判断某个问题是否值得问。生成用户问题前读取。
- `references/challenge-quota-loop.md`：可配置有效问题 quota、阶段覆盖、视角覆盖和用户接受规则。涉及配额或阶段准出时读取。
- `references/reviewer-perspectives.md`：多角色审查视角和轮换规则。选择问题视角时读取。
- `references/business-scenario-loop.md`：用户模型和关键业务流程闭环。涉及用户或业务流程时读取。
- `references/root-cause-repair-loop.md`：根因回退、修复后当前阶段深挖和逐阶段再推进规则。发现后置问题来自前置阶段时读取。
- `references/semantic-review-checklist.md`：W7/W9/W10 前的语义级反思清单。
- `references/review-adapters.md`：其他 Skill 的审查适配器注册表、触发条件、输出契约和非目标。只有触发条件命中时读取。
- `references/prd-kit.wf`：阶段、门禁、正式 PRD 章节、输出规则的当前事实源。
- `references/engineering-prd-template.md`：W11 研发版 PRD 投影模板。仅在 W11 使用，启动阶段和 W0-W10 不得预读。

## Review Adapter Layer

不要把 prd-kit 变成多个 Skill 的强制流水线。Adapter 只在明确提升 PRD 质量时使用：

- `lens`：吸收其他 Skill 的问题框架，由当前 prd-kit 会话执行，不切换 workflow。
- `handoff`：在当前项目内读取目标 Skill 并执行其评审规则，不创建外部会话，不要求派发凭证。
- `evidence`：只消费合规证据产物；需要 knowledge 事实时必须走 `/k query` 的 evidence bundle，不直接读取外部 knowledge root。
- `mechanism_borrowed`：只借鉴流程机制，不把来源 Skill 当作 PRD adapter 调用。

每轮最多触发一个 deep adapter。deep adapter 指会产生阻断性账本项、独立重读要求或 high/critical 结论的 adapter。若没有触发条件，不需要为了完整性填写 adapter 账本。

## Runtime 边界

Runtime 只做确定性校验和结构化写入，不理解自然语言。用户说“切回 W08”“继续”“正式 PRD 有问题，退回需求清单阶段”时，由当前 LLM 会话解析成结构化阶段，再调用 runtime 校验和写回。

常用命令：

```powershell
python -X utf8 .trae\skills\yxm-prd-kit\executors\prd_kit_runtime.py inspect-wf --wf .trae\skills\yxm-prd-kit\references\prd-kit.wf
python -X utf8 .trae\skills\yxm-prd-kit\executors\prd_kit_runtime.py check-status --wf .trae\skills\yxm-prd-kit\references\prd-kit.wf --process-file output\prd-kit\<应用slug>\<应用名称>-过程文件.md
python -X utf8 .trae\skills\yxm-prd-kit\executors\prd_kit_runtime.py apply-stage-transition --wf .trae\skills\yxm-prd-kit\references\prd-kit.wf --process-file output\prd-kit\<应用slug>\<应用名称>-过程文件.md --target-stage W8_verification_checkpoint
python -X utf8 .trae\skills\yxm-prd-kit\executors\prd_kit_runtime.py check-formal-prd --wf .trae\skills\yxm-prd-kit\references\prd-kit.wf --prd output\prd-kit\<应用slug>\<应用名称>-PRD.md
python -X utf8 .trae\skills\yxm-prd-kit\executors\prd_kit_runtime.py check-engineering-prd --wf .trae\skills\yxm-prd-kit\references\prd-kit.wf --engineering-prd output\prd-kit\<应用slug>\<应用名称>-研发版PRD-YYYYMMDD-HHmmss.md --formal-prd output\prd-kit\<应用slug>\<应用名称>-PRD.md --process-file output\prd-kit\<应用slug>\<应用名称>-过程文件.md
```

Runtime JSON 默认输出到 stdout。只有显式传入 `--out <path>` 时才写 JSON 文件。不要默认生成 run record。

W4→W5 阶段切换时，runtime 会强制检查过程文件中的关键业务流程账本；检查复用现有结构校验，不生成独立 W4 artifact，过程文件仍是唯一多轮事实源。

W11 研发版 PRD 投影时，runtime 只校验当前传入的研发版 PRD 文件，不检查历史研发版 PRD，不维护 projection ledger。

## 质疑原则

只问会改变 PRD 质量的问题。每个问题都必须能回灌到事实、边界、对象、流程、状态、验收标准、排除项或风险依赖。

向用户输出问题时，必须按 `question-quality-rubric.md` 的合格问题格式表达：问题正文、必要性、模拟场景、建议口径、回灌位置。模拟场景只给 1 个，优先使用当前 PRD 已有业务对象，不得扩展新需求或把未确认场景写成事实。建议口径默认给 1 个推荐方案；只有确实存在两个合理产品方案时，才给 A/B 两个选项，并明确 A 为默认推荐项。用户回复“接受”默认采用推荐方案。

不要问：

- 用户已经回答过或明确否定过的问题。
- 不影响 PRD 的泛泛问题。
- 可以低风险假设且不会阻塞阶段推进的问题。
- 为了显得严谨而增加用户负担的问题。

## 阶段与修复

阶段推进遵循 `prd-kit.wf` 的 W0-W10 顺序。用户可以自然语言要求回退或切换阶段，但必须由 LLM 解析为合法 `target_stage`，再由 runtime 校验。

W10 读取 `.trae/skills/yxm-plan-ceo-review/SKILL.md`，并把过程文件、正式 PRD 和阶段账本作为评审输入；不要复制或改写 `yxm-plan-ceo-review` 的内部评审逻辑。W10 passed 后才允许进入 W11 研发版 PRD 投影。


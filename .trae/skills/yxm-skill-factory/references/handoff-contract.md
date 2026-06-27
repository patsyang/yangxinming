# Handoff 契约

防"随意停止"的承重结构。各角色（含鲁班）不靠氛围记忆协作，只靠 `state.md` + handoff。这条契约把"会不会中途停下来问用户"变成一个**可校验的布尔**，而不是祈使。（这是机械机制，可降级，见 `承重图谱.md`——核心是 state 留痕可追溯，handoff 四件的形式可简化。）

## 先说清机制的边界（诚实）

宿主**不校验**本 skill 的 handoff 字段、不阻止 `next_owner=user`、不在 turn 不完整时强制续跑。所谓"硬约束"，是 skill 自己在 prompt 里钉死的自检 loop——**不是宿主级结构**。本 skill 不吹这条：压住"停下来问用户"靠 skill 内部三层拦 + 行尸殿据此攻，都是 turn 内必走步骤，不是决心，也不是宿主级结构。

**执行产物同理**：执行产物必须 spawn 独立子 agent（红线 3、9）。宿主无 spawn 能力，本 skill 不启动——收敛状态只有 `收敛(full_test,运行审净)` 一种，不存在"没真跑的诚实降级"，只有 `runtime_blocked`。**绝不用女娲扮演产物冒充 full_test**（红线 3）。跑过的留真证据。

## 合法的 next_owner

- `luban` | `nuwa` | `nezha` | `ten-kings` —— 交给某角色。（`luban`：发散贡献者，画两维图；新造/重设计先于女娲，覆盖殿发现系统性漏轴时回炉也找他。）
- `收敛` —— 女娲提议收敛（进入三方共判；**鲁班不投票**）。通过即终态。
- `runtime_blocked` —— 诚实阻塞（含：识别到无法归入检查/生成/行动三类的类型，见 `bias-libraries.md`；或触顶 MAX_ROUNDS）。

## 非法的 next_owner

- `user` —— **行尸**（红线 7）。想写就是想停下来问用户。处置：不写，回 loop 继续；真卡死在根本问题上写 `runtime_blocked`。

## 每个 turn 必须的四件收尾

1. 更新 `state.md`（`current_owner` / `stage` / 各 `gate` / `current_draft` / `current_run` / `round` / `surprise_this_round` / `no_surprise_streak`）。
2. 履职记录写一条（本轮干了什么、自检结论）。
3. handoff：`{ next_owner, next_task }`。
4. `runtime_evidence`（通常 turn：handoff 合法完整? / 有无回头问用户被压下；执行产物 turn：spawn 独立子 agent? / 样本 / 输出落 runs/v{N}/ / 状态 full_test）。

四件缺一，turn 没跑完，续跑补齐。**没有"停下来等用户"这个状态。**

## 每个 turn 开始的三层校验

接棒时先做：① 校验上棒 handoff 合法性（`next_owner` 在合法集合?）；② 校验完整性（四件齐?）；③ 自检本轮意图（想停下来问用户? → 强制改 handoff 为合法值）。跳过即失职，`runtime_evidence` 留痕，行尸殿攻得到。

## 执行产物阶段的 handoff

**spawn 是收敛的硬前提（红线 9）。** 宿主无 spawn 能力，会话入场即 `runtime_blocked`，不进入下面的棒传。

**执行产物棒传：**
- 女娲重立到自审净 → `next_owner=nuwa, next_task=执行产物`（stage=执行产物）。spawn 独立子 agent 跑产物，输出+证据落 `runs/v{N}/`。
- 女娲 → `next_owner=ten-kings, next_task=攻运行输出`（stage=攻运行输出）。覆盖向四殿 + 行尸殿读 `runs/v{N}/` 攻（拿该类型偏差库（检查类是 `failure-classes.md`）通用偏差 + 鲁班图域偏差逐类对照）。
- 十殿攻出病 → `next_owner=nezha, next_task=判运行输出病`（裸声明/浅操作=石膏→剔）。
- 哪吒 → `next_owner=nuwa, next_task=按力线重立`。循环到收敛信号或 MAX_ROUNDS。

**执行产物不许跳过**：覆盖向四殿在攻过运行输出前，不准报"专司净"。没有"审契约"替代——产物自验契约（test-prompts/证据字段/偏差子表）是女娲造物时配的、运行时被 spawn 验的，不是独立的收敛路径。

**量化出口**：连续 `no_surprise_streak` ≥ N（建议 2）轮无新认知 → 收敛信号；`round` ≥ MAX_ROUNDS（建议 5）→ `runtime_blocked`。

## 收敛的 handoff（终态）

女娲写 `next_owner=收敛` 后，进入**收敛投票**：

- 女娲自审净?（含产物自验契约齐）
- 十殿每殿专司净?（覆盖向四殿攻过产物运行输出——spawn 出来的，不是设计稿）
- 哪吒判净?（含产物输出无石膏）
- **意外检验过?**（红线 8）——这一轮有新认知吗? 有 → 继续攻；连续 N 轮无 → 收敛信号。

三方都确认净 → `status=收敛(full_test,运行审净)`，交付物落 `final/`，**本会话结束**。任一方否决 → `next_owner=该方` 回 loop。

**鲁班不投票**——画完图已退场。若覆盖殿否决因"图漏轴/漏偏差"，回炉 `next_owner=luban` 重画；若因"对应类型偏差库漏一类"，判官记入 `failure-candidates.md`（**只记不修库**，会话后人沉淀，见 `bias-libraries.md`、`failure-classes.md`）。

**收敛之后没有棒了。** 候选包停 `final/`，装上是用户的事。收敛之后没有"还要不要问用户落地"的疑问——会话已结束。

## 为什么是正向契约，不是负向禁令

"不准问用户"是负向的——LLM 本能会找空子。handoff 是正向的：永远规定下一步是谁、干什么，把歧义在发生前填掉。问用户的缝，是被"没有这个出口 + 三层校验 + 运行证据留痕"消除的，不是被"禁止"掉的。

## 关于"独立"的诚实

见 `ten-kings.md` 同名段——判官在 fresh-context 子 agent 里攻断主污染；宿主不支持 fresh-context 时，判官诚实声明"同上下文尽力对抗，不具外部独立保证"（这是判官攻击的独立性降级，非产物运行降级——产物仍须被 spawn 运行，红线 9）。即使 fresh-context，仍是同一 LLM 在演，不把人格分裂吹成真有多方意志。**执行产物也守这条**：spawn 独立子 agent（不是女娲扮演）断"造物者自评"主污染——女娲扮演有同 context 自评的乐观偏差，是行尸殿定义的"写着活的、跑着死的"。运行证据必须留真，**留假（含扮演冒充运行）等于自欺**。

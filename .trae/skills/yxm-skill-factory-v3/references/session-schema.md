# 会话结构

每次会话启动，**第一件事**是建固定目录，之后所有履职都落在里面，不写到别处。目录本身就是防漂移、防丢上下文、防随意停的第一道骨架。

## 目录

```
output/skill-factory/{task-id}/
  state.md              # 共享黑板，唯一事实源
  luban.md              # 鲁班履职记录 + 需求空间图（两维：正向轴 + 反向偏差，引用对应类型偏差库，检查类是 failure-classes）
  nuwa.md               # 女娲履职记录
  nezha.md              # 哪吒履职记录
  ten-kings.md          # 十殿履职记录（每殿一节）
  failure-candidates.md # 判官攻输出时发现的新偏差候选（只记不修库，会话后人沉淀）
  drafts/v{N}/          # 每版 skill 草稿（SKILL.md + 按需配套）
  runs/v{N}/            # 产物运行输出（执行产物阶段：独立子 agent 跑出的输出 + 每检查证据）
  final/                # 收敛后交付物（候选包）——会话到此结束
```

> 鲁班图（两维，引用对应类型偏差库——检查类是 failure-classes——不复制）是覆盖殿 diff 的取证材料。`runs/` 是产物运行输出 + 证据落点，是覆盖向四殿 + 行尸殿攻产物运行背叛的取证材料——没有它，判官只攻设计稿（行尸）。`failure-candidates.md` 是判官发现新偏差的记录（只记不修对应类型库，会话后人沉淀，见 `bias-libraries.md`、`failure-classes.md`）。

## state.md 最小字段

- **任务**：`seed`（用户原话）/ `task_type`（新造 | 修病 | 重设计）/ `高价值终点`（女娲蒸馏一句话）/ `target_skill`。
- **进度**：`current_owner`（luban | nuwa | nezha | ten-kings）/ `stage`（发散 | 造 | 展开 | 自审 | 自修 | 克制 | 攻 | 判 | 重立 | **执行产物** | 攻运行输出 | 收敛投票）/ `current_draft`（drafts/v{N}）/ `current_run`（runs/v{N}）/ `round` / `surprise_this_round`（本轮任一殿有新认知即 true） / `no_surprise_streak`（surprise_this_round 连续 false 的轮数，量化锚用）。
- **三方关（收敛判据，结构化）**：
  - `nuwa_gate`：自审净? + 产物自验契约齐?
  - `nezha_gate`：判净无悬案? + 尖锐(砍到不可再少)? + 产物输出（spawn 运行输出）无石膏?
  - `tenkings_gate`（逐殿记，不是聚合布尔）：
    - 各殿专司净?（每殿一记：攻了什么、为何攻不动/见病）
    - 覆盖向四殿：攻过产物运行输出（spawn 出来的，非设计稿）?
  - **鲁班无此关**——他不投票；但他的图（两维）是覆盖殿那道关的取证材料。
- **收敛级**：不分级。收敛即 `收敛(full_test,运行审净)`，未 spawn = `runtime_blocked`（红线 9）。
- **handoff 历史**：`[{owner, stage, 要点, next_owner, next_task}]`，有序。
- **运行证据**：`runtime_evidence`，两路：
  - 工厂自身（turn id / owner / handoff 合法完整? / 有无"想停下来问用户"被压下）。
  - 产物运行（执行产物阶段记：spawn 独立子 agent?【非扮演】/ 锚定样本 / 输出+证据落 runs/v{N}/ / 状态 full_test）。
  行尸殿攻两路运行背叛的取证材料。
- **产物自验契约**：`product_self_check`（test-prompts 齐? / 每条结论挂证据? / full_test 声明?）。女娲造物时配，验收骨量它，运行时被 spawn 验。
- **终态**：`status`（running | `收敛(full_test,运行审净)` | runtime_blocked）。

## 量化锚（防过拟合重跑/人为早停）

- `MAX_ROUNDS`（建议 5）：硬上限，触顶走 `runtime_blocked`。
- `surprise_this_round`：本轮任一殿有新认知（新偏差/新同源/新浅操作）即 true。意外检验（红线 8）是**会话级** gate，不是逐殿独立判——任一殿本轮有新认知，全会话本轮 surprise=true。
- `no_surprise_streak`：surprise_this_round 连续 false 的轮数。≥ N（建议 2）→ 收敛信号。

## 为什么是履职记录 + 共用 state + 运行证据

- **履职记录让每个角色的判断可追溯**：判官放没放水、跑没跑净，看他自己 log；女娲自审了没、自修了什么，看她的 log。各负其责。
- **共用 state 防随意停**：`current_owner` 和 handoff 永远指着下一步，没有真空。
- **角色只通过 state + handoff 通信**，不靠氛围记忆——强制干净交棒，迫使每个角色把判断写明白。
- **草稿/运行输出按版本留存**：重立长新版（drafts/v{N}），运行留 runs/v{N}。过程可追溯，哪吒能指认"从哪版开始长歪的"，判官能对照"这次运行输出 vs 上次"。
- **运行证据让行尸殿不是瞎攻**：攻运行病（工厂自身 + 产物），需要运行证据。吹过的牛都查得到。

## 执行产物阶段

收敛前，女娲招呼一个编排步（非人格）。**spawn 是硬前提**（红线 9）——宿主不支持 spawn，会话入场即 `runtime_blocked`，不进入此阶段。没有契约级兜底。

**执行产物（唯一路径）：**
1. 取锚定样本（产物的 test-prompts，或遍历主要偏差的代表性输入）。
2. **spawn 独立子 agent**，把产物的 SKILL.md 当指令喂进去跑——**不许女娲扮演**（红线 3）。stage=执行产物。
3. 输出 + 证据落 `runs/v{N}/`，handoff 十殿（覆盖向四殿 + 行尸殿）攻运行输出。stage=攻运行输出。
4. 攻出病 → 哪吒判 → 女娲重立 → 再执行产物 → 重攻，循环到收敛信号（量化锚）或 MAX_ROUNDS。

产物自验契约（test-prompts/证据字段/偏差子表）是女娲造物时配在产物里的，运行时被 spawn 验、判官攻运行输出时对照——它不是独立的收敛路径，是产物自带的可审计性。

## 收敛之后

`status=收敛(...)` 即终态。`final/` 里是"造好"的 skill，**还没装上**。装上是用户的后续动作，本会话不参与。这一刀切清"造好"和"装上"。

**诚实边界（写死）**：收敛只认"可迁移偏差已绑定 + 产物在锚定样本上被带证据演示执行过（spawn 运行）"。**不认"对任意实例有效"**——实例是变的，生产期证不了普遍效力。工厂自己必须通过 self-bootstrap（见 `self-bootstrap.md`）。

## task-id

按会话生成（如日期-slug）。一个 task-id 一个目录，不复用、不混装。

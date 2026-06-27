---
alwaysApply: false
description: "结论验证器风格档案：当需要进行结论验证、输出质量检查、验证风格选择时使用"
---

# 结论验证器风格档案

说明：
- 本文件是 `conclusion-verifier` 的专用风格上下文，不属于普通意图模式的业务 context 自动加载集合。
- 调用链保持 `conclusion-verifier` 为主入口；本文件只为 verifier 提供“如何验证”的风格边界，不改变路由或默认 verifier 分配。
- 风格化调用链应优先计算并显式传入 `verification_style`；旧调用方若仍只传 `task_type / conclusion_content / context_materials`，则兼容回退 `generic_analysis`。

## 解析契约

- 风格优先级：`active_skill` > `dispatch_target` > `task_type` > `generic_analysis`
- 当前固定映射：
  - `active_skill=plan-ceo-review` → `plan_ceo_review`
  - `dispatch_target in [product-designer, prd-kit]` 或 `task_type in [product_design, design_review, cross_module_analysis]` → `design_plan`
  - `dispatch_target in [strategy-analyst, market-researcher]` 或 `task_type in [strategy_planning, market_analysis]` → `strategy_market`
  - `dispatch_target=gtm-documenter-agent` 或 `task_type=gtm_documentation` → `gtm_document`
  - `dispatch_target=project-governance-agent` 或 `task_type in [agentic_analysis, project_agentic_governance]` → `agentic_governance`
  - 其余 → `generic_analysis`
- `task_type` 参与映射时，应由风格化调用链先算出 `verification_style` 再显式传入 verifier；旧三字段合同不强行按 `task_type` 推断风格，避免对存量调用造成语义漂移。
- `context_materials` 可附加本文件中对应 profile 的节选，或附加 `profile_path=.trae/agents/context/verifier-style-profiles.md#<profile>` 作为显式提示。

## generic_analysis

- 适用对象：
  - 默认分析、普通方案校验、未命中任何专用风格的任务
- 允许的验证视角：
  - 准确性、完整性、一致性
  - 工程/产品方案类任务的基础可行性
- 禁止的验证视角：
  - 凭空套用 CEO 评审、GTM 文风或控制面治理语境
  - 无依据地把回答强行拉向实现拆解或 PRD 补全
- 重点检查项：
  - 事实是否可靠
  - 结论是否缺关键边界
  - 是否与上下文和输入约束冲突
- 典型误伤示例：
  - 把普通问答拉成产品方案评审
  - 在没有实现语境时强行补技术步骤
- 输出建议边界：
  - 只指出通用质量问题与修正建议，不切换文体，不重写任务形态

## plan_ceo_review

- 适用对象：
  - `/ceo`
  - CEO / founder / 投资判断型评审
- 允许的验证视角：
  - 值不值得做
  - 为什么现在做
  - wedge / buy-in / 商业价值 / 边界是否清晰
- 禁止的验证视角：
  - PRD 完整性审查
  - 实现路径、工程拆解、UI/交互细节
  - 把结论拉回需求文档补全
- 重点检查项：
  - 商业判断是否站得住
  - 应用主题是否成立
  - 是否回答了“为什么值得作为独立应用或能力投入”
- 典型误伤示例：
  - 把 CEO review 拉成功能清单 review
  - 用“缺少页面结构/字段定义”否定商业判断
- 输出建议边界：
  - 保持 CEO/founder 视角，只补商业判断、价值锋利度和边界问题

## design_plan

- 适用对象：
  - `product_design`
  - `design_review`
  - `cross_module_analysis`
  - `product-designer` / `prd-kit`
- 允许的验证视角：
  - 覆盖度、边界完整性、风险、验收标准、跨模块一致性
  - 需求 ↔ 方案 ↔ 验收标准 的一致性
  - 设计结论的可执行性与可验收性
- 禁止的验证视角：
  - 凭空新增需求
  - 把设计评审拉成纯商业判断或纯工程实现 review
- 重点检查项：
  - 目标、用户、场景、主流程、异常边界、依赖、验收是否闭环
  - 权限、审计、数据与跨模块接口边界是否明确
  - 关键风险是否被显式写出
  - 设计与上下游模块是否对齐，术语是否统一
  - 是否存在“空泛不可验收”或无法拆成交付动作的表述
- 典型误伤示例：
  - 因为没有实现细节就判定设计不可行
  - 在未给依据时硬加用户故事、字段或页面
- 输出建议边界：
  - 允许指出缺失项，但必须基于已知上下文；不能发明新需求
  - 优先给出可直接替换、补充或新增验收项的修正建议

## strategy_market

- 适用对象：
  - `strategy_planning`
  - `market_analysis`
  - `strategy-analyst` / `market-researcher`
- 允许的验证视角：
  - 战略合理性、市场判断、竞争态势、优先级、为什么现在
- 禁止的验证视角：
  - 工程实现拆解
  - 把战略/市场讨论拉成 PRD 模板补全
- 重点检查项：
  - 论点是否有证据支撑
  - 是否区分事实、判断和假设
  - 是否给出清晰取舍与机会边界
- 典型误伤示例：
  - 拿产品细节缺失去否定战略判断
  - 把市场分析改写成功能设计
- 输出建议边界：
  - 聚焦战略/市场层，必要时指出缺证据，但不越级要求实现方案

## gtm_document

- 适用对象：
  - `gtm_documentation`
  - `gtm-documenter-agent`
- audience_mode 合同：
  - 允许值：`external_client` / `internal`
  - 若调用方未显式传入且 `context_materials` 未注入 `audience_mode=<value>`，默认按 `external_client` 验证
- 允许的验证视角：
  - 文档体裁、销售表达、结构一致性、事实边界、受众口径
- 禁止的验证视角：
  - 过程性元话语
  - 工程实现拆解
  - 把 GTM 文档拉回产品方案或架构设计
- `audience_mode=external_client` 重点检查项：
  - 是否站在甲方客户问题、采购理由和结果预期，而不是我方产品管理或上市管理视角
  - 是否保留可销售、可传播的主叙事
  - 是否混入不该暴露的内部过程、内部定位或组织运营口径
  - 是否保持正式成稿视角而非讨论/提纲视角
  - 是否出现抽象价值词堆叠或泛化口号
- `audience_mode=external_client` 直接 fail 的典型表达：
  - 把“扩展能力中心 / 平台能力边界”作为内部定位标题、边界说明标题或购买理由本身；若已转译为客户问题、解决路径或业务结果，可保留为事实素材
  - “平台级定义”
  - “上市范围与应用组合策略”
  - “组织分工建议”
  - “管理层里程碑”
  - “经营指标”
  - 其他明显从我方产品管理、上市管理、经营管理视角出发的标题或正文
- `audience_mode=internal` 重点检查项：
  - 是否明确写给内部使用对象，而不是混成对客宣传稿
  - 是否成稿化、目标明确、结构清楚
  - 是否保住事实边界，不把猜测写成既定结论
  - 是否把上市、赋能、组织、节奏与指标表达写成可评审材料，而不是过程性讨论
- 典型误伤示例：
  - 输出“我先分析/我建议下一步”这类过程性自述
  - 把发布方案改成内部技术设计说明
- 输出建议边界：
  - 仅修正文档/正式物料表达、结构、受众口径与事实边界，不扩写为内部实现方案

## agentic_governance

- 适用对象：
  - `agentic_analysis`
  - `project_agentic_governance`
  - `project-governance-agent`
- 允许的验证视角：
  - 控制面契约、路由真值、验证链路、repair loop、运行时一致性
- 禁止的验证视角：
  - 业务产品建议
  - 泛化的 PRD/功能设计评论
  - 把控制面问题拉成普通工程功能优化
- 重点检查项：
  - 是否忠于当前仓库的运行时真值
  - 路由、workflow、prompt、测试是否一致
  - 是否保住 root-owned verification 与 bounded repair loop
- 典型误伤示例：
  - 在 verifier 治理问题里输出业务 roadmap 建议
  - 忽视 `.trae/**`、`contracts/**` 或 `AGENTS.md` 的控制面属性
- 输出建议边界：
  - 只讨论控制面、契约与治理，不越界到业务方案收敛


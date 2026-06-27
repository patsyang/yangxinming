# 查询策略

## 目标

生成一张搜索网，用来发现品类、竞品、替代方案、当前 workaround 路径、相邻生态和用户痛点。不要只搜索用户初始想法里的词。

## 查询族

### 1. 品类发现

用它了解市场如何命名这个问题。

```text
<problem> software
<problem> tools
<problem> platform
<job_to_be_done> automation
<category_guess> market map
<category_guess> landscape
best <category_guess> tools
top <category_guess> software
<category_guess> vendors
<category_guess> startup
<category_guess> open source
```

期望输出：

- 品类名称。
- 同义词。
- 缩写。
- 上位品类。
- 细分子品类。

### 2. 竞品发现

在找到品类名称或产品名称后使用。

```text
<category> competitors
<category> alternatives
<category> comparison
<category> buyer guide
<category> vendors
<discovered_product> competitors
<discovered_product> alternatives
<discovered_product> vs
<discovered_product> pricing
```

期望输出：

- 直接竞品。
- 购买路径中经常被对比的产品。
- 可用于深度画像的候选产品。

### 3. 替代方案与 Status Quo 发现

用它寻找用户不使用目标产品时如何解决问题。

```text
how to <job_to_be_done>
<job_to_be_done> spreadsheet
<job_to_be_done> template
<job_to_be_done> manual process
<job_to_be_done> consulting
<job_to_be_done> agency
<job_to_be_done> open source
<job_to_be_done> internal tool
<job_to_be_done> workflow
```

期望输出：

- 手工工作流。
- 模板和电子表格。
- 服务型替代方案。
- 内部工具。
- 开源替代方案。
- 平台原生功能。

### 4. 用户声音

用它发现痛点、投诉、切换原因和未满足需求。

```text
<category> reviews
<category> complaints
<category> reddit
<category> forum
<category> Hacker News
<product> reviews
<product> complaints
<product> GitHub issues
"switched from" <product>
"migrated from" <product>
"too expensive" <category>
"hard to use" <category>
```

期望输出：

- 痛点。
- 切换触发点。
- 未满足需求。
- 定价投诉。
- UX 和集成问题。

### 5. 相邻生态

用它避免陷入同品类 tunnel vision。

```text
<category> integrations
<category> API
<category> workflow
<category> plugin
<category> for <persona>
<category> for <industry>
<upstream_tool> <job_to_be_done>
<downstream_tool> <job_to_be_done>
<platform_name> <category>
```

期望输出：

- 上游/下游工具。
- 生态合作方。
- 插件和集成。
- 平台功能。
- 细分垂直产品。

### 6. 新鲜度与活跃度

用它避免已死亡产品或过期摘要。

```text
<product> changelog
<product> release notes
<product> docs
<product> pricing
<product> customers
<product> case study
<product> GitHub
<product> careers
```

期望输出：

- 产品是否活跃。
- 包装方式变化。
- 客户证明。
- 近期产品方向。

## 多语言策略

全球产品发现默认使用英文。只有当用户限定地理范围，或本地参考很重要时，才加入中文或其他语言。

中文查询模式：

```text
<问题> 工具
<问题> 系统
<问题> 平台
<任务> 自动化
<品类> 替代
<品类> 竞品
<品类> 对比
<品类> 选型
<品类> 评测
```

## 来源组合

优先级：

1. 官方产品页、文档、定价、客户故事。
2. 评论平台、社区、GitHub、HN、Reddit、论坛。
3. 独立对比、买方指南、market map。
4. 新闻、融资、招聘、changelog。
5. Analyst 或行业报告。

SEO 榜单只作为发现线索，不作为证明。

## 停止条件

Quick scan：

- 20 条有效证据。
- 8 个以上候选项。
- 覆盖 direct、substitute 和 status quo。

Standard landscape：

- 40 条有效证据。
- 15 个以上候选项。
- 8-12 个优先参考对象。
- 覆盖 direct、indirect、substitute、status quo、adjacent。

Deep report：

- Standard 条件之外，还要为每个优先参考对象做多来源验证。

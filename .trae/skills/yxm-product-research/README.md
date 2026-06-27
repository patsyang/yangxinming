# 产品研究助手（Product Research Assistant）

> 🔍 **通用产品/公司研究自动化工具** — 输入官网 URL，输出结构化研究报告

[![Version](https://img.shields.io/badge/version-2.6.0-blue.svg)](https://github.com/workbuddy/pat-product-research)
[![Skill](https://img.shields.io/badge/type-WorkBuddy_Skill-green.svg)](./SKILL.md)

---

## ✨ 功能特性

| 能力 | 描述 |
|------|------|
| 🔗 **智能页面发现** | 自动从官网首页发现并分类关键页面（产品、技术、案例等 7 大类） |
| 🖼️ **上下文优先图片分类 v2.5** | 基于来源页、区域标题、截图类型、尺寸和视觉质量分类架构图/功能图/方案图，统一处理静态图片和 Agent Browser 截图 |
| 📄 **文档自动下载** | 自动识别并下载白皮书、案例、产品手册等文档，按类型分类存放 |
| 🌐 **动态页面适配** | 自动检测 SPA/动态渲染网站，选择合适的抓取方式 |
| 📊 **结构化报告** | 按照标准 11 章节模板生成完整的中文 Markdown 研究报告 |

## 🚀 快速开始

### 使用方式

在对话中直接发起产品研究请求：

```
帮我研究一下 https://www.example.com 这家公司的产品
对 https://product.example.com 进行产品调研
研究 XX 公司：www.xxcompany.com.cn
```

Agent 会自动调用本技能完成全流程。

> 说明：当前目录下的 `.agents/skills/yxm-product-research/` 是安装产物。若后续仓库中引入正式源目录，应优先修改源目录并重新导出安装产物。

### 手动执行脚本（调试用）

```text
# 1. 发现关键链接
python scripts/discover_links.py --url https://www.example.com -o links.json

# 2. 下载筛选后的图片
python scripts/download_images.py --urls links.json --output-dir ./images --min-width 200 --min-height 150

# 2b. 处理 Agent Browser 采集结果
python scripts/download_images.py --urls browser_assets.json --output-dir ./images --min-width 200 --min-height 150

# 3. 下载文档资料
python scripts/download_docs.py --urls links.json --output-dir ./documents

# 4. 打包素材
python scripts/package_assets.py --source-dir . --output-dir ./output
```

## 📁 输出产物

### 目录结构

```
yxm-product-research/
└── <公司名>/
    └── research-YYYYMMDD-HHMMSS/
        ├── output/                              # 最终产出
        │   ├── 产品研究_<公司名>_<日期>.md      # ⭐ 结构化研究报告
        │   └── 产品研究素材_<公司名>_<日期>.zip  # 图片+文档压缩包
        ├── pages/                               # 页面快照（MD格式）
        ├── images/                              # 有价值图片（已分类）
        │   ├── architecture/                    # 架构图
        │   ├── feature/                         # 功能图
        │   ├── solution/                        # 方案图
        │   └── other/                           # 其他有价值图片
        ├── documents/                           # 文档资料（已分类）
        │   ├── whitepaper/                      # 白皮书
        │   ├── case/                            # 用户案例
        │   ├── brochure/                        # 产品手册
        │   └── other/                           # 其他文档
        └── temp/                                # 临时文件（可删除）
```

版本隔离规则：

- 每次研究都必须创建新的 `research-YYYYMMDD-HHMMSS/`
- 新研究只能读取和写入当前版本目录
- 不允许读取旧版本目录中的 `pages/ images/ documents/ output/ temp/`
- 不允许修改旧版本目录中的任何文件

### 研究报告章节

报告包含 **11 个核心章节**：

| # | 章节 | 主要内容 |
|---|------|---------|
| 1 | **公司概况** | 基本信息、定位、团队、资质荣誉 |
| 2 | **核心定位** | 产品定位、Slogan、价值主张 |
| 3 | **目标市场** | 客户画像、行业覆盖、地域分布 |
| 4 | **场景痛点** | 应用场景、痛点分析、前后对比 |
| 5 | **产品架构** | 技术架构、功能架构、部署模式、集成能力 |
| 6 | **功能特性** | 功能清单、亮点功能详解 |
| 7 | **差异化优势** | 多维度对比、护城河分析 |
| 8 | **解决方案** | 场景方案、行业方案 |
| 9 | **典型案例** | 客户案例详情、成效数据 |
| 10 | **竞品清单** | 直接/间接竞品分析 |
| 11 | **关键发现** | Top 发现、成熟度评估、风险提示 |

---

## 🛠️ 技术实现

### 依赖库

```text
pip install requests beautifulsoup4 Pillow
```

| 库 | 用途 |
|----|------|
| `requests` | HTTP 请求 |
| `beautifulsoup4` | HTML 解析与链接提取 |
| `Pillow` | 图片尺寸与视觉质量检测（可选） |

### 脚本说明

#### `scripts/discover_links.py`
- 从首页 HTML 中提取所有 `<a>` 链接和静态图片入口
- 按 P0-P3 四级优先级自动分类 7 种页面类型
- 输出 `links.json`，用于后续页面采集、图片补充和文档下载

#### `scripts/download_images.py`
- 统一处理 `links.json`、`browser_assets.json`、URL 列表和本地截图
- 基于来源页、区域标题、周边文本、截图类型和视觉质量进行分类
- 排除规则：图标/logo、装饰图、广告、二维码、UI元素
- 支持最小尺寸过滤、文件大小限制、重名处理

#### `scripts/download_docs.py`
- 支持格式：PDF、Word、PPT、Excel、Markdown、TXT
- 自动按关键词分类到 4 个子目录（whitepaper/case/brochure/other）
- 安全限制：禁止下载可执行文件、单文件上限 200MB

#### `scripts/package_assets.py`
- 只打包 `images/` 和 `documents/` 目录（不含页面快照）
- 输出压缩率统计和分类文件清单

### 动态页面处理

当目标网站使用 JavaScript 动态渲染时，技能会：

1. **自动检测** — 通过 web_fetch 返回内容和 HTML 特征判断是否为 SPA
2. **优先使用 Agent Browser** — 渲染页面、滚动触发懒加载、抓取图片候选和全页截图
3. **降级到搜索聚合** — 通过 web_search 补充公开信息
4. **诚实标注** — 在报告中声明信息缺口

详见 `references/dynamic-page-guide.md`。

---

## 📋 工作流程

```
输入官网URL
     │
     ▼
 ┌─────────────┐
 │ Phase 1: 准备 │ ← 初始化目录、检测页面类型
 └──────┬──────┘
        │
        ▼
 ┌─────────────┐     ┌──────────────────┐
 │ Phase 2: 采集 │ ◀─▶│ 动态页面检测(内嵌) │
 ├─────────────┤     └──────────────────┘
 │ • 首页内容   │
 │ • 链接发现   │
 │ • 分页采集   │
 │ • 图片下载   │
 │ • 文档下载   │
 │ • 补充搜索   │
 └──────┬──────┘
        │
        ▼
 ┌─────────────┐
 │ Phase 3: 分析 │ ← 读取所有素材 → 分类整理 → 竞品分析
 └──────┬──────┘
        │
        ▼
 ┌─────────────┐
 │ Phase 4: 交付 │ ← 生成报告(MD) + 打包素材(ZIP)
 └─────────────┘
```

---

## ⚙️ 配置选项

### 链接发现配置

```text
python discover_links.py \
  --url https://example.com \     # 目标 URL（必填）
  -o links.json \                 # 输出 JSON 文件
  --depth 1 \                     # 发现深度
  --timeout 15                    # 超时秒数
```

### 图片下载配置

```text
python download_images.py \
  --urls links.json \             # 图片 URL 列表或 JSON 文件
  -o ./images \                   # 输出目录
  --min-width 200 \               # 最小宽度(px)
  --min-height 150 \              # 最小高度(px)
  --timeout 20                    # 下载超时(s)
```

### 文档下载配置

```text
python download_docs.py \
  --urls links.json \             # 文档 URL 列表或 JSON 文件
  -o ./documents \                # 输出目录
  --timeout 30                    # 下载超时(s)
```

### Agent Browser 采集产物

动态页面采集完成后，应生成 `browser_assets.json`：

```json
{
  "images": [
    {
      "url": "https://www.example.com/static/product-architecture.png",
      "source_page": "https://www.example.com/product",
      "capture_type": "dom_image",
      "section_heading": "产品架构",
      "nearby_text": "平台由数据接入、策略引擎、审计分析和处置联动模块组成。",
      "page_type": "product",
      "alt": "产品架构图",
      "width": 1280,
      "height": 720
    }
  ],
  "captures": [
    {
      "path": "./screenshots/product-architecture-section.png",
      "source_page": "https://www.example.com/product",
      "capture_type": "section_screenshot",
      "section_heading": "部署架构",
      "nearby_text": "展示私有化部署、数据源接入和第三方系统集成关系。",
      "page_type": "product"
    }
  ]
}
```

每个条目至少包含 `source_page`、`capture_type`、`section_heading`、`nearby_text`、`page_type`。

图片下载后必须复核 `_review_pending/`，并对高置信目录进行抽样或全量视觉检查。首页轮播图、客户案例图、新闻头图和营销横幅不得仅凭附近文案中的“架构、能力、方案”等词直接用于报告。

---

## 📝 注意事项

1. **请求礼仪** — 单站点不超过 50 个页面请求，间隔 1-2 秒
2. **尊重 robots.txt** — 如禁止爬取则告知用户
3. **版权声明** — 下载素材仅用于研究目的
4. **信息完整性** — 如遇技术限制导致信息不完整，会在报告中明确标注
5. **中文输出** — 研究报告全部使用中文撰写

---

## 🔄 版本历史

### v2.5.0 (2026-04-25) 🌐 Agent Browser + 上下文优先分类
- 🚨 **图片采集主路径切换为 Agent Browser** — 动态页面不再依赖 Playwright 或 OCR
- ✅ **新增 `browser_assets.json` 约定**：Agent Browser 采集结果统一输出 `images` + `captures`
- ✅ **`download_images.py` 重构为统一离线处理器**：同时接收静态图片 URL、动态资源 URL 和本地截图
- ✅ **分类策略改为上下文优先**：基于来源页、区域标题、附近文本、截图类型、尺寸和视觉质量进行分类
- ✅ **`source_page` 成为统一来源页字段**，兼容静态入口发现和浏览器采集结果
- ✅ **保留 `_review_pending/` 作为安全兜底**，将不确定但可能有价值的截图交给 Agent 视觉复核

### v2.4.0 (2026-04-24) 📝 OCR 文字关联度分析
- 🚨 **解决"图片有但没信息量"的根本问题** — 元数据和视觉特征都无法判断图片的实际信息含量，必须通过图中文字来判断
- ★ **新增第六维：OCR 文字关联度分析引擎（Tesseract）**：
  - **文字提取**：对每张下载图片执行 Tesseract OCR（中英混合识别）
  - **4类产品关键词体系**：
    - `architecture`(权重10): 架构/拓扑/微服务/网关/负载均衡等
    - `tech_detail`(权重9): API/SDK/算法/数据库/K8s/Docker/加密等
    - `business_logic`(权重7.5): 流程/步骤/审批/权限/订单等
    - `product_feature`(权重6.5): 功能/特性/支持/场景/配置等
  - **关联度评分 0~10 分**：根据命中关键词数量和质量计算
  - **装饰性文字检测**：自动识别 slogan/营销口号/空洞词汇并标记为 decorative
- ✅ **OCR 高关联(≥6分)自动提升** → 无需人工审核直接归入高置信度分类
- ✅ **装饰性 OCR 自动降级或跳过** → "智领未来""领先科技"这类图不再漏网
- ✅ **结构化内容检测** → 编号列表/箭头/制表符/括号注释等信号加分
- ✅ **`_download_results.json` 大幅增强**：每张图附带完整 OCR 分析结果（原始文字/清洗后文字/命中关键词/关联分/是否装饰性）
- ✅ **SKILL.md Step 2.4.5 审核流程增强**：Agent 必须结合 OCR 结果做去留决策
- ⚠️ **OCR 为可选依赖**：未安装 Tesseract 时优雅降级为五维模式（更多图进 _review_pending）

### v2.3.0 (2026-04-24) 🔍 图片视觉质量审核
- 🚨 **解决"图片有但没信息量"问题** — v3.0 的兜底策略导致大量装饰性大图被误选
- ★ **新增第五维：PIL 视觉质量分析引擎**：
  - **图像熵值** — 低熵(<2.5)自动识别纯色/简单渐变装饰图并跳过
  - **边缘密度** — 拉普拉斯算子检测，低边缘密度=缺乏细节纹理
  - **颜色多样性** — ≤8 种颜色可能是图标/simple graphic
  - **Banner 形态检测** — 宽高比>3:1 且高度≤300px 判定为 Hero banner
- ✅ **新增 `--strict` 模式** — 更激进的质量过滤门槛
- ✅ **新增 `_review_pending/` 目录** — 不确定的兜底图片不再直接存入 other/，而是单独存放
- ✅ **新增 Step 2.4.5「视觉审核」步骤**（SKILL.md）— Agent 必须逐张查看 `_review_pending/` 中的图片，用"眼睛"判断是否有实质信息含量
- ✅ **`_download_results.json` 大幅增强** — 每张图附带 entropy/edge_density/color_count/is_banner 等质量指标
- 🔧 核心设计转变：「下载」与「审核」分离——脚本做初筛(元数据+图像特征)，Agent 做终审(视觉内容理解)

### v2.2.0 (2026-04-24) 🖼️ 图片筛选重大升级
- 🚨 **修复图片文件夹为空的关键问题** — v2.x 白名单模式导致 `p7.jpg` 等文件名无语义但实际高价值的图片全部被遗漏
- 🔄 **筛选策略从白名单改为黑名单+兜底**：只排除明确无价值的图片（icon/banner/ad/qr），不再要求图片必须匹配关键词才下载
- ✅ 新增 **四维分类引擎 v3.0**：(1)黑名单排除 (2)关键词精确匹配 (3)页面位置加权 (4)尺寸兜底保留
- ✅ **discover_links.py v2.0** 输出带上下文的图片数据（`images` 字段），包含 source_page/alt/parent_class/surrounding_text/page_type
- ✅ **download_images.py v3.0** 支持丰富输入格式（纯URL + 带上下文对象），自动从 links.json 读取上下文
- ✅ 兜底保留规则：来自 product/tech/solution 页面的图片（>500x300 或 >50KB）即使无语义文件名也会保留到 other/
- ✅ 输出 `_download_results.json` 便于 Agent 在分析阶段查看每张图的分类原因和评分
- 🔧 默认尺寸门槛从 400x300 降低至 150x100（黑名单模式已承担主要过滤职责）

### v2.1.0 (2026-04-24) 🔧 关键修复
- 🚨 **修复报告结构不严格遵循11章节的问题** — 将完整报告模板直接嵌入 SKILL.md Phase 4 工作流
- ✅ 新增「核心约束」章节（执行前必须阅读）— 用铁律形式规定11个章节不可省略/不可合并/不可调序
- ✅ Phase 3 新增「按11章节逐章归集信息」步骤 — 带 checklist 的信息收集指引，确保每章都有素材支撑
- ✅ Phase 4 报告模板从引用外部文件改为**内嵌完整模板** — 每个章节都给出精确的 Markdown 格式和最低质量标准
- ✅ 新增 Step 4.2 **写作质量强制检查清单** — 7项必须逐项确认的检查项，不通过则返回重写
- ✅ 每个章节新增**最低质量标准**（字数/条目数要求）

### v2.0.0 (2026-04-24)
- ✨ 全面重构，基于实际使用经验优化
- ✨ 新增中英文双语图片语义分类
- ✨ 新增 `<img>` 标签全面支持（懒加载/srcset/CSS背景图/Base64）
- ✨ 新增动态页面自动检测与多级降级策略
- ✨ 新增 11 章节标准化报告模板
- ✨ 文档自动分类（白皮书/案例/手册/其他）
- 🔧 优化链接发现算法，支持 7 类页面自动分类

### v1.0.0 (2026-04-23)
- 🎉 初始版本
- 基础链接发现、图片下载、文档下载功能

---

## 📄 许可证

本技能仅供 WorkBuddy 平台内部使用。使用时请遵守目标网站的服务条款和 robots.txt 规定。

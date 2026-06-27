# 动态页面抓取策略指南

> 当目标网站使用 JavaScript 动态渲染内容时，传统 HTTP 请求只能拿到不完整 HTML。本指南规定 `pat-product-research` 在动态页面上的唯一浏览器路径是 **Agent Browser**。

---

## 问题诊断

### 如何判断页面是动态页面

满足任一条件即可判定为动态页面：

- `web_fetch` 获取到的正文极少，只有脚本和占位容器
- HTML 中包含 React/Vue/Angular/Next/Nuxt 等 SPA 特征
- 页面需要滚动、点击 Tab、展开折叠面板后才出现内容
- 静态 HTML 中几乎没有 `<img>`，但浏览器打开后存在大量可视化内容

常见 HTML 特征：

```html
<div id="app"></div>
<div id="root"></div>
<noscript>请启用 JavaScript</noscript>
```

---

## 主策略：Agent Browser

### 适用场景

- React/Vue/Angular 等现代 SPA 网站
- 需要滚动才能触发图片或正文加载的页面
- 需要点击 Tab、Accordion、轮播切换内容的页面
- 架构图、方案图、产品截图以 CSS 背景图、SVG、canvas 或组合 DOM 的形式呈现

### 标准命令序列

```text
agent-browser --session pat-product-research open https://target-site.com
agent-browser wait --load networkidle
agent-browser set viewport 1920 1080 2
agent-browser screenshot --full --screenshot-dir ./screenshots
```

### 懒加载处理

对重点页面至少执行 3-5 轮滚动：

```text
agent-browser scroll down 1200
agent-browser wait 800
```

如果页面有独立滚动容器，使用：

```text
agent-browser scroll down 800 --selector "div.content"
```

### 交互内容处理

如果页面存在以下元素，必须逐个展开或切换后重新采集：

- Tab
- Accordion
- Carousel
- “查看更多”“展开”“更多方案”等按钮

标准流程：

```text
agent-browser snapshot -i
agent-browser click @e1
agent-browser wait --load networkidle
agent-browser screenshot --full --screenshot-dir ./screenshots
```

---

## 图片候选提取

### DOM 图片与背景图

使用 `agent-browser eval` 在浏览器上下文提取：

- `img.currentSrc`
- `img.src`
- `picture source[srcset]`
- `data-src` / `data-original`
- computed style 的 `background-image`
- SVG `<image>`
- 图片附近的 section 标题和说明文字

推荐使用 `--stdin`，避免 shell 转义问题：

```text
agent-browser eval --stdin <<'EVALEOF'
JSON.stringify(
  Array.from(document.querySelectorAll("img")).map((img) => ({
    url: img.currentSrc || img.src || "",
    alt: img.alt || "",
    title: img.title || "",
    width: img.naturalWidth || img.width || 0,
    height: img.naturalHeight || img.height || 0
  }))
)
EVALEOF
```

### 网络图片

对动态加载的 CDN 图片，使用：

```text
agent-browser network requests
```

重点记录：

- 图片请求 URL
- 来源页 URL
- 触发时机
- 所在页面区域

### 页面截图

每个重点页面至少保存一张 full-page screenshot：

```text
agent-browser screenshot --full --screenshot-dir ./screenshots
```

对包含以下标题的页面区域，应保存额外截图或后续裁剪候选：

- 产品架构
- 技术架构
- 部署架构
- 解决方案
- 功能特性
- 流程
- 模块
- 拓扑

---

## `browser_assets.json` 输出规范

Agent Browser 采集完成后，整理为 `browser_assets.json`。

顶层结构：

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

`images` 中保存远程可下载资源，`captures` 中保存本地截图或裁剪图。

每个条目至少包含：

```json
{
  "source_page": "https://example.com/product",
  "capture_type": "section_screenshot",
  "section_heading": "产品架构",
  "nearby_text": "平台采用分层架构...",
  "page_type": "product"
}
```

可选字段：

- `url`
- `path`
- `alt`
- `title`
- `class_name`
- `id`
- `width`
- `height`

`capture_type` 只能使用：

- `dom_image`
- `network_image`
- `section_screenshot`
- `fullpage_screenshot_crop`

---

## 降级路径

### Agent Browser 不可用

按以下顺序降级：

1. 使用静态 `web_fetch` + `discover_links.py` 获取可见入口和文档链接
2. 使用 `web_search` 聚合公开资料
3. 在报告中明确标注信息缺口

### 内容不完整

若页面无法稳定加载或存在反爬限制，必须在最终报告中声明：

> **信息完整性说明**
>
> 由于目标网站采用动态渲染或存在访问限制，部分页面内容与图片素材未能完整采集。报告已基于已获取页面、截图、文档和公开资料整理。

---

## 请求礼仪

- 单站点总请求量控制在合理范围，优先采集 P0/P1 页面
- 连续请求之间保留短暂等待，避免高频轰击
- 对明显需要登录的页面，不尝试绕过认证
- 遇到验证码、Cloudflare、人机校验时，停止自动化并改用降级路径

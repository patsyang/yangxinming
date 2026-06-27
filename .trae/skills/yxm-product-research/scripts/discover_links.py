#!/usr/bin/env python3
"""
链接发现与分类脚本 v2.0 - Product Research Skill
=================================================
从公司官网首页 HTML 中自动发现关键页面链接和图片资源，
按优先级和类别分类输出。图片数据包含上下文信息供后续筛选使用。

Usage:
    python discover_links.py --url <homepage_url> [--output links.json] [--depth 1]

Output (JSON):
{
  "homepage": "https://example.com",
  "crawled_at": "2026-04-24T12:00:00",
  "categories": {
    "P0_product": [{ "url": "...", "text": "...", "priority": 0 }],
    ...
  },
  "image_urls": ["https://..."],                        // 简单格式（向后兼容）
  "images": [                                            // ★ 丰富格式（推荐）
    {
      "url": "https://example.com/images/p7.jpg",
      "source_page": "https://example.com/products",
      "alt": "产品架构图",
      "parent_class": "product-banner",
      "parent_id": "",
      "surrounding_text": "产品架构采用微服务设计...",
      "page_type": "product"
    }
  ],
  "doc_urls": ["https://..."]
}
"""

import argparse
import json
import re
import sys
import time
import urllib.parse
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any
from pathlib import Path


def configure_console_output() -> None:
    """避免 Windows GBK 控制台遇到 emoji 时抛出编码异常。"""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")


configure_console_output()

try:
    import requests
except ImportError:
    print("错误: 需要安装 requests 库。运行: pip install requests", file=sys.stderr)
    sys.exit(1)

try:
    from bs4 import BeautifulSoup, Tag
except ImportError:
    print("错误: 需要安装 beautifulsoup4 库。运行: pip install beautifulsoup4", file=sys.stderr)
    sys.exit(1)


# ============================================================
# 配置：URL 模式匹配规则
# ============================================================

CATEGORY_RULES = [
    # P0 - 核心页面（必须深度采集）
    {
        "key": "P0_product",
        "label": "产品/解决方案",
        "priority": 0,
        "patterns": [
            r"/product(s)?(/|$)", r"/solution(s)?(/|$)",
            r"/platform(/|$)", r"/service(s)?(/|$)",
            r"offerings?(/|$)",
            r"产品|解决方案|平台|服务",
        ],
        "url_keywords": ["product", "solution", "platform", "service", "offering"],
        "page_type_hint": "product",
    },
    {
        "key": "P0_tech",
        "label": "技术/白皮书",
        "priority": 0,
        "patterns": [
            r"/tech(nology)?(/|$)", r"/architecture(/|$)",
            r"/white-?paper", r"/developer(s)?(/|$)",
            r"/api(/|$)",
            r"技术|架构|白皮书|开发",
        ],
        "url_keywords": ["tech", "architecture", "whitepaper", "developer", "api"],
        "page_type_hint": "tech",
    },
    # P1 - 重要页面（应当采集）
    {
        "key": "P1_case",
        "label": "客户案例",
        "priority": 1,
        "patterns": [
            r"/case(s)?(/|$)", r"/customer(s)?(/|$)",
            r"/client(s)?(/|$)", r"story|stories(/|$)",
            r"/reference(/|$)", r"/project(s)?(/|$)",
            r"案例|客户|成功故事|项目",
        ],
        "url_keywords": ["case", "customer", "client", "story", "reference", "project"],
        "page_type_hint": "case",
    },
    {
        "key": "P1_about",
        "label": "关于我们",
        "priority": 1,
        "patterns": [
            r"/about(/|$)", r"/company(/|$)",
            r"/team(/|$)", r"/profile(/|$)",
            r"intro(duction)?(/|$)",
            r"关于|公司介绍|团队",
        ],
        "url_keywords": ["about", "company", "team", "profile", "introduction"],
        "page_type_hint": "about",
    },
    # P2 - 补充页面
    {
        "key": "P2_news",
        "label": "新闻/动态",
        "priority": 2,
        "patterns": [
            r"/news(/|$)", r"/blog(/|$)",
            r"/event(s)?(/|$)", r"/press(/|$)",
            r"/article(s)?(/|$)", r"/post(s)?(/|$)",
            r"新闻|博客|动态|资讯",
        ],
        "url_keywords": ["news", "blog", "event", "press", "article"],
        "page_type_hint": "news",
    },
    {
        "key": "P2_docs",
        "label": "帮助/文档",
        "priority": 2,
        "patterns": [
            r"/doc(s)?(/|$)", r"/help(/|$)",
            r"/support(/|$)", r"/resource(s)?(/|$)",
            r"/download(s)?(/|$)", r"/center(/|$)",
            r"文档|帮助|支持|资源|下载",
        ],
        "url_keywords": ["doc", "help", "support", "resource", "download"],
        "page_type_hint": "docs",
    },
    # P3 - 其他
    {
        "key": "P3_other",
        "label": "其他",
        "priority": 3,
        "patterns": [
            r"/contact(/|$)", r"/join|/careers?|/job(s)?(/|$)",
            r"/partner(s)?(/|$)",
            r"联系|加入|合作|招聘",
        ],
        "url_keywords": ["contact", "join", "career", "partner"],
        "page_type_hint": "default",
    },
]


# 图片文件扩展名
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".ico"}

# 文档文件扩展名
DOC_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".ppt", ".pptx",
    ".xls", ".xlsx", ".md", ".markdown", ".txt",
}


@dataclass
class DiscoveredLink:
    """发现的链接"""
    url: str
    text: str = ""
    priority: int = 3
    category: str = "P3_other"

    def to_dict(self):
        return asdict(self)


@dataclass
class DiscoveredImage:
    """发现的图片（含上下文）"""
    url: str
    source_page: str = ""
    alt: str = ""
    title: str = ""
    parent_class: str = ""
    parent_id: str = ""
    parent_tag: str = ""
    surrounding_text: str = ""  # img 周围的文本内容（截取前200字符）
    page_type: str = ""          # 推断的页面类型
    lazy_loaded: bool = False     # 是否为懒加载图片

    def to_dict(self):
        return asdict(self)


def normalize_url(base_url: str, href: str) -> Optional[str]:
    """将相对 URL 转换为绝对 URL"""
    if not href:
        return None

    href = href.strip()

    if href.startswith(("#", "javascript:", "mailto:", "tel:", "data:")):
        return None

    if href.startswith(("http://", "https://")):
        parsed = urllib.parse.urlparse(href)
        base_parsed = urllib.parse.urlparse(base_url)
        if parsed.netloc == base_parsed.netloc or parsed.netloc.endswith("." + base_parsed.netloc):
            return href
        return None

    try:
        absolute = urllib.parse.urljoin(base_url, href)
        return absolute
    except Exception:
        return None


def classify_link(url: str, link_text: str = "") -> tuple:
    """对链接进行分类。返回 (category_key, priority) 元组。"""
    url_lower = url.lower()
    text_lower = link_text.lower()

    for rule in CATEGORY_RULES:
        for pattern in rule.get("patterns", []):
            try:
                if re.search(pattern, url_lower, re.IGNORECASE):
                    return (rule["key"], rule["priority"])
            except re.error:
                pass

        for kw in rule.get("url_keywords", []):
            if kw in url_lower:
                return (rule["key"], rule["priority"])

        for pattern in rule.get("patterns", []):
            try:
                if re.search(pattern, text_lower, re.IGNORECASE):
                    return (rule["key"], rule["priority"])
            except re.error:
                pass

    return ("P3_other", 3)


def is_image_url(url: str) -> bool:
    path = urllib.parse.urlparse(url).path.lower()
    return any(path.endswith(ext) for ext in IMAGE_EXTENSIONS)


def is_doc_url(url: str) -> bool:
    path = urllib.parse.urlparse(url).path.lower()
    return any(path.endswith(ext) for ext in DOC_EXTENSIONS)


def get_element_context(element: Tag, max_chars: int = 200) -> str:
    """
    获取 HTML 元素周围的文本上下文。
    按优先级获取：父元素文本 > 前一个兄弟元素文本 > 后一个兄弟元素文本
    """
    texts = []

    # 父元素的直接文本内容（去除子元素递归后的纯文本）
    parent = element.parent
    if parent:
        parent_text = parent.get_text(separator=" ", strip=True)
        if parent_text:
            texts.append(parent_text)

    # 前一个有意义的兄弟元素
    prev = element.find_previous(["h1", "h2", "h3", "h4", "p", "div", "section", "li"])
    if prev:
        prev_text = prev.get_text(separator=" ", strip=True)
        if prev_text and prev_text != texts[-1] if texts else True:
            texts.append(prev_text)

    # 后一个有意义的兄弟元素
    next_el = element.find_next_sibling(["p", "div", "section", "li"])
    if next_el:
        next_text = next_el.get_text(separator=" ", strip=True)
        if next_text:
            texts.append(next_text)

    combined = " | ".join(texts)
    # 清理多余空白
    combined = re.sub(r'\s+', ' ', combined).strip()
    return combined[:max_chars] if combined else ""


def get_parent_info(element: Tag) -> tuple:
    """
    获取父元素的 class、id 和标签名。
    Returns: (class_str, id_str, tag_name)
    """
    parent = element.parent
    if parent is None or not isinstance(parent, Tag):
        return ("", "", "")

    classes = " ".join(parent.get("class", []))
    pid = parent.get("id", "") or ""
    tag = parent.name if hasattr(parent, 'name') else ""

    # 如果父元素是通用容器，再往上找一层
    if tag in ("a", "span", "strong", "em", "i", "b"):
        grandparent = parent.parent
        if grandparent and isinstance(grandparent, Tag):
            gclasses = " ".join(grandparent.get("class", []))
            gid = grandparent.get("id", "") or ""
            gtag = grandparent.name if hasattr(grandparent, 'name') else ""
            if gtag not in ("a", "span"):
                # 使用祖父级信息（更有意义）
                return (gclasses or classes, gid or pid, gtag or tag)

    return (classes, pid, tag)


def infer_image_page_type(page_url: str) -> str:
    """从页面 URL 快速推断页面类型"""
    if not page_url:
        return "home"

    path = urllib.parse.urlparse(page_url).path.lower()
    parts = [p for p in path.split("/") if p]

    type_map = {
        "product": ["product", "products", "solution", "solutions", "platform", "service", "services", "offering"],
        "tech": ["tech", "technology", "arch", "developer", "api", "whitepaper"],
        "case": ["case", "cases", "customer", "customers", "client", "story", "project", "reference"],
        "about": ["about", "company", "team", "profile", "intro"],
        "news": ["news", "blog", "event", "press", "article", "post"],
        "docs": ["doc", "docs", "help", "support", "resource", "download", "center"],
        "home": [],
    }

    if not parts or path in ["/", "/index.html", "/index.php"]:
        return "home"

    for ptype, keywords in type_map.items():
        if ptype == "home":
            continue
        for part in parts:
            for kw in keywords:
                if kw in part:
                    return ptype

    return "default"


def extract_images_from_html(html: str, base_url: str, page_url: str = "") -> List[DiscoveredImage]:
    """
    从 HTML 中提取所有图片及其上下文信息。

    提取方式包括：
    - <img src="..."> / <img data-src="..."> （懒加载）/ <img srcset="...">
    - <picture><source srcset="...">
    - style="background-image:url(...)"
    - SVG <image> 标签

    每张图片都会附带上下文信息：
    - alt/title 属性文本
    - 父元素 class/id/tag
    - 周围文本内容
    - 页面类型推断
    """
    images = []

    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return images

    # 页面类型推断（只需一次）
    page_type = infer_image_page_type(page_url)

    def _add_image(url: str, img_tag: Tag = None, lazy: bool = False):
        """内部辅助函数：添加图片到结果列表"""
        if not url:
            return
        full_url = normalize_url(base_url, url)
        if not full_url:
            return
        # 去重
        if any(i.url == full_url for i in images):
            return

        # 构建带上下文的图片记录
        img_record = DiscoveredImage(
            url=full_url,
            source_page=page_url or base_url,
            page_type=page_type,
            lazy_loaded=lazy,
        )

        if img_tag is not None and isinstance(img_tag, Tag):
            img_record.alt = img_tag.get("alt", "") or ""
            img_record.title = img_tag.get("title", "") or ""
            img_record.parent_class, img_record.parent_id, img_record.parent_tag = get_parent_info(img_tag)
            img_record.surrounding_text = get_element_context(img_tag)

        images.append(img_record)

    # ========== 1. <img> 标签 ==========
    for img in soup.find_all("img"):
        src = None
        lazy = False

        # 1a. 检查懒加载属性（按常见顺序）
        for attr in ["data-src", "data-lazy-src", "data-original", "data-url",
                      "data-lazyload-src", "data-srcfallback"]:
            val = img.get(attr)
            if val:
                src = val
                lazy = True
                break

        # 1b. 普通 src
        if not src:
            src = img.get("src")

        if src:
            _add_image(src, img, lazy=lazy)

        # 1c. srcset（响应式图片）
        srcset = img.get("srcset")
        if srcset:
            for part in srcset.split(","):
                part = part.strip()
                if part:
                    url_part = part.split()[0]
                    if url_part != src:  # 避免重复添加同一个主图
                        _add_image(url_part, img, lazy=lazy)

    # ========== 2. <picture> / <source> 标签 ==========
    for picture in soup.find_all("picture"):
        # 获取 picture 内的 img 标签作为上下文来源
        context_img = picture.find("img")
        for source in picture.find_all("source"):
            srcset = source.get("srcset")
            if srcset:
                for part in srcset.split(","):
                    part = part.strip()
                    if part:
                        url_part = part.split()[0]
                        _add_image(url_part, context_img, lazy=False)

    # ========== 3. CSS background-image（内联样式）==========
    for element in soup.find_all(style=True):
        style = element.get("style", "")
        matches = re.findall(
            r'background-image\s*:\s*url\(["\']?(.*?)["\']?\)',
            style, re.IGNORECASE
        )
        for match in matches:
            _add_image(match, element, lazy=False)

    # ========== 4. SVG <image> 标签 ==========
    for svg_img in soup.find_all("image"):
        href = svg_img.get("href") or svg_img.get("xlink:href") or svg_img.get("href")
        if href:
            _add_image(href, svg_img, lazy=False)

    return images


def discover_links(homepage_url: str, depth: int = 1, timeout: int = 15) -> dict:
    """主函数：从首页发现所有链接并分类"""
    result = {
        "homepage": homepage_url,
        "crawled_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "categories": {},
        "image_urls": [],       # 简单格式（向后兼容）
        "images": [],           # ★ 丰富格式（带上下文）
        "doc_urls": [],
        "errors": [],
    }

    for rule in CATEGORY_RULES:
        result["categories"][rule["key"]] = []

    # 规范化 URL
    if not homepage_url.startswith(("http://", "https://")):
        homepage_url = "https://" + homepage_url

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }

    print(f"🔍 正在抓取首页: {homepage_url}")

    try:
        resp = requests.get(homepage_url, headers=headers, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
        html_content = resp.text
        actual_url = resp.url
        print(f"✅ 首页获取成功 ({len(html_content)} 字符)")
    except requests.exceptions.RequestException as e:
        result["errors"].append(f"无法访问首页: {str(e)}")
        print(f"❌ 无法访问首页: {e}", file=sys.stderr)
        return result

    try:
        soup = BeautifulSoup(html_content, "html.parser")
    except Exception as e:
        result["errors"].append(f"HTML 解析失败: {str(e)}")
        print(f"❌ HTML 解析失败: {e}", file=sys.stderr)
        return result

    seen_urls = set()

    # ===== 提取所有 <a> 标签 =====
    for a_tag in soup.find_all("a", href=True):
        href = a_tag.get("href", "")
        link_text = a_tag.get_text(strip=True)

        full_url = normalize_url(actual_url, href)
        if not full_url:
            continue

        normalized = full_url.rstrip("/")
        if normalized in seen_urls:
            continue
        seen_urls.add(normalized)

        if normalized.rstrip("/") == actual_url.rstrip("/"):
            continue

        # 图片直接链接
        if is_image_url(normalized):
            if normalized not in result["image_urls"]:
                result["image_urls"].append(normalized)
                # 同时加入丰富格式
                result["images"].append(DiscoveredImage(
                    url=normalized,
                    source_page=actual_url,
                    alt=link_text[:200],
                    surrounding_text=link_text[:200],
                    page_type=infer_image_page_type(actual_url),
                ).to_dict())
            continue

        # 文档直接链接
        if is_doc_url(normalized):
            if normalized not in result["doc_urls"]:
                result["doc_urls"].append(normalized)
            continue

        # 分类普通链接
        category, priority = classify_link(normalized, link_text)
        link_obj = DiscoveredLink(
            url=normalized,
            text=link_text[:200],
            priority=priority,
            category=category,
        )
        result["categories"][category].append(link_obj.to_dict())

    # ===== 从 HTML 中提取图片（带上下文信息）=====
    page_images = extract_images_from_html(html_content, actual_url, page_url=actual_url)
    for img_record in page_images:
        img_dict = img_record.to_dict()
        url = img_dict["url"]
        if url not in result["image_urls"]:
            result["image_urls"].append(url)
        # 检查丰富格式是否已有该 URL
        if not any(i["url"] == url for i in result["images"]):
            result["images"].append(img_dict)

    # ===== 统计信息 =====
    total_links = sum(len(v) for v in result["categories"].values())
    print(f"\n📊 链接发现完成:")
    print(f"   总计: {total_links} 个页面链接, {len(result['images'])} 张图片(含上下文), {len(result['doc_urls'])} 个文档")

    for rule in CATEGORY_RULES:
        count = len(result["categories"][rule["key"]])
        if count > 0:
            print(f"   {rule['label']} ({rule['key']}): {count} 个")

    # 统计图片中带上下文的比例
    images_with_alt = sum(1 for i in result["images"] if i.get("alt"))
    images_with_context = sum(1 for i in result["images"] if i.get("surrounding_text"))
    print(f"   🖼️ 图片详情: {len(result['images'])} 张 "
          f"(含alt: {images_with_alt}, 含上下文: {images_with_context}, 懒加载: {sum(1 for i in result['images'] if i.get('lazy_loaded'))})")

    return result


def main():
    parser = argparse.ArgumentParser(
        description="从官网首页发现和分类关键链接（v2.0 — 图片带上下文信息）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python discover_links.py --url https://www.example.com
  python discover_links.py --url https://www.example.com --output links.json
  python discover_links.py --url https://www.example.com -o links.json --timeout 20

输出格式:
  image_urls — 简单字符串列表（向后兼容旧版 download_images.py）
  images    — 对象列表（推荐，包含 alt/parent_class/surrounding_text/page_type 等上下文）
        """,
    )
    parser.add_argument("--url", required=True, help="目标官网首页 URL")
    parser.add_argument("--output", "-o", default=None, help="输出 JSON 文件路径（默认 stdout）")
    parser.add_argument("--depth", type=int, default=1, help="链接发现深度（默认 1）")
    parser.add_argument("--timeout", type=int, default=15, help="HTTP 请求超时秒数（默认 15）")
    args = parser.parse_args()

    result = discover_links(args.url, depth=args.depth, timeout=args.timeout)

    output_json = json.dumps(result, ensure_ascii=False, indent=2)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output_json, encoding="utf-8")
        print(f"\n💾 结果已保存到: {output_path}")
    else:
        print(output_json)

    if result.get("errors"):
        print("\n错误: 链接发现存在未恢复的抓取错误，请改用浏览器采集或重试。", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()

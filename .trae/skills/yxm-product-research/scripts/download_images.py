#!/usr/bin/env python3
"""
智能图片筛选与整理脚本 v2.5 - Product Research Skill
=====================================================
面向 Agent Browser 工作流的离线图片处理器。

核心职责：
1. 接收 links.json、browser_assets.json、URL 列表或本地截图路径
2. 统一归一化远程图片与本地截图元数据
3. 基于页面上下文、标题、来源页、截图类型和视觉质量进行分类
4. 输出 architecture/feature/solution/other/_review_pending 五类目录
5. 生成 _download_results.json 供后续分析和人工复核

不包含：
- OCR
- Playwright
- 浏览器自动化封装
"""

import argparse
import json
import math
import os
import re
import shutil
import sys
import urllib.parse
from dataclasses import dataclass, field, asdict
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union


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
    from PIL import Image as PILImage, ImageFilter
except ImportError:
    PILImage = None
    ImageFilter = None


SUPPORTED_CAPTURE_TYPES = {
    "dom_image",
    "network_image",
    "section_screenshot",
    "fullpage_screenshot_crop",
}

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

REMOTE_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".ico"}

SKIP_RULES = [
    {
        "label": "图标/Logo",
        "patterns": [
            r"\bicon[-_.]?\d*\.(png|jpg|svg|ico)",
            r"\bfavicon\b",
            r"\bavatar\b",
            r"\blogo\b.*\.(png|jpg|svg)",
            r"/icons/",
            r"\bicon[-_]\w+\.\w+$",
            r"(?:^|[-_/])vector(?:[-_]\d+)?\.(svg|png)$",
            r"sprites?",
            r"sprite[-_]",
        ],
        "check_size": True,
        "max_pixels": 10000,
    },
    {
        "label": "装饰性背景",
        "patterns": [
            r"\bbg[-_](image|photo|pic)",
            r"\bbackground[-_]?(image|img)?\.\w+$",
            r"\bdecoration\b",
            r"\bdecorative[-_]?\w*\.\w+$",
            r"\bpattern\b.*\.(png|jpg|svg)$",
            r"\btexture\b",
            r"bg-\w+\.\w+$",
        ],
        "check_size": False,
    },
    {
        "label": "广告/推广",
        "patterns": [
            r"\bad[-_](image?|banner?|img)\b",
            r"\badvertisement\b",
            r"\bpromo[-_](image?|banner?|img)\b",
            r"\bmarketing[-_]?(banner|img)\b",
        ],
        "check_size": False,
    },
    {
        "label": "社交媒体/二维码",
        "patterns": [
            r"\bwechat[-_]?(qr|code|image)?\b",
            r"\bweibo[-_]?\w+\.\w+$",
            r"\bqrcode\b",
            r"\bqr[-_]?(code|image|img)\b",
            r"微信",
            r"微博",
            r"二维码",
            r"扫码",
        ],
        "check_size": False,
    },
    {
        "label": "UI小元件",
        "patterns": [
            r"\bbutton[-_]?(img|image|icon)?\.\w+$",
            r"\bbtn[-_]\w+\.\w+$",
            r"\barrow[-_](left|right|up|down|next|prev)\.\w+$",
            r"\bloading\b",
            r"\bspinner\b",
            r"\bloader\b",
        ],
        "check_size": True,
        "max_pixels": 6400,
    },
    {
        "label": "招聘/文化装饰图",
        "patterns": [
            r"let'?s%20build",
            r"lets[-_%20]+build",
            r"future[-_%20]+of[-_%20]+ai",
        ],
        "check_size": False,
    },
    {
        "label": "厂商Logo",
        "patterns": [
            r"(amazonbedrock|windsurf|cursor|openai|gemini|claude|github|gitlab|databricks|salesforce)[-_]?(white|dark|logo)?\.(png|jpg|jpeg|webp|svg)$",
        ],
        "check_size": False,
    },
]

DECORATIVE_TEXT_PATTERNS = [
    r"领先科技",
    r"智领未来",
    r"赋能",
    r"引领",
    r"创新驱动",
    r"值得信赖",
    r"共创",
]

NOISE_CONTEXT_PATTERNS = [
    r"团队",
    r"员工",
    r"办公",
    r"企业文化",
    r"加入我们",
    r"联系我们",
    r"let'?s build",
    r"future of ai",
    r"合作伙伴",
    r"公众号",
    r"扫码",
]

NON_PRODUCT_VISUAL_PATTERNS = [
    r"客户(?:案例|见证|照片)?",
    r"案例(?:封面|头图|配图)",
    r"新闻(?:封面|头图|配图)",
    r"活动(?:照片|现场|报道)",
    r"建筑",
    r"大楼",
    r"园区",
    r"门头",
    r"车辆",
    r"汽车",
    r"监管机构",
    r"金融监管",
    r"营销(?:横幅|主视觉|海报)",
    r"横幅",
    r"主视觉",
    r"\bbanner\b",
    r"\bhero\b",
    r"\bcover\b",
]


@dataclass
class ImageRule:
    category: str
    label: str
    keywords_zh: List[str]
    keywords_en: List[str]
    patterns: List[str] = field(default_factory=list)
    base_score: float = 5.0


HIGH_VALUE_RULES = [
    ImageRule(
        category="architecture",
        label="架构图",
        keywords_zh=["架构", "系统架构", "技术架构", "部署架构", "拓扑", "数据流", "组件", "模块", "分层", "网关"],
        keywords_en=["architecture", "topology", "deployment", "system design", "data flow", "component", "module"],
        patterns=[
            r"(?:^|[-_/])architecture[-_.]?\w*\.\w+$",
            r"(?:^|[-_/])arch[-_.]\w+\.\w+$",
            r"(?:^|[-_/])topo(?:logy)?[-_.]?\w*\.\w+$",
            r"(?:^|[-_/])deploy(?:ment)?[-_.]?\w*\.\w+$",
        ],
        base_score=7.0,
    ),
    ImageRule(
        category="feature",
        label="功能图",
        keywords_zh=["功能", "能力", "模块", "流程", "工作流", "操作", "控制台", "仪表盘", "界面", "看板"],
        keywords_en=["feature", "capability", "workflow", "dashboard", "console", "screen", "ui", "interface"],
        patterns=[r"feature[-_]?\w*\.\w+$", r"workflow[-_]?\w*\.\w+$", r"dashboard[-_]?\w*\.\w+$"],
        base_score=6.5,
    ),
    ImageRule(
        category="solution",
        label="方案图",
        keywords_zh=["方案", "解决方案", "场景", "行业方案", "案例方案", "用例"],
        keywords_en=["solution", "scenario", "use-case", "industry solution", "application"],
        patterns=[r"solution[-_]?\w*\.\w+$", r"scenario[-_]?\w*\.\w+$"],
        base_score=6.0,
    ),
    ImageRule(
        category="other",
        label="总览图",
        keywords_zh=["产品全景", "平台总览", "生态", "矩阵", "对比", "优势", "平台"],
        keywords_en=["overview", "platform", "ecosystem", "matrix", "comparison", "advantage"],
        patterns=[r"overview[-_]?\w*\.\w+$", r"platform[-_]?\w*\.\w+$"],
        base_score=5.0,
    ),
]


PAGE_TYPE_WEIGHTS = {
    "product": {"weight": 4.5, "label": "产品页"},
    "products": {"weight": 4.5, "label": "产品页"},
    "solution": {"weight": 4.0, "label": "解决方案页"},
    "solutions": {"weight": 4.0, "label": "解决方案页"},
    "tech": {"weight": 4.5, "label": "技术页"},
    "technology": {"weight": 4.5, "label": "技术页"},
    "case": {"weight": 3.5, "label": "案例页"},
    "cases": {"weight": 3.5, "label": "案例页"},
    "customer": {"weight": 3.5, "label": "客户页"},
    "about": {"weight": 1.5, "label": "关于页"},
    "service": {"weight": 3.0, "label": "服务页"},
    "services": {"weight": 3.0, "label": "服务页"},
    "docs": {"weight": 3.0, "label": "文档页"},
    "doc": {"weight": 3.0, "label": "文档页"},
    "help": {"weight": 2.5, "label": "帮助页"},
    "news": {"weight": 1.0, "label": "新闻页"},
    "blog": {"weight": 1.5, "label": "博客页"},
    "home": {"weight": 2.5, "label": "首页"},
    "default": {"weight": 1.5, "label": "未知页"},
}

CAPTURE_TYPE_WEIGHTS = {
    "dom_image": 2.0,
    "network_image": 1.5,
    "section_screenshot": 4.0,
    "fullpage_screenshot_crop": 3.0,
}


@dataclass
class ImageQualityMetrics:
    entropy: float = 0.0
    edge_density: float = 0.0
    color_diversity: int = 0
    is_banner_like: bool = False
    quality_verdict: str = ""
    quality_score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def infer_page_type(page_url: str) -> str:
    if not page_url:
        return "default"
    path = urllib.parse.urlparse(page_url).path.lower()
    parts = [p for p in path.split("/") if p]
    for part in parts:
        for ptype in PAGE_TYPE_WEIGHTS:
            if ptype != "default" and (part.startswith(ptype) or ptype in part):
                return ptype
    if not parts or path in ["/", "/index.html", "/index.php"]:
        return "home"
    return "default"


def should_skip(identifier: str, image_size: Tuple[int, int] = (0, 0)) -> Tuple[bool, str]:
    identifier = (identifier or "").lower()
    for rule in SKIP_RULES:
        for pattern in rule["patterns"]:
            try:
                if re.search(pattern, identifier, re.IGNORECASE):
                    if rule.get("check_size") and image_size[0] > 0 and image_size[1] > 0:
                        pixels = image_size[0] * image_size[1]
                        if pixels > rule.get("max_pixels", 0):
                            continue
                    return (True, f"跳过({rule['label']})")
            except re.error:
                pass
    return (False, "")


def sanitize_filename(source: str, fallback_prefix: str = "image", max_length: int = 100) -> str:
    if source.startswith(("http://", "https://")):
        parsed = urllib.parse.urlparse(source)
        filename = parsed.path.rstrip("/").split("/")[-1] or fallback_prefix
    else:
        filename = Path(source).name or fallback_prefix
    name_part, ext = os.path.splitext(filename)
    if not ext:
        ext = ".png"
    filename = re.sub(r'[<>:"/\\|?*]', "_", name_part) + ext
    filename = re.sub(r"_+", "_", filename).strip("_")
    if len(filename) > max_length:
        stem, ext = os.path.splitext(filename)
        filename = stem[:max_length - len(ext)] + ext
    return filename or f"{fallback_prefix}.png"


def resolve_output_path(output_dir: str, category: str, filename: str) -> Path:
    target_dir = Path(output_dir) / category
    target_dir.mkdir(parents=True, exist_ok=True)
    output_path = target_dir / filename
    counter = 1
    while output_path.exists():
        stem, ext = os.path.splitext(filename)
        output_path = target_dir / f"{stem}_{counter}{ext}"
        counter += 1
    return output_path


def get_image_size(image_bytes: bytes) -> Tuple[int, int]:
    if PILImage is None:
        return (0, 0)
    try:
        img = PILImage.open(BytesIO(image_bytes))
        return img.size
    except Exception:
        return (0, 0)


def _calculate_entropy(img: "PILImage.Image") -> float:
    hist = img.histogram()
    total = sum(hist)
    if total <= 0:
        return 0.0
    entropy = 0.0
    for value in hist:
        if value > 0:
            p = value / total
            entropy -= p * math.log2(p)
    return round(entropy, 2)


def _calculate_edge_density(img: "PILImage.Image") -> float:
    if ImageFilter is None:
        return 0.0
    try:
        thumbnail = img.copy()
        thumbnail.thumbnail((500, 500), PILImage.LANCZOS)
        gray = thumbnail.convert("L")
        laplacian = gray.filter(ImageFilter.Kernel(
            (3, 3), [-1, -1, -1, -1, 8, -1, -1, -1, -1], scale=1, offset=0
        ))
        try:
            import numpy as np
        except ImportError:
            extrema = laplacian.getextrema()
            diff = abs(extrema[1] - extrema[0])
            return min(diff / 255.0, 1.0)
        edges = np.array(laplacian)
        threshold = np.mean(edges) + np.std(edges) * 0.5
        edge_pixels = np.sum(edges > threshold)
        total = edges.shape[0] * edges.shape[1]
        return round(edge_pixels / max(total, 1), 3)
    except Exception:
        return 0.0


def _calculate_color_diversity(img: "PILImage.Image") -> int:
    try:
        quantized = img.quantize(colors=64)
        return len(quantized.getcolors(maxcolors=256) or [])
    except Exception:
        return 0


def _compute_quality_score(m: ImageQualityMetrics) -> float:
    score = 0.0
    score += min(m.entropy / 2.0, 4.0)
    score += m.edge_density * 3.0
    if m.color_diversity < 8:
        score += 0.0
    elif m.color_diversity < 20:
        score += 1.0
    else:
        score += 2.0
    if m.is_banner_like:
        score -= 1.0
    return round(max(0.0, min(score, 10.0)), 1)


def _get_quality_verdict(m: ImageQualityMetrics) -> str:
    reasons = []
    if m.entropy < 3.0:
        reasons.append(f"低熵({m.entropy:.1f})")
    elif m.entropy < 4.5:
        reasons.append(f"中低熵({m.entropy:.1f})")
    if m.edge_density < 0.08:
        reasons.append(f"边缘稀疏({m.edge_density:.3f})")
    elif m.edge_density < 0.15:
        reasons.append(f"边缘一般({m.edge_density:.3f})")
    if m.color_diversity <= 8:
        reasons.append(f"颜色单调({m.color_diversity})")
    if m.is_banner_like:
        reasons.append("Banner形态")
    if not reasons:
        return "高质量"
    return "疑似低质量(" + ", ".join(reasons) + ")"


def analyze_image_quality(image_bytes: bytes, dimensions: Tuple[int, int]) -> ImageQualityMetrics:
    metrics = ImageQualityMetrics()
    if PILImage is None or not image_bytes:
        return metrics
    try:
        img = PILImage.open(BytesIO(image_bytes))
        if img.mode != "RGB":
            if img.mode == "RGBA":
                background = PILImage.new("RGB", img.size, (255, 255, 255))
                background.paste(img, mask=img.split()[-1])
                img = background
            else:
                img = img.convert("RGB")
        metrics.entropy = _calculate_entropy(img)
        metrics.edge_density = _calculate_edge_density(img)
        metrics.color_diversity = _calculate_color_diversity(img)
        width, height = dimensions
        metrics.is_banner_like = bool(height > 0 and width / max(height, 1) > 3 and height <= 320)
        metrics.quality_score = _compute_quality_score(metrics)
        metrics.quality_verdict = _get_quality_verdict(metrics)
    except Exception:
        pass
    return metrics


def _extract_remote_image_from_text(text: str) -> str:
    """从懒加载占位图附近的 HTML/文本中提取真实远程图片地址。"""
    if not text:
        return ""
    matches = re.findall(r"https?://[^\s'\"<>]+?\.(?:png|jpe?g|webp|gif|svg)(?:\?[^\s'\"<>]*)?", text, re.IGNORECASE)
    return matches[0] if matches else ""


def _resolve_local_path(path: str, base_dir: Optional[Path] = None) -> str:
    """解析 browser_assets.json 中的本地截图相对路径。"""
    if not path:
        return ""
    raw_path = Path(path)
    if raw_path.is_absolute() or raw_path.exists():
        return str(raw_path)
    candidates: List[Path] = []
    if base_dir:
        candidates.append(base_dir / raw_path)
        candidates.append(base_dir.parent / raw_path)
    candidates.append(raw_path)
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return str(candidates[0] if candidates else raw_path)


def normalize_item(raw_item: Union[str, Dict[str, Any]], base_dir: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    if isinstance(raw_item, str):
        raw_item = raw_item.strip()
        if not raw_item:
            return None
        if raw_item.startswith(("http://", "https://")):
            return {
                "url": raw_item,
                "path": "",
                "source_page": "",
                "page_type": "default",
                "capture_type": "dom_image",
                "section_heading": "",
                "nearby_text": "",
                "alt": "",
                "title": "",
                "class_name": "",
                "id": "",
            }
        maybe_path = Path(_resolve_local_path(raw_item, base_dir))
        if maybe_path.exists() and maybe_path.is_file():
            return {
                "url": "",
                "path": str(maybe_path),
                "source_page": "",
                "page_type": "default",
                "capture_type": "section_screenshot",
                "section_heading": "",
                "nearby_text": "",
                "alt": "",
                "title": "",
                "class_name": "",
                "id": "",
            }
        return None

    url = (raw_item.get("url") or "").strip()
    path = _resolve_local_path(str(raw_item.get("path") or "").strip(), base_dir)
    source_page = (raw_item.get("source_page") or raw_item.get("page_url") or "").strip()
    page_type = (raw_item.get("page_type") or "").strip() or infer_page_type(source_page)
    capture_type = (raw_item.get("capture_type") or "").strip()
    if capture_type not in SUPPORTED_CAPTURE_TYPES:
        capture_type = "dom_image" if url else "section_screenshot"
    section_heading = (raw_item.get("section_heading") or "").strip()
    nearby_text = (
        raw_item.get("nearby_text")
        or raw_item.get("surrounding_text")
        or raw_item.get("context_text")
        or ""
    ).strip()
    if url.startswith("data:image"):
        extracted_url = _extract_remote_image_from_text(nearby_text)
        if extracted_url:
            url = extracted_url
        else:
            url = ""
    alt = (raw_item.get("alt") or raw_item.get("alt_text") or "").strip()
    title = (raw_item.get("title") or "").strip()
    class_name = (raw_item.get("class_name") or raw_item.get("parent_class") or "").strip()
    item_id = (raw_item.get("id") or raw_item.get("parent_id") or "").strip()

    if not url and not path:
        return None

    return {
        "url": url,
        "path": path,
        "source_page": source_page,
        "page_type": page_type,
        "capture_type": capture_type,
        "section_heading": section_heading,
        "nearby_text": nearby_text,
        "alt": alt,
        "title": title,
        "class_name": class_name,
        "id": item_id,
    }


def parse_urls_input(input_str: str) -> List[Dict[str, Any]]:
    input_str = input_str.strip()
    items: List[Dict[str, Any]] = []

    input_base_dir: Optional[Path] = None

    def _extend_from_data(data: Any, base_dir: Optional[Path] = None) -> None:
        if isinstance(data, list):
            for item in data:
                normalized = normalize_item(item, base_dir)
                if normalized:
                    items.append(normalized)
            return
        if isinstance(data, dict):
            if isinstance(data.get("images"), list):
                for item in data["images"]:
                    normalized = normalize_item(item, base_dir)
                    if normalized:
                        items.append(normalized)
            if isinstance(data.get("captures"), list):
                for item in data["captures"]:
                    normalized = normalize_item(item, base_dir)
                    if normalized:
                        items.append(normalized)
            if isinstance(data.get("image_urls"), list):
                for item in data["image_urls"]:
                    normalized = normalize_item(item, base_dir)
                    if normalized:
                        items.append(normalized)

    if input_str.startswith("["):
        _extend_from_data(json.loads(input_str))
    elif input_str.startswith("{"):
        parsed = Path(input_str)
        if parsed.is_file():
            input_base_dir = parsed.parent
            with open(parsed, "r", encoding="utf-8") as f:
                _extend_from_data(json.load(f), input_base_dir)
        else:
            _extend_from_data(json.loads(input_str))
    else:
        parsed = Path(input_str)
        if parsed.is_file():
            input_base_dir = parsed.parent
            if parsed.suffix.lower() in REMOTE_IMAGE_EXTENSIONS:
                normalized = normalize_item(str(parsed), input_base_dir)
                if normalized:
                    items.append(normalized)
                return items
            try:
                content = parsed.read_text(encoding="utf-8").strip()
                if content.startswith("[") or content.startswith("{"):
                    _extend_from_data(json.loads(content), input_base_dir)
                else:
                    for line in content.splitlines():
                        normalized = normalize_item(line, input_base_dir)
                        if normalized:
                            items.append(normalized)
            except UnicodeDecodeError:
                normalized = normalize_item(str(parsed), input_base_dir)
                if normalized:
                    items.append(normalized)
        else:
            normalized = normalize_item(input_str)
            if normalized:
                items.append(normalized)

    deduped: List[Dict[str, Any]] = []
    seen = set()
    for item in items:
        key = ("url", item["url"]) if item.get("url") else ("path", os.path.abspath(item["path"]))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def load_image_bytes(item: Dict[str, Any], timeout: int) -> Tuple[bytes, int, str]:
    url = item.get("url", "")
    path = item.get("path", "")
    if url:
        headers = dict(DEFAULT_HEADERS)
        if item.get("source_page"):
            headers["Referer"] = item["source_page"]
        response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "")
        if not (
            content_type.startswith("image/")
            or content_type.startswith("application/octet-stream")
            or content_type == ""
        ):
            raise ValueError(f"非图片Content-Type: {content_type}")
        raw = response.content
        return raw, len(raw), content_type
    raw = Path(path).read_bytes()
    return raw, len(raw), ""


def classify_image_v25(
    item: Dict[str, Any],
    image_size: Tuple[int, int],
    file_size: int,
    quality_metrics: Optional[ImageQualityMetrics],
    strict_mode: bool = False,
) -> Tuple[Optional[str], float, str, Dict[str, Any]]:
    source_id = item.get("url") or item.get("path") or ""
    skip, skip_reason = should_skip(source_id, image_size)
    details: Dict[str, Any] = {
        "matched_keywords": [],
        "page_type": item.get("page_type") or infer_page_type(item.get("source_page", "")),
        "capture_type": item.get("capture_type", "dom_image"),
        "page_weight": 0.0,
        "capture_weight": 0.0,
        "size_bonus": 0.0,
        "quality": quality_metrics.to_dict() if quality_metrics else None,
        "decision": "",
    }
    if skip:
        details["decision"] = "skip_rule"
        return (None, 0.0, skip_reason, details)

    section_heading = item.get("section_heading", "")
    nearby_text = item.get("nearby_text", "")
    alt = item.get("alt", "")
    title = item.get("title", "")
    class_name = item.get("class_name", "")
    item_id = item.get("id", "")
    source_page = item.get("source_page", "")
    page_type = details["page_type"]
    capture_type = details["capture_type"]

    url_or_path = " ".join(filter(None, [item.get("url", ""), item.get("path", "")]))
    combined_text = " ".join(
        filter(None, [section_heading, nearby_text, alt, title, class_name, item_id, source_page, url_or_path, page_type])
    )
    combined_lower = combined_text.lower()

    for pattern in NOISE_CONTEXT_PATTERNS:
        if re.search(pattern, combined_text, re.IGNORECASE):
            if not any(kw in combined_text for kw in ["架构", "方案", "功能", "architecture", "solution", "feature"]):
                details["decision"] = "noise_context"
                return (None, 0.0, "跳过(无产品价值上下文)", details)

    page_weight_info = PAGE_TYPE_WEIGHTS.get(page_type, PAGE_TYPE_WEIGHTS["default"])
    page_weight = page_weight_info["weight"]
    capture_weight = CAPTURE_TYPE_WEIGHTS.get(capture_type, 1.0)
    details["page_weight"] = page_weight
    details["capture_weight"] = capture_weight

    width, height = image_size
    size_bonus = 0.0
    pixels = width * height
    if pixels >= 1200 * 700:
        size_bonus += 3.0
    elif pixels >= 800 * 500:
        size_bonus += 2.0
    elif pixels >= 500 * 300:
        size_bonus += 1.0
    if file_size >= 200 * 1024:
        size_bonus += 1.5
    elif file_size >= 80 * 1024:
        size_bonus += 0.8
    details["size_bonus"] = round(size_bonus, 2)

    best_category: Optional[str] = None
    best_score = 0.0
    best_reason = ""
    matched_keywords: List[str] = []

    def _score_keyword_set(rule: ImageRule) -> Tuple[float, List[str]]:
        score = rule.base_score
        matches: List[str] = []
        for pattern in rule.patterns:
            try:
                if re.search(pattern, url_or_path.lower(), re.IGNORECASE):
                    score += 2.5
                    matches.append(f"url:{pattern[:20]}")
            except re.error:
                pass

        def _bump(value: str, bonus: float, keyword: str) -> None:
            nonlocal score
            if keyword not in matches:
                matches.append(keyword)
            score += bonus

        for kw in rule.keywords_zh:
            if kw in section_heading:
                _bump(section_heading, 3.0, kw)
            elif kw in nearby_text:
                _bump(nearby_text, 2.0, kw)
            elif kw in alt or kw in title:
                _bump(alt + title, 1.5, kw)
            elif kw in combined_text:
                _bump(combined_text, 1.0, kw)

        for kw in rule.keywords_en:
            pattern = re.escape(kw.replace("-", r"[-_. ]?"))
            if re.search(pattern, section_heading, re.IGNORECASE):
                _bump(section_heading, 2.5, kw)
            elif re.search(pattern, nearby_text, re.IGNORECASE):
                _bump(nearby_text, 1.8, kw)
            elif re.search(pattern, alt + " " + title, re.IGNORECASE):
                _bump(alt + title, 1.2, kw)
            elif re.search(pattern, combined_text, re.IGNORECASE):
                _bump(combined_text, 0.8, kw)
        return score, matches

    for rule in HIGH_VALUE_RULES:
        score, matches = _score_keyword_set(rule)
        if capture_type in {"section_screenshot", "fullpage_screenshot_crop"} and matches:
            score += 1.5
        score += page_weight + capture_weight + size_bonus
        if score > best_score and matches:
            best_category = rule.category
            best_score = score
            best_reason = f"{rule.label}({', '.join(matches[:6])})"
            matched_keywords = matches

    quality_penalty = 0.0
    if quality_metrics:
        if quality_metrics.entropy < (3.5 if strict_mode else 2.6):
            quality_penalty += 2.0
        if quality_metrics.edge_density < (0.06 if strict_mode else 0.04):
            quality_penalty += 1.0
        if quality_metrics.is_banner_like and best_category is None:
            quality_penalty += 1.5
        if quality_metrics.color_diversity <= 6 and quality_metrics.entropy < 4.0:
            quality_penalty += 1.0

    details["quality_penalty"] = quality_penalty

    decorative_context = any(re.search(p, combined_text, re.IGNORECASE) for p in DECORATIVE_TEXT_PATTERNS)
    if decorative_context and quality_metrics and quality_metrics.is_banner_like and best_category is None:
        details["decision"] = "decorative_banner"
        return (None, 0.0, "跳过(营销Banner/装饰图)", details)

    final_score = best_score - quality_penalty
    details["matched_keywords"] = matched_keywords[:10]
    details["final_score"] = round(final_score, 2)

    high_value_page = page_type in {"product", "products", "solution", "solutions", "tech", "technology", "docs", "doc"}
    screenshot_candidate = capture_type in {"section_screenshot", "fullpage_screenshot_crop"}
    large_candidate = pixels >= 150000 or file_size >= 50000
    weak_context_page = page_type in {"home", "news", "blog", "case", "cases", "customer"}
    strong_signal_text = " ".join(filter(None, [section_heading, alt, title, class_name, item_id, url_or_path]))
    strong_visual_terms = [
        "架构图",
        "能力架构",
        "应用架构",
        "技术架构",
        "部署架构",
        "拓扑图",
        "流程图",
        "关系图谱",
        "产品界面",
        "控制台",
        "仪表盘",
        "看板",
        "architecture",
        "topology",
        "workflow",
        "dashboard",
        "console",
    ]
    has_strong_visual_signal = bool(
        any(term in strong_signal_text for term in strong_visual_terms)
        or any(term in combined_lower for term in ["architecture diagram", "system diagram", "product screenshot"])
    )
    has_non_product_visual_context = any(
        re.search(pattern, combined_text, re.IGNORECASE) for pattern in NON_PRODUCT_VISUAL_PATTERNS
    )
    filename = Path(urllib.parse.urlparse(url_or_path.split()[0]).path).name.lower() if url_or_path else ""
    logo_like_dom_asset = (
        capture_type == "dom_image"
        and best_category == "other"
        and not has_strong_visual_signal
        and (
            re.search(r"(^logo\.)|(^svg-\d+)|(^\d+[-_a-z0-9]+)", filename)
            or (width <= 500 and height <= 250 and file_size <= 32 * 1024)
        )
    )
    if logo_like_dom_asset:
        details["decision"] = "skip_logo_like_other"
        return (None, 0.0, "跳过(疑似Logo/客户标识/控件图)", details)

    if has_non_product_visual_context and not has_strong_visual_signal and best_category:
        if weak_context_page:
            details["decision"] = "skip_non_product_visual_context"
            return (None, 0.0, "跳过(客户照片/营销横幅/装饰图上下文)", details)
        if large_candidate:
            details["decision"] = "pending_non_product_visual_context"
            return ("_review_pending", final_score, f"待审-疑似非产品视觉素材{best_reason}", details)

    if best_category and capture_type == "dom_image" and weak_context_page and not has_strong_visual_signal:
        if large_candidate and final_score >= 5.0:
            details["decision"] = "pending_weak_context"
            return ("_review_pending", final_score, f"待审-弱上下文{best_reason}", details)
        details["decision"] = "skip_weak_context"
        return (None, 0.0, "跳过(首页/新闻/案例弱上下文图片)", details)

    if best_category and final_score >= 10.0:
        details["decision"] = "classified"
        return (best_category, final_score, best_reason, details)

    if best_category and final_score >= 8.0 and not (quality_metrics and quality_metrics.is_banner_like and best_category == "other"):
        details["decision"] = "classified"
        return (best_category, final_score, best_reason, details)

    if best_category and final_score >= 6.0 and screenshot_candidate:
        details["decision"] = "classified"
        return (best_category, final_score, f"{best_reason} +截图候选", details)

    if best_category and final_score >= 5.0 and high_value_page:
        details["decision"] = "pending"
        return ("_review_pending", final_score, f"待审-{best_reason}", details)

    if (screenshot_candidate and high_value_page and large_candidate) or ("架构" in section_heading and large_candidate):
        details["decision"] = "pending"
        return ("_review_pending", page_weight + capture_weight + size_bonus - quality_penalty, "待审-重点页面截图候选", details)

    if large_candidate and high_value_page and quality_penalty <= 2.0:
        details["decision"] = "pending"
        return ("_review_pending", page_weight + size_bonus - quality_penalty, "待审-重点页面大图", details)

    if quality_metrics and quality_metrics.is_banner_like and quality_penalty >= 2.0:
        details["decision"] = "low_quality_banner"
        return (None, 0.0, "跳过(疑似Banner/装饰图)", details)

    details["decision"] = "skip_no_signal"
    return (None, 0.0, "跳过(无足够上下文信号)", details)


def write_output_bytes(item: Dict[str, Any], category: str, output_dir: str, image_bytes: bytes) -> Path:
    source = item.get("url") or item.get("path") or "image"
    filename = sanitize_filename(source)
    output_path = resolve_output_path(output_dir, category, filename)
    with open(output_path, "wb") as f:
        f.write(image_bytes)
    return output_path


def process_image_item(
    item: Dict[str, Any],
    output_dir: str,
    min_width: int,
    min_height: int,
    timeout: int,
    strict_mode: bool,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "url": item.get("url", ""),
        "path": item.get("path", ""),
        "source_page": item.get("source_page", ""),
        "page_type": item.get("page_type", ""),
        "capture_type": item.get("capture_type", ""),
        "section_heading": item.get("section_heading", ""),
        "nearby_text": item.get("nearby_text", ""),
        "success": False,
        "saved_path": None,
        "category": None,
        "size": 0,
        "dimensions": (0, 0),
        "score": 0.0,
        "reason": "",
        "needs_review": False,
        "quality": None,
        "evidence": None,
    }

    source = item.get("url") or item.get("path")
    if not source:
        result["reason"] = "无可处理来源"
        return result

    try:
        image_bytes, content_length, _ = load_image_bytes(item, timeout)
        if content_length < 512:
            result["reason"] = f"文件过小 ({content_length} bytes)"
            return result
        if content_length > 50 * 1024 * 1024:
            result["reason"] = f"文件过大 ({content_length / 1024 / 1024:.1f} MB)"
            return result

        dimensions = get_image_size(image_bytes)
        width, height = dimensions
        if min_width > 0 and width > 0 and width < min_width:
            result["reason"] = f"宽度不足 ({width} < {min_width})"
            return result
        if min_height > 0 and height > 0 and height < min_height:
            result["reason"] = f"高度不足 ({height} < {min_height})"
            return result

        quality_metrics = analyze_image_quality(image_bytes, dimensions)
        category, score, reason, details = classify_image_v25(
            item=item,
            image_size=dimensions,
            file_size=content_length,
            quality_metrics=quality_metrics,
            strict_mode=strict_mode,
        )

        result["size"] = content_length
        result["dimensions"] = dimensions
        result["score"] = score
        result["reason"] = reason
        result["quality"] = quality_metrics.to_dict()
        result["evidence"] = details

        if category is None:
            return result

        output_path = write_output_bytes(item, category, output_dir, image_bytes)
        result["success"] = True
        result["saved_path"] = str(output_path)
        result["category"] = category
        result["needs_review"] = category == "_review_pending"
        return result

    except requests.exceptions.RequestException as exc:
        result["reason"] = f"下载失败: {exc}"
    except FileNotFoundError as exc:
        result["reason"] = f"本地文件不存在: {exc}"
    except IOError as exc:
        result["reason"] = f"读写失败: {exc}"
    except Exception as exc:
        result["reason"] = f"未知错误: {exc}"
    return result


def merge_results_data(existing: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
    """合并多次图片下载运行的结果，保留完整验收证据。"""
    if not existing:
        return current

    merged_downloaded = list(existing.get("downloaded") or []) + list(current.get("downloaded") or [])
    merged_skipped = list(existing.get("skipped") or []) + list(current.get("skipped") or [])

    inputs: List[str] = []
    for value in [existing.get("inputs"), current.get("inputs")]:
        if isinstance(value, list):
            inputs.extend(str(item) for item in value)
        elif value:
            inputs.append(str(value))

    by_category: Dict[str, int] = {}
    total_size = 0
    for item in merged_downloaded:
        category = item.get("category")
        if category:
            by_category[category] = by_category.get(category, 0) + 1
        total_size += int(item.get("size") or 0)

    current["inputs"] = list(dict.fromkeys(inputs))
    current["summary"] = {
        "total": len(merged_downloaded) + len(merged_skipped),
        "saved": len(merged_downloaded),
        "high_confidence": sum(1 for r in merged_downloaded if not r.get("needs_review")),
        "pending_review": sum(1 for r in merged_downloaded if r.get("needs_review")),
        "skipped": len(merged_skipped),
        "total_size_bytes": total_size,
        "by_category": by_category,
    }
    current["downloaded"] = merged_downloaded
    current["skipped"] = merged_skipped
    return current


def main() -> None:
    parser = argparse.ArgumentParser(
        description="智能图片筛选与整理工具 v2.5 — Agent Browser 资产 + 静态发现统一处理",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python download_images.py --urls links.json -o ./images
  python download_images.py --urls browser_assets.json -o ./images
  python download_images.py --urls captures.json -o ./images --strict

输入支持:
  - links.json
  - browser_assets.json
  - JSON 数组
  - 文本 URL 列表
  - 本地截图路径
        """,
    )
    parser.add_argument("--urls", required=True, help="图片数据（links.json / browser_assets.json / JSON / URL / 本地路径）")
    parser.add_argument("--output-dir", "-o", default="./images", help="输出根目录（默认 ./images）")
    parser.add_argument("--min-width", type=int, default=150, help="最小宽度像素（默认 150）")
    parser.add_argument("--min-height", type=int, default=100, help="最小高度像素（默认 100）")
    parser.add_argument("--timeout", type=int, default=20, help="超时秒数（默认 20）")
    parser.add_argument("--strict", action="store_true", help="严格质量模式——更积极地过滤低质量图片")
    parser.add_argument("--verbose", "-v", action="store_true", help="输出详细分类过程")
    args = parser.parse_args()

    items = parse_urls_input(args.urls)
    if not items:
        print("❌ 未找到有效的图片数据", file=sys.stderr)
        sys.exit(1)

    output_root = Path(args.output_dir)
    for cat in ["architecture", "feature", "solution", "other", "_review_pending"]:
        (output_root / cat).mkdir(parents=True, exist_ok=True)

    print(f"[images] 待处理素材: {len(items)} 项")
    print(f"[output] 输出目录: {args.output_dir}")
    print(f"[size] 最小尺寸: {args.min_width}x{args.min_height}")
    mode_tag = "【严格】" if args.strict else ""
    print(f"[mode] 策略: v2.5 上下文优先分类{mode_tag}(来源页+标题+截图类型+尺寸+视觉质量)")
    print("-" * 70)

    stats = {"downloaded": [], "skipped": []}

    for index, item in enumerate(items, 1):
        display = item.get("url") or item.get("path") or "???"
        print(f"[{index}/{len(items)}] {display[:70]}...", end=" ", flush=True)
        result = process_image_item(
            item=item,
            output_dir=args.output_dir,
            min_width=args.min_width,
            min_height=args.min_height,
            timeout=args.timeout,
            strict_mode=args.strict,
        )
        if result["success"]:
            marker = "[review]" if result["needs_review"] else "[saved]"
            dim = result["dimensions"]
            size_kb = result["size"] / 1024
            keywords = ", ".join(result.get("evidence", {}).get("matched_keywords", [])[:4])
            print(f"{marker} {result['category']} ({dim[0]}x{dim[1]}, {size_kb:.1f}KB) [{result['reason']}]")
            if args.verbose and keywords:
                print(f"      关键词: {keywords}")
            stats["downloaded"].append(result)
        else:
            print(f"[skip] {result['reason']}")
            stats["skipped"].append(result)

    print("\n" + "=" * 70)
    print("[summary] 处理完成:")
    print(f"   saved: {sum(1 for r in stats['downloaded'] if not r['needs_review'])} 项")
    print(f"   review_pending: {sum(1 for r in stats['downloaded'] if r['needs_review'])} 项")
    print(f"   skipped: {len(stats['skipped'])} 项")

    by_category: Dict[str, int] = {}
    total_size = 0
    for item in stats["downloaded"]:
        by_category[item["category"]] = by_category.get(item["category"], 0) + 1
        total_size += item["size"]
    print(f"   total_size: {total_size / 1024 / 1024:.2f} MB")
    print("[categories]")
    for category in ["architecture", "feature", "solution", "other", "_review_pending"]:
        if by_category.get(category):
            print(f"   {category}/: {by_category[category]} 项")

    results_file = output_root / "_download_results.json"
    results_data = {
        "version": "2.5",
        "strategy": "context-first",
        "inputs": args.urls,
        "summary": {
            "total": len(items),
            "saved": len(stats["downloaded"]),
            "high_confidence": sum(1 for r in stats["downloaded"] if not r["needs_review"]),
            "pending_review": sum(1 for r in stats["downloaded"] if r["needs_review"]),
            "skipped": len(stats["skipped"]),
            "total_size_bytes": total_size,
            "by_category": by_category,
        },
        "downloaded": [
            {
                "url": r["url"],
                "path": r["path"],
                "saved_path": r["saved_path"],
                "source_page": r["source_page"],
                "page_type": r["page_type"],
                "capture_type": r["capture_type"],
                "section_heading": r["section_heading"],
                "nearby_text": r["nearby_text"],
                "category": r["category"],
                "size": r["size"],
                "dimensions": list(r["dimensions"]),
                "reason": r["reason"],
                "needs_review": r["needs_review"],
                "quality": r.get("quality"),
                "evidence": r.get("evidence"),
            }
            for r in stats["downloaded"]
        ],
        "skipped": [
            {
                "url": r["url"],
                "path": r["path"],
                "source_page": r["source_page"],
                "page_type": r["page_type"],
                "capture_type": r["capture_type"],
                "section_heading": r["section_heading"],
                "nearby_text": r["nearby_text"],
                "reason": r["reason"],
                "quality": r.get("quality"),
                "evidence": r.get("evidence"),
            }
            for r in stats["skipped"]
        ],
    }
    existing_results: Dict[str, Any] = {}
    if results_file.exists():
        try:
            existing_results = json.loads(results_file.read_text(encoding="utf-8"))
        except Exception:
            existing_results = {}
    results_data = merge_results_data(existing_results, results_data)

    with open(results_file, "w", encoding="utf-8") as f:
        json.dump(results_data, f, ensure_ascii=False, indent=2)
    print(f"\n[results] 详细结果已保存至: {results_file}")


if __name__ == "__main__":
    main()

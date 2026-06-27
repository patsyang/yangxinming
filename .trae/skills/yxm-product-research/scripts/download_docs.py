#!/usr/bin/env python3
"""
文档资源下载脚本 - Product Research Skill
==========================================
自动识别并下载官网上的产品文档（白皮书、案例、手册等），
按类型分类存放。

Usage:
    python download_docs.py --urls <json_or_file> --output-dir ./documents

Output:
    documents/
    ├── whitepaper/   # 白皮书
    ├── case/         # 用户案例
    ├── brochure/     # 产品手册
    └── other/        # 其他文档
"""

import argparse
import json
import mimetypes
import os
import re
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Optional, List, Tuple


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


# ============================================================
# 配置
# ============================================================

# 支持的文档格式映射
DOC_FORMATS = {
    ".pdf": ("application/pdf", "PDF 文档"),
    ".doc": ("application/msword", "Word 文档"),
    ".docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "Word 文档"),
    ".ppt": ("application/vnd.ms-powerpoint", "PPT 文档"),
    ".pptx": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", "PPT 文档"),
    ".xls": ("application/vnd.ms-excel", "Excel 文档"),
    ".xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "Excel 文档"),
    ".md": ("text/markdown", "Markdown 文档"),
    ".markdown": ("text/markdown", "Markdown 文档"),
    ".txt": ("text/plain", "文本文件"),
}

# 文档类型自动分类规则（基于 URL 路径/文件名关键词）
CLASSIFICATION_RULES = [
    {
        "category": "whitepaper",
        "label": "白皮书",
        "keywords_zh": ["白皮书", "技术白皮书", "行业报告", "研究报告"],
        "keywords_en": [
            "whitepaper", "white-paper", "wp-", "white_paper",
            "tech-report", "industry-report", "research",
        ],
    },
    {
        "category": "case",
        "label": "用户案例",
        "keywords_zh": ["案例", "客户案例", "成功故事", "实践", "标杆"],
        "keywords_en": [
            "case", "case-study", "customer", "client",
            "story", "success-story", "practice", "reference",
        ],
    },
    {
        "category": "brochure",
        "label": "产品手册",
        "keywords_zh": ["手册", "指南", "产品介绍", "说明书", "datasheet", "数据单"],
        "keywords_en": [
            "brochure", "guide", "handbook", "manual",
            "datasheet", "product-intro", "specification",
            "flyer", "overview", "product-sheet",
        ],
    },
]

# 不允许下载的文件扩展名
BLOCKED_EXTENSIONS = {
    ".exe", ".msi", ".dmg", ".app", ".deb", ".rpm",  # 可执行文件
    ".sh", ".bat", ".cmd", ".ps1",                    # 脚本文件
    ".jar", ".war", ".dll", ".so",                   # 程序库
    ".zip", ".rar", ".7z", ".tar", ".gz",           # 压缩包（除非明确需要）
}


def classify_document(url: str) -> str:
    """
    根据 URL 判断文档类型，返回目标子目录名。
    """
    url_lower = url.lower()
    path = urllib.parse.urlparse(url).path.lower()
    filename = os.path.basename(path)

    # 合并检查文本来源：URL路径 + 文件名
    check_text = path + " " + filename

    for rule in CLASSIFICATION_RULES:
        for kw in rule["keywords_en"]:
            pattern = re.escape(kw.replace("-", r"[-_.]?"))
            try:
                if re.search(pattern, check_text, re.IGNORECASE):
                    return rule["category"]
            except re.error:
                pass

        for kw in rule["keywords_zh"]:
            try:
                if re.search(re.escape(kw), check_text, re.IGNORECASE):
                    return rule["category"]
            except re.error:
                pass

    return "other"


def get_extension_from_url(url: str) -> str:
    """从 URL 提取文件扩展名"""
    path = urllib.parse.urlparse(url).path
    _, ext = os.path.splitext(path)
    return ext.lower()


def get_extension_from_content_type(content_type: str) -> str:
    """从 Content-Type 推断扩展名"""
    if not content_type:
        return ""

    # 常见 MIME 到扩展名的映射
    mime_map = {
        "application/pdf": ".pdf",
        "application/msword": ".doc",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/vnd.ms-powerpoint": ".ppt",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
        "application/vnd.ms-excel": ".xls",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
        "text/markdown": ".md",
        "text/plain": ".txt",
        "application/octet-stream": "",  # 二进制流，无法确定
    }

    # 处理带参数的 Content-Type (如 "application/pdf; charset=utf-8")
    base_type = content_type.split(";")[0].strip().lower()
    return mime_map.get(base_type, "")


def sanitize_filename(url: str, fallback_ext: str = ".pdf") -> str:
    """从 URL 生成安全的文件名"""
    parsed = urllib.parse.urlparse(url)
    path = parsed.path

    # 提取文件名
    filename = path.rstrip("/").split("/")[-1] if path else "document"

    # 清理查询参数残留（有些 URL 文件名后带 ?xxx=yyy）
    if "?" in filename:
        filename = filename.split("?")[0]
    if "#" in filename:
        filename = filename.split("#")[0]

    name_part, ext = os.path.splitext(filename)

    # 如果扩展名不在支持列表中，使用推断的扩展名
    if ext.lower() not in DOC_FORMATS:
        ext = fallback_ext
        filename = name_part + ext

    # 清理非法字符
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    filename = re.sub(r'_+', '_', filename).strip("_")

    # 限制长度
    if len(filename) > 120:
        filename = name_part[:100] + ext

    return filename or f"document_{int(time.time())}{fallback_ext}"


def detect_download_filename(response: requests.Response, url: str) -> str:
    """
    从响应头或 URL 中检测最佳文件名。

    优先级：Content-Disposition > URL 路径 > 自动生成
    """
    # 1. 尝试从 Content-Disposition 获取
    cd = response.headers.get("Content-Disposition", "")
    if cd:
        match = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';]+)', cd, re.IGNORECASE)
        if match:
            raw_name = match.group(1).strip()
            # URL decode
            decoded = urllib.parse.unquote(raw_name)
            return decoded

        match = re.search(r'filename="?([^"]+)"?', cd)
        if match:
            return match.group(1).strip()

    # 2. 使用 URL 中的文件名
    ext_from_ct = get_extension_from_content_type(response.headers.get("Content-Type", ""))
    return sanitize_filename(url, ext_from_ct or ".pdf")


def is_blocked_url(url: str) -> bool:
    """检查是否为不允许下载的文件类型"""
    ext = get_extension_from_url(url)
    return ext in BLOCKED_EXTENSIONS


def download_document(
    url: str,
    output_dir: str,
    timeout: int = 30,
    retries: int = 1,
) -> dict:
    """
    下载单个文档文件。

    Returns:
        结果字典
    """
    result = {
        "url": url,
        "success": False,
        "path": None,
        "category": None,
        "size": 0,
        "format": "",
        "reason": "",
        "attempts": 0,
    }

    # 检查是否被阻止的文件类型
    if is_blocked_url(url):
        result["reason"] = "不支持的文件类型"
        return result

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "application/pdf,application/msword,application/vnd.openxmlformats-officedocument.*,"
            "application/vnd.ms-*,*/*"
        ),
        "Referer": urllib.parse.urljoin(url, "/"),
    }

    max_attempts = max(1, retries + 1)
    last_network_error = ""

    for attempt in range(1, max_attempts + 1):
        result["attempts"] = attempt
        try:
            # 使用 stream 模式以支持大文件
            resp = requests.get(url, headers=headers, timeout=timeout, stream=True, allow_redirects=True)
            break
        except requests.exceptions.RequestException as e:
            last_network_error = str(e)
            if attempt < max_attempts:
                time.sleep(min(2, attempt))
                continue
            result["reason"] = f"网络错误(已重试 {max_attempts - 1} 次): {last_network_error}"
            return result

    try:
        resp.raise_for_status()

        content_type = resp.headers.get("Content-Type", "")

        # 检查内容类型是否为支持的文档
        base_ct = content_type.split(";")[0].strip().lower()

        # 如果是 HTML 页面而非文件下载，跳过
        if "text/html" in base_ct and not any(ext in url.lower() for ext in [".pdf", ".doc", ".docx"]):
            result["reason"] = f"返回的是HTML页面而非文档文件 ({base_ct})"
            return result

        # 确定文件名和格式
        filename = detect_download_filename(resp, url)
        ext = get_extension_from_url(filename) or get_extension_from_content_type(content_type)
        format_label = DOC_FORMATS.get(ext, ("unknown", "未知格式"))[1]

        # 内容长度检查
        content_length = int(resp.headers.get("Content-Length", 0))

        # 最小文件大小检查（避免下载空页面）
        if content_length > 0 and content_length < 512:
            result["reason"] = f"文件过小 ({content_length} bytes)"
            return result

        # 最大文件大小检查（200MB 上限）
        max_size = 200 * 1024 * 1024
        if content_length > max_size:
            result["reason"] = f"文件过大 ({content_length / 1024 / 1024:.1f} MB)"
            return result

        # 分类
        category = classify_document(url)

        # 创建目录并写入文件
        target_dir = Path(output_dir) / category
        target_dir.mkdir(parents=True, exist_ok=True)

        output_path = target_dir / filename

        # 处理重名冲突
        counter = 1
        while output_path.exists():
            name, e = os.path.splitext(filename)
            output_path = target_dir / f"{name}_{counter}{e}"
            counter += 1

        # 写入文件（分块写入以处理大文件）
        with open(output_path, "wb") as f:
            total_written = 0
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    total_written += len(chunk)
                    # 运行时大小检查
                    if total_written > max_size:
                        output_path.unlink()  # 删除已写入的部分
                        result["reason"] = f"下载过程中超过大小限制 ({total_written / 1024 / 1024:.1f} MB)"
                        return result

        result.update({
            "success": True,
            "path": str(output_path),
            "category": category,
            "size": total_written or os.path.getsize(output_path),
            "format": format_label,
            "reason": f"成功下载({format_label})",
        })

    except requests.exceptions.RequestException as e:
        result["reason"] = f"网络错误: {str(e)}"
    except IOError as e:
        result["reason"] = f"写入失败: {str(e)}"
    except Exception as e:
        result["reason"] = f"未知错误: {str(e)}"

    return result


def build_results_summary(results: dict) -> dict:
    """生成文档下载结果摘要，便于报告追踪失败原因。"""
    downloaded = results.get("downloaded", [])
    skipped = results.get("skipped", [])
    total_size = sum(int(r.get("size") or 0) for r in downloaded)
    by_category = {}
    for item in downloaded:
        category = item.get("category") or "other"
        by_category[category] = by_category.get(category, 0) + 1
    return {
        "total": len(downloaded) + len(skipped),
        "downloaded": len(downloaded),
        "skipped": len(skipped),
        "total_size_bytes": total_size,
        "by_category": by_category,
        "failures": [
            {
                "url": item.get("url", ""),
                "reason": item.get("reason", ""),
                "attempts": item.get("attempts", 0),
            }
            for item in skipped
        ],
    }


def main():
    parser = argparse.ArgumentParser(
        description="文档资源自动下载与分类工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--urls", required=True, help=(
        "文档 URL 列表（JSON 数组、JSON 文件、或纯文本文件每行一个URL）"
    ))
    parser.add_argument("--output-dir", "-o", default="./documents", help="输出根目录（默认 ./documents）")
    parser.add_argument("--timeout", type=int, default=30, help="下载超时秒数（默认 30）")
    parser.add_argument("--retries", type=int, default=1, help="网络失败重试次数（默认 1）")
    args = parser.parse_args()

    # 解析输入
    urls_input = args.urls.strip()

    if urls_input.startswith("["):
        url_list = json.loads(urls_input)
    elif Path(urls_input).is_file():
        with open(urls_input, "r", encoding="utf-8") as f:
            content = f.read().strip()
        try:
            data = json.loads(content)
            url_list = data.get("doc_urls", [])
        except json.JSONDecodeError:
            url_list = [line.strip() for line in content.splitlines()
                       if line.strip() and line.strip().startswith("http")]
    else:
        url_list = [urls_input] if urls_input.startswith("http") else []

    if not url_list:
        print("❌ 未找到有效的文档 URL", file=sys.stderr)
        sys.exit(1)

    print(f"📄 待处理文档: {len(url_list)} 个")
    print(f"📁 输出目录: {args.output_dir}")
    print("-" * 60)

    results = {"downloaded": [], "skipped": []}

    for i, url in enumerate(url_list, 1):
        print(f"[{i}/{len(url_list)}] {url[:70]}...", end=" ", flush=True)
        result = download_document(url, args.output_dir, timeout=args.timeout, retries=args.retries)

        if result["success"]:
            size_kb = result["size"] / 1024
            cat = result["category"]
            fmt = result["format"]
            print(f"✅ {cat}/ ({fmt}, {size_kb:.1f}KB)")
            results["downloaded"].append(result)
        else:
            print(f"⏭️ {result['reason']}")
            results["skipped"].append(result)

    # 统计
    print("\n" + "=" * 60)
    print(f"📊 下载完成:")
    print(f"   ✅ 成功下载: {len(results['downloaded'])} 个")
    print(f"   ⏭️ 已跳过: {len(results['skipped'])} 个")

    total_size = sum(r["size"] for r in results["downloaded"])
    print(f"   📦 总大小: {total_size / 1024 / 1024:.2f} MB")

    print("\n📂 按类别:")
    by_cat = {}
    for r in results["downloaded"]:
        cat = r["category"]
        by_cat.setdefault(cat, []).append((Path(r["path"]).name, r["size"]))

    for cat, files in sorted(by_cat.items()):
        print(f"   📁 {cat}/: {len(files)} 个文件")
        for fname, fsize in sorted(files)[:3]:  # 显示前3个
            print(f"      - {fname} ({fsize / 1024:.1f} KB)")
        if len(files) > 3:
            print(f"      ... 还有 {len(files) - 3} 个")

    output_root = Path(args.output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    results_data = {
        "version": "1.1",
        "inputs": args.urls,
        "summary": build_results_summary(results),
        "downloaded": results["downloaded"],
        "skipped": results["skipped"],
    }
    results_file = output_root / "_download_results.json"
    with open(results_file, "w", encoding="utf-8") as f:
        json.dump(results_data, f, ensure_ascii=False, indent=2)
    print(f"\n📋 下载结果已保存至: {results_file}")


if __name__ == "__main__":
    main()

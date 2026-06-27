#!/usr/bin/env python3
"""
素材打包脚本 - YD Product Research Skill
=====================================
将产品研究中抓取的图片和文档打包为 ZIP 文件。

Usage:
    python package_assets.py --source-dir <工作目录> --output-dir ./output [--zip-name 素材.zip]
"""

import argparse
import os
import sys
import time
import zipfile
from pathlib import Path
from typing import List, Tuple


def configure_console_output() -> None:
    """避免 Windows GBK 控制台遇到 emoji 时抛出编码异常。"""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")


configure_console_output()


def collect_files(source_dir: Path, include_dirs: List[str]) -> List[Tuple[str, int]]:
    """
    收集需要打包的文件。
    返回 [(相对路径, 文件大小), ...] 列表
    """
    files = []

    for dir_name in include_dirs:
        dir_path = source_dir / dir_name
        if not dir_path.exists():
            continue

        for file_path in sorted(dir_path.rglob("*")):
            if file_path.is_file():
                rel_path = file_path.relative_to(source_dir)
                size = file_path.stat().st_size
                files.append((str(rel_path), size))

    return files


def create_zip(
    source_dir: str,
    output_path: str,
    include_dirs: List[str],
) -> dict:
    """
    创建 ZIP 压缩包。
    """
    result = {
        "success": False,
        "zip_path": output_path,
        "file_count": 0,
        "total_size": 0,
        "by_category": {},
    }

    source = Path(source_dir)
    files = collect_files(source, include_dirs)

    if not files:
        result["reason"] = "没有找到可打包的文件"
        return result

    # 确保输出目录存在
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    # 创建 ZIP 文件
    try:
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as zf:
            for rel_path, size in files:
                full_path = source / rel_path
                # 使用正斜杠作为 ZIP 内路径分隔符（兼容性）
                arc_name = rel_path.replace("\\", "/")
                zf.write(full_path, arc_name)

                # 统计
                result["file_count"] += 1
                result["total_size"] += size

                # 按顶层目录分类统计
                top_dir = rel_path.split(os.sep)[0]
                result["by_category"].setdefault(top_dir, {"count": 0, "size": 0})
                result["by_category"][top_dir]["count"] += 1
                result["by_category"][top_dir]["size"] += size

        result["success"] = True
        result["zip_size"] = output.stat().st_size

    except Exception as e:
        result["reason"] = f"打包失败: {str(e)}"

    return result


def format_size(size_bytes: int) -> str:
    """格式化文件大小"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / 1024 / 1024:.2f} MB"


def main():
    parser = argparse.ArgumentParser(
        description="将产品研究素材打包为 ZIP 文件",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python package_assets.py --source-dir . --output-dir ./output
  python package_assets.py --source-dir . --output-dir ./output \\
      --zip-name "素材_某公司_20260424.zip"
        """,
    )
    parser.add_argument("--source-dir", "-s", default=".", help="源目录（默认当前目录）")
    parser.add_argument("--output-dir", "-o", default="./output", help="输出目录（默认 ./output）")
    parser.add_argument(
        "--zip-name",
        default=None,
        help="ZIP 文件名（默认自动生成）",
    )
    parser.add_argument(
        "--include",
        nargs="+",
        default=["images", "documents"],
        help="要包含的子目录（默认 images documents）",
    )
    args = parser.parse_args()

    source = Path(args.source_dir).resolve()

    # 自动生成 ZIP 文件名
    zip_name = args.zip_name
    if not zip_name:
        parent_name = source.name if source.name != "." else "pat-product-research-assets"
        date_str = time.strftime("%Y%m%d")
        zip_name = f"产品研究素材_{parent_name}_{date_str}.zip"

    output_path = Path(args.output_dir) / zip_name

    print(f"📦 准备打包素材...")
    print(f"   源目录: {source}")
    print(f"   包含目录: {args.include}")
    print(f"   输出路径: {output_path}")
    print("-" * 50)

    result = create_zip(
        source_dir=str(source),
        output_path=str(output_path),
        include_dirs=args.include,
    )

    if result["success"]:
        print(f"\n✅ 打包成功!")
        print(f"   📁 文件: {result['zip_path']}")
        print(f"   📊 文件数: {result['file_count']} 个")
        print(f"   💾 源文件总计: {format_size(result['total_size'])}")
        print(f"   🗜️  ZIP 大小: {format_size(result['zip_size'])}")
        compression = (1 - result['zip_size'] / result['total_size']) * 100 if result['total_size'] > 0 else 0
        print(f"   📈 压缩率: {compression:.1f}%")

        print("\n📂 内容详情:")
        for cat, info in sorted(result["by_category"].items()):
            print(f"   {cat}/: {info['count']} 个文件 ({format_size(info['size'])})")

    else:
        print(f"\n❌ 打包失败: {result.get('reason', '未知错误')}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

"""Collect explicitly provided text materials for pat-synthesis.

This script is intentionally mechanical. It never searches default folders and
never decides what matters. It only expands user-provided paths, reads text
files, and emits line-aware chunks for later human/agent synthesis.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable


TEXT_EXTENSIONS = {
    ".md",
    ".markdown",
    ".mdown",
    ".mkd",
    ".txt",
    ".org",
    ".rst",
}


def iter_files(paths: Iterable[Path]) -> list[Path]:
    files: list[Path] = []
    for input_path in paths:
        path = input_path.expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Path does not exist: {input_path}")
        if path.is_file():
            if path.suffix.lower() in TEXT_EXTENSIONS:
                files.append(path)
            continue
        if path.is_dir():
            for child in path.rglob("*"):
                if child.is_file() and child.suffix.lower() in TEXT_EXTENSIONS:
                    files.append(child.resolve())
            continue
        raise ValueError(f"Unsupported path type: {input_path}")
    return sorted(dict.fromkeys(files))


def read_text(path: Path) -> str:
    encodings = ["utf-8-sig", "utf-8", "gb18030", "utf-16"]
    last_error: Exception | None = None
    for encoding in encodings:
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    raise UnicodeDecodeError(
        "unknown",
        b"",
        0,
        1,
        f"Could not decode {path}: {last_error}",
    )


def title_guess(lines: list[str]) -> str:
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.lower().startswith("#+title:"):
            return stripped.split(":", 1)[1].strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
        if stripped.startswith("*"):
            return stripped.lstrip("*").strip()
        return stripped[:120]
    return ""


def paragraph_chunks(lines: list[str], max_chars: int) -> list[dict[str, object]]:
    chunks: list[dict[str, object]] = []
    start_line: int | None = None
    buffer: list[str] = []

    def flush(end_line: int) -> None:
        nonlocal start_line, buffer
        text = "\n".join(buffer).strip()
        if text:
            chunks.append(
                {
                    "line_start": start_line,
                    "line_end": end_line,
                    "text": text[:max_chars],
                    "truncated": len(text) > max_chars,
                }
            )
        start_line = None
        buffer = []

    for index, line in enumerate(lines, start=1):
        if line.strip():
            if start_line is None:
                start_line = index
            buffer.append(line)
        elif buffer:
            flush(index - 1)
    if buffer:
        flush(len(lines))
    return chunks


def collect(paths: list[str], max_chunk_chars: int) -> dict[str, object]:
    input_paths = [Path(item) for item in paths]
    files = iter_files(input_paths)
    materials = []
    for file_path in files:
        text = read_text(file_path)
        lines = text.splitlines()
        materials.append(
            {
                "path": str(file_path),
                "name": file_path.name,
                "extension": file_path.suffix.lower(),
                "line_count": len(lines),
                "char_count": len(text),
                "title_guess": title_guess(lines),
                "chunks": paragraph_chunks(lines, max_chunk_chars),
            }
        )
    return {
        "input_paths": [str(Path(item).expanduser().resolve()) for item in paths],
        "file_count": len(materials),
        "materials": materials,
    }


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Collect only explicitly provided text files/directories for pat-synthesis."
    )
    parser.add_argument("paths", nargs="+", help="Explicit files or directories to read.")
    parser.add_argument(
        "--max-chunk-chars",
        type=int,
        default=1200,
        help="Maximum characters to include per paragraph chunk.",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")
    args = parser.parse_args()

    result = collect(args.paths, args.max_chunk_chars)
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))


if __name__ == "__main__":
    main()

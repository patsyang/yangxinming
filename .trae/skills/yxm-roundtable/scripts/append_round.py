#!/usr/bin/env python3
"""Append one pat-roundtable round before the global knowledge section."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


KNOWLEDGE_HEADING = "# 知识网络（全局）"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def latest_round(text: str) -> int:
    nums = [int(m.group(1)) for m in re.finditer(r"(?m)^## 第 (\d+) 轮.*$", text)]
    return nums[-1] if nums else 0


def update_frontmatter_status(text: str, status: str) -> str:
    match = re.match(r"\A---\r?\n(.*?)\r?\n---\r?\n", text, re.S)
    if not match:
        raise ValueError("frontmatter is missing")

    body = match.group(1)
    if re.search(r"(?m)^status:\s*.*$", body):
        body = re.sub(r"(?m)^status:\s*.*$", f'status: "{status}"', body)
    else:
        body = body.rstrip() + f'\nstatus: "{status}"'

    return "---\n" + body + "\n---\n" + text[match.end() :]


def append_round(markdown_path: Path, round_number: int, round_text: str) -> str:
    text = read_text(markdown_path)

    if "ROUND_TABLE_STATE" in text:
        raise ValueError("ROUND_TABLE_STATE must be removed from Markdown before appending")

    marker_matches = list(re.finditer(r"(?m)^" + re.escape(KNOWLEDGE_HEADING) + r"\s*$", text))
    if len(marker_matches) != 1:
        raise ValueError(f"{KNOWLEDGE_HEADING} must exist exactly once")

    if re.search(rf"(?m)^## 第 {round_number} 轮", text):
        raise ValueError(f"round {round_number} already exists")

    previous = latest_round(text)
    if round_number != previous + 1:
        raise ValueError(f"round {round_number} is not next after existing round {previous}")

    if not re.search(rf"(?m)^## 第 {round_number} 轮", round_text):
        raise ValueError(f"round content must contain heading for round {round_number}")

    marker_start = marker_matches[0].start()
    before = text[:marker_start].rstrip()
    after = text[marker_start:].lstrip()
    return before + "\n\n" + round_text.strip() + "\n\n" + after


def write_state(
    state_path: Path,
    markdown_path: Path,
    round_number: int,
    status: str,
    participants: list[str] | None,
    last_question: str | None,
    current_dispute: str | None,
) -> None:
    state = {}
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8-sig"))

    state["round"] = round_number
    state["status"] = status
    state["markdown_path"] = str(markdown_path.resolve())
    if participants is not None:
        state["participants"] = participants
    if last_question is not None:
        state["last_question"] = last_question
    if current_dispute is not None:
        state["current_dispute"] = current_dispute

    state_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def run_validator(markdown_path: Path, state_path: Path) -> None:
    script = Path(__file__).with_name("validate_roundtable.py")
    result = subprocess.run(
        [sys.executable, str(script), str(markdown_path), "--state", str(state_path)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        output = (result.stdout + result.stderr).strip()
        raise ValueError(output or "roundtable validation failed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True, type=Path, help="Roundtable Markdown file")
    parser.add_argument("--round", required=True, type=int, help="Round number to append")
    parser.add_argument("--content", required=True, type=Path, help="Markdown file containing one round")
    parser.add_argument("--state", type=Path, help="Sidecar state JSON file")
    parser.add_argument("--status", default="draft", choices=["draft", "complete"])
    parser.add_argument("--participant", action="append", dest="participants")
    parser.add_argument("--last-question")
    parser.add_argument("--current-dispute")
    args = parser.parse_args()

    state_path = args.state or args.file.with_suffix(".state.json")

    try:
        round_text = read_text(args.content)
        new_text = append_round(args.file, args.round, round_text)
        new_text = update_frontmatter_status(new_text, args.status)
        write_text(args.file, new_text)
        write_state(
            state_path,
            args.file,
            args.round,
            args.status,
            args.participants,
            args.last_question,
            args.current_dispute,
        )
        run_validator(args.file, state_path)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

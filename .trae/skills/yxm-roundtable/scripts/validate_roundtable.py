#!/usr/bin/env python3
"""Validate a pat-roundtable Markdown artifact."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


REQUIRED_HEADINGS = [
    "# 议题与参会者",
    "# 开场：定义",
    "# 各轮讨论记录",
    "# 知识网络（全局）",
    "# 开放问题",
]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def parse_frontmatter(text: str) -> tuple[str | None, dict[str, str]]:
    match = re.match(r"\A---\r?\n(.*?)\r?\n---\r?\n", text, re.S)
    if not match:
        return None, {}

    body = match.group(1)
    values: dict[str, str] = {}
    for line in body.splitlines():
        kv = re.match(r"^([A-Za-z0-9_-]+):\s*(.*?)\s*$", line)
        if not kv:
            continue
        key = kv.group(1)
        value = kv.group(2).strip()
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        values[key] = value
    return body, values


def find_heading(text: str, heading: str) -> list[int]:
    pattern = r"(?m)^" + re.escape(heading) + r"\s*$"
    return [m.start() for m in re.finditer(pattern, text)]


def derive_state_path(markdown_path: Path) -> Path:
    return markdown_path.with_suffix(".state.json")


def validate(markdown_path: Path, state_path: Path | None = None) -> list[str]:
    errors: list[str] = []

    if not markdown_path.exists():
        return [f"Markdown file not found: {markdown_path}"]

    text = read_text(markdown_path)
    _, frontmatter = parse_frontmatter(text)
    if not frontmatter:
        errors.append("frontmatter is missing or invalid")
    else:
        status = frontmatter.get("status")
        if status not in {"draft", "complete"}:
            errors.append("frontmatter status must be draft or complete")

    if "ROUND_TABLE_STATE" in text:
        errors.append("ROUND_TABLE_STATE must not appear in Markdown body")

    heading_positions: dict[str, int] = {}
    for heading in REQUIRED_HEADINGS:
        positions = find_heading(text, heading)
        if len(positions) == 0:
            errors.append(f"required heading missing: {heading}")
            continue
        if len(positions) > 1:
            errors.append(f"required heading appears more than once: {heading}")
        heading_positions[heading] = positions[0]

    if len(heading_positions) == len(REQUIRED_HEADINGS):
        ordered_positions = [heading_positions[h] for h in REQUIRED_HEADINGS]
        if ordered_positions != sorted(ordered_positions):
            errors.append("required top-level headings are out of order")

    knowledge_pos = heading_positions.get("# 知识网络（全局）")
    open_pos = heading_positions.get("# 开放问题")
    if knowledge_pos is not None and open_pos is not None and knowledge_pos > open_pos:
        errors.append("# 知识网络（全局） must appear before # 开放问题")

    round_matches = list(re.finditer(r"(?m)^## 第 (\d+) 轮.*$", text))
    round_nums = [int(m.group(1)) for m in round_matches]
    if round_nums:
        expected = list(range(1, max(round_nums) + 1))
        if round_nums != expected:
            errors.append(
                "round headings must be continuous and ordered: "
                + f"found {round_nums}, expected {expected}"
            )
        if knowledge_pos is not None:
            late_rounds = [int(m.group(1)) for m in round_matches if m.start() > knowledge_pos]
            if late_rounds:
                errors.append(
                    "all round sections must appear before # 知识网络（全局）: "
                    + f"late rounds {late_rounds}"
                )
    latest_round = round_nums[-1] if round_nums else 0

    if state_path is not None:
        if not state_path.exists():
            errors.append(f"state file not found: {state_path}")
        else:
            try:
                state = json.loads(state_path.read_text(encoding="utf-8-sig"))
            except json.JSONDecodeError as exc:
                errors.append(f"state file is not valid JSON: {exc}")
            else:
                state_round = state.get("round")
                if state_round != latest_round:
                    errors.append(
                        f"state round {state_round!r} does not match latest round {latest_round}"
                    )
                state_status = state.get("status")
                fm_status = frontmatter.get("status")
                if state_status not in {"draft", "complete"}:
                    errors.append("state status must be draft or complete")
                if fm_status and state_status and state_status != fm_status:
                    errors.append(
                        f"state status {state_status!r} does not match frontmatter status {fm_status!r}"
                    )

                markdown_ref = state.get("markdown_path")
                if markdown_ref:
                    ref_path = Path(markdown_ref)
                    try:
                        same_file = ref_path.resolve() == markdown_path.resolve()
                    except OSError:
                        same_file = False
                    if not same_file:
                        errors.append("state markdown_path does not point to the validated file")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("markdown", type=Path, help="Roundtable Markdown file")
    parser.add_argument("--state", type=Path, help="Sidecar state JSON file")
    parser.add_argument(
        "--require-state",
        action="store_true",
        help="Require the derived .state.json file when --state is omitted",
    )
    args = parser.parse_args()

    state_path = args.state
    if state_path is None and args.require_state:
        state_path = derive_state_path(args.markdown)

    errors = validate(args.markdown, state_path)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

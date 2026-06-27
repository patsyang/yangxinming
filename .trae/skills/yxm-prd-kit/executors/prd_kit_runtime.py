#!/usr/bin/env python3
"""Deterministic runtime for the repo-local prd-kit skill.

The runtime validates and updates markdown process artifacts. It intentionally
does not perform open-ended natural-language understanding or PRD authoring.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


REPO_ROOT = Path(__file__).resolve().parents[4]
PASS_HANDLED = {"是", "true", "yes", "pass", "passed", "closed", "completed", "已处理", "已关闭", "完成"}
CLOSED_STATUSES = {
    "answered",
    "resolved",
    "resolved_by_assumption",
    "waived",
    "superseded",
    "rejected",
    "converted_to_requirement",
    "closed",
    "completed",
    "done",
    "已回答",
    "已处理",
    "已关闭",
    "关闭",
    "完成",
}
OPEN_STATUSES = {"open", "todo", "pending", "未处理", "待处理", "未关闭", "打开"}
HIGH_SEVERITIES = {"high", "critical", "高", "严重", "致命", "高危"}
EMPTY_VALUES = {"", "-", "无", "none", "n/a", "na", "null"}
ADAPTER_REVIEW_SECTION = "Adapter Review Ledger"
ADAPTER_WAIVER_SECTION = "Adapter Waiver Ledger"
REREAD_SECTION = "真实重读记录"
W9_COVERAGE_SECTION = "W9 章节语义质疑覆盖记录"
CONFIG_SECTION = "PRD Kit Configuration"
EFFECTIVE_CHALLENGE_SECTION = "Effective Challenge Ledger"
USER_MODEL_SECTION = "用户模型账本"
BUSINESS_SCENARIO_SECTION = "关键业务流程账本"
REPAIR_LOOP_SECTION = "Repair Loop Ledger"
STAGE_REVALIDATION_SECTION = "Stage Revalidation Ledger"
DOMAIN_LANGUAGE_SECTION = "领域语言账本"
CONCEPT_ALIGNMENT_SECTION = "概念对齐检查点"
DEFAULT_TARGET_TOTAL = 200
DEFAULT_QUALITY_SCORE_MIN = 3
DEFAULT_CONCEPT_ALIGNMENT_ENFORCEMENT = "strict"
TRUE_VALUES = {"true", "yes", "是", "1", "accepted", "已接受", "确认", "confirmed"}
ANSWERED_STATUSES = {"answered", "confirmed", "已回答", "已确认"}
ENGINEERING_PRD_TEMPLATE = ".trae/skills/yxm-prd-kit/references/engineering-prd-template.md"
ENGINEERING_PRD_FILENAME_PATTERN = "*-研发版PRD-YYYYMMDD-HHmmss.md"
ENGINEERING_PRD_FILENAME_RE = re.compile(r"^.+-研发版PRD-\d{8}-\d{6}\.md$")
ENGINEERING_PRD_REQUIRED_SECTIONS = [
    "文档信息",
    "交付目标",
    "非目标",
    "实现优先级与完成定义",
    "角色与权限",
    "命名与文案真源",
    "领域规则",
    "可执行业务流程",
    "页面与交互",
    "状态机",
    "核心数据模型",
    "验收标准",
    "实现约束",
    "开发切片顺序",
]
UNRESOLVED_FACT_SECTIONS = ["未决问题", "实现待确认"]
ADAPTER_REVIEW_FIELDS = [
    "issue_id",
    "stage",
    "source_adapter",
    "adapter_mode",
    "trigger",
    "severity",
    "status",
    "blocking_stage",
    "conclusion",
    "target_ledger",
    "waiver_id",
    "evidence_provenance",
    "updated_at",
]
ADAPTER_WAIVER_FIELDS = [
    "waiver_id",
    "stage_or_section",
    "waived_item",
    "user_quote",
    "risk",
    "expiry_condition",
    "updated_at",
]
VALID_ADAPTER_MODES = {"lens", "handoff", "evidence", "mechanism_borrowed"}
VALID_ADAPTER_STATUSES = {"open", "resolved", "waived", "superseded"}
VALID_ADAPTER_SEVERITIES = {"low", "medium", "high", "critical"}
EFFECTIVE_CHALLENGE_FIELDS = [
    "challenge_id",
    "stage",
    "perspective",
    "category",
    "question",
    "why_matters",
    "affected_section",
    "answer_summary",
    "answer_status",
    "acceptance_type",
    "user_acceptance_ref",
    "invalidation_reason",
    "quality_score",
    "backfill_location",
    "asked_at",
    "answered_at",
]
REPAIR_LOOP_FIELDS = [
    "issue_id",
    "found_stage",
    "root_stage",
    "root_cause_type",
    "affected_stages",
    "severity",
    "repair_question_id",
    "user_acceptance",
    "repair_status",
    "current_repair_stage",
    "rerun_policy",
    "root_stage_revalidated_at",
    "status",
]
STAGE_REVALIDATION_FIELDS = [
    "repair_issue_id",
    "stage",
    "new_challenge_count_after_reopen",
    "exit_criteria_status",
    "exit_evidence",
    "next_stage",
]
DOMAIN_LANGUAGE_FIELDS = [
    "term_id",
    "阶段",
    "标准术语",
    "定义",
    "避免用词",
    "概念类型",
    "所属对象/流程",
    "影响章节",
    "用户确认",
    "user_turn_ref",
    "回灌位置",
    "状态",
]
CONCEPT_ALIGNMENT_FIELDS = [
    "stage",
    "新增概念",
    "变更概念",
    "冲突概念",
    "最高风险概念",
    "对齐问题ID",
    "user_turn_ref",
    "exit_status",
    "blocker",
]
CONCEPT_ALIGNMENT_REQUIRED_STAGES = [
    "W1_value_alignment",
    "W2_scenario_roles",
    "W3_function_architecture",
    "W4_pages_and_flows",
    "W5_object_state_audit",
    "W6_requirement_acceptance",
    "W9_formal_prd_output",
    "W10_plan_ceo_review",
]
CONCEPT_ALIGNMENT_PROACTIVE_STAGES = {
    "W1_value_alignment",
    "W2_scenario_roles",
    "W3_function_architecture",
    "W4_pages_and_flows",
    "W5_object_state_audit",
    "W6_requirement_acceptance",
}
CONCEPT_HIGH_IMPACT_TYPES = {
    "object",
    "state",
    "action",
    "permission",
    "business_flow",
    "acceptance",
    "对象",
    "状态",
    "动作",
    "权限",
    "业务流程",
    "验收",
}
CONCEPT_CONFIRMED_VALUES = {"confirmed", "answer", "accept", "已确认", "用户确认"}
CONCEPT_ASSUMED_VALUES = {"assumed", "假设", "低风险假设"}
CONCEPT_REJECTED_VALUES = {"rejected", "deprecated", "superseded", "否定", "废弃", "已废弃"}
CONCEPT_OPEN_VALUES = {"open", "conflict", "待确认", "冲突"}
CONCEPT_EXIT_PASSED = {"pass", "passed", "closed", "completed", "confirmed", "通过", "已通过", "完成"}
USER_MODEL_REQUIRED_FIELDS = [
    "用户定义",
    "所属组织/租户",
    "使用入口",
    "业务目标",
    "能看到什么",
    "能创建什么",
    "能修改什么",
    "能删除/终止什么",
    "能执行的关键动作",
    "明确不能做什么",
    "与其他用户的关系",
    "数据边界",
    "审计/留痕字段",
    "涉及的关键业务流程",
]
BUSINESS_FLOW_REQUIRED_FIELDS = [
    "业务目标",
    "参与用户",
    "用户关系",
    "触发条件",
    "关键业务判断",
    "业务结果",
    "失败/中止后果",
    "涉及对象与状态",
    "数据/证据来源",
    "验收映射",
]
BASELINE_STAGE_DISTRIBUTION = {
    "W1_value_alignment": 6,
    "W2_scenario_roles": 6,
    "W3_function_architecture": 8,
    "W4_pages_and_flows": 8,
    "W5_object_state_audit": 8,
    "W6_requirement_acceptance": 8,
    "W7_prd_gate": 4,
    "W9_formal_prd_output": 2,
}
BASELINE_PERSPECTIVE_DISTRIBUTION = {
    "客户一线使用者": 8,
    "客户安全/合规/管理者": 8,
    "产品经理": 8,
    "CTO/架构负责人": 6,
    "研发实现者": 6,
    "QA/测试": 6,
    "CEO/商业负责人": 6,
    "交付/客户成功": 2,
}
VALID_REPAIR_STATUSES = {
    "open",
    "root_stage_identified",
    "waiting_user",
    "accepted_by_user",
    "repair_applied",
    "root_stage_reopened",
    "root_stage_revalidated",
    "closed",
    "invalidated",
}
VALID_USER_ACCEPTANCE = {"answered", "confirmed", "waived", "rejected", "已回答", "已确认", "豁免", "拒绝"}
VALID_CHALLENGE_ACCEPTANCE_TYPES = {"answer", "accept", "repair"}
COUNTED_CHALLENGE_ACCEPTANCE_TYPES = {"answer", "accept"}
REPAIR_CLOSED_STATUSES = {"closed", "invalidated"}


class RuntimeErrorWithResult(Exception):
    def __init__(self, result: dict[str, Any]) -> None:
        super().__init__(result.get("message", "runtime error"))
        self.result = result


@dataclass
class Lock:
    path: Path
    stale_seconds: int
    warnings: list[str]
    acquired: bool = False

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        now = time.time()
        if self.path.exists():
            age = now - self.path.stat().st_mtime
            if age > self.stale_seconds:
                self.path.unlink()
                self.warnings.append(f"removed stale lock: {self.path}")
            else:
                raise RuntimeErrorWithResult(
                    {
                        "ok": False,
                        "blocked": True,
                        "blocking_reasons": [f"process file is locked: {self.path}"],
                        "warnings": self.warnings,
                    }
                )
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        fd = os.open(str(self.path), flags)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            payload = {
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "pid": os.getpid(),
                "purpose": "prd-kit process-file write lock",
            }
            json.dump(payload, handle, ensure_ascii=False)
        self.acquired = True

    def release(self) -> None:
        if self.acquired and self.path.exists():
            self.path.unlink()
        self.acquired = False


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def emit(result: dict[str, Any], out: str | None) -> None:
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if out:
        write_text(Path(out), text + "\n")
    print(text)


def indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def gather_list_after_key(lines: list[str], key: str) -> list[str]:
    values: list[str] = []
    key_index = -1
    key_indent = 0
    for i, line in enumerate(lines):
        if line.strip() == f"{key}:":
            key_index = i
            key_indent = indent_of(line)
            break
    if key_index == -1:
        return values
    for line in lines[key_index + 1 :]:
        stripped = line.strip()
        if not stripped:
            continue
        current_indent = indent_of(line)
        if current_indent <= key_indent and not stripped.startswith("- "):
            break
        if stripped.startswith("- "):
            values.append(stripped[2:].strip())
    return values


def parse_wf(path: Path) -> dict[str, Any]:
    text = read_text(path)
    lines = text.splitlines()
    stage_order = gather_list_after_key(lines, "stage_order")
    required_sections = gather_list_after_key(lines, "required_sections")
    adapter_review_fields = gather_list_after_key(lines, "adapter_review_ledger_fields")
    adapter_waiver_fields = gather_list_after_key(lines, "adapter_waiver_ledger_fields")
    adapter_sources = sorted(set(re.findall(r"(?m)^\s*-\s+source_adapter:\s*([^\n#]+)", text)))
    forbidden_content = gather_list_after_key(lines, "forbidden_content")
    forbidden_content.extend(
        [
            "generation_manifest",
            "quality_gate_report",
            "artifact_stage",
            "blocking_gaps",
            "challenge_ledger",
            "Effective Challenge Ledger",
            "Challenge Quota Summary",
            "Repair Loop Ledger",
            "Adapter Review Ledger",
            "root_stage",
            "repair_applied",
            "counts_toward_quota",
            "assumption_ledger",
            "conflict_ledger",
            "未闭合阻断项",
            "过程判断",
        ]
    )
    return {
        "wf": str(path),
        "stage_order": stage_order,
        "required_sections": required_sections,
        "review_adapter_contract_present": "review_adapter_contract:" in text,
        "concept_alignment_contract_present": "concept_alignment_contract:" in text,
        "adapter_sources": adapter_sources,
        "adapter_review_ledger_fields": adapter_review_fields,
        "adapter_waiver_ledger_fields": adapter_waiver_fields,
        "domain_language_ledger_fields": DOMAIN_LANGUAGE_FIELDS,
        "concept_alignment_checkpoint_fields": CONCEPT_ALIGNMENT_FIELDS,
        "concept_alignment_required_stages": CONCEPT_ALIGNMENT_REQUIRED_STAGES,
        "challenge_quota_default_target_total": DEFAULT_TARGET_TOTAL,
        "effective_challenge_ledger_fields": EFFECTIVE_CHALLENGE_FIELDS,
        "baseline_stage_distribution": BASELINE_STAGE_DISTRIBUTION,
        "baseline_perspective_distribution": BASELINE_PERSPECTIVE_DISTRIBUTION,
        "repair_loop_ledger_fields": REPAIR_LOOP_FIELDS,
        "stage_revalidation_ledger_fields": STAGE_REVALIDATION_FIELDS,
        "forbidden_content": sorted(set(forbidden_content)),
        "engineering_prd_template": ENGINEERING_PRD_TEMPLATE,
        "required_engineering_prd_sections": ENGINEERING_PRD_REQUIRED_SECTIONS,
        "engineering_prd_filename_pattern": ENGINEERING_PRD_FILENAME_PATTERN,
    }


def next_stage_for(stage_order: list[str], current_stage: str) -> str:
    if current_stage not in stage_order:
        return ""
    index = stage_order.index(current_stage)
    if index + 1 >= len(stage_order):
        return ""
    return stage_order[index + 1]


def section_bounds(markdown: str, title: str) -> tuple[int, int] | None:
    pattern = re.compile(rf"(?m)^##\s+{re.escape(title)}\s*$")
    match = pattern.search(markdown)
    if not match:
        return None
    next_match = re.search(r"(?m)^##\s+", markdown[match.end() :])
    end = len(markdown) if not next_match else match.end() + next_match.start()
    return match.start(), end


def section_text(markdown: str, title: str) -> str:
    bounds = section_bounds(markdown, title)
    if not bounds:
        return ""
    return markdown[bounds[0] : bounds[1]]


def parse_markdown_table(section: str) -> tuple[list[str], list[dict[str, str]]]:
    lines = [line.strip() for line in section.splitlines() if line.strip().startswith("|")]
    if len(lines) < 2:
        return [], []
    header = [cell.strip() for cell in lines[0].strip("|").split("|")]
    rows: list[dict[str, str]] = []
    for line in lines[2:]:
        if re.fullmatch(r"\|?[\s:\-|]+\|?", line):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < len(header):
            cells.extend([""] * (len(header) - len(cells)))
        rows.append({header[i]: cells[i] for i in range(len(header))})
    return header, rows


def parse_workflow_state(markdown: str) -> dict[str, str]:
    section = section_text(markdown, "Workflow State")
    header, rows = parse_markdown_table(section)
    if header and rows:
        return rows[0]
    result: dict[str, str] = {}
    for key in ["current_stage", "artifact_stage", "gate", "next_stage", "stage_exit_criteria_status", "updated_at"]:
        match = re.search(rf"{key}\s*[=:]\s*([^\n|]+)", markdown)
        if match:
            result[key] = match.group(1).strip()
    return result


def replace_or_insert_section(markdown: str, title: str, body: str, after_title: str | None = None) -> str:
    new_section = f"## {title}\n{body.strip()}\n\n"
    bounds = section_bounds(markdown, title)
    if bounds:
        return markdown[: bounds[0]] + new_section + markdown[bounds[1] :].lstrip("\n")
    if after_title:
        after_bounds = section_bounds(markdown, after_title)
        if after_bounds:
            return markdown[: after_bounds[1]].rstrip() + "\n\n" + new_section + markdown[after_bounds[1] :].lstrip("\n")
    return markdown.rstrip() + "\n\n" + new_section


def workflow_state_table(state: dict[str, str]) -> str:
    keys = ["current_stage", "artifact_stage", "gate", "next_stage", "stage_exit_criteria_status", "updated_at"]
    header = "| " + " | ".join(keys) + " |"
    sep = "| " + " | ".join(["---"] * len(keys)) + " |"
    row = "| " + " | ".join(state.get(key, "") for key in keys) + " |"
    return "\n".join([header, sep, row])


def append_stage_ledger(markdown: str, row: dict[str, str]) -> str:
    title = "Stage Ledger"
    section = section_text(markdown, title)
    fields = ["stage", "entered_at", "exit_status", "exit_evidence", "next_stage"]
    row_line = "| " + " | ".join(row.get(field, "") for field in fields) + " |"
    if not section:
        body = "\n".join(
            [
                "| " + " | ".join(fields) + " |",
                "| " + " | ".join(["---"] * len(fields)) + " |",
                row_line,
            ]
        )
        return replace_or_insert_section(markdown, title, body, after_title="Workflow State")
    if "|" not in section:
        body = "\n".join(
            [
                "| " + " | ".join(fields) + " |",
                "| " + " | ".join(["---"] * len(fields)) + " |",
                row_line,
            ]
        )
        return replace_or_insert_section(markdown, title, body, after_title="Workflow State")
    bounds = section_bounds(markdown, title)
    assert bounds is not None
    updated_section = section.rstrip() + "\n" + row_line + "\n\n"
    return markdown[: bounds[0]] + updated_section + markdown[bounds[1] :].lstrip("\n")


def normalize(value: str) -> str:
    return value.strip().lower()


def row_value(row: dict[str, str], names: list[str]) -> str:
    lowered = {normalize(key): value for key, value in row.items()}
    for name in names:
        if name in row:
            return row[name]
        value = lowered.get(normalize(name))
        if value is not None:
            return value
    return ""


def nonempty(value: str) -> bool:
    return normalize(value) not in EMPTY_VALUES


def stage_index(stage_order: list[str], stage: str) -> int:
    return stage_order.index(stage) if stage in stage_order else -1


def missing_table_fields(header: list[str], required: list[str]) -> list[str]:
    normalized_header = {normalize(item) for item in header}
    return [field for field in required if normalize(field) not in normalized_header]


def stage_reached(stage_order: list[str], current_stage: str, blocking_stage: str) -> bool:
    current_index = stage_index(stage_order, current_stage)
    blocking_index = stage_index(stage_order, blocking_stage)
    if current_index < 0 or blocking_index < 0:
        return True
    return current_index >= blocking_index


def unresolved_high_challenges(markdown: str) -> list[dict[str, str]]:
    _, rows = parse_markdown_table(section_text(markdown, "质疑账本"))
    unresolved: list[dict[str, str]] = []
    for row in rows:
        severity = normalize(row_value(row, ["严重级别", "severity"]))
        status = normalize(row_value(row, ["状态", "status"]))
        if severity in {normalize(item) for item in HIGH_SEVERITIES}:
            if not status or status in {normalize(item) for item in OPEN_STATUSES} or status not in {normalize(item) for item in CLOSED_STATUSES}:
                unresolved.append(row)
    return unresolved


def open_conflicts(markdown: str) -> list[dict[str, str]]:
    _, rows = parse_markdown_table(section_text(markdown, "冲突账本"))
    conflicts: list[dict[str, str]] = []
    for row in rows:
        status = normalize(row_value(row, ["状态", "status"]))
        content = " ".join(row.values()).strip()
        if not content:
            continue
        if status and status in {normalize(item) for item in CLOSED_STATUSES}:
            continue
        conflicts.append(row)
    return conflicts


def adapter_waiver_status(markdown: str) -> dict[str, Any]:
    section = section_text(markdown, ADAPTER_WAIVER_SECTION)
    if not section:
        return {
            "present": False,
            "passed": True,
            "waiver_ids": set(),
            "blocking_reasons": [],
            "row_count": 0,
        }
    header, rows = parse_markdown_table(section)
    blockers: list[str] = []
    if not header:
        blockers.append("Adapter Waiver Ledger has no markdown table")
    else:
        missing = missing_table_fields(header, ADAPTER_WAIVER_FIELDS)
        if missing:
            blockers.append(f"Adapter Waiver Ledger missing fields: {', '.join(missing)}")
    waiver_ids: set[str] = set()
    for index, row in enumerate(rows, start=1):
        waiver_id = row_value(row, ["waiver_id"])
        if not nonempty(waiver_id):
            blockers.append(f"Adapter Waiver Ledger row {index} missing waiver_id")
            continue
        waiver_ids.add(waiver_id)
    return {
        "present": True,
        "passed": not blockers,
        "waiver_ids": waiver_ids,
        "blocking_reasons": blockers,
        "row_count": len(rows),
    }


def adapter_review_status(markdown: str, stage_order: list[str], current_stage: str) -> dict[str, Any]:
    section = section_text(markdown, ADAPTER_REVIEW_SECTION)
    if not section:
        return {
            "present": False,
            "passed": True,
            "row_count": 0,
            "open_blocking_count": 0,
            "blocking_reasons": [],
            "open_blocking_rows": [],
        }
    header, rows = parse_markdown_table(section)
    blockers: list[str] = []
    if not header:
        blockers.append("Adapter Review Ledger has no markdown table")
    else:
        missing = missing_table_fields(header, ADAPTER_REVIEW_FIELDS)
        if missing:
            blockers.append(f"Adapter Review Ledger missing fields: {', '.join(missing)}")
    waiver_status = adapter_waiver_status(markdown)
    valid_waiver_ids = waiver_status["waiver_ids"]
    blockers.extend(waiver_status["blocking_reasons"])
    open_blocking_rows: list[dict[str, str]] = []
    required_nonempty = [
        "issue_id",
        "stage",
        "source_adapter",
        "adapter_mode",
        "trigger",
        "severity",
        "status",
        "blocking_stage",
        "conclusion",
        "target_ledger",
        "updated_at",
    ]
    for index, row in enumerate(rows, start=1):
        if not " ".join(row.values()).strip():
            continue
        for field in required_nonempty:
            if not nonempty(row_value(row, [field])):
                blockers.append(f"Adapter Review Ledger row {index} missing {field}")
        issue_id = row_value(row, ["issue_id"]) or f"row {index}"
        stage = row_value(row, ["stage"])
        blocking_stage = row_value(row, ["blocking_stage"])
        mode = normalize(row_value(row, ["adapter_mode"]))
        severity = normalize(row_value(row, ["severity"]))
        status = normalize(row_value(row, ["status"]))
        if stage and stage not in stage_order:
            blockers.append(f"{issue_id} has unknown stage: {stage}")
        if blocking_stage and blocking_stage not in stage_order:
            blockers.append(f"{issue_id} has unknown blocking_stage: {blocking_stage}")
        if mode and mode not in VALID_ADAPTER_MODES:
            blockers.append(f"{issue_id} has invalid adapter_mode: {mode}")
        if severity and severity not in VALID_ADAPTER_SEVERITIES:
            blockers.append(f"{issue_id} has invalid severity: {severity}")
        if status and status not in VALID_ADAPTER_STATUSES:
            blockers.append(f"{issue_id} has invalid status: {status}")
        waiver_id = row_value(row, ["waiver_id"])
        if status == "waived":
            if not nonempty(waiver_id):
                blockers.append(f"{issue_id} status=waived requires waiver_id")
            elif waiver_id not in valid_waiver_ids:
                blockers.append(f"{issue_id} references missing waiver_id: {waiver_id}")
        if mode == "evidence" and not nonempty(row_value(row, ["evidence_provenance"])):
            blockers.append(f"{issue_id} evidence adapter missing evidence_provenance")
        if severity in {"high", "critical"} and status == "open" and stage_reached(stage_order, current_stage, blocking_stage):
            open_blocking_rows.append(row)
    if open_blocking_rows:
        blockers.append(f"open high/critical adapter blocking issues: {len(open_blocking_rows)}")
    return {
        "present": True,
        "passed": not blockers,
        "row_count": len(rows),
        "open_blocking_count": len(open_blocking_rows),
        "blocking_reasons": blockers,
        "open_blocking_rows": open_blocking_rows,
    }


def table_rows_by_section(rows: list[dict[str, str]], section_name: str) -> list[dict[str, str]]:
    matches: list[dict[str, str]] = []
    for row in rows:
        value = row_value(row, ["章节", "section"]).strip()
        if value == section_name:
            matches.append(row)
    return matches


def reread_artifact_key(value: str) -> str:
    text = normalize(value)
    if "process" in text or "过程" in text:
        return "process_file"
    if "formal" in text or "prd" in text or "正式" in text:
        return "formal_prd"
    return text


def row_status_passed(row: dict[str, str]) -> bool:
    status = normalize(row_value(row, ["status", "状态", "已处理", "handled"]))
    return status in {normalize(item) for item in PASS_HANDLED | CLOSED_STATUSES}


def parse_int(value: str, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def parse_bool(value: str) -> bool:
    return normalize(value) in TRUE_VALUES


def parse_config(markdown: str) -> dict[str, str]:
    _, rows = parse_markdown_table(section_text(markdown, CONFIG_SECTION))
    config: dict[str, str] = {}
    for row in rows:
        key = row_value(row, ["key"])
        value = row_value(row, ["value"])
        if key:
            config[key] = value
    return config


def quota_config(markdown: str) -> dict[str, Any]:
    config = parse_config(markdown)
    target_total = parse_int(config.get("challenge_quota.target_total", ""), DEFAULT_TARGET_TOTAL)
    quality_score_min = parse_int(config.get("challenge_quota.quality_score_min", ""), DEFAULT_QUALITY_SCORE_MIN)
    return {
        "raw": config,
        "target_total": max(target_total, 0),
        "quality_score_min": max(quality_score_min, 0),
    }


def concept_alignment_enforcement(markdown: str) -> str:
    config = parse_config(markdown)
    value = normalize(config.get("concept_alignment.enforcement", DEFAULT_CONCEPT_ALIGNMENT_ENFORCEMENT))
    if value in {"migration_warning", "warning", "warn"}:
        return "migration_warning"
    return "strict"


def proportional_requirements(total: int, baseline: dict[str, int]) -> dict[str, int]:
    keys = list(baseline.keys())
    if total <= 0 or not keys:
        return {key: 0 for key in keys}
    ordered = sorted(keys, key=lambda key: baseline[key], reverse=True)
    if total < len(keys):
        return {key: 1 if key in set(ordered[:total]) else 0 for key in keys}
    requirements = {key: 1 for key in keys}
    remaining = total - len(keys)
    weight_sum = sum(baseline.values()) or 1
    raw = {key: baseline[key] / weight_sum * remaining for key in keys}
    for key in keys:
        requirements[key] += int(raw[key])
    leftover = total - sum(requirements.values())
    ranked = sorted(keys, key=lambda key: (raw[key] - int(raw[key]), baseline[key]), reverse=True)
    for key in ranked[:leftover]:
        requirements[key] += 1
    return requirements


def effective_challenge_status(markdown: str, stage_order: list[str], current_stage: str) -> dict[str, Any]:
    section = section_text(markdown, EFFECTIVE_CHALLENGE_SECTION)
    config = quota_config(markdown)
    stage_requirements = proportional_requirements(config["target_total"], BASELINE_STAGE_DISTRIBUTION)
    perspective_requirements = proportional_requirements(config["target_total"], BASELINE_PERSPECTIVE_DISTRIBUTION)
    result: dict[str, Any] = {
        "present": bool(section),
        "passed": True,
        "target_total": config["target_total"],
        "quality_score_min": config["quality_score_min"],
        "total_counted": 0,
        "invalidated_count": 0,
        "stage_counts": {},
        "perspective_counts": {},
        "stage_requirements": stage_requirements,
        "perspective_requirements": perspective_requirements,
        "blocking_reasons": [],
    }
    blockers: list[str] = []
    if not section:
        result["blocking_reasons"] = blockers
        result["passed"] = not blockers
        return result
    header, rows = parse_markdown_table(section)
    if not header:
        blockers.append("Effective Challenge Ledger has no markdown table")
    else:
        missing = missing_table_fields(header, EFFECTIVE_CHALLENGE_FIELDS)
        if missing:
            blockers.append(f"Effective Challenge Ledger missing fields: {', '.join(missing)}")
    stage_counts = {key: 0 for key in BASELINE_STAGE_DISTRIBUTION}
    perspective_counts = {key: 0 for key in BASELINE_PERSPECTIVE_DISTRIBUTION}
    counted = 0
    invalidated = 0
    for index, row in enumerate(rows, start=1):
        if not " ".join(row.values()).strip():
            continue
        challenge_id = row_value(row, ["challenge_id"]) or f"row {index}"
        stage = row_value(row, ["stage"])
        perspective = row_value(row, ["perspective"])
        answer_status = normalize(row_value(row, ["answer_status"]))
        acceptance_type = normalize(row_value(row, ["acceptance_type"]))
        user_acceptance_ref = row_value(row, ["user_acceptance_ref"])
        invalidation_reason = row_value(row, ["invalidation_reason"])
        score = parse_int(row_value(row, ["quality_score"]), -1)
        backfill = row_value(row, ["backfill_location"])
        counts = acceptance_type in COUNTED_CHALLENGE_ACCEPTANCE_TYPES and not nonempty(invalidation_reason)
        if stage and stage not in stage_order:
            blockers.append(f"{challenge_id} has unknown stage: {stage}")
        if nonempty(invalidation_reason):
            invalidated += 1
            if user_acceptance_ref:
                blockers.append(f"{challenge_id} is invalidated but has user_acceptance_ref")
        if acceptance_type:
            if acceptance_type not in VALID_CHALLENGE_ACCEPTANCE_TYPES:
                blockers.append(f"{challenge_id} has invalid acceptance_type")
        if counts:
            if answer_status not in ANSWERED_STATUSES:
                blockers.append(f"{challenge_id} counts toward quota without answered/confirmed status")
            if not nonempty(backfill):
                blockers.append(f"{challenge_id} counts toward quota without backfill_location")
            if score < config["quality_score_min"]:
                blockers.append(f"{challenge_id} quality_score below minimum")
            if not nonempty(row_value(row, ["why_matters"])):
                blockers.append(f"{challenge_id} missing why_matters")
            if not nonempty(row_value(row, ["affected_section"])):
                blockers.append(f"{challenge_id} missing affected_section")
            if all(
                [
                    answer_status in ANSWERED_STATUSES,
                    acceptance_type in COUNTED_CHALLENGE_ACCEPTANCE_TYPES,
                    not nonempty(invalidation_reason),
                    nonempty(backfill),
                    score >= config["quality_score_min"],
                ]
            ):
                counted += 1
                if stage in stage_counts:
                    stage_counts[stage] += 1
                if perspective in perspective_counts:
                    perspective_counts[perspective] += 1
                else:
                    blockers.append(f"{challenge_id} has unknown perspective: {perspective}")
    result["total_counted"] = counted
    result["invalidated_count"] = invalidated
    result["stage_counts"] = stage_counts
    result["perspective_counts"] = perspective_counts
    result["blocking_reasons"] = blockers
    result["passed"] = not blockers
    return result


def quota_blockers(
    markdown: str,
    stage_order: list[str],
    current_stage: str,
    check_stage: str,
    require_total: bool = False,
) -> list[str]:
    status = effective_challenge_status(markdown, stage_order, current_stage)
    blockers = list(status["blocking_reasons"])
    current_index = stage_index(stage_order, current_stage)
    for stage, required in status["stage_requirements"].items():
        if required <= 0:
            continue
        stage_idx = stage_index(stage_order, stage)
        if stage_idx >= 0 and current_index >= stage_idx:
            actual = status["stage_counts"].get(stage, 0)
            if actual < required:
                blockers.append(f"challenge quota missing for {stage}: required {required}, accepted {actual}")
    if require_total:
        if status["total_counted"] < status["target_total"]:
            blockers.append(
                f"challenge quota total not met: required {status['target_total']}, accepted {status['total_counted']}"
            )
        for perspective, required in status["perspective_requirements"].items():
            if required <= 0:
                continue
            actual = status["perspective_counts"].get(perspective, 0)
            if actual < required:
                blockers.append(f"perspective quota missing for {perspective}: required {required}, accepted {actual}")
    return blockers


def parse_structured_entries(section: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw_line in section.splitlines():
        line = raw_line.strip()
        if line.startswith("### "):
            if current:
                entries.append(current)
            current = {"title": line[4:].strip(), "fields": {}}
            continue
        if current and line.startswith("- "):
            item = line[2:].strip()
            if "：" in item:
                key, value = item.split("：", 1)
            elif ":" in item:
                key, value = item.split(":", 1)
            else:
                continue
            current["fields"][key.strip()] = value.strip()
    if current:
        entries.append(current)
    return entries


def structured_section_status(markdown: str, title: str, required_fields: list[str], min_entries: int = 1) -> dict[str, Any]:
    section = section_text(markdown, title)
    blockers: list[str] = []
    entries = parse_structured_entries(section) if section else []
    if not section:
        blockers.append(f"missing {title} section")
    elif len(entries) < min_entries:
        blockers.append(f"{title} has no structured entries")
    for entry in entries:
        fields = entry["fields"]
        missing = [field for field in required_fields if not nonempty(fields.get(field, ""))]
        if missing:
            blockers.append(f"{title} entry {entry['title']} missing fields: {', '.join(missing)}")
    return {
        "present": bool(section),
        "passed": not blockers,
        "entry_count": len(entries),
        "blocking_reasons": blockers,
    }


def user_model_status(markdown: str) -> dict[str, Any]:
    return structured_section_status(markdown, USER_MODEL_SECTION, USER_MODEL_REQUIRED_FIELDS)


def business_scenario_status(markdown: str) -> dict[str, Any]:
    return structured_section_status(markdown, BUSINESS_SCENARIO_SECTION, BUSINESS_FLOW_REQUIRED_FIELDS)


def table_status(markdown: str, title: str, required_fields: list[str]) -> dict[str, Any]:
    section = section_text(markdown, title)
    blockers: list[str] = []
    if not section:
        blockers.append(f"missing {title} section")
        return {"present": False, "passed": False, "rows": [], "blocking_reasons": blockers}
    header, rows = parse_markdown_table(section)
    if not header:
        blockers.append(f"{title} has no markdown table")
    else:
        missing = missing_table_fields(header, required_fields)
        if missing:
            blockers.append(f"{title} missing fields: {', '.join(missing)}")
    return {"present": True, "passed": not blockers, "rows": rows, "blocking_reasons": blockers}


def concept_alignment_status(markdown: str, stage_order: list[str], current_stage: str) -> dict[str, Any]:
    enforcement = concept_alignment_enforcement(markdown)
    domain = table_status(markdown, DOMAIN_LANGUAGE_SECTION, DOMAIN_LANGUAGE_FIELDS)
    checkpoint = table_status(markdown, CONCEPT_ALIGNMENT_SECTION, CONCEPT_ALIGNMENT_FIELDS)
    blockers = [*domain["blocking_reasons"], *checkpoint["blocking_reasons"]]
    warnings: list[str] = []
    open_high_rows: list[dict[str, str]] = []
    missing_confirmation_rows: list[dict[str, str]] = []
    rejected_terms: list[str] = []
    active_terms: list[str] = []
    status_by_term: dict[str, str] = {}

    for index, row in enumerate(domain["rows"], start=1):
        content = " ".join(row.values()).strip()
        if not content:
            continue
        term_id = row_value(row, ["term_id"]) or f"row {index}"
        stage = row_value(row, ["阶段", "stage"])
        term = row_value(row, ["标准术语", "term", "standard_term"])
        definition = row_value(row, ["定义", "definition"])
        concept_type = normalize(row_value(row, ["概念类型", "concept_type"]))
        confirmation = normalize(row_value(row, ["用户确认", "confirmation"]))
        user_turn_ref = row_value(row, ["user_turn_ref"])
        backfill = row_value(row, ["回灌位置", "backfill_location"])
        status = normalize(row_value(row, ["状态", "status"]))
        has_ref = nonempty(user_turn_ref)
        high_impact = concept_type in {normalize(item) for item in CONCEPT_HIGH_IMPACT_TYPES}

        if stage and stage not in stage_order:
            blockers.append(f"{term_id} has unknown concept stage: {stage}")
        if not nonempty(term):
            blockers.append(f"{term_id} missing 标准术语")
        if not nonempty(definition):
            blockers.append(f"{term_id} missing 定义")
        if not nonempty(concept_type):
            blockers.append(f"{term_id} missing 概念类型")
        if not nonempty(backfill):
            blockers.append(f"{term_id} missing 回灌位置")
        if confirmation in {normalize(item) for item in CONCEPT_CONFIRMED_VALUES} and not has_ref:
            blockers.append(f"{term_id} confirmed concept missing user_turn_ref")
        if high_impact and confirmation in {normalize(item) for item in CONCEPT_ASSUMED_VALUES}:
            missing_confirmation_rows.append(row)
        if high_impact and status in {normalize(item) for item in CONCEPT_OPEN_VALUES}:
            open_high_rows.append(row)
        if status in {normalize(item) for item in CONCEPT_REJECTED_VALUES}:
            if nonempty(term):
                rejected_terms.append(term)
                status_by_term[term] = status
        elif nonempty(term):
            active_terms.append(term)
            status_by_term[term] = status or "active"

    checkpoint_rows_for_stage = [
        row
        for row in checkpoint["rows"]
        if row_value(row, ["stage"]) == current_stage and " ".join(row.values()).strip()
    ]
    w10_backfill_required = False
    if current_stage in CONCEPT_ALIGNMENT_REQUIRED_STAGES and not checkpoint_rows_for_stage:
        blockers.append(f"missing concept alignment checkpoint for {current_stage}")
    for index, row in enumerate(checkpoint["rows"], start=1):
        if not " ".join(row.values()).strip():
            continue
        stage = row_value(row, ["stage"])
        if stage and stage not in stage_order:
            blockers.append(f"concept alignment checkpoint row {index} has unknown stage: {stage}")
        exit_status = normalize(row_value(row, ["exit_status"]))
        blocker = row_value(row, ["blocker"])
        if stage in CONCEPT_ALIGNMENT_PROACTIVE_STAGES and exit_status not in {normalize(item) for item in CONCEPT_EXIT_PASSED}:
            if not nonempty(blocker):
                blockers.append(f"concept alignment checkpoint for {stage} not passed without blocker")
        if stage == "W10_plan_ceo_review":
            conflict = row_value(row, ["冲突概念"])
            high_risk = row_value(row, ["最高风险概念"])
            if nonempty(conflict) or nonempty(high_risk) or nonempty(blocker):
                w10_backfill_required = True

    if open_high_rows:
        blockers.append(f"open high-impact concept conflicts: {len(open_high_rows)}")
    if missing_confirmation_rows:
        blockers.append(f"high-impact concepts are assumed without user confirmation: {len(missing_confirmation_rows)}")

    if blockers and enforcement == "migration_warning":
        warnings.extend(blockers)
        blockers = []

    return {
        "present": domain["present"] and checkpoint["present"],
        "passed": not blockers,
        "enforcement": enforcement,
        "domain_language_row_count": len(domain["rows"]),
        "checkpoint_row_count": len(checkpoint["rows"]),
        "current_stage_checkpoint_count": len(checkpoint_rows_for_stage),
        "active_terms": active_terms,
        "rejected_terms": rejected_terms,
        "term_status": status_by_term,
        "w10_backfill_required": w10_backfill_required,
        "open_high_impact_count": len(open_high_rows),
        "missing_confirmation_count": len(missing_confirmation_rows),
        "blocking_reasons": blockers,
        "warnings": warnings,
    }


def concept_alignment_formal_prd_blockers(
    process_markdown: str,
    formal_markdown: str,
    stage_order: list[str],
) -> list[str]:
    status = concept_alignment_status(process_markdown, stage_order, "W9_formal_prd_output")
    blockers = list(status["blocking_reasons"])
    for term in status["rejected_terms"]:
        if term and term in formal_markdown:
            blockers.append(f"formal PRD uses rejected/deprecated concept term: {term}")
    for term, term_status in status["term_status"].items():
        if normalize(term_status) in {normalize(item) for item in CONCEPT_OPEN_VALUES} and term in formal_markdown:
            blockers.append(f"formal PRD uses unconfirmed/open concept term: {term}")
    return blockers


def stage_revalidation_status(markdown: str) -> dict[str, Any]:
    section = section_text(markdown, STAGE_REVALIDATION_SECTION)
    if not section:
        return {"present": False, "passed": True, "rows": [], "blocking_reasons": []}
    header, rows = parse_markdown_table(section)
    blockers: list[str] = []
    if not header:
        blockers.append("Stage Revalidation Ledger has no markdown table")
    else:
        missing = missing_table_fields(header, STAGE_REVALIDATION_FIELDS)
        if missing:
            blockers.append(f"Stage Revalidation Ledger missing fields: {', '.join(missing)}")
    return {"present": True, "passed": not blockers, "rows": rows, "blocking_reasons": blockers}


def repair_loop_status(markdown: str, stage_order: list[str], current_stage: str) -> dict[str, Any]:
    section = section_text(markdown, REPAIR_LOOP_SECTION)
    if not section:
        return {
            "present": False,
            "passed": True,
            "row_count": 0,
            "open_count": 0,
            "blocking_reasons": [],
            "open_rows": [],
        }
    header, rows = parse_markdown_table(section)
    blockers: list[str] = []
    if not header:
        blockers.append("Repair Loop Ledger has no markdown table")
    else:
        missing = missing_table_fields(header, REPAIR_LOOP_FIELDS)
        if missing:
            blockers.append(f"Repair Loop Ledger missing fields: {', '.join(missing)}")
    revalidation = stage_revalidation_status(markdown)
    blockers.extend(revalidation["blocking_reasons"])
    revalidated_issue_ids = {
        row_value(row, ["repair_issue_id"])
        for row in revalidation["rows"]
        if parse_int(row_value(row, ["new_challenge_count_after_reopen"]), 0) > 0
        and normalize(row_value(row, ["exit_criteria_status"])) in {normalize(item) for item in PASS_HANDLED | CLOSED_STATUSES}
    }
    open_rows: list[dict[str, str]] = []
    for index, row in enumerate(rows, start=1):
        if not " ".join(row.values()).strip():
            continue
        issue_id = row_value(row, ["issue_id"]) or f"row {index}"
        found_stage = row_value(row, ["found_stage"])
        root_stage = row_value(row, ["root_stage"])
        severity = normalize(row_value(row, ["severity"]))
        repair_status = normalize(row_value(row, ["repair_status"]))
        user_acceptance = normalize(row_value(row, ["user_acceptance"]))
        status = normalize(row_value(row, ["status"]))
        rerun_policy = row_value(row, ["rerun_policy"])
        if found_stage and found_stage not in stage_order:
            blockers.append(f"{issue_id} has unknown found_stage: {found_stage}")
        if root_stage and root_stage not in stage_order:
            blockers.append(f"{issue_id} has unknown root_stage: {root_stage}")
        if severity in {"high", "critical"} and user_acceptance not in {normalize(item) for item in VALID_USER_ACCEPTANCE}:
            blockers.append(f"{issue_id} high/critical repair requires user acceptance")
        if repair_status and repair_status not in VALID_REPAIR_STATUSES:
            blockers.append(f"{issue_id} has invalid repair_status: {repair_status}")
        if rerun_policy and rerun_policy != "stepwise_from_root_stage":
            blockers.append(f"{issue_id} rerun_policy must be stepwise_from_root_stage")
        if repair_status == "repair_applied" and not nonempty(row_value(row, ["root_stage_revalidated_at"])):
            blockers.append(f"{issue_id} repair_applied without root_stage_revalidated_at")
        if status not in REPAIR_CLOSED_STATUSES:
            open_rows.append(row)
        if repair_status in {"root_stage_revalidated", "closed"} and issue_id not in revalidated_issue_ids:
            blockers.append(f"{issue_id} is revalidated/closed without Stage Revalidation Ledger evidence")
    if open_rows and stage_index(stage_order, current_stage) >= stage_index(stage_order, "W9_formal_prd_output"):
        blockers.append(f"open Repair Loop issues: {len(open_rows)}")
    return {
        "present": True,
        "passed": not blockers,
        "row_count": len(rows),
        "open_count": len(open_rows),
        "blocking_reasons": blockers,
        "open_rows": open_rows,
    }


def w10_backfill_grill_blockers(markdown: str) -> list[str]:
    _, repair_rows = parse_markdown_table(section_text(markdown, REPAIR_LOOP_SECTION))
    _, challenge_rows = parse_markdown_table(section_text(markdown, EFFECTIVE_CHALLENGE_SECTION))
    challenge_by_id = {
        row_value(row, ["challenge_id"]): row
        for row in challenge_rows
        if nonempty(row_value(row, ["challenge_id"]))
    }
    matching_repairs = [
        row
        for row in repair_rows
        if row_value(row, ["found_stage"]) == "W10_plan_ceo_review" and nonempty(row_value(row, ["root_stage"]))
    ]
    if not matching_repairs:
        return ["W10 concept backfill requires Repair Loop row with found_stage=W10_plan_ceo_review and root_stage"]
    blockers: list[str] = []
    for row in matching_repairs:
        issue_id = row_value(row, ["issue_id"]) or "W10 repair issue"
        challenge_id = row_value(row, ["repair_question_id"])
        if not nonempty(challenge_id):
            blockers.append(f"{issue_id} missing repair_question_id for W10 concept backfill")
            continue
        challenge = challenge_by_id.get(challenge_id)
        if not challenge:
            blockers.append(f"{issue_id} repair_question_id not found in Effective Challenge Ledger: {challenge_id}")
            continue
        if not nonempty(row_value(challenge, ["backfill_location"])):
            blockers.append(f"{issue_id} W10 concept backfill challenge missing backfill_location")
    return blockers


def w9_readiness_status(markdown: str, required_sections: list[str]) -> dict[str, Any]:
    blockers: list[str] = []
    waiver_status = adapter_waiver_status(markdown)
    valid_waiver_ids = waiver_status["waiver_ids"]
    blockers.extend(waiver_status["blocking_reasons"])

    reread_section = section_text(markdown, REREAD_SECTION)
    reread_artifacts: set[str] = set()
    if not reread_section:
        blockers.append("missing reread record section")
    else:
        header, rows = parse_markdown_table(reread_section)
        if not header:
            blockers.append("reread record has no markdown table")
        for row in rows:
            artifact = reread_artifact_key(row_value(row, ["artifact", "产物"]))
            path = row_value(row, ["path", "路径"])
            if artifact in {"process_file", "formal_prd"} and row_status_passed(row) and nonempty(path):
                reread_artifacts.add(artifact)
        missing_artifacts = [item for item in ["process_file", "formal_prd"] if item not in reread_artifacts]
        if missing_artifacts:
            blockers.append(f"reread record missing artifacts: {', '.join(missing_artifacts)}")

    coverage_section = section_text(markdown, W9_COVERAGE_SECTION)
    missing_sections: list[str] = []
    if not coverage_section:
        blockers.append("missing W9 section challenge coverage section")
        missing_sections = required_sections[:]
    else:
        header, rows = parse_markdown_table(coverage_section)
        if not header:
            blockers.append("W9 section challenge coverage has no markdown table")
            missing_sections = required_sections[:]
        else:
            required_header = ["章节", "challenge_id", "source_adapter", "结论", "status", "waiver_id"]
            missing = [
                field
                for field in required_header
                if normalize(field) not in {normalize(item) for item in header}
            ]
            if missing:
                blockers.append(f"W9 section challenge coverage missing fields: {', '.join(missing)}")
            for section_name in required_sections:
                covered = False
                for row in table_rows_by_section(rows, section_name):
                    status = normalize(row_value(row, ["status", "状态"]))
                    waiver_id = row_value(row, ["waiver_id"])
                    challenge_id = row_value(row, ["challenge_id"])
                    conclusion = row_value(row, ["结论", "conclusion"])
                    if status == "waived" and nonempty(waiver_id) and waiver_id in valid_waiver_ids:
                        covered = True
                    elif nonempty(challenge_id) and nonempty(conclusion) and row_status_passed(row):
                        covered = True
                if not covered:
                    missing_sections.append(section_name)
        if missing_sections:
            blockers.append(f"W9 section challenge coverage missing sections: {', '.join(missing_sections)}")

    return {
        "passed": not blockers,
        "blocking_reasons": blockers,
        "reread_artifacts": sorted(reread_artifacts),
        "missing_sections": missing_sections,
    }


def semantic_reflection_status(markdown: str) -> dict[str, Any]:
    section = section_text(markdown, "语义反思记录")
    if not section:
        return {"present": False, "passed": False, "reason": "missing semantic reflection section"}
    _, rows = parse_markdown_table(section)
    if not rows:
        return {"present": True, "passed": False, "reason": "semantic reflection has no table rows"}
    last = rows[-1]
    must_fix = row_value(last, ["必须修复项", "must_fix", "must_fix_items"]).strip()
    handled = normalize(row_value(last, ["已处理", "handled"]))
    no_fix = must_fix in {"", "无", "none", "None", "N/A", "na", "-"}
    handled_ok = handled in {normalize(item) for item in PASS_HANDLED}
    return {
        "present": True,
        "passed": bool(no_fix and handled_ok),
        "reason": "" if no_fix and handled_ok else "semantic reflection has unresolved must-fix items",
        "last_row": last,
    }


def status_blockers(
    markdown: str,
    stage_order: list[str],
    current_stage: str,
    target_stage: str | None = None,
    required_sections: list[str] | None = None,
) -> list[str]:
    blockers: list[str] = []
    check_stage = target_stage or current_stage
    index = stage_order.index(check_stage) if check_stage in stage_order else -1
    if index >= 1:
        blockers.extend(
            quota_blockers(
                markdown,
                stage_order,
                current_stage,
                check_stage,
                require_total=index >= 10,
            )
        )
        concept = concept_alignment_status(markdown, stage_order, current_stage)
        blockers.extend(concept["blocking_reasons"])
        if current_stage == "W10_plan_ceo_review" and concept["w10_backfill_required"]:
            blockers.extend(w10_backfill_grill_blockers(markdown))
    w5_index = stage_index(stage_order, "W5_object_state_audit")
    if w5_index >= 0 and index >= w5_index:
        business = business_scenario_status(markdown)
        blockers.extend(business["blocking_reasons"])
    if index >= 7:
        if not section_text(markdown, "质疑账本"):
            blockers.append("missing challenge ledger section")
        if not section_text(markdown, "冲突账本"):
            blockers.append("missing conflict ledger section")
        high = unresolved_high_challenges(markdown)
        conflicts = open_conflicts(markdown)
        if high:
            blockers.append(f"unresolved high/critical challenges: {len(high)}")
        if conflicts:
            blockers.append(f"open conflicts: {len(conflicts)}")
        user_model = user_model_status(markdown)
        repair = repair_loop_status(markdown, stage_order, check_stage)
        blockers.extend(user_model["blocking_reasons"])
        blockers.extend(repair["blocking_reasons"])
        adapter = adapter_review_status(markdown, stage_order, check_stage)
        blockers.extend(adapter["blocking_reasons"])
    if index >= 9:
        semantic = semantic_reflection_status(markdown)
        if not semantic["passed"]:
            blockers.append(semantic["reason"])
        w9 = w9_readiness_status(markdown, required_sections or [])
        blockers.extend(w9["blocking_reasons"])
    if check_stage == "W11_engineering_prd_projection" and not w10_passed(markdown):
        blockers.append("W10_plan_ceo_review has not passed")
    return blockers


def cmd_inspect_wf(args: argparse.Namespace) -> dict[str, Any]:
    wf = parse_wf(Path(args.wf))
    return {
        "ok": True,
        "blocked": False,
        "command": "inspect-wf",
        "wf": wf["wf"],
        "stage_count": len(wf["stage_order"]),
        "stage_order": wf["stage_order"],
        "required_formal_prd_sections": wf["required_sections"],
        "review_adapter_contract_present": wf["review_adapter_contract_present"],
        "concept_alignment_contract_present": wf["concept_alignment_contract_present"],
        "adapter_sources": wf["adapter_sources"],
        "adapter_review_ledger_fields": wf["adapter_review_ledger_fields"],
        "adapter_waiver_ledger_fields": wf["adapter_waiver_ledger_fields"],
        "domain_language_ledger_fields": wf["domain_language_ledger_fields"],
        "concept_alignment_checkpoint_fields": wf["concept_alignment_checkpoint_fields"],
        "concept_alignment_required_stages": wf["concept_alignment_required_stages"],
        "challenge_quota_default_target_total": wf["challenge_quota_default_target_total"],
        "effective_challenge_ledger_fields": wf["effective_challenge_ledger_fields"],
        "baseline_stage_distribution": wf["baseline_stage_distribution"],
        "baseline_perspective_distribution": wf["baseline_perspective_distribution"],
        "repair_loop_ledger_fields": wf["repair_loop_ledger_fields"],
        "stage_revalidation_ledger_fields": wf["stage_revalidation_ledger_fields"],
        "forbidden_formal_prd_terms": wf["forbidden_content"],
        "engineering_prd_template": wf["engineering_prd_template"],
        "required_engineering_prd_sections": wf["required_engineering_prd_sections"],
        "engineering_prd_filename_pattern": wf["engineering_prd_filename_pattern"],
        "blocking_reasons": [],
        "warnings": [],
    }


def cmd_check_status(args: argparse.Namespace) -> dict[str, Any]:
    wf = parse_wf(Path(args.wf))
    path = Path(args.process_file)
    warnings: list[str] = []
    if not path.exists():
        return {
            "ok": False,
            "blocked": True,
            "command": "check-status",
            "process_file": str(path),
            "blocking_reasons": ["process file does not exist"],
            "warnings": warnings,
        }
    markdown = read_text(path)
    state = parse_workflow_state(markdown)
    current_stage = state.get("current_stage", "")
    stage_order = wf["stage_order"]
    blockers: list[str] = []
    if not current_stage:
        blockers.append("Workflow State.current_stage is missing")
    elif current_stage not in stage_order:
        blockers.append(f"unknown current_stage: {current_stage}")
    blockers.extend(status_blockers(markdown, stage_order, current_stage, required_sections=wf["required_sections"]))
    if not section_text(markdown, "Stage Ledger"):
        warnings.append("Stage Ledger section is missing")
    for ledger_title in ["质疑账本", "假设账本", "冲突账本", "语义反思记录"]:
        if not section_text(markdown, ledger_title):
            warnings.append(f"{ledger_title} section is missing")
    concept_status = concept_alignment_status(markdown, stage_order, current_stage)
    warnings.extend(concept_status["warnings"])
    return {
        "ok": not blockers,
        "blocked": bool(blockers),
        "command": "check-status",
        "process_file": str(path),
        "current_stage": current_stage,
        "next_stage": next_stage_for(stage_order, current_stage) if current_stage in stage_order else "",
        "workflow_state": state,
        "unresolved_high_challenge_count": len(unresolved_high_challenges(markdown)),
        "open_conflict_count": len(open_conflicts(markdown)),
        "challenge_quota": effective_challenge_status(markdown, stage_order, current_stage),
        "user_model": user_model_status(markdown),
        "business_scenario": business_scenario_status(markdown),
        "concept_alignment": concept_status,
        "repair_loop": repair_loop_status(markdown, stage_order, current_stage),
        "adapter_review": adapter_review_status(markdown, stage_order, current_stage),
        "semantic_reflection": semantic_reflection_status(markdown),
        "w9_readiness": w9_readiness_status(markdown, wf["required_sections"]),
        "blocking_reasons": blockers,
        "warnings": warnings,
    }


def cmd_next_stage(args: argparse.Namespace) -> dict[str, Any]:
    wf = parse_wf(Path(args.wf))
    current_stage = args.current_stage or ""
    if args.process_file:
        markdown = read_text(Path(args.process_file))
        current_stage = parse_workflow_state(markdown).get("current_stage", current_stage)
    blockers: list[str] = []
    if not current_stage:
        blockers.append("current stage is missing")
    elif current_stage not in wf["stage_order"]:
        blockers.append(f"unknown current_stage: {current_stage}")
    return {
        "ok": not blockers,
        "blocked": bool(blockers),
        "command": "next-stage",
        "current_stage": current_stage,
        "next_stage": "" if blockers else next_stage_for(wf["stage_order"], current_stage),
        "blocking_reasons": blockers,
        "warnings": [],
    }


def default_artifact(stage: str, stage_order: list[str]) -> str:
    if stage == "W11_engineering_prd_projection":
        return "engineering_prd"
    return "formal_prd" if stage in stage_order and stage_order.index(stage) >= 9 else "process_file"


def default_gate(stage: str) -> str:
    if stage == "W10_plan_ceo_review":
        return "reviewing"
    if stage in {
        "W7_prd_gate",
        "W8_verification_checkpoint",
        "W9_formal_prd_output",
        "W11_engineering_prd_projection",
    }:
        return "pass"
    return "blocked"


def cmd_apply_stage_transition(args: argparse.Namespace) -> dict[str, Any]:
    wf = parse_wf(Path(args.wf))
    stage_order = wf["stage_order"]
    process_path = Path(args.process_file)
    warnings: list[str] = []
    lock = Lock(process_path.parent / ".prd-kit.lock", args.stale_lock_seconds, warnings)
    lock.acquire()
    try:
        markdown = read_text(process_path) if process_path.exists() else f"# {process_path.stem}\n\n"
        state = parse_workflow_state(markdown)
        current_stage = state.get("current_stage", "")
        target_stage = args.target_stage
        blockers: list[str] = []
        if target_stage not in stage_order:
            blockers.append(f"unknown target_stage: {target_stage}")
        if current_stage and current_stage not in stage_order:
            blockers.append(f"unknown current_stage: {current_stage}")
        if current_stage in stage_order and target_stage in stage_order and not args.allow_skip:
            current_index = stage_order.index(current_stage)
            target_index = stage_order.index(target_stage)
            if target_index > current_index + 1:
                blockers.append(f"forward skip is forbidden: {current_stage} -> {target_stage}")
        repair = repair_loop_status(markdown, stage_order, current_stage)
        for row in repair.get("open_rows", []):
            issue_id = row_value(row, ["issue_id"]) or "repair issue"
            root_stage = row_value(row, ["root_stage"])
            found_stage = row_value(row, ["found_stage"])
            if current_stage == root_stage and target_stage == found_stage and found_stage != next_stage_for(stage_order, root_stage):
                blockers.append(f"repair skip is forbidden for {issue_id}: {root_stage} -> {found_stage}")
        if target_stage in stage_order:
            blockers.extend(
                status_blockers(
                    markdown,
                    stage_order,
                    current_stage,
                    target_stage,
                    required_sections=wf["required_sections"],
                )
            )
        if blockers and not args.force:
            return {
                "ok": False,
                "blocked": True,
                "command": "apply-stage-transition",
                "process_file": str(process_path),
                "current_stage": current_stage,
                "target_stage": target_stage,
                "blocking_reasons": blockers,
                "warnings": warnings,
            }
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        reason = args.reason or "stage transition requested"
        new_state = {
            "current_stage": target_stage,
            "artifact_stage": args.artifact_stage or default_artifact(target_stage, stage_order),
            "gate": args.gate or default_gate(target_stage),
            "next_stage": next_stage_for(stage_order, target_stage),
            "stage_exit_criteria_status": args.stage_exit_criteria_status or f"transitioned; reason={reason}",
            "updated_at": now,
        }
        markdown = replace_or_insert_section(markdown, "Workflow State", workflow_state_table(new_state))
        ledger_row = {
            "stage": current_stage or "new_process_file",
            "entered_at": state.get("updated_at", now),
            "exit_status": args.exit_status or "transitioned",
            "exit_evidence": reason,
            "next_stage": target_stage,
        }
        markdown = append_stage_ledger(markdown, ledger_row)
        write_text(process_path, markdown)
        return {
            "ok": True,
            "blocked": False,
            "command": "apply-stage-transition",
            "process_file": str(process_path),
            "previous_stage": current_stage,
            "current_stage": target_stage,
            "next_stage": new_state["next_stage"],
            "workflow_state": new_state,
            "blocking_reasons": [],
            "warnings": warnings,
        }
    finally:
        lock.release()


def heading_exists(markdown: str, title: str) -> bool:
    pattern = rf"(?m)^#+\s+(?:\d+(?:\.\d+)*[.、]?\s*)?{re.escape(title)}\s*$"
    return re.search(pattern, markdown) is not None


def cmd_check_formal_prd(args: argparse.Namespace) -> dict[str, Any]:
    wf = parse_wf(Path(args.wf))
    path = Path(args.prd)
    if not path.exists():
        return {
            "ok": False,
            "blocked": True,
            "command": "check-formal-prd",
            "prd": str(path),
            "blocking_reasons": ["formal PRD does not exist"],
            "warnings": [],
        }
    markdown = read_text(path)
    missing_sections = [section for section in wf["required_sections"] if not heading_exists(markdown, section)]
    forbidden_hits = [term for term in wf["forbidden_content"] if term and term in markdown]
    blockers: list[str] = []
    if missing_sections:
        blockers.append(f"missing required sections: {', '.join(missing_sections)}")
    if forbidden_hits:
        blockers.append(f"forbidden process/internal terms found: {', '.join(forbidden_hits)}")
    process_file_status: dict[str, Any] | None = None
    if args.process_file:
        process_path = Path(args.process_file)
        if not process_path.exists():
            blockers.append("process file does not exist")
        else:
            process_markdown = read_text(process_path)
            state = parse_workflow_state(process_markdown)
            current_stage = state.get("current_stage", "W9_formal_prd_output")
            process_file_status = {
                "challenge_quota": effective_challenge_status(process_markdown, wf["stage_order"], current_stage),
                "user_model": user_model_status(process_markdown),
                "business_scenario": business_scenario_status(process_markdown),
                "concept_alignment": concept_alignment_status(process_markdown, wf["stage_order"], current_stage),
                "repair_loop": repair_loop_status(process_markdown, wf["stage_order"], current_stage),
                "adapter_review": adapter_review_status(process_markdown, wf["stage_order"], current_stage),
                "w9_readiness": w9_readiness_status(process_markdown, wf["required_sections"]),
            }
            blockers.extend(
                quota_blockers(
                    process_markdown,
                    wf["stage_order"],
                    current_stage,
                    "W10_plan_ceo_review",
                    require_total=True,
                )
            )
            blockers.extend(process_file_status["user_model"]["blocking_reasons"])
            blockers.extend(process_file_status["business_scenario"]["blocking_reasons"])
            blockers.extend(process_file_status["concept_alignment"]["blocking_reasons"])
            blockers.extend(concept_alignment_formal_prd_blockers(process_markdown, markdown, wf["stage_order"]))
            blockers.extend(process_file_status["repair_loop"]["blocking_reasons"])
            blockers.extend(process_file_status["adapter_review"]["blocking_reasons"])
            blockers.extend(process_file_status["w9_readiness"]["blocking_reasons"])
    return {
        "ok": not blockers,
        "blocked": bool(blockers),
        "command": "check-formal-prd",
        "prd": str(path),
        "process_file": args.process_file or "",
        "missing_sections": missing_sections,
        "forbidden_hits": forbidden_hits,
        "process_file_status": process_file_status,
        "blocking_reasons": blockers,
        "warnings": [],
    }


def engineering_prd_filename_valid(path: Path) -> bool:
    return bool(ENGINEERING_PRD_FILENAME_RE.fullmatch(path.name))


def contains_unresolved_placeholders(markdown: str) -> bool:
    return bool(re.search(r"\{[^{}\n]+\}", markdown))


def has_unresolved_fact_section(markdown: str) -> bool:
    return any(heading_exists(markdown, title) for title in UNRESOLVED_FACT_SECTIONS)


def w10_passed(process_markdown: str) -> bool:
    normalized = re.sub(r"\s+", "", process_markdown).lower()
    if "final_release_status=passed" in normalized:
        return True
    if "final_release_status|passed" in normalized:
        return True

    _, rows = parse_markdown_table(section_text(process_markdown, "Stage Ledger"))
    for row in rows:
        stage = row_value(row, ["stage"])
        exit_status = row_value(row, ["exit_status", "status", "gate", "result"])
        evidence = row_value(row, ["exit_evidence", "evidence", "summary"])
        if stage == "W10_plan_ceo_review":
            if normalize(exit_status) in {"passed", "pass", "completed", "done", "通过", "已通过", "完成"}:
                return True
            if "final_release_status=passed" in re.sub(r"\s+", "", evidence).lower():
                return True
    return False


def cmd_check_engineering_prd(args: argparse.Namespace) -> dict[str, Any]:
    wf = parse_wf(Path(args.wf))
    engineering_path = Path(args.engineering_prd)
    formal_path = Path(args.formal_prd)
    process_path = Path(args.process_file)
    blockers: list[str] = []
    warnings: list[str] = []

    if not engineering_path.exists():
        blockers.append("engineering PRD does not exist")
        engineering_markdown = ""
    else:
        engineering_markdown = read_text(engineering_path)

    if not formal_path.exists():
        blockers.append("formal PRD does not exist")

    if not process_path.exists():
        blockers.append("process file does not exist")
        process_markdown = ""
    else:
        process_markdown = read_text(process_path)
        if not w10_passed(process_markdown):
            blockers.append("W10_plan_ceo_review has not passed")

    filename_valid = engineering_prd_filename_valid(engineering_path)
    if not filename_valid:
        blockers.append(
            f"engineering PRD filename must match {wf['engineering_prd_filename_pattern']}"
        )

    missing_sections: list[str] = []
    forbidden_hits: list[str] = []
    unresolved_placeholders = False
    unresolved_section_present = False
    if engineering_markdown:
        missing_sections = [
            section
            for section in wf["required_engineering_prd_sections"]
            if not heading_exists(engineering_markdown, section)
        ]
        forbidden_hits = [term for term in wf["forbidden_content"] if term and term in engineering_markdown]
        unresolved_placeholders = contains_unresolved_placeholders(engineering_markdown)
        unresolved_section_present = has_unresolved_fact_section(engineering_markdown)
        if missing_sections:
            blockers.append(f"missing required engineering PRD sections: {', '.join(missing_sections)}")
        if forbidden_hits:
            blockers.append(f"forbidden process/internal terms found: {', '.join(forbidden_hits)}")
        if unresolved_placeholders and not unresolved_section_present:
            blockers.append("unresolved placeholders require 未决问题 or 实现待确认 section")

    return {
        "ok": not blockers,
        "blocked": bool(blockers),
        "command": "check-engineering-prd",
        "engineering_prd": str(engineering_path),
        "formal_prd": str(formal_path),
        "process_file": str(process_path),
        "filename_valid": filename_valid,
        "missing_sections": missing_sections,
        "forbidden_hits": forbidden_hits,
        "unresolved_placeholders": unresolved_placeholders,
        "unresolved_fact_section_present": unresolved_section_present,
        "engineering_prd_template": wf["engineering_prd_template"],
        "required_engineering_prd_sections": wf["required_engineering_prd_sections"],
        "blocking_reasons": blockers,
        "warnings": warnings,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="prd-kit deterministic runtime")
    parser.add_argument("--out", help="Optional JSON output path. Defaults to stdout only.")
    sub = parser.add_subparsers(dest="command", required=True)

    inspect = sub.add_parser("inspect-wf")
    inspect.add_argument("--wf", required=True)
    inspect.set_defaults(func=cmd_inspect_wf)

    status = sub.add_parser("check-status")
    status.add_argument("--wf", required=True)
    status.add_argument("--process-file", required=True)
    status.set_defaults(func=cmd_check_status)

    next_stage = sub.add_parser("next-stage")
    next_stage.add_argument("--wf", required=True)
    next_stage.add_argument("--current-stage")
    next_stage.add_argument("--process-file")
    next_stage.set_defaults(func=cmd_next_stage)

    transition = sub.add_parser("apply-stage-transition")
    transition.add_argument("--wf", required=True)
    transition.add_argument("--process-file", required=True)
    transition.add_argument("--target-stage", required=True)
    transition.add_argument("--reason", default="")
    transition.add_argument("--artifact-stage", default="")
    transition.add_argument("--gate", default="")
    transition.add_argument("--stage-exit-criteria-status", default="")
    transition.add_argument("--exit-status", default="")
    transition.add_argument("--allow-skip", action="store_true")
    transition.add_argument("--force", action="store_true")
    transition.add_argument("--stale-lock-seconds", type=int, default=900)
    transition.set_defaults(func=cmd_apply_stage_transition)

    formal = sub.add_parser("check-formal-prd")
    formal.add_argument("--wf", required=True)
    formal.add_argument("--prd", required=True)
    formal.add_argument("--process-file")
    formal.set_defaults(func=cmd_check_formal_prd)

    engineering = sub.add_parser("check-engineering-prd")
    engineering.add_argument("--wf", required=True)
    engineering.add_argument("--engineering-prd", required=True)
    engineering.add_argument("--formal-prd", required=True)
    engineering.add_argument("--process-file", required=True)
    engineering.set_defaults(func=cmd_check_engineering_prd)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        result = args.func(args)
    except RuntimeErrorWithResult as exc:
        result = exc.result
        result.setdefault("command", args.command)
    except Exception as exc:  # noqa: BLE001 - CLI must return JSON on unexpected errors.
        result = {
            "ok": False,
            "blocked": True,
            "command": args.command,
            "blocking_reasons": [str(exc)],
            "warnings": [],
        }
    emit(result, args.out)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())


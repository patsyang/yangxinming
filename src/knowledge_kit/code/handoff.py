from __future__ import annotations

import json
import hashlib
import re
from pathlib import Path

from knowledge_kit.workflow_contract import KCODE_HUMAN_READABLE_OUTPUT_LANGUAGE, KCODE_LANGUAGE_POLICY, KU_CONTRACT_REFS

from .evidence import batch_slug
from .models import CodeRun
from .workspace import mark_stage

REQUIRED_FIXED_HEADINGS = [
    "现有实现",
    "代码定位",
    "实现链",
    "复用边界",
    "改动点",
    "暂不应改动",
    "数据/权限/运行约束",
    "测试/验证路径",
    "PRD 设计影响",
    "缺口与继续探索",
]

REQUIRED_CHECKS = [
    "preflight_QUERY",
    "wiki_reconciliation",
    "no_state_artifact_as_formal_wiki_body",
    "no_blocking_gaps_as_current_facts",
    "fixed_code_feature_sections",
    "index_recall_summary",
    "query_bundle_profile_quality",
    "knowledge_verifier_handoff",
]

CODE_MAP_ACCEPTANCE_QUERY = "代码仓库导航和功能入口如何继续探索"

BLUEPRINT_PROCESS_INSTRUCTION_MARKERS = [
    "从当前实现、coverage_claims 和 evidence_refs 中提取",
    "feature_implementation finding 未提供",
    "如果 handoff 未给出改动点",
    "如果 coverage claim 标记测试层为",
    "正式页应明确",
    "当前 handoff 未提供",
    "不得从目录结构自行推断",
]


def generate_handoff(run: CodeRun) -> dict:
    handoff_dir = run.run_dir / "handoff"
    shards_dir = handoff_dir / "shards"
    blueprints_dir = handoff_dir / "page-blueprints"
    source_blueprints_dir = handoff_dir / "source-summary-blueprints"
    handoff_dir.mkdir(parents=True, exist_ok=True)
    clear_generated_handoff_files(handoff_dir)
    shards_dir.mkdir(parents=True, exist_ok=True)
    blueprints_dir.mkdir(parents=True, exist_ok=True)
    source_blueprints_dir.mkdir(parents=True, exist_ok=True)
    clear_generated_handoff_files(shards_dir)
    clear_generated_handoff_files(blueprints_dir)
    clear_generated_handoff_files(source_blueprints_dir)
    completion = planned_batch_completion(run)
    if not completion["passed"]:
        mark_stage(run, "handoff", "blocked")
        return {"status": "failed", "error": "handoff_unverified_batches", **completion}
    verified_paths = sorted((run.run_dir / "batches").glob("*/verified-findings.jsonl")) if (run.run_dir / "batches").exists() else []
    shards = []
    for index, path in enumerate(verified_paths, start=1):
        findings = read_jsonl(path)
        if not findings:
            continue
        blocking = [gap for finding in findings for gap in finding.get("blocking_gaps") or []]
        if blocking:
            mark_stage(run, "handoff", "blocked")
            return {"status": "failed", "error": "blocking_gaps_present", "source_batch": path.parent.name, "blocking_gaps": blocking}
        topic = findings[0].get("title", path.parent.name)
        shard_name = f"H{index:03d}-{path.parent.name}.md"
        shard_path = shards_dir / shard_name
        shard_path.write_text(render_shard(run, path, findings, topic), encoding="utf-8")
        shard = {
            "path": shard_path.relative_to(run.run_dir).as_posix(),
            "topic": topic,
            "findings": len(findings),
            "source_batch": path.parent.name,
            "verified_findings": path.relative_to(run.run_dir).as_posix(),
            "analysis": f"{path.parent.relative_to(run.run_dir).as_posix()}/analysis.md",
            "evidence": f"{path.parent.relative_to(run.run_dir).as_posix()}/evidence.json",
            "source_summary_path": f"wiki/sources/code/kcode-runs/{run.run_id}/{shard_name}",
            "candidate_wiki_pages": candidate_wiki_pages(path.parent.name, findings),
            "primary_wiki_pages": primary_wiki_pages(path.parent.name, findings),
            "knowledge_levels": sorted({str(finding.get("knowledge_level", "")) for finding in findings if finding.get("knowledge_level")}),
        }
        shard["source_summary_blueprint"] = write_source_summary_blueprint(run, source_blueprints_dir, shard, findings)
        shard["page_blueprints"] = write_page_blueprints(run, blueprints_dir, shard, findings)
        shards.append(shard)
    if not shards:
        mark_stage(run, "handoff", "blocked")
        return {"status": "failed", "error": "verified_findings_missing", "shards": []}
    index_path = handoff_dir / "index.md"
    index_path.write_text(render_index(run, shards), encoding="utf-8")
    manifest_path = handoff_dir / "manifest.json"
    manifest_path.write_text(json.dumps(render_manifest(run, shards), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manager_request_path = handoff_dir / "knowledge-manager-request.md"
    manager_request_path.write_text(render_manager_request(run, shards), encoding="utf-8")
    quality = validate_handoff_artifacts(run, handoff_dir, shards)
    quality_path = handoff_dir / "handoff-quality.json"
    quality_path.write_text(json.dumps(quality, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not quality["passed"]:
        mark_stage(run, "handoff", "blocked", {"handoff_quality": quality_path.relative_to(run.run_dir).as_posix()})
        return {"status": "failed", "error": "handoff_quality_failed", "handoff_quality": str(quality_path), "quality": quality}
    mark_stage(
        run,
        "handoff",
        "completed",
        {
            "handoff_index": index_path.relative_to(run.run_dir).as_posix(),
            "handoff_manifest": manifest_path.relative_to(run.run_dir).as_posix(),
            "knowledge_manager_request": manager_request_path.relative_to(run.run_dir).as_posix(),
            "handoff_quality": quality_path.relative_to(run.run_dir).as_posix(),
        },
    )
    return {
        "status": "completed",
        "handoff_index": str(index_path),
        "handoff_manifest": str(manifest_path),
        "knowledge_manager_request": str(manager_request_path),
        "handoff_quality": str(quality_path),
        "quality": quality,
        "shards": shards,
    }


def read_jsonl(path: Path) -> list[dict]:
    result: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            result.append(json.loads(line))
    return result


def planned_batch_completion(run: CodeRun) -> dict:
    plan_path = run.run_dir / "plan" / "analysis-plan.json"
    if not plan_path.exists():
        return {
            "passed": False,
            "issue": "analysis_plan_missing",
            "unverified_batches": [],
            "orphan_verified_batches": [],
        }
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {
            "passed": False,
            "issue": "analysis_plan_invalid",
            "unverified_batches": [],
            "orphan_verified_batches": [],
        }
    batches = plan.get("batches")
    if not isinstance(batches, list) or not batches:
        return {
            "passed": False,
            "issue": "analysis_plan_batches_missing",
            "unverified_batches": [],
            "orphan_verified_batches": [],
        }
    expected_slugs: set[str] = set()
    unverified = []
    for batch in batches:
        if not isinstance(batch, dict):
            unverified.append({"batch_id": "", "slug": "", "reason": "batch_not_object"})
            continue
        slug = batch_slug(batch)
        expected_slugs.add(slug)
        verified_path = run.run_dir / "batches" / slug / "verified-findings.jsonl"
        if not verified_path.exists() or not verified_path.is_file():
            unverified.append({"batch_id": str(batch.get("batch_id", "")), "slug": slug, "reason": "verified_findings_missing"})
            continue
        if not read_jsonl(verified_path):
            unverified.append({"batch_id": str(batch.get("batch_id", "")), "slug": slug, "reason": "verified_findings_empty"})
    orphan_verified = []
    for path in sorted((run.run_dir / "batches").glob("*/verified-findings.jsonl")) if (run.run_dir / "batches").exists() else []:
        if path.parent.name not in expected_slugs:
            orphan_verified.append(path.parent.name)
    return {
        "passed": not unverified and not orphan_verified,
        "issue": "" if not unverified and not orphan_verified else "planned_batch_completion_mismatch",
        "unverified_batches": unverified,
        "orphan_verified_batches": orphan_verified,
    }


def clear_generated_handoff_files(path: Path) -> None:
    for item in path.iterdir():
        if item.is_file():
            item.unlink()


def render_index(run: CodeRun, shards: list[dict]) -> str:
    rows = ["| 分片 | 主题 | 发现数 | 来源批次 | 主落页 | 落页蓝图 |", "| --- | --- | ---: | --- | --- | --- |"]
    for item in shards:
        rows.append(
            f"| {item['path']} | {item['topic']} | {item['findings']} | {item['source_batch']} | "
            + "<br>".join(str(path) for path in item.get("primary_wiki_pages", []))
            + " | "
            + "<br>".join(str(path) for path in item.get("page_blueprints", []))
            + " |"
        )
    if not shards:
        rows.append("| _none_ | _none_ | 0 | _none_ | _none_ | _none_ |")
    return (
        "# KCode 交接索引\n\n"
        "## 目标\n\n"
        f"- knowledge_id: {run.workspace.knowledge_id}\n"
        f"- knowledge_root: {run.workspace.knowledge_root}\n"
        f"- run_id: {run.run_id}\n"
        f"- mode: {run.mode}\n\n"
        "## 人工下一步\n\n"
        "检查分片后，把 `handoff/knowledge-manager-request.md` 作为维护请求交给 `knowledge-manager-agent.toml`；"
        "结构化输入优先使用 `handoff/manifest.json`，并保持所有人读输出为中文。\n\n"
        "## 分片\n\n"
        + "\n".join(rows)
        + "\n\n"
        "## 缺口\n\n"
        "- 执行 knowledge-manager 前，先检查 deferred 或 blocked 批次产物。\n"
    )


def render_manifest(run: CodeRun, shards: list[dict]) -> dict:
    acceptance_query = acceptance_query_for_shards(shards)
    requires_feature_profile = acceptance_requires_feature_profile(shards)
    acceptance_checks = [
        f"python -m knowledge_kit lint -k {run.workspace.knowledge_id} 不再报告 code_knowledge_pages_missing、code_knowledge_index_missing 或代码 feature 固定章节缺失。",
        f"python -m knowledge_kit query-bundle -k {run.workspace.knowledge_id} \"{acceptance_query}\" 必须选中正式代码知识页。",
    ]
    if requires_feature_profile:
        acceptance_checks.extend(
            [
                "query bundle 的 evidence_pages 至少包含一个 wiki/entities/code/features/** 页面。",
                "query bundle 不得返回 profile_no_evidence_pages、profile_code_feature_evidence_missing、profile_code_feature_source_trace_missing、profile_code_feature_source_summary_missing、profile_required_section_missing 或 profile_query_topic_not_covered。",
                "每个被 query bundle 选中的 wiki/entities/code/features/** 页面都必须独立具备 Agentic Coding / PRD 设计所需章节；不能把必要章节拆散到多页后依赖综合拼接。",
                "如果 profile_required_section_missing 带有具体 path，必须修复该 path 对应页面，不能用其他页面内容抵消。",
                "代码 feature 固定章节不得是空壳；代码定位必须包含仓库相对路径、类名、函数名、endpoint、配置名或测试入口。",
            ]
        )
    else:
        acceptance_checks.append("code_map-only handoff 的 query bundle 必须选中 wiki/entities/code/modules/** 导航页，并给出可继续探索的 repo/入口线索。")
    acceptance_checks.append("knowledge-verifier 的 focus 覆盖代码引用完整性、coding_context 落页、blocking_gaps 未写成事实、index 可召回、schema 包含 Code Knowledge 约定。")
    return {
        "schema_version": "kcode.handoff_manifest.v1",
        "knowledge_id": run.workspace.knowledge_id,
        "knowledge_root": str(run.workspace.knowledge_root),
        "run_id": run.run_id,
        "mode": run.mode,
        "handoff_index": "handoff/index.md",
        "handoff_quality": "handoff/handoff-quality.json",
        "knowledge_manager_request": "handoff/knowledge-manager-request.md",
        "human_readable_output_language": KCODE_HUMAN_READABLE_OUTPUT_LANGUAGE,
        "language_policy": KCODE_LANGUAGE_POLICY,
        "contract_refs": KU_CONTRACT_REFS,
        "task_classification": "KCode handoff 整理维护",
        "request": {
            "must_run_preflight_query": True,
            "must_run_wiki_reconciliation": True,
            "must_not_copy_state_artifacts_as_formal_wiki_body": True,
            "must_not_write_blocking_gaps_as_current_facts": True,
            "must_prepare_verifier_handoff": True,
            "each_code_feature_page_must_independently_satisfy_query_profiles": True,
        },
        "required_fixed_headings": REQUIRED_FIXED_HEADINGS,
        "required_checks": REQUIRED_CHECKS,
        "acceptance_query": acceptance_query,
        "acceptance_commands": acceptance_commands(run, acceptance_query),
        "acceptance_checks": acceptance_checks,
        "shards": shards,
    }


def acceptance_query_for_shards(shards: list[dict]) -> str:
    for shard in shards:
        if all(level == "code_map" for level in shard.get("knowledge_levels", [])):
            continue
        topic = str(shard.get("topic") or "").strip()
        if topic:
            return f"{topic} 如何基于现有代码设计和实现"
    return CODE_MAP_ACCEPTANCE_QUERY


def acceptance_requires_feature_profile(shards: list[dict]) -> bool:
    return any(not all(level == "code_map" for level in shard.get("knowledge_levels", [])) for shard in shards)


def acceptance_commands(run: CodeRun, acceptance_query: str) -> list[str]:
    return [
        f"python -m knowledge_kit lint -k {run.workspace.knowledge_id}",
        f'python -m knowledge_kit query-bundle -k {run.workspace.knowledge_id} "{acceptance_query}"',
    ]


def validate_handoff_artifacts(run: CodeRun, handoff_dir: Path, shards: list[dict]) -> dict:
    issues: list[dict] = []
    manifest_path = handoff_dir / "manifest.json"
    request_path = handoff_dir / "knowledge-manager-request.md"
    index_path = handoff_dir / "index.md"
    if not shards:
        issues.append({"severity": "major", "code": "handoff_shards_missing"})
    index_text = validate_required_file(issues, run, index_path, "handoff/index.md")
    validate_markdown_human_language(issues, "handoff/index.md", index_text)
    manifest = validate_manifest_file(issues, run, manifest_path)
    request_text = validate_required_file(issues, run, request_path, "handoff/knowledge-manager-request.md")
    validate_markdown_human_language(issues, "handoff/knowledge-manager-request.md", request_text)
    if "handoff/manifest.json" not in request_text:
        issues.append({"severity": "major", "code": "manager_request_manifest_ref_missing", "path": "handoff/knowledge-manager-request.md"})
    if "handoff/page-blueprints" not in request_text:
        issues.append({"severity": "major", "code": "manager_request_blueprint_ref_missing", "path": "handoff/knowledge-manager-request.md"})
    if manifest.get("human_readable_output_language") != KCODE_HUMAN_READABLE_OUTPUT_LANGUAGE:
        issues.append({"severity": "major", "code": "manifest_language_policy_missing", "path": "handoff/manifest.json"})
    if manifest.get("handoff_index") != "handoff/index.md":
        issues.append({"severity": "major", "code": "manifest_handoff_index_missing", "path": "handoff/manifest.json"})
    if manifest.get("knowledge_manager_request") != "handoff/knowledge-manager-request.md":
        issues.append({"severity": "major", "code": "manifest_manager_request_missing", "path": "handoff/manifest.json"})
    if manifest.get("required_fixed_headings") != REQUIRED_FIXED_HEADINGS:
        issues.append({"severity": "major", "code": "manifest_fixed_headings_mismatch", "path": "handoff/manifest.json"})
    for shard_index, shard in enumerate(shards):
        validate_shard_descriptor(issues, run, shard, shard_index)
        validate_blueprint_uniqueness(issues, run, shard)
    return {
        "schema_version": "kcode.handoff_quality.v1",
        "passed": not issues,
        "issues": issues,
        "checked": {
            "shards": len(shards),
            "blueprints": sum(len(shard.get("page_blueprints", []) or []) for shard in shards),
            "source_summary_blueprints": sum(1 for shard in shards if shard.get("source_summary_blueprint")),
            "required_fixed_headings": REQUIRED_FIXED_HEADINGS,
            "human_readable_output_language": KCODE_HUMAN_READABLE_OUTPUT_LANGUAGE,
        },
    }


def validate_required_file(issues: list[dict], run: CodeRun, path: Path, relative_label: str) -> str:
    if not path.exists() or not path.is_file():
        issues.append({"severity": "major", "code": "handoff_artifact_missing", "path": relative_label})
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        issues.append({"severity": "major", "code": "handoff_artifact_empty", "path": relative_label})
    if not contains_chinese_text(text):
        issues.append({"severity": "major", "code": "handoff_artifact_not_chinese", "path": relative_label})
    return text


def validate_manifest_file(issues: list[dict], run: CodeRun, path: Path) -> dict:
    text = validate_required_file(issues, run, path, "handoff/manifest.json")
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        issues.append({"severity": "major", "code": "manifest_json_invalid", "path": "handoff/manifest.json"})
        return {}
    if not isinstance(payload, dict):
        issues.append({"severity": "major", "code": "manifest_not_object", "path": "handoff/manifest.json"})
        return {}
    if payload.get("schema_version") != "kcode.handoff_manifest.v1":
        issues.append({"severity": "major", "code": "manifest_schema_invalid", "path": "handoff/manifest.json"})
    if payload.get("knowledge_id") != run.workspace.knowledge_id:
        issues.append({"severity": "major", "code": "manifest_knowledge_mismatch", "path": "handoff/manifest.json"})
    if not isinstance(payload.get("shards"), list) or not payload.get("shards"):
        issues.append({"severity": "major", "code": "manifest_shards_missing", "path": "handoff/manifest.json"})
    return payload


def validate_shard_descriptor(issues: list[dict], run: CodeRun, shard: dict, index: int) -> None:
    for key in ["path", "topic", "source_batch", "verified_findings", "analysis", "evidence", "source_summary_path", "source_summary_blueprint"]:
        if not str(shard.get(key, "")).strip():
            issues.append({"severity": "major", "code": "shard_field_missing", "shard_index": index, "field": key})
    if not str(shard.get("source_summary_path", "")).startswith("wiki/sources/code/kcode-runs/"):
        issues.append({"severity": "major", "code": "source_summary_path_invalid", "shard": shard.get("path", "")})
    for key in ["path", "verified_findings", "analysis", "evidence"]:
        relative = str(shard.get(key, "")).strip()
        if relative and not (run.run_dir / relative).exists():
            issues.append({"severity": "major", "code": "shard_artifact_missing", "shard": shard.get("path", ""), "field": key, "path": relative})
    shard_relative = str(shard.get("path", "")).strip()
    if shard_relative:
        shard_text = validate_required_file(issues, run, run.run_dir / shard_relative, shard_relative)
        validate_markdown_human_language(issues, shard_relative, shard_text)
    validate_source_summary_blueprint(issues, run, shard)
    candidate_pages = shard.get("candidate_wiki_pages")
    if not isinstance(candidate_pages, list) or not candidate_pages:
        issues.append({"severity": "major", "code": "candidate_pages_missing", "shard": shard.get("path", "")})
    else:
        for page in candidate_pages:
            page_text = str(page)
            if not page_text.startswith("wiki/entities/code/") or not page_text.endswith(".md"):
                issues.append({"severity": "major", "code": "candidate_page_invalid", "shard": shard.get("path", ""), "page": page_text})
    blueprints = shard.get("page_blueprints")
    if not isinstance(blueprints, list) or not blueprints:
        issues.append({"severity": "major", "code": "page_blueprints_missing", "shard": shard.get("path", "")})
        return
    primary_pages = shard.get("primary_wiki_pages")
    if not isinstance(primary_pages, list) or not primary_pages:
        issues.append({"severity": "major", "code": "primary_pages_missing", "shard": shard.get("path", "")})
    elif len(blueprints) != len(primary_pages):
        issues.append(
            {
                "severity": "major",
                "code": "page_blueprints_not_limited_to_primary_pages",
                "shard": shard.get("path", ""),
                "blueprints": len(blueprints),
                "primary_pages": len(primary_pages),
            }
        )
    for blueprint in blueprints:
        validate_blueprint(issues, run, str(blueprint), shard)


def validate_source_summary_blueprint(issues: list[dict], run: CodeRun, shard: dict) -> None:
    relative = str(shard.get("source_summary_blueprint", "")).strip()
    if not relative:
        return
    path = run.run_dir / relative
    text = validate_required_file(issues, run, path, relative)
    if not text:
        return
    validate_markdown_human_language(issues, relative, text)
    for required in [
        "不是正式 wiki 正文",
        "source_summary_path:",
        "source_shard:",
        "verified_findings:",
        "analysis:",
        "evidence:",
        "frontmatter sources",
    ]:
        if required not in text:
            issues.append({"severity": "major", "code": "source_summary_blueprint_contract_missing", "path": relative, "text": required})


def validate_blueprint(issues: list[dict], run: CodeRun, relative: str, shard: dict) -> None:
    path = run.run_dir / relative
    text = validate_required_file(issues, run, path, relative)
    if not text:
        return
    validate_markdown_human_language(issues, relative, text)
    for heading in REQUIRED_FIXED_HEADINGS:
        if f"## {heading}" not in text:
            issues.append({"severity": "major", "code": "blueprint_required_heading_missing", "path": relative, "heading": heading})
        section = markdown_section_body(text, heading)
        if section and blueprint_section_is_process_instruction(section):
            issues.append({"severity": "major", "code": "blueprint_section_process_instruction", "path": relative, "heading": heading})
    for required in ["不是正式 wiki 正文", "preflight QUERY", "wiki_reconciliation", "candidate_wiki_page:", "verified_findings:", "evidence:"]:
        if required not in text:
            issues.append({"severity": "major", "code": "blueprint_contract_text_missing", "path": relative, "text": required})
    findings_path = run.run_dir / str(shard.get("verified_findings", ""))
    if not findings_path.exists() or not findings_path.is_file():
        return
    for finding in read_jsonl(findings_path):
        if finding.get("blocking_gaps"):
            issues.append({"severity": "major", "code": "blueprint_includes_blocking_gap_finding", "path": relative, "finding_id": finding.get("finding_id", "")})
        if not finding.get("evidence_refs"):
            issues.append({"severity": "major", "code": "verified_finding_evidence_refs_missing", "path": relative, "finding_id": finding.get("finding_id", "")})
        if not finding.get("coverage_claims"):
            issues.append({"severity": "major", "code": "verified_finding_coverage_claims_missing", "path": relative, "finding_id": finding.get("finding_id", "")})
        if str(finding.get("knowledge_level", "")) == "coding_playbook" and not isinstance(finding.get("coding_context"), dict):
            issues.append({"severity": "major", "code": "coding_playbook_context_missing", "path": relative, "finding_id": finding.get("finding_id", "")})


def validate_blueprint_uniqueness(issues: list[dict], run: CodeRun, shard: dict) -> None:
    seen: dict[str, str] = {}
    for relative in shard.get("page_blueprints", []) or []:
        path = run.run_dir / str(relative)
        if not path.exists() or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        normalized = normalize_blueprint_for_duplicate_check(text)
        if normalized in seen:
            issues.append(
                {
                    "severity": "major",
                    "code": "duplicate_page_blueprint_body",
                    "shard": shard.get("path", ""),
                    "path": str(relative),
                    "duplicate_of": seen[normalized],
                }
            )
        else:
            seen[normalized] = str(relative)


def normalize_blueprint_for_duplicate_check(text: str) -> str:
    lines = []
    for line in text.splitlines():
        if line.startswith("# KCode 正式页落页蓝图："):
            continue
        if line.startswith("- candidate_wiki_page:"):
            continue
        lines.append(line.strip())
    return "\n".join(lines).strip()


def markdown_section_body(text: str, heading: str) -> str:
    pattern = re.compile(rf"^## {re.escape(heading)}\s*$", re.MULTILINE)
    match = pattern.search(text)
    if not match:
        return ""
    next_heading = re.search(r"^## \S.*$", text[match.end() :], re.MULTILINE)
    end = match.end() + next_heading.start() if next_heading else len(text)
    return text[match.end() : end].strip()


def blueprint_section_is_process_instruction(section: str) -> bool:
    compact = section.strip()
    if not compact:
        return True
    return any(marker in compact for marker in BLUEPRINT_PROCESS_INSTRUCTION_MARKERS)


def contains_chinese_text(value: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", value))


def validate_markdown_human_language(issues: list[dict], relative_label: str, text: str) -> None:
    if not text:
        return
    in_fence = False
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or markdown_line_is_language_neutral(stripped):
            continue
        human_part = strip_inline_code(stripped)
        suffix = human_suffix_after_label(human_part)
        if suffix:
            human_part = suffix
        if looks_like_english_human_sentence(human_part):
            issues.append(
                {
                    "severity": "major",
                    "code": "handoff_human_text_not_chinese",
                    "path": relative_label,
                    "line": line_number,
                }
            )


def markdown_line_is_language_neutral(value: str) -> bool:
    if not value:
        return True
    if value.startswith("|") or re.fullmatch(r"[-:| ]+", value):
        return True
    if re.fullmatch(r"[-*]\s+[A-Za-z0-9_ -]+:\s*[^。！？；，、]*", value):
        return True
    return False


def strip_inline_code(value: str) -> str:
    return re.sub(r"`[^`]*`", "", value)


def human_suffix_after_label(value: str) -> str:
    if not contains_chinese_text(value):
        return value
    for delimiter in ("：", ":"):
        if delimiter in value:
            _label, suffix = value.split(delimiter, 1)
            return suffix.strip()
    return ""


def looks_like_english_human_sentence(value: str) -> bool:
    if not value or contains_chinese_text(value):
        return False
    if not re.search(r"\s", value):
        return False
    normalized = re.sub(r"\S+=\S+", " ", value)
    normalized = re.sub(r"\b(covered|not_applicable|blocking_gap)\b", " ", normalized)
    words = re.findall(r"(?<![/_.-])\b[A-Za-z]{2,}\b(?![/_.-])", normalized)
    return len(words) >= 5


def render_manager_request(run: CodeRun, shards: list[dict]) -> str:
    acceptance_query = acceptance_query_for_shards(shards)
    requires_feature_profile = acceptance_requires_feature_profile(shards)
    rows = ["| 分片 | 主题 | 来源批次 |", "| --- | --- | --- |"]
    for item in shards:
        rows.append(f"| {item['path']} | {item['topic']} | {item['source_batch']} |")
    source_rows = ["| 分片 | 来源摘要页 | 来源摘要蓝图 |", "| --- | --- | --- |"]
    for item in shards:
        source_rows.append(
            "| "
            + str(item["path"])
            + " | "
            + str(item.get("source_summary_path", ""))
            + " | "
            + str(item.get("source_summary_blueprint", ""))
            + " |"
        )
    page_rows = ["| 分片 | 来源摘要页 | 主正式代码页 | 备选候选页 | 知识层级 | 落页蓝图 |", "| --- | --- | --- | --- | --- | --- |"]
    for item in shards:
        primary_pages = [str(path) for path in item.get("primary_wiki_pages", [])]
        alternate_pages = [str(path) for path in item.get("candidate_wiki_pages", []) if str(path) not in set(primary_pages)]
        page_rows.append(
            "| "
            + str(item["path"])
            + " | "
            + str(item.get("source_summary_path", ""))
            + " | "
            + "<br>".join(primary_pages)
            + " | "
            + ("<br>".join(alternate_pages) if alternate_pages else "无")
            + " | "
            + ", ".join(str(level) for level in item.get("knowledge_levels", []))
            + " | "
            + "<br>".join(str(path) for path in item.get("page_blueprints", []))
            + " |"
        )
    return (
        "# Knowledge Manager 维护请求\n\n"
        "## 目标\n\n"
        f"- knowledge_id: {run.workspace.knowledge_id}\n"
        f"- knowledge_root: {run.workspace.knowledge_root}\n"
        f"- kcode_run_id: {run.run_id}\n"
        "- manifest: handoff/manifest.json\n"
        f"- human_readable_output_language: {KCODE_HUMAN_READABLE_OUTPUT_LANGUAGE}\n"
        "- 任务类型: KCode handoff 整理维护\n\n"
        "## 请求\n\n"
        "请优先读取 `handoff/manifest.json`，并按 `knowledge-manager-agent.toml` 维护 selected knowledge root，"
        "把下列已验证 KCode handoff 分片沉淀为正式 Karpathy Wiki 代码知识页；Markdown 表格仅供人工检查，机器处理以 manifest 为准。\n\n"
        "所有新增或更新的正式 wiki Markdown 正文、人读摘要、缺口说明和 verifier handoff 说明必须使用中文；"
        "schema id、JSON 字段名、路径、代码标识符、命令、API endpoint、枚举值、类名和函数名保持原文。\n\n"
        "必须先执行 preflight QUERY 和 wiki_reconciliation；不得把 `state/kcode-runs/**` artifact 原样复制成正式 wiki 正文；"
        "不得写入带 `blocking_gaps` 的 finding；写入后必须准备 verifier handoff。\n\n"
        "## 输入分片\n\n"
        + "\n".join(rows)
        + "\n\n"
        "## 来源摘要页蓝图\n\n"
        + "\n".join(source_rows)
        + "\n\n"
        "## 建议输出页面\n\n"
        + "\n".join(page_rows)
        + "\n\n"
        "## 正式页面要求\n\n"
        "- 先参考 `handoff/source-summary-blueprints/*.md` 为 handoff 建立或更新 `wiki/sources/code/kcode-runs/<run_id>/<shard>.md` source summary，保留 handoff、analysis、evidence、verified findings 的追溯路径。\n"
        "- 优先参考 `handoff/page-blueprints/*.md` 的主落页固定章节映射，但它只是交接蓝图，不是正式 wiki 正文；正式写入前仍要执行 preflight QUERY 和 wiki_reconciliation。\n"
        "- 每个正式代码知识页 frontmatter `sources` 必须包含对应 `source_summary_path`；`state/kcode-runs/**` artifact 只能作为 source summary 的来源材料，不得作为正式代码页唯一来源。\n"
        "- `候选正式代码页` 中没有落页蓝图的路径只作为 wiki_reconciliation 和后续拆页参考；不得把同一条 finding 机械复制成多个重复正式页。\n"
        "- 为 feature implementation 或 coding playbook 建立或更新 `wiki/entities/code/features/**` 页面；code map 才写入 `wiki/entities/code/modules/**`。\n"
        "- feature 页面必须使用固定二级标题：`## 现有实现`、`## 代码定位`、`## 实现链`、`## 复用边界`、`## 改动点`、`## 暂不应改动`、`## 数据/权限/运行约束`、`## 测试/验证路径`、`## PRD 设计影响`、`## 缺口与继续探索`。\n"
        "- 固定章节必须有实质内容，不能只有标题或占位语；`## 代码定位` 必须包含仓库相对路径、类名、函数名、endpoint、配置名或测试入口之一。\n"
        "- 每个正式 `wiki/entities/code/features/**` 页面都必须独立支撑 Agentic Coding / PRD 设计查询所需章节；不得把 `代码定位`、`复用边界`、`改动点`、`约束`、`测试/验证路径` 等必要内容拆散到多个 feature 页后依赖 query-bundle 拼接通过。\n"
        "- 正式 wiki 页面所有人读正文必须使用中文；代码路径、类名、函数名、endpoint、配置名和测试入口保持原文。\n"
        "- 代码定位必须保留仓库相对路径、类名、函数名、endpoint、配置名和测试入口；这些标识保持原文。\n"
        "- `wiki/index.md` 摘要必须包含能力名、模块名、关键代码路径或 endpoint 线索，保证 `/k query` 可召回。\n"
        "- 同步判断并更新 `wiki/log.md`、必要时 `wiki/overview.md` 和 `relations/` decision。\n\n"
        "## 验收检查\n\n"
        "- `python -m knowledge_kit lint -k "
        + run.workspace.knowledge_id
        + "` 不再报告 `code_knowledge_pages_missing`、`code_knowledge_index_missing` 或代码 feature 固定章节缺失。\n"
        "- `/k query -k "
        + run.workspace.knowledge_id
        + f" \"{acceptance_query}\"` 的 query bundle 必须选中正式代码知识页。"
        + (
            "`evidence_pages` 至少包含一个 `wiki/entities/code/features/**` 页面，并且不得返回 `profile_no_evidence_pages`、`profile_code_feature_evidence_missing`、`profile_code_feature_source_trace_missing`、`profile_code_feature_source_summary_missing`、`profile_required_section_missing` 或 `profile_query_topic_not_covered`。\n"
            if requires_feature_profile
            else "code_map-only handoff 必须选中 `wiki/entities/code/modules/**` 导航页，并给出可继续探索的 repo/入口线索。\n"
        )
        + "- 如果 query bundle 返回的 `profile_required_section_missing` 带有具体 `path`，必须修复该 path 对应页面，不能用其他页面内容抵消。\n"
        "- knowledge-verifier 的 focus 必须覆盖：代码引用完整性、`coding_context` 是否落入正式页面、`blocking_gaps` 未被写成事实、index 是否可召回、schema 是否包含 Code Knowledge 约定。\n"
    )


def write_source_summary_blueprint(run: CodeRun, blueprints_dir: Path, shard: dict, findings: list[dict]) -> str:
    filename = f"{safe_file_stem(shard['path'])}.md"
    target = blueprints_dir / filename
    target.write_text(render_source_summary_blueprint(run, shard, findings), encoding="utf-8")
    return target.relative_to(run.run_dir).as_posix()


def render_source_summary_blueprint(run: CodeRun, shard: dict, findings: list[dict]) -> str:
    lines = [
        f"# KCode 来源摘要蓝图：{shard.get('source_summary_path', '')}",
        "",
        "## 目标",
        "",
        f"- knowledge_id: {run.workspace.knowledge_id}",
        f"- run_id: {run.run_id}",
        f"- source_summary_path: {shard.get('source_summary_path', '')}",
        f"- source_shard: {shard.get('path', '')}",
        f"- verified_findings: {shard.get('verified_findings', '')}",
        f"- analysis: {shard.get('analysis', '')}",
        f"- evidence: {shard.get('evidence', '')}",
        f"- human_readable_output_language: {KCODE_HUMAN_READABLE_OUTPUT_LANGUAGE}",
        "",
        "## 使用边界",
        "",
        "- 这是交接蓝图，不是正式 wiki 正文；正式写入前仍必须执行 preflight QUERY 和 wiki_reconciliation。",
        "- source summary 是正式代码知识页 frontmatter sources 的可引用来源页；正式代码知识页不得只引用 `state/kcode-runs/**` artifact。",
        "- source summary 应概括 handoff、analysis、evidence、verified findings 的来源范围和追溯路径，不得原样复制 state artifact。",
        "- frontmatter sources 应保留原始 KCode 运行材料路径；正文人读内容必须使用中文。",
        "",
        "## 正式 source summary 应包含",
        "",
        f"- 目标路径：`{shard.get('source_summary_path', '')}`",
        f"- 对应分片：`{shard.get('path', '')}`",
        f"- 分析材料：`{shard.get('analysis', '')}`",
        f"- 证据材料：`{shard.get('evidence', '')}`",
        f"- 已验证发现：`{shard.get('verified_findings', '')}`",
        "- 摘要需说明本分片覆盖的能力、知识层级、候选正式页和主要代码证据类型。",
        "- 摘要需列出非阻断缺口和后续探索提示，但不得把缺口写成当前实现事实。",
        "",
        "## 已验证发现索引",
        "",
    ]
    for finding in findings:
        lines.append(f"- `{finding.get('finding_id', '')}`：{finding.get('title', '')}；knowledge_level=`{finding.get('knowledge_level', '')}`；confidence={finding.get('confidence', '')}。")
    lines.extend(
        [
            "",
            "## 候选正式页",
            "",
        ]
    )
    for page in shard.get("primary_wiki_pages", []) or []:
        lines.append(f"- 主落页：`{page}`")
    for page in shard.get("candidate_wiki_pages", []) or []:
        if page not in set(shard.get("primary_wiki_pages", []) or []):
            lines.append(f"- 备选候选页：`{page}`")
    lines.extend(
        [
            "",
            "## 禁止事项",
            "",
            "- 不得把本 source summary 写成 Agentic Coding 正式代码知识页。",
            "- 不得把 source summary 作为 query-bundle 的主要 evidence 来替代 `wiki/entities/code/features/**` 或 `wiki/entities/code/modules/**` 页面。",
            "- 不得把带 `blocking_gaps` 的 finding 写成当前实现。",
        ]
    )
    return "\n".join(lines) + "\n"


def write_page_blueprints(run: CodeRun, blueprints_dir: Path, shard: dict, findings: list[dict]) -> list[str]:
    result: list[str] = []
    for index, candidate in enumerate(shard.get("primary_wiki_pages", []) or [], start=1):
        filename = page_blueprint_filename(str(shard["source_batch"]), index, str(candidate))
        target = blueprints_dir / filename
        target.write_text(render_page_blueprint(run, shard, str(candidate), findings), encoding="utf-8")
        result.append(target.relative_to(run.run_dir).as_posix())
    return result


def render_page_blueprint(run: CodeRun, shard: dict, candidate_page: str, findings: list[dict]) -> str:
    levels = ", ".join(str(level) for level in shard.get("knowledge_levels", []))
    is_code_map = bool(shard.get("knowledge_levels")) and all(str(level) == "code_map" for level in shard.get("knowledge_levels", []))
    lines = [
        f"# KCode 正式页落页蓝图：{candidate_page}",
        "",
        "## 目标",
        "",
        f"- knowledge_id: {run.workspace.knowledge_id}",
        f"- run_id: {run.run_id}",
        f"- candidate_wiki_page: {candidate_page}",
        f"- source_summary_path: {shard.get('source_summary_path', '')}",
        f"- source_shard: {shard.get('path', '')}",
        f"- verified_findings: {shard.get('verified_findings', '')}",
        f"- analysis: {shard.get('analysis', '')}",
        f"- evidence: {shard.get('evidence', '')}",
        f"- knowledge_levels: {levels}",
        f"- human_readable_output_language: {KCODE_HUMAN_READABLE_OUTPUT_LANGUAGE}",
        "",
        "## 使用边界",
        "",
        "- 这是交接蓝图，不是正式 wiki 正文；正式写入前仍必须执行 preflight QUERY 和 wiki_reconciliation。",
        "- 只能沉淀无 `blocking_gaps` 的 verified findings；非阻断缺口和探索提示必须写入缺口，不得写成当前事实。",
        f"- 正式页 frontmatter `sources` 必须包含 `{shard.get('source_summary_path', '')}`；不得把 `state/kcode-runs/**` artifact 作为正式页唯一来源。",
        "- 代码路径、类名、函数名、endpoint、命令、配置名和枚举值保持原文。",
    ]
    if is_code_map:
        lines.append("- 本页是 `code_map` 导航页，只能沉淀仓库用途、模块边界、入口和继续探索路径；不得写成可直接编码的功能实现结论。")
    lines.extend(["", "## 现有实现", ""])
    lines.extend(render_finding_text_values(findings, "current_state", fallback="当前 handoff 未提供现有实现说明。"))
    lines.extend(["", "## 代码定位", ""])
    lines.extend(render_evidence_refs(findings))
    lines.extend(["", "## 实现链", ""])
    lines.extend(render_coverage_claims(findings))
    lines.extend(["", "## 复用边界", ""])
    lines.extend(render_context_section(findings, "reuse_points", page_blueprint_fallback(is_code_map, "reuse")))
    lines.extend(["", "## 改动点", ""])
    lines.extend(render_context_section(findings, "change_points", page_blueprint_fallback(is_code_map, "change")))
    lines.extend(["", "## 暂不应改动", ""])
    lines.extend(render_context_section(findings, "do_not_change_without_extra_exploration", page_blueprint_fallback(is_code_map, "avoid")))
    lines.extend(["", "## 数据/权限/运行约束", ""])
    lines.extend(render_context_section(findings, "data_contracts", page_blueprint_fallback(is_code_map, "constraints")))
    lines.extend(render_context_section(findings, "runtime_constraints", "", prefix_when_present=False))
    lines.extend(["", "## 测试/验证路径", ""])
    lines.extend(render_context_section(findings, "verification_entrypoints", page_blueprint_fallback(is_code_map, "verification")))
    lines.extend(["", "## PRD 设计影响", ""])
    lines.extend(render_finding_list_values(findings, "design_implications", fallback="本 batch 未提供 PRD 设计影响字段；不能从目录结构自行推断设计结论。"))
    lines.extend(["", "## 缺口与继续探索", ""])
    lines.extend(render_gaps_and_hints(findings))
    return "\n".join(lines) + "\n"


def page_blueprint_fallback(is_code_map: bool, section: str) -> str:
    if is_code_map:
        values = {
            "reuse": "本页是 `code_map` 导航页；可复用的是仓库选择、入口定位和继续探索路径，不得把本页当作功能实现复用边界。",
            "change": "本页不提供可直接执行的改动方案；具体新增或变更点必须先进入对应 feature/coding batch 的页面、API、controller/service/repository、配置或测试入口继续确认。",
            "avoid": "不得仅凭本页修改业务逻辑、权限、运行时 wiring、公共合同、存储合同或跨模块边界；这些内容需要功能级证据链支撑。",
            "constraints": "本页只说明入口和模块边界，不声明字段合同、权限规则或运行时约束；相关约束必须从 feature_implementation 或 coding_playbook 页面读取。",
            "verification": "本页未验证功能级测试路径；只能作为定位测试入口的导航线索，不能替代具体功能的测试或手工验证方案。",
        }
        return values[section]
    values = {
        "reuse": "可复用范围限定在本页已验证实现链：`代码定位` 中列出的页面、API、controller/service/repository、配置或外部接口。未在 `实现链` 覆盖声明中出现的跨模块能力不作为可复用事实。",
        "change": "本页是 `feature_implementation` 现有实现页；具体新增或变更点需要沿 `代码定位` 的入口和 `实现链` 的已覆盖层继续确认。本页只提供变更起点，不声明具体改动方案已确定。",
        "avoid": "未完成目标功能级探索前，不应修改权限、运行时 wiring、公共合同、存储合同或跨模块边界；这些边界需回到本页证据和缺口继续确认。",
        "constraints": "当前可确定的是：约束来源限定在 `实现链` 中覆盖的 DTO/schema/table/权限/配置/运行时 wiring；本 batch 没有单独给出 `coding_context.data_contracts`，所以不能声明未被 evidence refs 覆盖的字段合同。",
        "verification": "当前未证明自动化测试路径；测试层 coverage claim 为 `not_applicable` 或没有 `coding_context.verification_entrypoints` 时，只能把验证入口列为缺口，并沿探索提示继续定位测试或手工 QA 文档。",
    }
    return values[section]


def render_finding_text_values(findings: list[dict], field: str, *, fallback: str) -> list[str]:
    values = [str(finding.get(field, "")).strip() for finding in findings if str(finding.get(field, "")).strip()]
    return [f"- {value}" for value in values] or [f"- {fallback}"]


def render_finding_list_values(findings: list[dict], field: str, *, fallback: str) -> list[str]:
    values: list[str] = []
    for finding in findings:
        for value in finding.get(field, []) if isinstance(finding.get(field), list) else []:
            text = str(value).strip()
            if text:
                values.append(text)
    return [f"- {value}" for value in values] or [f"- {fallback}"]


def render_evidence_refs(findings: list[dict]) -> list[str]:
    lines: list[str] = []
    for finding in findings:
        finding_id = str(finding.get("finding_id", "")).strip()
        refs = finding.get("evidence_refs", [])
        if not isinstance(refs, list) or not refs:
            continue
        lines.append(f"- {finding_id or 'finding'} 证据定位：")
        lines.extend(f"  - `{ref}`" for ref in refs)
    return lines or ["- 当前 handoff 未提供可解析 evidence refs，正式页不得写入代码定位结论。"]


def render_coverage_claims(findings: list[dict]) -> list[str]:
    lines: list[str] = []
    for finding in findings:
        finding_id = str(finding.get("finding_id", "")).strip()
        claims = finding.get("coverage_claims", [])
        if not isinstance(claims, list) or not claims:
            continue
        lines.append(f"- {finding_id or 'finding'} 覆盖声明：")
        for claim in claims:
            if not isinstance(claim, dict):
                continue
            refs = claim.get("evidence_refs") if isinstance(claim.get("evidence_refs"), list) else []
            refs_text = "；证据: " + ", ".join(f"`{ref}`" for ref in refs) if refs else ""
            lines.append(f"  - `{claim.get('item', '')}` = `{claim.get('status', '')}`{refs_text}")
    return lines or ["- 当前 handoff 未提供 coverage_claims，正式页不得声称实现链闭合。"]


def render_context_section(findings: list[dict], key: str, fallback: str, *, prefix_when_present: bool = True) -> list[str]:
    lines: list[str] = []
    for finding in findings:
        context = finding.get("coding_context")
        if not isinstance(context, dict):
            continue
        values = context.get(key)
        if not isinstance(values, list) or not values:
            continue
        if prefix_when_present:
            lines.append(f"- 来自 `{finding.get('finding_id', '')}` 的 `{key}`：")
        for item in values:
            if isinstance(item, dict):
                summary = str(item.get("summary", "")).strip()
                refs = item.get("evidence_refs") if isinstance(item.get("evidence_refs"), list) else []
                suffix = "（证据: " + ", ".join(f"`{ref}`" for ref in refs) + "）" if refs else ""
                if summary:
                    lines.append(f"  - {summary}{suffix}" if prefix_when_present else f"- {summary}{suffix}")
            elif str(item).strip():
                lines.append(f"  - {item}" if prefix_when_present else f"- {item}")
    if lines:
        return lines
    return [f"- {fallback}"] if fallback else []


def render_gaps_and_hints(findings: list[dict]) -> list[str]:
    lines: list[str] = []
    for finding in findings:
        finding_id = str(finding.get("finding_id", "")).strip()
        for gap in finding.get("non_blocking_gaps", []) if isinstance(finding.get("non_blocking_gaps"), list) else []:
            lines.append(f"- 非阻断缺口（{finding_id}）: {format_structured_value(gap)}")
        for hint in finding.get("exploration_hints", []) if isinstance(finding.get("exploration_hints"), list) else []:
            lines.append(f"- 探索提示（{finding_id}）: {format_structured_value(hint)}")
    return lines or ["- 已验证 finding 未报告非阻断缺口或探索提示。"]


def safe_file_stem(value: str) -> str:
    normalized = value.replace("\\", "/").removesuffix(".md")
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", normalized).strip("-").lower()
    return stem[-120:] or "page"


def short_file_stem(value: str, *, max_length: int = 32) -> str:
    normalized = value.replace("\\", "/").removesuffix(".md")
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", normalized).strip("-").lower() or "page"
    return stem[-max_length:]


def stable_short_hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]


def page_blueprint_filename(source_batch: str, index: int, candidate_page: str) -> str:
    return f"{short_file_stem(source_batch)}-{index:02d}-{short_file_stem(candidate_page)}-{stable_short_hash(candidate_page)}.md"


def candidate_wiki_pages(batch_name: str, findings: list[dict]) -> list[str]:
    candidates: list[str] = []
    levels = [str(finding.get("knowledge_level", "")) for finding in findings]
    preferred_level = "code_map" if levels and all(level == "code_map" for level in levels) else "feature_implementation"
    for finding in findings:
        level = str(finding.get("knowledge_level", preferred_level))
        for item in finding.get("knowledge_object_candidates", []) or []:
            normalized = normalize_code_candidate_path(str(item), level)
            if normalized:
                candidates.append(normalized)
    if not candidates:
        candidates.append(fallback_candidate_page(batch_name, preferred_level))
    return unique(candidates)


def primary_wiki_pages(batch_name: str, findings: list[dict]) -> list[str]:
    candidates: list[str] = []
    levels = [str(finding.get("knowledge_level", "")) for finding in findings]
    preferred_level = "code_map" if levels and all(level == "code_map" for level in levels) else "feature_implementation"
    for finding in findings:
        level = str(finding.get("knowledge_level", preferred_level))
        normalized_candidates = [
            normalize_code_candidate_path(str(item), level)
            for item in finding.get("knowledge_object_candidates", []) or []
        ]
        first_candidate = next((candidate for candidate in normalized_candidates if candidate), "")
        candidates.append(first_candidate or fallback_candidate_page(batch_name, level))
    return unique(candidates)


def normalize_code_candidate_path(path: str, knowledge_level: str) -> str:
    normalized = path.replace("\\", "/").strip()
    if not normalized.startswith("wiki/entities/code/"):
        return ""
    if normalized.startswith("wiki/entities/code/features/") or normalized.startswith("wiki/entities/code/modules/"):
        return normalized
    rest = normalized.removeprefix("wiki/entities/code/").lstrip("/")
    bucket = "modules" if knowledge_level == "code_map" else "features"
    return f"wiki/entities/code/{bucket}/{rest}"


def fallback_candidate_page(batch_name: str, knowledge_level: str) -> str:
    cleaned = re.sub(r"^B\d+-", "", batch_name)
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", cleaned).strip("-").lower() or "code-knowledge"
    bucket = "modules" if knowledge_level == "code_map" else "features"
    return f"wiki/entities/code/{bucket}/{slug}.md"


def unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def render_shard(run: CodeRun, findings_path: Path, findings: list[dict], topic: str) -> str:
    lines = [
        f"# KCode 交接材料：{topic}",
        "",
        "## 目标",
        "",
        f"- knowledge_id: {run.workspace.knowledge_id}",
        f"- knowledge_root: {run.workspace.knowledge_root}",
        f"- run_id: {run.run_id}",
        f"- shard_id: {findings_path.parent.name}",
        "",
        "## 维护任务",
        "",
        f"使用下方已验证代码发现，更新 `{topic}` 对应的现有实现知识。",
        "",
        "## 材料",
        "",
        f"- {findings_path.relative_to(run.run_dir).as_posix()}",
        f"- {findings_path.parent.relative_to(run.run_dir).as_posix()}/analysis.md",
        f"- {findings_path.parent.relative_to(run.run_dir).as_posix()}/evidence.json",
        "",
        "## 已验证发现",
        "",
    ]
    for finding in findings:
        lines.extend(
            [
                f"### {finding.get('finding_id', '')} - {finding.get('title', '')}",
                "",
                f"- 类型: {finding.get('kind', '')}",
                f"- 知识层级: {finding.get('knowledge_level', '')}",
                f"- 当前状态: {finding.get('current_state', '')}",
                f"- 证据: {', '.join(str(item) for item in finding.get('evidence_refs', []))}",
                f"- 覆盖声明: {format_coverage_claims(finding.get('coverage_claims', []))}",
                f"- 置信度: {finding.get('confidence', '')}",
                f"- 设计影响: {', '.join(str(item) for item in finding.get('design_implications', []))}",
                "",
            ]
        )
        coding_context = finding.get("coding_context")
        if isinstance(coding_context, dict):
            lines.extend(render_coding_context(coding_context))
    lines.extend(["## 缺口", ""])
    non_blocking = [gap for finding in findings for gap in finding.get("non_blocking_gaps") or []]
    hints = [hint for finding in findings for hint in finding.get("exploration_hints") or []]
    if non_blocking:
        lines.extend(f"- 非阻断缺口: {format_structured_value(gap)}" for gap in non_blocking)
    if hints:
        lines.extend(f"- 探索提示: {format_structured_value(hint)}" for hint in hints)
    if not non_blocking and not hints:
        lines.append("- 已验证 finding 未报告非阻断缺口。")
    return "\n".join(lines) + "\n"


def format_coverage_claims(claims: list[dict]) -> str:
    if not isinstance(claims, list):
        return ""
    values = []
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        item = claim.get("item", "")
        status = claim.get("status", "")
        if item or status:
            values.append(f"{item}={status}")
    return ", ".join(values)


def format_structured_value(value) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def render_coding_context(context: dict) -> list[str]:
    sections = [
        ("change_points", "改动点"),
        ("reuse_points", "复用点"),
        ("do_not_change_without_extra_exploration", "暂不应改动"),
        ("data_contracts", "数据约束"),
        ("runtime_constraints", "运行约束"),
        ("verification_entrypoints", "验证入口"),
    ]
    lines = ["#### 编码上下文", ""]
    for key, label in sections:
        values = context.get(key)
        if not isinstance(values, list) or not values:
            continue
        lines.append(f"- {label}:")
        for item in values:
            if isinstance(item, dict):
                summary = str(item.get("summary", "")).strip()
                refs = item.get("evidence_refs") or []
                suffix = f"（证据: {', '.join(str(ref) for ref in refs)}）" if refs else ""
                lines.append(f"  - {summary}{suffix}")
            else:
                lines.append(f"  - {item}")
    lines.append("")
    return lines

from __future__ import annotations

import json
import re
from pathlib import Path

from knowledge_kit.workflow_contract import KCODE_CONTINUATION_POLICY, KCODE_HUMAN_READABLE_OUTPUT_LANGUAGE, KCODE_LANGUAGE_POLICY, KCODE_REQUIRES_LLM_KIND

from .coverage_contract import (
    AGENTIC_CODING_COVERAGE_CONTRACT,
    CODING_CONTEXT_REQUIRED_FIELDS,
    VALID_COVERAGE_STATUSES,
    VALID_KNOWLEDGE_LEVELS,
    requirements_for_level,
)
from .evidence import batch_slug, load_plan, select_batch
from .models import CodeRun
from .workspace import code_stage_command, codex_next_step, mark_stage


CHINESE_TEXT_RE = re.compile(r"[\u3400-\u9fff]")
HUMAN_READABLE_JSON_FIELD_NAMES = {
    "analysis_questions",
    "blocking_gaps",
    "coverage_notes",
    "current_state",
    "description",
    "design_implications",
    "detail",
    "exploration_hints",
    "message",
    "non_blocking_gaps",
    "note",
    "notes",
    "reason",
    "required_repairs",
    "rationale",
    "summary",
    "suggestions",
    "title",
}


def verify_plan(run: CodeRun) -> dict:
    verifier_dir = run.run_dir / "verifier"
    verifier_dir.mkdir(parents=True, exist_ok=True)
    plan_path = run.run_dir / "plan" / "analysis-plan.json"
    ledger_path = run.run_dir / "plan" / "coverage-ledger.json"
    report_path = verifier_dir / "plan-verification.json"
    if not plan_path.exists():
        mark_stage(run, "plan_verification", "blocked")
        return {"status": "failed", "error": "analysis_plan_missing"}
    if not ledger_path.exists():
        mark_stage(run, "plan_verification", "blocked")
        return {"status": "failed", "error": "coverage_ledger_missing"}
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    analysis_plan_path = run.run_dir / "plan" / "analysis-plan.md"
    analysis_plan_text = analysis_plan_path.read_text(encoding="utf-8") if analysis_plan_path.exists() else ""
    deterministic = deterministic_plan_check(plan, ledger, analysis_plan_text)
    deterministic_path = verifier_dir / "plan-deterministic-verification.json"
    deterministic_path.write_text(json.dumps(deterministic, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not deterministic["passed"]:
        mark_stage(run, "plan_verification", "blocked", {"plan_deterministic_verification": deterministic_path.relative_to(run.run_dir).as_posix()})
        return {"status": "failed", "deterministic": deterministic}
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report_language_issues = verifier_report_language_issues(report, "verifier/plan-verification.json")
        if report_language_issues:
            deterministic["issues"].extend(report_language_issues)
            deterministic["passed"] = False
            deterministic_path.write_text(json.dumps(deterministic, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            mark_stage(run, "plan_verification", "blocked", {"plan_deterministic_verification": deterministic_path.relative_to(run.run_dir).as_posix()})
            return {"status": "failed", "deterministic": deterministic}
        if report.get("passed") is True:
            mark_stage(
                run,
                "plan_verification",
                "passed",
                {
                    "analysis_plan": "plan/analysis-plan.json",
                    "coverage_ledger": "plan/coverage-ledger.json",
                    "plan_verification": "verifier/plan-verification.json",
                },
            )
            mark_stage(run, "plan", "completed")
            return {
                "status": "completed",
                "verification": report,
                "run_id": run.run_id,
                "run_dir": str(run.run_dir),
                "next_command": code_stage_command(run, "evidence"),
            }
        mark_stage(run, "plan_verification", "blocked", {"plan_verification": "verifier/plan-verification.json"})
        return {"status": "failed", "verification": report}
    package = write_plan_verifier_input(run, verifier_dir)
    mark_stage(run, "plan_verification", "requires_llm", {"plan_verifier_input": package.relative_to(run.run_dir).as_posix()})
    expected_outputs = [report_path.relative_to(run.run_dir).as_posix()]
    next_step = codex_next_step(
        run,
        stage="plan-verify",
        agent="kcode-verifier",
        prompt="prompts/kcode-verifier.md",
        input_path=package.relative_to(run.run_dir).as_posix(),
        expected_outputs=expected_outputs,
        after_outputs_stage="plan-verify",
    )
    return {
        "kind": KCODE_REQUIRES_LLM_KIND,
        "status": "requires_llm",
        "continuation_policy": KCODE_CONTINUATION_POLICY,
        "run_id": run.run_id,
        "run_dir": str(run.run_dir),
        "agent": "kcode-verifier",
        "prompt": "prompts/kcode-verifier.md",
        "input": package.relative_to(run.run_dir).as_posix(),
        "human_readable_output_language": KCODE_HUMAN_READABLE_OUTPUT_LANGUAGE,
        "language_policy": KCODE_LANGUAGE_POLICY,
        "expected_outputs": expected_outputs,
        "after_writing_outputs_command": next_step["after_writing_outputs_command"],
        "codex_next_step": next_step,
    }


def verify_batch(run: CodeRun, batch_id: str | None) -> dict:
    plan = load_plan(run)
    batch = select_batch(plan, batch_id)
    batch_dir = run.run_dir / "batches" / batch_slug(batch)
    evidence_path = batch_dir / "evidence.json"
    analysis_path = batch_dir / "analysis.md"
    findings_path = batch_dir / "findings.jsonl"
    if analysis_path.exists() and findings_path.exists():
        mark_stage(run, "analyze", "completed")
    evidence = json.loads(evidence_path.read_text(encoding="utf-8")) if evidence_path.exists() else {"snippets": [], "files": []}
    findings = read_jsonl(findings_path)
    analysis_text = analysis_path.read_text(encoding="utf-8") if analysis_path.exists() else ""
    deterministic = deterministic_check(run, evidence, findings, analysis_text)
    deterministic_path = batch_dir / "deterministic-verification.json"
    deterministic_path.write_text(json.dumps(deterministic, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    semantic_path = batch_dir / "semantic-verification.json"
    if not deterministic["passed"]:
        mark_stage(run, "verify", "blocked", {f"batch_{batch.get('batch_id')}_deterministic_verification": deterministic_path.relative_to(run.run_dir).as_posix()})
        return {"status": "failed", "deterministic": deterministic}
    if not semantic_path.exists():
        package = write_semantic_verifier_input(run, batch, batch_dir)
        mark_stage(run, "verify", "requires_llm")
        expected_outputs = [semantic_path.relative_to(run.run_dir).as_posix()]
        next_step = codex_next_step(
            run,
            stage="verify",
            agent="kcode-verifier",
            prompt="prompts/kcode-verifier.md",
            input_path=package.relative_to(run.run_dir).as_posix(),
            expected_outputs=expected_outputs,
            after_outputs_stage="verify",
            batch_id=str(batch.get("batch_id") or ""),
        )
        return {
            "kind": "kcode_requires_llm",
            "status": "requires_llm",
            "continuation_policy": KCODE_CONTINUATION_POLICY,
            "run_id": run.run_id,
            "run_dir": str(run.run_dir),
            "agent": "kcode-verifier",
            "prompt": "prompts/kcode-verifier.md",
            "input": package.relative_to(run.run_dir).as_posix(),
            "human_readable_output_language": KCODE_HUMAN_READABLE_OUTPUT_LANGUAGE,
            "language_policy": KCODE_LANGUAGE_POLICY,
            "expected_outputs": expected_outputs,
            "after_writing_outputs_command": next_step["after_writing_outputs_command"],
            "codex_next_step": next_step,
        }
    semantic = json.loads(semantic_path.read_text(encoding="utf-8"))
    semantic_language_issues = verifier_report_language_issues(semantic, semantic_path.relative_to(run.run_dir).as_posix())
    if semantic_language_issues:
        deterministic["issues"].extend(semantic_language_issues)
        deterministic["passed"] = False
        deterministic_path.write_text(json.dumps(deterministic, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        mark_stage(run, "verify", "blocked", {f"batch_{batch.get('batch_id')}_deterministic_verification": deterministic_path.relative_to(run.run_dir).as_posix()})
        return {"status": "failed", "deterministic": deterministic, "semantic": semantic}
    if semantic.get("passed") is True:
        verified_ids = semantic.get("verified_finding_ids")
        if not isinstance(verified_ids, list) or not verified_ids:
            mark_stage(run, "verify", "blocked")
            return {"status": "failed", "deterministic": deterministic, "semantic": semantic, "error": "verified_finding_ids_missing"}
        selected = selected_findings(findings, semantic)
        if len(selected) != len(set(verified_ids)):
            mark_stage(run, "verify", "blocked")
            return {"status": "failed", "deterministic": deterministic, "semantic": semantic, "error": "verified_finding_ids_unknown"}
        blocking = blocking_gaps(selected)
        if blocking:
            mark_stage(run, "verify", "blocked")
            return {"status": "failed", "deterministic": deterministic, "semantic": semantic, "blocking_gaps": blocking}
        verified_path = batch_dir / "verified-findings.jsonl"
        write_verified_findings(findings_path, verified_path, semantic)
        mark_stage(run, "verify", "completed", {f"batch_{batch.get('batch_id')}_verified_findings": verified_path.relative_to(run.run_dir).as_posix()})
        return {
            "status": "completed",
            "deterministic": deterministic,
            "semantic": semantic,
            "verified_findings": str(verified_path),
            "run_id": run.run_id,
            "run_dir": str(run.run_dir),
            "next_command_if_all_batches_verified": code_stage_command(run, "handoff"),
            "next_instruction": "继续处理 plan/analysis-plan.json 中尚未完成的 batch；只有所有可通过 batch 都完成 verify 后才执行 handoff。",
        }
    mark_stage(run, "verify", "blocked")
    return {"status": "failed", "deterministic": deterministic, "semantic": semantic}


def deterministic_plan_check(plan: dict, ledger: dict, analysis_plan_text: str = "") -> dict:
    issues: list[dict] = []
    if not analysis_plan_text.strip():
        issues.append({"severity": "major", "code": "analysis_plan_markdown_missing"})
    elif not contains_chinese_text(analysis_plan_text):
        issues.append({"severity": "major", "code": "human_text_not_chinese", "artifact": "plan/analysis-plan.md"})
    issues.extend(json_human_language_issues(plan, "plan/analysis-plan.json"))
    issues.extend(json_human_language_issues(ledger, "plan/coverage-ledger.json"))
    batches = plan.get("batches")
    if not isinstance(batches, list) or not batches:
        issues.append({"severity": "major", "code": "plan_batches_missing"})
    for batch in batches or []:
        batch_id = str(batch.get("batch_id", ""))
        for field in ["batch_id", "slug", "repo_ids", "paths", "expected_outputs", "knowledge_level"]:
            if field not in batch:
                issues.append({"severity": "major", "code": "batch_field_missing", "batch_id": batch_id, "field": field})
        if "evidence_budget" in batch:
            issues.append({"severity": "major", "code": "legacy_evidence_budget", "batch_id": batch_id})
        level = str(batch.get("knowledge_level", ""))
        if level and level not in VALID_KNOWLEDGE_LEVELS:
            issues.append({"severity": "major", "code": "invalid_knowledge_level", "batch_id": batch_id, "knowledge_level": level})
        if not batch.get("paths") and not batch.get("entrypoints"):
            issues.append({"severity": "major", "code": "batch_has_no_code_seed", "batch_id": batch_id})
        validate_optional_chinese_field(issues, batch, "title", "plan_batch", batch_id)
        validate_optional_chinese_list(issues, batch, "analysis_questions", "plan_batch", batch_id)
        validate_optional_chinese_list(issues, batch, "notes", "plan_batch", batch_id)
        if level in {"feature_implementation", "coding_playbook"}:
            required_field = "required_claims" if level == "coding_playbook" else "required_layers"
            required = batch.get(required_field)
            if not isinstance(required, list) or not required:
                issues.append({"severity": "major", "code": f"{required_field}_missing", "batch_id": batch_id})
            else:
                contract_items = set(requirements_for_level(level))
                provided = {str(item) for item in required}
                invalid = sorted(provided - contract_items)
                missing = sorted(contract_items - provided)
                if invalid:
                    issues.append({"severity": "major", "code": f"{required_field}_not_in_contract", "batch_id": batch_id, "items": invalid})
                if missing:
                    issues.append({"severity": "major", "code": f"{required_field}_incomplete", "batch_id": batch_id, "items": missing})
            rules = batch.get("blocking_gap_rules")
            if not isinstance(rules, list) or not rules:
                issues.append({"severity": "major", "code": "blocking_gap_rules_missing", "batch_id": batch_id})
    items = ledger.get("items")
    if not isinstance(items, list):
        issues.append({"severity": "major", "code": "coverage_ledger_items_missing"})
    return {
        "schema_version": "kcode.verification.plan_deterministic.v1",
        "passed": not issues,
        "issues": issues,
        "checked_batches": len(batches or []),
    }


def deterministic_check(run: CodeRun, evidence: dict, findings: list[dict], analysis_text: str = "") -> dict:
    evidence_ids = {item.get("evidence_id") for item in evidence.get("snippets", [])}
    evidence_ranges = evidence_file_ranges(evidence)
    issues: list[dict] = []
    if not analysis_text.strip():
        issues.append({"severity": "major", "code": "analysis_markdown_missing", "artifact": "analysis.md"})
    elif not contains_chinese_text(analysis_text):
        issues.append({"severity": "major", "code": "human_text_not_chinese", "artifact": "analysis.md"})
    validate_evidence_bundle(evidence, findings, issues)
    if not findings:
        issues.append({"severity": "major", "code": "findings_missing", "finding_id": ""})
    for finding in findings:
        issues.extend(json_human_language_issues(finding, "finding", finding_id=str(finding.get("finding_id", ""))))
        for field in [
            "finding_id",
            "batch_id",
            "kind",
            "title",
            "current_state",
            "evidence_refs",
            "confidence",
            "knowledge_level",
            "coverage_claims",
            "blocking_gaps",
            "non_blocking_gaps",
            "exploration_hints",
        ]:
            if field not in finding:
                issues.append({"severity": "major", "code": "finding_field_missing", "finding_id": finding.get("finding_id", ""), "field": field})
        level = str(finding.get("knowledge_level", ""))
        validate_required_chinese_field(issues, finding, "title", "finding", finding.get("finding_id", ""))
        validate_required_chinese_field(issues, finding, "current_state", "finding", finding.get("finding_id", ""))
        validate_optional_chinese_list(issues, finding, "design_implications", "finding", finding.get("finding_id", ""))
        validate_gap_list_chinese(issues, finding, "blocking_gaps")
        validate_gap_list_chinese(issues, finding, "non_blocking_gaps")
        validate_gap_list_chinese(issues, finding, "exploration_hints")
        validate_knowledge_object_candidates(finding, level, issues)
        if level and level not in VALID_KNOWLEDGE_LEVELS:
            issues.append({"severity": "major", "code": "invalid_knowledge_level", "finding_id": finding.get("finding_id", ""), "knowledge_level": level})
        coverage_claims = finding.get("coverage_claims")
        if not isinstance(coverage_claims, list) or not coverage_claims:
            issues.append({"severity": "major", "code": "coverage_claims_missing", "finding_id": finding.get("finding_id", "")})
        else:
            validate_coverage_claims(evidence_ids, evidence_ranges, finding, level, coverage_claims, issues)
        if level == "coding_playbook":
            validate_coding_context(evidence_ids, evidence_ranges, finding, issues)
        if "gaps" in finding:
            issues.append({"severity": "major", "code": "legacy_gaps_field", "finding_id": finding.get("finding_id", "")})
        for field in ["blocking_gaps", "non_blocking_gaps", "exploration_hints"]:
            if field in finding and not isinstance(finding.get(field), list):
                issues.append({"severity": "major", "code": "finding_field_not_list", "finding_id": finding.get("finding_id", ""), "field": field})
        confidence = finding.get("confidence")
        if not isinstance(confidence, int | float) or not 0 <= float(confidence) <= 1:
            issues.append({"severity": "major", "code": "invalid_confidence", "finding_id": finding.get("finding_id", "")})
        for ref in finding.get("evidence_refs", []):
            ref_text = str(ref)
            if ref_text in evidence_ids:
                continue
            if not validate_evidence_file_ref(ref_text, evidence_ranges):
                issues.append({"severity": "major", "code": "invalid_evidence_ref", "finding_id": finding.get("finding_id", ""), "ref": ref_text})
    return {
        "schema_version": "kcode.verification.deterministic.v1",
        "passed": not issues,
        "issues": issues,
        "checked_findings": len(findings),
    }


def validate_coverage_claims(evidence_ids: set, evidence_ranges: dict[str, list[tuple[int, int]]], finding: dict, level: str, claims: list, issues: list[dict]) -> None:
    required = set(requirements_for_level(level))
    seen: set[str] = set()
    has_blocking_status = False
    finding_id = finding.get("finding_id", "")
    covered_ref_sets: list[tuple[str, tuple[str, ...]]] = []
    for index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            issues.append({"severity": "major", "code": "coverage_claim_invalid", "finding_id": finding_id, "index": index})
            continue
        item = str(claim.get("item", ""))
        status = str(claim.get("status", ""))
        if not item:
            issues.append({"severity": "major", "code": "coverage_claim_item_missing", "finding_id": finding_id, "index": index})
        elif required and item not in required:
            issues.append({"severity": "major", "code": "coverage_claim_item_not_in_contract", "finding_id": finding_id, "item": item})
        else:
            seen.add(item)
        if status not in VALID_COVERAGE_STATUSES:
            issues.append({"severity": "major", "code": "coverage_claim_status_invalid", "finding_id": finding_id, "item": item, "status": status})
        if status == "blocking_gap":
            has_blocking_status = True
        if status == "covered":
            refs = claim.get("evidence_refs")
            if not isinstance(refs, list) or not refs:
                issues.append({"severity": "major", "code": "coverage_claim_evidence_missing", "finding_id": finding_id, "item": item})
            else:
                covered_ref_sets.append((item, tuple(sorted(str(ref) for ref in refs))))
                for ref in refs:
                    ref_text = str(ref)
                    if ref_text not in evidence_ids and not validate_evidence_file_ref(ref_text, evidence_ranges):
                        issues.append({"severity": "major", "code": "invalid_coverage_claim_evidence_ref", "finding_id": finding_id, "item": item, "ref": ref_text})
    if level in {"feature_implementation", "coding_playbook"} and required:
        missing = sorted(required - seen)
        if missing:
            issues.append({"severity": "major", "code": "coverage_contract_items_missing", "finding_id": finding_id, "items": missing})
    if has_blocking_status and not finding.get("blocking_gaps"):
        issues.append({"severity": "major", "code": "blocking_coverage_without_blocking_gap", "finding_id": finding_id})
    if level == "feature_implementation":
        validate_feature_claim_evidence_specificity(finding_id, covered_ref_sets, issues)


def validate_feature_claim_evidence_specificity(finding_id: str, covered_ref_sets: list[tuple[str, tuple[str, ...]]], issues: list[dict]) -> None:
    if len(covered_ref_sets) < 3:
        return
    unique_ref_sets = {refs for _item, refs in covered_ref_sets}
    if len(unique_ref_sets) == 1:
        issues.append(
            {
                "severity": "major",
                "code": "coverage_claims_not_layer_specific",
                "finding_id": finding_id,
                "items": [item for item, _refs in covered_ref_sets],
            }
        )


def validate_knowledge_object_candidates(finding: dict, level: str, issues: list[dict]) -> None:
    if level not in {"feature_implementation", "coding_playbook"}:
        return
    finding_id = finding.get("finding_id", "")
    candidates = finding.get("knowledge_object_candidates")
    if not isinstance(candidates, list) or not candidates:
        issues.append({"severity": "major", "code": "knowledge_object_candidates_missing", "finding_id": finding_id})
        return
    for index, candidate in enumerate(candidates):
        candidate_text = str(candidate).replace("\\", "/").strip()
        if not candidate_text:
            issues.append({"severity": "major", "code": "knowledge_object_candidate_empty", "finding_id": finding_id, "index": index})
            continue
        if candidate_text.startswith("entities/code/features/"):
            candidate_text = f"wiki/{candidate_text}"
        if not candidate_text.startswith("wiki/entities/code/features/") or not candidate_text.endswith(".md"):
            issues.append(
                {
                    "severity": "major",
                    "code": "knowledge_object_candidate_invalid",
                    "finding_id": finding_id,
                    "candidate": str(candidate),
                }
            )


def validate_coding_context(evidence_ids: set, evidence_ranges: dict[str, list[tuple[int, int]]], finding: dict, issues: list[dict]) -> None:
    finding_id = finding.get("finding_id", "")
    context = finding.get("coding_context")
    if not isinstance(context, dict):
        issues.append({"severity": "major", "code": "coding_context_missing", "finding_id": finding_id})
        return
    for field in CODING_CONTEXT_REQUIRED_FIELDS:
        values = context.get(field)
        if not isinstance(values, list) or not values:
            issues.append({"severity": "major", "code": "coding_context_field_missing", "finding_id": finding_id, "field": field})
            continue
        for index, item in enumerate(values):
            if not isinstance(item, dict):
                issues.append({"severity": "major", "code": "coding_context_item_invalid", "finding_id": finding_id, "field": field, "index": index})
                continue
            if not str(item.get("summary", "")).strip():
                issues.append({"severity": "major", "code": "coding_context_summary_missing", "finding_id": finding_id, "field": field, "index": index})
            elif not contains_chinese_text(str(item.get("summary", ""))):
                issues.append({"severity": "major", "code": "human_text_not_chinese", "finding_id": finding_id, "field": f"coding_context.{field}.summary", "index": index})
            refs = item.get("evidence_refs")
            if not isinstance(refs, list) or not refs:
                issues.append({"severity": "major", "code": "coding_context_evidence_missing", "finding_id": finding_id, "field": field, "index": index})
                continue
            for ref in refs:
                ref_text = str(ref)
                if ref_text not in evidence_ids and not validate_evidence_file_ref(ref_text, evidence_ranges):
                    issues.append({"severity": "major", "code": "invalid_coding_context_evidence_ref", "finding_id": finding_id, "field": field, "ref": ref_text})


def contains_chinese_text(value: str) -> bool:
    return bool(CHINESE_TEXT_RE.search(value))


def validate_required_chinese_field(issues: list[dict], source: dict, field: str, artifact: str, item_id: str) -> None:
    text = str(source.get(field, "")).strip()
    if text and not contains_chinese_text(text):
        issue = {"severity": "major", "code": "human_text_not_chinese", "artifact": artifact, "field": field}
        if artifact == "finding":
            issue["finding_id"] = item_id
        elif item_id:
            issue["item_id"] = item_id
        issues.append(issue)


def validate_optional_chinese_field(issues: list[dict], source: dict, field: str, artifact: str, item_id: str) -> None:
    if field in source and str(source.get(field, "")).strip():
        validate_required_chinese_field(issues, source, field, artifact, item_id)


def validate_optional_chinese_list(issues: list[dict], source: dict, field: str, artifact: str, item_id: str) -> None:
    values = source.get(field)
    if not isinstance(values, list):
        return
    for index, value in enumerate(values):
        text = str(value).strip()
        if text and not contains_chinese_text(text):
            issue = {"severity": "major", "code": "human_text_not_chinese", "artifact": artifact, "field": field, "index": index}
            if artifact == "finding":
                issue["finding_id"] = item_id
            elif item_id:
                issue["item_id"] = item_id
            issues.append(issue)


def validate_gap_list_chinese(issues: list[dict], finding: dict, field: str) -> None:
    values = finding.get(field)
    if not isinstance(values, list):
        return
    for index, value in enumerate(values):
        if isinstance(value, dict):
            detail = str(value.get("detail", "")).strip()
        else:
            detail = str(value).strip()
        if detail and not contains_chinese_text(detail):
            issues.append(
                {
                    "severity": "major",
                    "code": "human_text_not_chinese",
                    "artifact": "finding",
                    "finding_id": finding.get("finding_id", ""),
                    "field": field,
                    "index": index,
                }
            )


def verifier_report_language_issues(report: dict, artifact: str) -> list[dict]:
    return json_human_language_issues(report, artifact)


def json_human_language_issues(value: object, artifact: str, *, finding_id: str = "", path: str = "") -> list[dict]:
    issues: list[dict] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}" if path else key_text
            if key_text in HUMAN_READABLE_JSON_FIELD_NAMES:
                issues.extend(human_field_language_issues(child, artifact, child_path, finding_id=finding_id))
            else:
                issues.extend(json_human_language_issues(child, artifact, finding_id=finding_id, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            issues.extend(json_human_language_issues(child, artifact, finding_id=finding_id, path=f"{path}[{index}]"))
    return issues


def human_field_language_issues(value: object, artifact: str, field: str, *, finding_id: str = "") -> list[dict]:
    issues: list[dict] = []
    if isinstance(value, str):
        text = value.strip()
        if text and not contains_chinese_text(text):
            issue = {"severity": "major", "code": "human_text_not_chinese", "artifact": artifact, "field": field}
            if finding_id:
                issue["finding_id"] = finding_id
            issues.append(issue)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            child_field = f"{field}[{index}]"
            if isinstance(child, str):
                issues.extend(human_field_language_issues(child, artifact, child_field, finding_id=finding_id))
            else:
                issues.extend(json_human_language_issues(child, artifact, finding_id=finding_id, path=child_field))
    elif isinstance(value, dict):
        issues.extend(json_human_language_issues(value, artifact, finding_id=finding_id, path=field))
    return issues


def validate_evidence_bundle(evidence: dict, findings: list[dict], issues: list[dict]) -> None:
    files = evidence.get("files")
    snippets = evidence.get("snippets")
    if not isinstance(files, list) or not files:
        issues.append({"severity": "major", "code": "evidence_files_missing", "finding_id": ""})
    if not isinstance(snippets, list) or not snippets:
        issues.append({"severity": "major", "code": "evidence_snippets_missing", "finding_id": ""})
    needs_closure = any(str(finding.get("knowledge_level", "")) in {"feature_implementation", "coding_playbook"} for finding in findings)
    closure = evidence.get("closure")
    if needs_closure:
        if not isinstance(closure, dict):
            issues.append({"severity": "major", "code": "evidence_closure_missing", "finding_id": ""})
            return
        expected_policy = "worklist_until_no_new_references_without_fixed_file_or_line_budget"
        if closure.get("expansion_policy") != expected_policy:
            issues.append({"severity": "major", "code": "evidence_closure_policy_invalid", "finding_id": "", "policy": closure.get("expansion_policy")})
        if closure.get("stopped_reason") != "worklist_exhausted":
            issues.append({"severity": "major", "code": "evidence_closure_not_exhausted", "finding_id": "", "stopped_reason": closure.get("stopped_reason")})
        if closure.get("file_count") != len(files or []):
            issues.append({"severity": "major", "code": "evidence_closure_file_count_mismatch", "finding_id": "", "file_count": closure.get("file_count"), "actual": len(files or [])})
        if "references" in closure and isinstance(closure.get("references"), list):
            reference_count = len(closure.get("references") or [])
            if closure.get("reference_count") != reference_count:
                issues.append({"severity": "major", "code": "evidence_closure_reference_count_mismatch", "finding_id": "", "reference_count": closure.get("reference_count"), "actual": reference_count})


def evidence_file_ranges(evidence: dict) -> dict[str, list[tuple[int, int]]]:
    result: dict[str, list[tuple[int, int]]] = {}
    for item in evidence.get("files", []) if isinstance(evidence.get("files"), list) else []:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path", "")).replace("\\", "/")
        if not path:
            continue
        ranges: list[tuple[int, int]] = []
        for range_item in item.get("ranges", []) if isinstance(item.get("ranges"), list) else []:
            try:
                start = int(range_item.get("start"))
                end = int(range_item.get("end"))
            except (TypeError, ValueError, AttributeError):
                continue
            if start >= 1 and end >= start:
                ranges.append((start, end))
        result[path] = ranges
    return result


def validate_evidence_file_ref(ref: str, evidence_ranges: dict[str, list[tuple[int, int]]]) -> bool:
    parsed = parse_file_ref(ref)
    if parsed is None:
        return False
    path_text, start, end = parsed
    ranges = evidence_ranges.get(path_text)
    if not ranges:
        return False
    return any(range_start <= start and end <= range_end for range_start, range_end in ranges)


def parse_file_ref(ref: str) -> tuple[str, int, int] | None:
    if ":" not in ref:
        return None
    path_text, range_text = ref.rsplit(":", 1)
    path_text = path_text.replace("\\", "/")
    if "-" not in range_text:
        return None
    try:
        start_text, end_text = range_text.split("-", 1)
        start = int(start_text)
        end = int(end_text)
    except ValueError:
        return None
    if start < 1 or end < start:
        return None
    return path_text, start, end


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    result: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            result.append(json.loads(line))
    return result


def write_verified_findings(findings_path: Path, verified_path: Path, semantic: dict) -> None:
    findings = read_jsonl(findings_path)
    verified_ids = set(semantic.get("verified_finding_ids") or [])
    if not verified_ids:
        lines = [json.dumps(finding, ensure_ascii=False) for finding in findings if not finding.get("blocking_gaps")]
        verified_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        return
    lines = []
    for finding in findings:
        if finding.get("finding_id") in verified_ids and not finding.get("blocking_gaps"):
            lines.append(json.dumps(finding, ensure_ascii=False))
    verified_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def selected_findings(findings: list[dict], semantic: dict) -> list[dict]:
    verified_ids = set(semantic.get("verified_finding_ids") or [])
    if not verified_ids:
        return findings
    return [finding for finding in findings if finding.get("finding_id") in verified_ids]


def blocking_gaps(findings: list[dict]) -> list[dict]:
    result: list[dict] = []
    for finding in findings:
        for gap in finding.get("blocking_gaps") or []:
            result.append({"finding_id": finding.get("finding_id", ""), "gap": gap})
    return result


def write_semantic_verifier_input(run: CodeRun, batch: dict, batch_dir: Path) -> Path:
    target = batch_dir / "semantic-verifier-input.json"
    payload = {
        "verification_type": "analysis",
        "knowledge_id": run.workspace.knowledge_id,
        "run_id": run.run_id,
        "batch_id": batch.get("batch_id"),
        "human_readable_output_language": KCODE_HUMAN_READABLE_OUTPUT_LANGUAGE,
        "language_policy": KCODE_LANGUAGE_POLICY,
        "artifacts": {
            "evidence": (batch_dir / "evidence.json").relative_to(run.run_dir).as_posix(),
            "analysis": (batch_dir / "analysis.md").relative_to(run.run_dir).as_posix(),
            "findings": (batch_dir / "findings.jsonl").relative_to(run.run_dir).as_posix(),
        },
        "coverage_contract": AGENTIC_CODING_COVERAGE_CONTRACT,
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def write_plan_verifier_input(run: CodeRun, verifier_dir: Path) -> Path:
    target = verifier_dir / "plan-verifier-input.json"
    payload = {
        "verification_type": "plan",
        "knowledge_id": run.workspace.knowledge_id,
        "run_id": run.run_id,
        "human_readable_output_language": KCODE_HUMAN_READABLE_OUTPUT_LANGUAGE,
        "language_policy": KCODE_LANGUAGE_POLICY,
        "artifacts": {
            "planner_input": "plan/planner-input.json",
            "repo_map": "inventory/repo-map.json",
            "analysis_plan": "plan/analysis-plan.json",
            "coverage_ledger": "plan/coverage-ledger.json",
        },
        "coverage_contract": AGENTIC_CODING_COVERAGE_CONTRACT,
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target

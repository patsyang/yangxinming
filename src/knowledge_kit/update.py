from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .config import KitConfig
from .runtime import append_ledger, new_run_id, now_iso, write_run_artifact
from .search import query_one
from .workflow_contract import (
    CLI_LIMITATIONS,
    KCODE_HUMAN_READABLE_OUTPUT_LANGUAGE,
    KCODE_LANGUAGE_POLICY,
    KU_CONTINUATION_POLICY,
    KU_CONTRACT_REFS,
    MAINTENANCE_PREFLIGHT_KIND,
    RELATION_DECISION_SKELETON,
)


def run_update(config: KitConfig, knowledge_id: str | None, task: str, content: str | None = None) -> dict:
    root = config.require_write_root(knowledge_id)
    run_id = new_run_id("update")
    content_analysis = analyze_update_content(root.path, content)
    preflight = query_one(root, task, config.query_candidate_limit, evidence_budget=config.query_evidence_budget)
    kcode_reconciliation_plans = kcode_reconciliation_read_plans(root, config, content_analysis)
    matched_pages = merged_preflight_values(preflight, kcode_reconciliation_plans, "candidate_page_paths")
    consulted_pages = merged_preflight_values(preflight, kcode_reconciliation_plans, "consulted_pages")
    materials = maintenance_materials(content_analysis)
    preflight_artifact = config.runs_dir / run_id / "maintenance-preflight-package.json"
    payload = {
        "run_id": run_id,
        "kind": MAINTENANCE_PREFLIGHT_KIND,
        "status": "requires_agent",
        "continuation_policy": KU_CONTINUATION_POLICY,
        "preflight_artifact": str(preflight_artifact),
        "operation": "QUERY",
        "cli_role": "deterministic_preflight_only",
        "task_classification": "curation",
        "knowledge_target": root.id,
        "actual_knowledge_root": str(root.path),
        "write_guard": {"enabled": root.enabled, "mode": root.mode, "single_target": True},
        "task": task,
        "content_provided": bool(content),
        "content_analysis": content_analysis,
        "karpathy_alignment": {
            "operations": ["QUERY"],
            "why": ["维护、更新、删除、清理前必须先按 Karpathy QUERY 从 index.md 找相关页，再读取页面和 wikilinks"],
        },
        "preflight_query_policy": {
            "required": True,
            "completed": True,
            "mechanism": preflight.get("query_mechanism"),
            "consulted_pages": preflight.get("consulted_pages", []),
            "read_plan": preflight,
            "kcode_reconciliation_queries": [item["query"] for item in kcode_reconciliation_plans],
            "kcode_reconciliation_read_plans": kcode_reconciliation_plans,
        },
        "wiki_artifact_summary": {"add": [], "update": [], "structural": []},
        "wiki_reconciliation": {
            "legacy_id_candidates": [],
            "canonical_path_candidates": reconciliation_path_candidates(preflight, content_analysis),
            "title_alias_candidates": reconciliation_title_candidates(preflight, content_analysis),
            "matched_pages": matched_pages,
            "allowed_operations": ["create", "update", "merge", "delete", "block"],
            "operations": ["block"],
            "confidence": 0.6 if matched_pages else 0.35,
            "blocked_reasons": [
                "当前 CLI 只能生成维护前置 QUERY 与 wiki_reconciliation 骨架；正式 create/update/merge/delete 需要 agent 按 Karpathy 机制编辑 source/concept/entity/overview/index/log 并移交 verifier。"
            ],
        },
        "relations_decision": RELATION_DECISION_SKELETON,
        "source_trace": {
            "raw_used": [],
            "consulted_wiki_pages": unique(consulted_pages + matched_pages),
            "maintenance_materials": materials,
        },
        "blockers": {"values": ["codex_agent_required_for_wiki_maintenance"]},
        "verifier_handoff": {
            "knowledge": root.id,
            "knowledge_files": [],
            "changes_summary": "CLI 仅完成维护预检；尚无正式 wiki 变更可验证。",
        },
        "quality_loop": {
            "completion_state": "aborted",
            "final_status": "blocked",
            "repair_rounds_used": 0,
            "factory_artifacts": [],
            "review_queue_ref": "",
        },
        "limitations": CLI_LIMITATIONS,
        "codex_next_step": ku_codex_next_step(root.id, task, content_analysis, materials, str(preflight_artifact)),
        "created_at": now_iso(),
    }
    artifact = write_run_artifact(config.runs_dir, run_id, "maintenance-preflight-package.json", payload)
    append_ledger(config.state_dir, {"run_id": run_id, "kind": MAINTENANCE_PREFLIGHT_KIND, "artifact": str(artifact), "created_at": payload["created_at"]})
    return payload


def kcode_reconciliation_read_plans(root, config: KitConfig, content_analysis: dict) -> list[dict]:
    queries = kcode_reconciliation_queries(content_analysis)
    plans: list[dict] = []
    for query in queries:
        plan = query_one(root, query, config.query_candidate_limit, evidence_budget=config.query_evidence_budget)
        plans.append(
            {
                "query": query,
                "mechanism": plan.get("query_mechanism", ""),
                "index_hits": [
                    {
                        "title": item.get("title", ""),
                        "path": item.get("path", ""),
                        "score": item.get("score", 0),
                    }
                    for item in plan.get("index_hits", [])
                ],
                "candidate_page_paths": plan.get("candidate_page_paths", []),
                "selected_evidence_paths": plan.get("selected_evidence_paths", []),
                "consulted_pages": plan.get("consulted_pages", []),
            }
        )
    return plans


def kcode_reconciliation_queries(content_analysis: dict) -> list[str]:
    kcode = content_analysis.get("kcode_handoff") if isinstance(content_analysis, dict) else None
    if not isinstance(kcode, dict) or not kcode.get("detected"):
        return []
    queries: list[str] = []
    for item in kcode.get("shards", []):
        topic = str(item.get("topic", "")).strip()
        if topic:
            queries.append(topic)
    for item in kcode.get("suggested_output_pages", []):
        for page in item.get("candidate_wiki_pages", []):
            page_text = str(page).strip()
            if page_text:
                queries.append(page_text)
                queries.append(candidate_page_query_text(page_text))
    return unique([item for item in queries if item])[:20]


def candidate_page_query_text(path: str) -> str:
    normalized = path.replace("\\", "/").removesuffix(".md")
    normalized = normalized.removeprefix("wiki/entities/code/features/")
    normalized = normalized.removeprefix("wiki/entities/code/modules/")
    return re.sub(r"[-_/]+", " ", normalized).strip()


def merged_preflight_values(primary_plan: dict, secondary_plans: list[dict], key: str) -> list[str]:
    values = list(primary_plan.get(key, []))
    for plan in secondary_plans:
        values.extend(str(item) for item in plan.get(key, []))
    return unique([item for item in values if item])


def analyze_update_content(knowledge_root: Path, content: str | None) -> dict:
    if not content:
        return {"provided": False, "kind": "none", "source_paths": []}
    text = str(content)
    candidate = resolve_content_path(knowledge_root, text)
    if candidate is not None:
        body = candidate.read_text(encoding="utf-8", errors="replace")
        relative = relative_to_root(candidate.resolve(), knowledge_root.resolve())
        payload = {
            "provided": True,
            "kind": "file",
            "path": str(candidate.resolve()),
            "knowledge_relative_path": relative,
            "sha256": hashlib.sha256(body.encode("utf-8", errors="replace")).hexdigest(),
            "source_paths": [relative or str(candidate.resolve())],
        }
        kcode = parse_kcode_content(body, relative, source_file=candidate, knowledge_root=knowledge_root)
        if kcode["detected"]:
            payload["kcode_handoff"] = kcode
        return payload
    payload = {
        "provided": True,
        "kind": "inline",
        "sha256": hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest(),
        "source_paths": [],
    }
    kcode = parse_kcode_content(text, "")
    if kcode["detected"]:
        payload["kcode_handoff"] = kcode
    return payload


def resolve_content_path(knowledge_root: Path, value: str) -> Path | None:
    direct = Path(value)
    if not direct.is_absolute():
        rooted = knowledge_root / value
        if rooted.exists() and rooted.is_file():
            return rooted
    if direct.exists() and direct.is_file():
        return direct
    return None


def parse_kcode_content(text: str, source_path: str, *, source_file: Path | None = None, knowledge_root: Path | None = None) -> dict:
    if source_file is not None and source_file.name == "manifest.json":
        manifest = parse_kcode_manifest_file(source_file, knowledge_root)
        if manifest["detected"]:
            return manifest
    request = parse_kcode_manager_request(text, source_path)
    if source_file is not None:
        manifest_ref = first_markdown_value(text, "manifest")
        manifest_file = resolve_related_manifest_path(source_file, manifest_ref, knowledge_root)
        if manifest_file is not None:
            manifest = parse_kcode_manifest_file(manifest_file, knowledge_root)
            if manifest["detected"]:
                manifest["request_path"] = source_path
                manifest["manager_request_path"] = source_path
                for key in ["knowledge_id", "knowledge_root", "kcode_run_id"]:
                    if not manifest.get(key):
                        manifest[key] = request.get(key, "")
                return manifest
    return request


def resolve_related_manifest_path(source_file: Path, manifest_ref: str, knowledge_root: Path | None) -> Path | None:
    if not manifest_ref:
        return None
    ref = Path(manifest_ref)
    candidates: list[Path] = []
    if ref.is_absolute():
        candidates.append(ref)
    else:
        candidates.append(source_file.parent / ref)
        candidates.append(source_file.parent.parent / ref)
        if knowledge_root is not None:
            candidates.append(knowledge_root / ref)
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def parse_kcode_manifest_file(path: Path, knowledge_root: Path | None) -> dict:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"detected": False, "request_path": "", "source": "manifest", "error": "manifest_unreadable"}
    if not isinstance(manifest, dict):
        return {"detected": False, "request_path": "", "source": "manifest", "error": "manifest_not_object"}
    root = knowledge_root.resolve() if knowledge_root is not None else None
    relative = relative_to_root(path.resolve(), root) if root is not None else ""
    return parse_kcode_manifest(manifest, relative or str(path.resolve()), source_file=path, knowledge_root=knowledge_root)


def parse_kcode_manifest(manifest: dict, manifest_path: str, *, source_file: Path | None = None, knowledge_root: Path | None = None) -> dict:
    detected = manifest.get("schema_version") == "kcode.handoff_manifest.v1"
    shards = manifest_shards(manifest)
    quality_ref = str(manifest.get("handoff_quality", ""))
    quality_file = resolve_related_manifest_path(source_file, quality_ref, knowledge_root) if source_file is not None else None
    quality = parse_handoff_quality_file(quality_file, knowledge_root) if quality_file is not None else {"detected": False, "path": quality_ref, "error": "handoff_quality_missing"}
    return {
        "detected": detected,
        "source": "manifest",
        "request_path": str(manifest.get("knowledge_manager_request", "")),
        "manifest_path": manifest_path,
        "handoff_quality_path": quality.get("path", quality_ref),
        "handoff_quality": quality,
        "knowledge_id": str(manifest.get("knowledge_id", "")),
        "knowledge_root": str(manifest.get("knowledge_root", "")),
        "kcode_run_id": str(manifest.get("run_id", "")),
        "human_readable_output_language": str(manifest.get("human_readable_output_language", "")),
        "language_policy": manifest.get("language_policy", {}) if isinstance(manifest.get("language_policy"), dict) else {},
        "request": manifest.get("request", {}) if isinstance(manifest.get("request"), dict) else {},
        "shards": shards,
        "suggested_output_pages": manifest_suggested_output_pages(manifest),
        "required_fixed_headings": manifest.get("required_fixed_headings", default_code_fixed_headings()),
        "required_checks": manifest.get("required_checks", default_kcode_required_checks()),
        "acceptance_commands": manifest.get("acceptance_commands", []),
        "acceptance_checks": manifest.get("acceptance_checks", []),
    }


def parse_handoff_quality_file(path: Path, knowledge_root: Path | None) -> dict:
    root = knowledge_root.resolve() if knowledge_root is not None else None
    relative = relative_to_root(path.resolve(), root) if root is not None else ""
    label = relative or str(path.resolve())
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"detected": False, "path": label, "error": "handoff_quality_unreadable"}
    if not isinstance(payload, dict):
        return {"detected": False, "path": label, "error": "handoff_quality_not_object"}
    return {
        "detected": payload.get("schema_version") == "kcode.handoff_quality.v1",
        "path": label,
        "schema_version": str(payload.get("schema_version", "")),
        "passed": payload.get("passed"),
        "issues": payload.get("issues", []),
        "checked": payload.get("checked", {}),
    }


def manifest_shards(manifest: dict) -> list[dict]:
    rows: list[dict] = []
    for item in manifest.get("shards", []) if isinstance(manifest.get("shards"), list) else []:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "path": str(item.get("path", "")),
                "topic": str(item.get("topic", "")),
                "source_batch": str(item.get("source_batch", "")),
                "verified_findings": str(item.get("verified_findings", "")),
                "analysis": str(item.get("analysis", "")),
                "evidence": str(item.get("evidence", "")),
                "source_summary_path": str(item.get("source_summary_path", "")),
                "source_summary_blueprint": str(item.get("source_summary_blueprint", "")),
                "candidate_wiki_pages": [str(path) for path in item.get("candidate_wiki_pages", []) if str(path)],
                "primary_wiki_pages": [str(path) for path in item.get("primary_wiki_pages", []) if str(path)],
                "page_blueprints": [str(path) for path in item.get("page_blueprints", []) if str(path)],
            }
        )
    return rows


def manifest_suggested_output_pages(manifest: dict) -> list[dict]:
    rows: list[dict] = []
    for item in manifest.get("shards", []) if isinstance(manifest.get("shards"), list) else []:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "shard": str(item.get("path", "")),
                "source_summary": str(item.get("source_summary_path", "")),
                "source_summary_blueprint": str(item.get("source_summary_blueprint", "")),
                "candidate_wiki_pages": [str(path) for path in item.get("candidate_wiki_pages", []) if str(path)],
                "primary_wiki_pages": [str(path) for path in item.get("primary_wiki_pages", []) if str(path)],
                "alternate_candidate_wiki_pages": alternate_candidate_pages(item),
                "knowledge_levels": [str(level) for level in item.get("knowledge_levels", []) if str(level)],
                "page_blueprints": [str(path) for path in item.get("page_blueprints", []) if str(path)],
            }
        )
    return rows


def alternate_candidate_pages(item: dict) -> list[str]:
    candidates = [str(path) for path in item.get("candidate_wiki_pages", []) if str(path)]
    primary = {str(path) for path in item.get("primary_wiki_pages", []) if str(path)}
    return [path for path in candidates if path not in primary]


def parse_kcode_manager_request(text: str, source_path: str) -> dict:
    detected = "# Knowledge Manager 维护请求" in text or "KCode handoff curation" in text or "KCode handoff 整理维护" in text
    source_summary_blueprints = parse_source_summary_blueprints(text)
    shards = attach_source_summary_blueprints_to_shards(parse_handoff_shard_table(text), source_summary_blueprints)
    suggested_output_pages = attach_source_summary_blueprints_to_outputs(parse_suggested_output_pages(text), source_summary_blueprints)
    result = {
        "detected": detected,
        "request_path": source_path,
        "knowledge_id": first_markdown_value(text, "knowledge_id"),
        "knowledge_root": first_markdown_value(text, "knowledge_root"),
        "kcode_run_id": first_markdown_value(text, "kcode_run_id"),
        "shards": shards,
        "suggested_output_pages": suggested_output_pages,
        "manifest_path": first_markdown_value(text, "manifest"),
        "human_readable_output_language": first_markdown_value(text, "human_readable_output_language"),
        "required_fixed_headings": default_code_fixed_headings(),
        "required_checks": default_kcode_required_checks(),
    }
    return result


def default_code_fixed_headings() -> list[str]:
    return [
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


def default_kcode_required_checks() -> list[str]:
    return [
        "preflight_QUERY",
        "wiki_reconciliation",
        "no_state_artifact_as_formal_wiki_body",
        "no_blocking_gaps_as_current_facts",
        "fixed_code_feature_sections",
        "index_recall_summary",
        "query_bundle_profile_quality",
        "knowledge_verifier_handoff",
    ]


def first_markdown_value(text: str, key: str) -> str:
    pattern = re.compile(rf"^\s*-\s+{re.escape(key)}:\s*(.+?)\s*$", re.MULTILINE)
    match = pattern.search(text)
    return match.group(1).strip() if match else ""


def parse_handoff_shard_table(text: str) -> list[dict]:
    rows: list[dict] = []
    in_table = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("| 分片 |") and "主题" in stripped:
            in_table = True
            continue
        if not in_table:
            continue
        if not stripped.startswith("|"):
            if rows:
                break
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 3 or set(cells[0]) <= {"-", ":"}:
            continue
        rows.append({"path": cells[0], "topic": cells[1], "source_batch": cells[2]})
    return rows


def parse_source_summary_blueprints(text: str) -> list[dict]:
    rows: list[dict] = []
    in_table = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("| 分片 |") and "来源摘要页" in stripped and "来源摘要蓝图" in stripped:
            in_table = True
            continue
        if not in_table:
            continue
        if not stripped.startswith("|"):
            if rows:
                break
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 3 or set(cells[0]) <= {"-", ":"}:
            continue
        rows.append(
            {
                "shard": cells[0],
                "source_summary": cells[1],
                "source_summary_blueprint": cells[2],
            }
        )
    return rows


def attach_source_summary_blueprints_to_shards(shards: list[dict], source_rows: list[dict]) -> list[dict]:
    by_shard = {item["shard"]: item for item in source_rows if item.get("shard")}
    result: list[dict] = []
    for shard in shards:
        merged = dict(shard)
        source = by_shard.get(str(shard.get("path", "")))
        if source:
            merged["source_summary_blueprint"] = source.get("source_summary_blueprint", "")
        result.append(merged)
    return result


def attach_source_summary_blueprints_to_outputs(outputs: list[dict], source_rows: list[dict]) -> list[dict]:
    by_shard = {item["shard"]: item for item in source_rows if item.get("shard")}
    result: list[dict] = []
    for output in outputs:
        merged = dict(output)
        source = by_shard.get(str(output.get("shard", "")))
        if source:
            merged.setdefault("source_summary", source.get("source_summary", ""))
            merged["source_summary_blueprint"] = source.get("source_summary_blueprint", "")
        result.append(merged)
    return result


def parse_suggested_output_pages(text: str) -> list[dict]:
    rows: list[dict] = []
    in_table = False
    headers: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("| 分片 |") and ("来源摘要页" in stripped or "Source summary" in stripped):
            in_table = True
            headers = [cell.strip() for cell in stripped.strip("|").split("|")]
            continue
        if not in_table:
            continue
        if not stripped.startswith("|"):
            if rows:
                break
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 4 or set(cells[0]) <= {"-", ":"}:
            continue
        row = suggested_output_row_from_cells(headers, cells)
        if row:
            rows.append(row)
    return rows


def suggested_output_row_from_cells(headers: list[str], cells: list[str]) -> dict:
    def cell_named(*names: str, default_index: int | None = None) -> str:
        for name in names:
            if name in headers:
                index = headers.index(name)
                return cells[index] if index < len(cells) else ""
        if default_index is not None and default_index < len(cells):
            return cells[default_index]
        return ""

    shard = cell_named("分片", default_index=0)
    source_summary = cell_named("来源摘要页", "Source summary", default_index=1)
    old_candidates = split_table_list(cell_named("候选正式代码页", default_index=2))
    primary = split_table_list(cell_named("主正式代码页"))
    alternates = [item for item in split_table_list(cell_named("备选候选页")) if item != "无"]
    candidates = unique(primary + alternates + old_candidates)
    if not shard or not source_summary or not candidates:
        return {}
    return {
        "shard": shard,
        "source_summary": source_summary,
        "candidate_wiki_pages": candidates,
        "primary_wiki_pages": primary or old_candidates[:1],
        "alternate_candidate_wiki_pages": alternates or old_candidates[1:],
        "knowledge_levels": split_table_list(cell_named("知识层级", default_index=3)),
        "page_blueprints": split_table_list(cell_named("落页蓝图")),
    }


def split_table_list(value: str) -> list[str]:
    parts: list[str] = []
    for segment in value.split("<br>"):
        parts.extend(item.strip() for item in segment.split(",") if item.strip())
    return parts


def reconciliation_path_candidates(preflight: dict, content_analysis: dict) -> list[str]:
    candidates = list(preflight.get("candidate_page_paths", []))
    kcode = content_analysis.get("kcode_handoff") if isinstance(content_analysis, dict) else None
    if isinstance(kcode, dict) and kcode.get("detected"):
        for item in kcode.get("suggested_output_pages", []):
            candidates.extend(item.get("candidate_wiki_pages", []))
            source_summary = str(item.get("source_summary", ""))
            if source_summary:
                candidates.append(source_summary)
        candidates.extend(["wiki/entities/code/features/**", "wiki/entities/code/modules/**", "wiki/sources/code/kcode-runs/**"])
    return unique(candidates)


def reconciliation_title_candidates(preflight: dict, content_analysis: dict) -> list[str]:
    candidates = [item["title"] for item in preflight.get("candidate_pages", [])]
    kcode = content_analysis.get("kcode_handoff") if isinstance(content_analysis, dict) else None
    if isinstance(kcode, dict) and kcode.get("detected"):
        candidates.extend(str(item.get("topic", "")) for item in kcode.get("shards", []))
    return unique([item for item in candidates if item])


def maintenance_materials(content_analysis: dict) -> list[str]:
    materials = list(content_analysis.get("source_paths", [])) if isinstance(content_analysis, dict) else []
    kcode = content_analysis.get("kcode_handoff") if isinstance(content_analysis, dict) else None
    if not isinstance(kcode, dict) or not kcode.get("detected"):
        return unique([item for item in materials if item])
    for key in ["manifest_path", "request_path", "manager_request_path", "handoff_quality_path"]:
        normalized = normalize_kcode_artifact_path(kcode, str(kcode.get(key, "")))
        if normalized:
            materials.append(normalized)
    for shard in kcode.get("shards", []) if isinstance(kcode.get("shards"), list) else []:
        if not isinstance(shard, dict):
            continue
        for key in ["path", "verified_findings", "analysis", "evidence", "source_summary_blueprint"]:
            normalized = normalize_kcode_artifact_path(kcode, str(shard.get(key, "")))
            if normalized:
                materials.append(normalized)
        for blueprint in shard.get("page_blueprints", []) if isinstance(shard.get("page_blueprints"), list) else []:
            normalized = normalize_kcode_artifact_path(kcode, str(blueprint))
            if normalized:
                materials.append(normalized)
    for output in kcode.get("suggested_output_pages", []) if isinstance(kcode.get("suggested_output_pages"), list) else []:
        if not isinstance(output, dict):
            continue
        normalized = normalize_kcode_artifact_path(kcode, str(output.get("source_summary_blueprint", "")))
        if normalized:
            materials.append(normalized)
        for blueprint in output.get("page_blueprints", []) if isinstance(output.get("page_blueprints"), list) else []:
            normalized = normalize_kcode_artifact_path(kcode, str(blueprint))
            if normalized:
                materials.append(normalized)
    return unique([item for item in materials if item])


def ku_codex_next_step(knowledge_id: str, task: str, content_analysis: dict, materials: list[str], preflight_artifact: str) -> dict:
    kcode = content_analysis.get("kcode_handoff") if isinstance(content_analysis, dict) else None
    next_step_path = Path(preflight_artifact).parent / "ku-next-step.json"
    payload = {
        "schema_version": "ku.codex_next_step.v1",
        "status": "requires_agent",
        "completion_state": "not_complete",
        "must_continue": True,
        "final_answer_allowed": False,
        "do_not_final_answer_at_preflight": True,
        "requires_agent_must_be_resolved_by": "knowledge_manager_sub_agent",
        "contract_refs": KU_CONTRACT_REFS,
        "must_read_contract_refs_before_wiki_write": True,
        "preflight_artifact": preflight_artifact,
        "agent": "knowledge-manager",
        "agent_config": ".trae/agents/knowledge-manager.md",
        "knowledge_id": knowledge_id,
        "task": task,
        "input_materials": materials,
        "kcode_handoff_detected": bool(isinstance(kcode, dict) and kcode.get("detected")),
        "human_readable_output_language": KCODE_HUMAN_READABLE_OUTPUT_LANGUAGE,
        "language_policy": KCODE_LANGUAGE_POLICY,
        "required_actions": [
            "当前主会话不得直接写正式 wiki；必须调用 knowledge-manager sub agent，并使用 .trae/agents/knowledge-manager.md 作为唯一角色合同继续执行。",
            "读取 preflight_artifact 指向的 maintenance-preflight-package，使用其中的 content_analysis、wiki_reconciliation 和 source_trace.maintenance_materials。",
            "写入任何正式 wiki Markdown、source summary、feature 页、index/log/overview 摘要或 verifier handoff 前，先读取 human_readable_output_language 和 language_policy；所有人读正文必须使用中文。",
            "按 Karpathy QUERY -> wiki_reconciliation -> wiki 维护 -> relations decision -> verifier handoff 执行，不得停在 CLI 预检包。",
            "写入后运行 python -m knowledge_kit lint -k <knowledge_id>。",
            "KCode 维护写入后读取 handoff/manifest.json 的 acceptance_commands，并执行其中的 lint 与 query-bundle 验收命令。",
            "不得把 maintenance_preflight_package 或 status=requires_agent 当作最终回答。",
        ],
        "expected_completion": "正式 wiki 变更完成并通过 verifier handoff；若质量门无法通过，报告 agent-level blocker，而不是把 CLI preflight 当完成。",
    }
    payload["next_step_artifact"] = str(next_step_path)
    next_step_path.parent.mkdir(parents=True, exist_ok=True)
    next_step_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def normalize_kcode_artifact_path(kcode: dict, value: str) -> str:
    text = value.replace("\\", "/").strip()
    if not text or text == "无":
        return ""
    if text.startswith("state/") or text.startswith("wiki/") or Path(text).is_absolute():
        return text
    run_id = str(kcode.get("kcode_run_id", "")).strip()
    if run_id and (text.startswith("handoff/") or text.startswith("batches/") or text.startswith("plan/") or text.startswith("verifier/") or text == "run.json"):
        return f"state/kcode-runs/{run_id}/{text}"
    return text


def relative_to_root(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return ""


def unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result

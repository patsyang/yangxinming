from __future__ import annotations

import json
import re
from pathlib import Path

from .code_map import (
    evidence_code_map_matches,
    evidence_code_map_repo_scores,
    evidence_code_path_repo_scores,
    prioritized_code_anchors,
)
from .config import KnowledgeRoot
from .code_verification_contract import (
    code_exploration_loop,
    code_exploration_steps,
    code_trace_requirements,
    code_verification_completion_criteria,
    code_verification_quality_gate,
    code_verification_report_template,
    code_verification_result_contract,
    code_verification_result_skeleton,
)
from .query_terms import CODE_SEARCH_ALIASES, unique_terms
from .workflow_contract import QUERY_CODE_EXPLORATION_CONTRACT_REFS


CODE_SEARCH_GLOBS = [
    "-g \"*.java\"",
    "-g \"*.kt\"",
    "-g \"*.js\"",
    "-g \"*.jsx\"",
    "-g \"*.ts\"",
    "-g \"*.tsx\"",
    "-g \"*.vue\"",
    "-g \"*.xml\"",
    "-g \"*.sql\"",
    "-g \"*.yml\"",
    "-g \"*.yaml\"",
    "-g \"*.json\"",
]
CODE_SEARCH_EXCLUDES = [
    "--glob \"!**/node_modules/**\"",
    "--glob \"!**/target/**\"",
    "--glob \"!**/dist/**\"",
    "--glob \"!**/build/**\"",
    "--glob \"!**/memory-bank/**\"",
    "--glob \"!**/package-lock.json\"",
    "--glob \"!**/yarn.lock\"",
    "--glob \"!**/pnpm-lock.yaml\"",
]
CODE_TRACE_PATH_PATTERN = (
    "controller|service|repository|repositories|mapper|resource|runner|task|impl|rest|api|http|views|view|router|test|spec"
)


def query_codex_next_step(code_exploration: dict) -> dict:
    execution_policy = code_exploration.get("execution_policy") if isinstance(code_exploration, dict) else {}
    if not isinstance(execution_policy, dict) or not execution_policy.get("must_execute_before_final"):
        return {}
    commands = [str(item) for item in code_exploration.get("suggested_rg", []) if str(item)]
    max_commands = initial_command_limit(code_exploration, int(execution_policy.get("max_initial_commands", 5)))
    selected_commands = commands[:max_commands]
    commands_by_workspace = code_exploration.get("suggested_rg_by_workspace", {})
    workspaces = [item for item in code_exploration.get("workspaces", []) if isinstance(item, dict)]
    workspace_commands = []
    for workspace in workspaces:
        knowledge_id = str(workspace.get("knowledge_id", ""))
        workspace_specific = []
        if isinstance(commands_by_workspace, dict):
            workspace_specific = [str(item) for item in commands_by_workspace.get(knowledge_id, []) if str(item)]
        workspace_commands.append(
            {
                "knowledge_id": knowledge_id,
                "command_cwd": str(workspace.get("command_cwd", "")),
                "commands": (workspace_specific or selected_commands)[:max_commands],
            }
        )
    command_cwd = str(code_exploration.get("suggested_rg_cwd", ""))
    return {
        "schema_version": "query.code_exploration_next_step.v1",
        "status": "requires_code_exploration",
        "completion_state": "not_complete",
        "must_continue": True,
        "final_answer_allowed": False,
        "requires_code_exploration_must_be_resolved_by": "current_session",
        "contract_refs": QUERY_CODE_EXPLORATION_CONTRACT_REFS,
        "must_read_contract_refs_before_final": True,
        "do_not_final_answer_before_code_verification": True,
        "command_cwd": command_cwd,
        "commands": selected_commands,
        "workspace_commands": workspace_commands,
        "max_initial_commands": max_commands,
        "code_map_matches": code_exploration.get("code_map_matches", []),
        "exploration_loop": code_exploration.get("exploration_loop", {}),
        "result_contract": code_exploration.get("result_contract", {}),
        "quality_gate": code_exploration.get("quality_gate", {}),
        "required_output_block": "代码验证结果",
        "verification_result_skeleton": code_exploration.get("verification_result_skeleton", {}),
        "verification_report_template": code_exploration.get("verification_report_template", {}),
        "completion_criteria": code_exploration.get("completion_criteria", {}),
        "required_actions": [
            "如果 command_cwd 非空，进入 command_cwd 指定的代码 workspace；如果 command_cwd 为空，逐个进入 workspace_commands[].command_cwd。",
            "执行 commands 中不超过 max_initial_commands 条命令；可以替换为等价且更精确的 rg 命令。",
            "按 exploration_loop 的阶段执行：先发现候选文件，再读取入口代码，再沿前端/API/controller/service/repository/runtime/test 追链。",
            "按 code_exploration.trace_requirements 覆盖入口、实现链、运行/数据/权限约束、测试入口和缺口；没有证据的项必须写未知。",
            "按 code_exploration.completion_criteria 判断是否足以输出已确认结论；不满足时继续探索或只报告不足和下一步。",
            "最终回答前按 quality_gate 执行自检；触发 blocking_fail_conditions 时不得把代码验证写成已确认结论。",
            "最终回答必须包含“代码验证结果”，列出已执行命令、关键路径、代码事实和仍需继续探索的缺口。",
            "代码验证结果必须和 wiki evidence_pages 结论分开标注；不得把 code_exploration 本身当作事实证据。",
        ],
    }


def initial_command_limit(code_exploration: dict, configured_limit: int) -> int:
    anchors = code_exploration.get("code_anchors", []) if isinstance(code_exploration, dict) else []
    has_path_anchors = any(isinstance(anchor, dict) and anchor.get("kind") == "path" for anchor in anchors)
    if has_path_anchors:
        return min(configured_limit, 2)
    return configured_limit


def code_verification_required(answer_requirements: dict) -> bool:
    if not answer_requirements.get("code_exploration_policy", {}).get("available"):
        return False
    return bool(set(answer_requirements.get("active_profiles") or []).intersection({"agentic_coding", "prd_design_from_code"}))


def build_code_exploration(read_plan: dict, code_plans: list[dict], evidence_pages: list[dict], terms: list[str], gaps: list[dict], answer_requirements: dict) -> dict:
    if not code_plans:
        return {"enabled": False}
    terms = terms[:12]
    code_map_modules = [str(module).lower() for plan in code_plans for module in plan.get("query_intent", {}).get("modules", []) if str(module)]
    code_map_matches = evidence_code_map_matches(evidence_pages, terms, code_map_modules)
    anchors = prioritized_code_anchors(code_map_matches, extract_code_anchors_from_evidence(evidence_pages))
    workspaces = code_exploration_workspaces(read_plan)
    repos = []
    for plan in code_plans:
        repos.extend(snapshot_repo_targets(plan, terms, evidence_pages))
    repo_target_status = code_repo_target_status(repos)
    gap_codes = {str(gap.get("code") or "") for gap in gaps}
    enabled = bool(
        code_plans
        or anchors
        or repos
        or gap_codes.intersection(
            {
                "query_topic_not_covered",
                "query_module_not_covered",
                "profile_query_topic_not_covered",
                "profile_query_subject_missing",
                "profile_code_feature_evidence_missing",
            }
        )
    )
    execution_policy = code_exploration_execution_policy(enabled, answer_requirements)
    return {
        "enabled": enabled,
        "source": "derived_from_selected_wiki_evidence_and_knowledge_state_snapshot",
        "not_evidence": True,
        "usage": "next_code_exploration_only_do_not_answer_as_fact",
        "execution_policy": execution_policy,
        "workspaces": workspaces,
        "suggested_rg_cwd": workspaces[0]["command_cwd"] if len(workspaces) == 1 else "",
        "query_terms": terms,
        "code_map_matches": code_map_matches,
        "code_anchors": anchors,
        "repo_targets": repos,
        "repo_target_status": repo_target_status,
        "exploration_steps": code_exploration_steps(),
        "exploration_loop": code_exploration_loop(),
        "trace_requirements": code_trace_requirements(),
        "result_contract": code_verification_result_contract(answer_requirements),
        "quality_gate": code_verification_quality_gate(answer_requirements),
        "verification_result_skeleton": code_verification_result_skeleton(answer_requirements),
        "verification_report_template": code_verification_report_template(answer_requirements),
        "completion_criteria": code_verification_completion_criteria(answer_requirements),
        "suggested_rg": suggested_rg_commands(terms, anchors, repos),
        "suggested_rg_by_workspace": suggested_rg_commands_by_workspace(terms, anchors, repos, workspaces),
    }


def code_exploration_execution_policy(enabled: bool, answer_requirements: dict) -> dict:
    active_profiles = set(answer_requirements.get("active_profiles") or [])
    must_execute = bool(enabled and active_profiles.intersection({"agentic_coding", "prd_design_from_code"}))
    return {
        "must_execute_before_final": must_execute,
        "reason": "agentic_coding_or_prd_design_requires_live_code_verification" if must_execute else "optional_navigation_or_low_context_followup",
        "max_initial_commands": 5,
        "must_keep_separate_from_wiki_evidence": True,
        "final_answer_must_include_code_findings_when_executed": must_execute,
    }



def code_exploration_workspaces(read_plan: dict) -> list[dict]:
    result: list[dict] = []
    for root in read_plan.get("selected_knowledge_roots", []):
        workspace = root.get("code_workspace")
        if not isinstance(workspace, dict):
            continue
        result.append(
            {
                "knowledge_id": str(root.get("id", "")),
                "workspace_root": str(workspace.get("workspace_root", "")),
                "repos_dir": str(workspace.get("repos_dir", "")),
                "repos_root": str(workspace.get("repos_root", "")),
                "submodule_mode": bool(workspace.get("submodule_mode", True)),
                "command_cwd": str(workspace.get("command_cwd", workspace.get("workspace_root", ""))),
            }
        )
    return result


def extract_code_anchors_from_evidence(evidence_pages: list[dict]) -> list[dict]:
    anchors: list[dict] = []
    seen: set[tuple[str, str]] = set()
    patterns = [
        ("path", r"\b(?:repos/)?[\w./-]+\.(?:java|kt|js|jsx|ts|tsx|vue|py|go|xml|yml|yaml|json|sql)\b"),
        ("symbol", r"\b[A-Z][A-Za-z0-9_]*(?:Controller|Service|ServiceImpl|Repository|Mapper|Dao|Client|DTO|Dto|Entity|Config|Resource)\b"),
        ("endpoint", r"/[A-Za-z0-9_$:{}./-]+"),
    ]
    for page in evidence_pages:
        content = str(page.get("content", ""))
        source_path = str(page.get("path", ""))
        for kind, pattern in patterns:
            for match in re.finditer(pattern, content):
                value = match.group(0).strip("`.,;:，。；：)")
                if not value or len(value) < 3:
                    continue
                if kind == "endpoint" and not is_searchable_endpoint(value):
                    continue
                key = (kind, value)
                if key in seen:
                    continue
                seen.add(key)
                anchors.append({"kind": kind, "value": value, "evidence_page": source_path})
                if len(anchors) >= 40:
                    return anchors
    return anchors


def snapshot_repo_targets(plan: dict, terms: list[str], evidence_pages: list[dict] | None = None) -> list[dict]:
    root_path = plan.get("actual_knowledge_root")
    if not root_path:
        return []
    knowledge_id = str(plan.get("knowledge_id") or "")
    snapshot = load_latest_snapshot(root_path)
    repos = snapshot.get("repos") if isinstance(snapshot, dict) else []
    if not isinstance(repos, list):
        return []
    modules = [str(item).lower() for item in plan.get("query_intent", {}).get("modules", []) if str(item)]
    evidence_scores = evidence_code_map_repo_scores(repos, evidence_pages or [], terms, modules)
    evidence_path_scores = evidence_code_path_repo_scores(repos, evidence_pages or [])
    ranked: list[tuple[int, str, dict, str]] = []
    lowered_terms = [term.lower() for term in terms]
    for repo in repos:
        if not isinstance(repo, dict):
            continue
        repo_key = str(repo.get("repo_id") or repo.get("path") or "")
        text = f"{repo.get('repo_id', '')} {repo.get('path', '')} {repo.get('remote', '')}".lower()
        score = 0
        reason = "code_snapshot_fallback"
        for module in modules:
            if module and module in text:
                score += 10
                reason = "module_or_term_match"
        for term in lowered_terms:
            if term and term in text:
                score += 2
                reason = "module_or_term_match"
        evidence_score = evidence_scores.get(repo_key, 0)
        if evidence_score:
            score += evidence_score
            reason = "evidence_code_map_match"
        evidence_path_score = evidence_path_scores.get(repo_key, 0)
        if evidence_path_score:
            score += evidence_path_score
            if reason == "code_snapshot_fallback":
                reason = "evidence_code_path_match"
        if not modules and not lowered_terms and score == 0:
            score = 1
        ranked.append((score, str(repo.get("repo_id", "")), repo, reason))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    positive_matches = [item for item in ranked if item[0] > 0]
    selected = positive_matches[:8] if positive_matches else ranked[:8]
    result = []
    for score, _repo_id, repo, reason in selected:
        result.append(
            {
                "repo_id": str(repo.get("repo_id", "")),
                "knowledge_id": knowledge_id,
                "path": str(repo.get("path", "")),
                "branch": str(repo.get("branch", "")),
                "commit": str(repo.get("commit", "")),
                "language_summary": repo.get("language_summary", {}),
                "selection_reason": reason if score > 0 else "code_snapshot_fallback",
            }
        )
    return result


def code_repo_target_status(repos: list[dict]) -> str:
    if not repos:
        return "none"
    if any(repo.get("selection_reason") != "code_snapshot_fallback" for repo in repos):
        return "matched"
    return "snapshot_fallback"


def load_latest_snapshot(root_path: object) -> dict:
    try:
        root = KnowledgeRoot(id="_snapshot", name="_snapshot", path=Path(str(root_path)), enabled=True, mode="read_only")
    except TypeError:
        return {}
    snapshot_path = root.path / "state" / "kcode" / "latest-snapshot.json"
    try:
        resolved = snapshot_path.resolve()
        resolved.relative_to(root.path.resolve())
        if not resolved.exists() or not resolved.is_file():
            return {}
        return json.loads(resolved.read_text(encoding="utf-8"))
    except Exception:
        return {}


def suggested_rg_commands(terms: list[str], anchors: list[dict], repos: list[dict]) -> list[str]:
    term_values = expanded_search_values(terms)
    search_values = list(term_values)
    for anchor in anchors:
        value = str(anchor.get("value", ""))
        if anchor.get("kind") == "endpoint" and not is_searchable_endpoint(value):
            continue
        if anchor.get("kind") in {"symbol", "endpoint"} and value not in search_values:
            search_values.append(value)
    path_values = [
        str(anchor.get("value", ""))
        for anchor in anchors
        if anchor.get("kind") == "path" and is_ascii_search_value(str(anchor.get("value", "")))
    ]
    repo_paths = [
        str(repo.get("path", ""))
        for repo in repos
        if repo.get("path") and repo.get("selection_reason") != "code_snapshot_fallback"
    ]
    commands = []
    target = " ".join(f'"{path}"' for path in repo_paths[:6]) if repo_paths else "repos"
    search_options = " ".join([*CODE_SEARCH_GLOBS, *CODE_SEARCH_EXCLUDES])
    exact_terms = [value for value in terms if value][:8]
    generic_file_terms = [
        value
        for value in term_values
        if is_ascii_search_value(value) and not value.startswith("/") and len(value) >= 4
    ]
    file_terms = unique_terms(path_values[:12]) if path_values else unique_terms(generic_file_terms)[:12]
    if file_terms:
        file_pattern = regex_union(file_terms, path_separators=True)
        commands.append(f'rg --files {target} {search_options} | rg -i "{file_pattern}"')
        commands.append(f'rg --files {target} {search_options} | rg -i "{file_pattern}" | rg -i "{CODE_TRACE_PATH_PATTERN}"')
    if exact_terms:
        commands.append(f'rg -n -i "{regex_union(exact_terms)}" {target} {search_options}')
    content_terms = search_values[:10]
    if content_terms and regex_union(content_terms) != regex_union(exact_terms):
        commands.append(f'rg -n -i "{regex_union(content_terms)}" {target} {search_options}')
    for value in search_values[:3]:
        escaped = value.replace('"', '\\"')
        commands.append(f'rg -n -i "{escaped}" {target} {search_options}')
    return commands


def suggested_rg_commands_by_workspace(terms: list[str], anchors: list[dict], repos: list[dict], workspaces: list[dict]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for workspace in workspaces:
        knowledge_id = str(workspace.get("knowledge_id", ""))
        workspace_repos = [
            repo
            for repo in repos
            if str(repo.get("knowledge_id", "")) == knowledge_id
        ]
        result[knowledge_id] = suggested_rg_commands(terms, anchors, workspace_repos)
    return result


def expanded_search_values(terms: list[str]) -> list[str]:
    values: list[str] = []
    for term in terms:
        if term not in values:
            values.append(term)
        for alias in CODE_SEARCH_ALIASES.get(term, []):
            if alias not in values:
                values.append(alias)
    return values


def is_ascii_search_value(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_./:-]+", value))


def regex_union(values: list[str], path_separators: bool = False) -> str:
    return "|".join(regex_value(value, path_separators=path_separators) for value in values if value)


def regex_value(value: str, path_separators: bool = False) -> str:
    if path_separators and ("/" in value or "\\" in value):
        normalized = value.replace("\\", "/")
        parts = [part for part in normalized.split("/") if part]
        if parts:
            return r"[\\/]".join(re.escape(part) for part in parts).replace('"', '\\"')
    return re.escape(value).replace('"', '\\"')


def is_searchable_endpoint(value: str) -> bool:
    if not value.startswith("/"):
        return False
    normalized = value.strip().rstrip("/")
    lowered = normalized.lower()
    if value.strip().endswith("/"):
        return False
    if not normalized or normalized in {"/api", "/apis", "/service", "/services"}:
        return False
    if "." in normalized:
        return False
    if lowered.startswith(("/sources/", "/repos/", "/wiki/", "/state/", "/raw/", "/relations/")):
        return False
    path_markers = {
        "src",
        "main",
        "java",
        "resources",
        "frontend",
        "backend",
        "entities",
        "code",
        "features",
        "modules",
        "repositories",
    }
    if any(part in path_markers for part in lowered.split("/") if part):
        return False
    if len([part for part in normalized.split("/") if part]) < 2:
        return False
    return True



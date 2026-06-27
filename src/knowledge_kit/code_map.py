from __future__ import annotations

import re


CODE_MAP_TERM_ALIASES = {
    "数据权限": ["访问管控", "访问控制"],
}


def evidence_code_map_repo_scores(repos: list[dict], evidence_pages: list[dict], terms: list[str], modules: list[str]) -> dict[str, int]:
    scores: dict[str, int] = {}
    matches = evidence_code_map_matches(evidence_pages, terms, modules)
    for match in matches:
        relevance = int(match.get("relevance_score", 0))
        row = match.get("row", {})
        if not isinstance(row, dict):
            continue
        for repo in repos:
            if not isinstance(repo, dict) or not code_map_row_matches_repo(row, repo):
                continue
            repo_key = str(repo.get("repo_id") or repo.get("path") or "")
            if repo_key:
                scores[repo_key] = max(scores.get(repo_key, 0), 30 + relevance)
    return scores


def evidence_code_path_repo_scores(repos: list[dict], evidence_pages: list[dict]) -> dict[str, int]:
    scores: dict[str, int] = {}
    candidate_paths: list[str] = []
    for page in evidence_pages:
        if not str(page.get("path", "")).replace("\\", "/").startswith("wiki/entities/code/features/"):
            continue
        content = str(page.get("content", ""))
        for match in re.finditer(r"\b(?:repos/)?[\w./-]+\.(?:java|kt|js|jsx|ts|tsx|vue|py|go|xml|yml|yaml|json|sql)\b", content):
            value = normalize_code_path_anchor(match.group(0))
            if value:
                candidate_paths.append(value)
    if not candidate_paths:
        return scores
    for repo in repos:
        if not isinstance(repo, dict):
            continue
        repo_key = str(repo.get("repo_id") or repo.get("path") or "")
        repo_path = str(repo.get("path") or "")
        if not repo_key or not repo_path:
            continue
        for value in candidate_paths:
            if path_refers_to_repo(value, repo_path):
                scores[repo_key] = scores.get(repo_key, 0) + 6
    return scores


def evidence_code_map_matches(evidence_pages: list[dict], terms: list[str], modules: list[str]) -> list[dict]:
    lowered_terms = [term.lower() for term in terms if term]
    matches: list[dict] = []
    for page in evidence_pages:
        content = str(page.get("content", ""))
        source_path = str(page.get("path", ""))
        for index, row in enumerate(markdown_table_rows(content), start=1):
            if not is_code_map_row(row):
                continue
            row_text = " ".join(row.values()).lower()
            relevance = code_map_row_relevance(row, row_text, lowered_terms, modules)
            if relevance <= 0:
                continue
            matches.append(
                {
                    "evidence_page": source_path,
                    "row_index": index,
                    "relevance_score": relevance,
                    "product_module": code_map_row_value(row, ["产品模块", "module"]),
                    "capability": code_map_row_value(row, ["产品能力/场景", "产品能力", "场景", "capability"]),
                    "repo_text": code_map_row_value(row, ["对应 Repo", "对应 repo", "repo", "仓库"]),
                    "entrypoint_text": code_map_row_value(row, ["经代码仓库验证的入口", "入口", "路径", "entry"]),
                    "judgement": code_map_row_value(row, ["当前导航判断", "对应状态", "状态"]),
                    "row": row,
                }
            )
    matches.sort(key=lambda item: (-int(item.get("relevance_score", 0)), str(item.get("evidence_page", "")), int(item.get("row_index", 0))))
    return matches[:8]


def code_map_row_value(row: dict[str, str], names: list[str]) -> str:
    lowered_names = [name.lower() for name in names]
    for key, value in row.items():
        if key.lower() in lowered_names:
            return value
    return ""


def prioritized_code_anchors(code_map_matches: list[dict], fallback_anchors: list[dict]) -> list[dict]:
    anchors: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for match in code_map_matches:
        source_path = str(match.get("evidence_page", ""))
        for value in code_map_anchor_path_values(match.get("row", {}) if isinstance(match.get("row"), dict) else {}):
            add_code_anchor(anchors, seen, {"kind": "path", "value": value, "evidence_page": source_path})
    for anchor in fallback_anchors:
        if code_map_matches and is_code_module_evidence_path(str(anchor.get("evidence_page", ""))):
            continue
        add_code_anchor(anchors, seen, anchor)
    return anchors[:40]


def is_code_module_evidence_path(path: str) -> bool:
    return path.replace("\\", "/").startswith("wiki/entities/code/modules/")


def add_code_anchor(anchors: list[dict], seen: set[tuple[str, str]], anchor: dict) -> None:
    kind = str(anchor.get("kind", ""))
    value = str(anchor.get("value", ""))
    if not kind or not value:
        return
    if kind == "path":
        value = normalize_code_path_anchor(value)
        if not value:
            return
    key = (kind, value)
    if key in seen:
        return
    seen.add(key)
    anchors.append({"kind": kind, "value": value, "evidence_page": str(anchor.get("evidence_page", ""))})


def code_map_anchor_path_values(row: dict[str, str]) -> list[str]:
    values: list[str] = []
    for value in code_map_candidate_paths(row):
        normalized = normalize_code_path_anchor(value)
        if not normalized:
            continue
        if normalized and normalized not in values:
            values.append(normalized)
    return values


def normalize_code_path_anchor(value: str) -> str:
    normalized = value.replace("\\", "/").strip().strip("`.,;:，。；：)")
    if not normalized:
        return ""
    if ".../" in normalized:
        normalized = normalized.split(".../", 1)[1].lstrip("/")
    elif "..." in normalized:
        normalized = normalized.rsplit("/", 1)[-1]
    if "*" in normalized:
        return ""
    basename = normalized.rsplit("/", 1)[-1].lower()
    if basename in {"package.json", "pom.xml", "package-lock.json", "yarn.lock", "pnpm-lock.yaml"}:
        return ""
    generic_basenames = {
        "index.vue",
        "index.js",
        "index.jsx",
        "index.ts",
        "index.tsx",
        "package.json",
        "pom.xml",
        "application.yml",
        "application.yaml",
    }
    if "/" not in normalized and normalized.lower() in generic_basenames:
        return ""
    return normalized


def markdown_table_rows(content: str) -> list[dict[str, str]]:
    lines = content.splitlines()
    rows: list[dict[str, str]] = []
    index = 0
    while index < len(lines) - 1:
        if is_markdown_table_line(lines[index]) and is_markdown_separator_line(lines[index + 1]):
            headers = parse_markdown_table_line(lines[index])
            index += 2
            while index < len(lines) and is_markdown_table_line(lines[index]):
                cells = parse_markdown_table_line(lines[index])
                if len(cells) == len(headers):
                    rows.append(dict(zip(headers, cells)))
                index += 1
            continue
        index += 1
    return rows


def is_markdown_table_line(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2


def is_markdown_separator_line(line: str) -> bool:
    cells = parse_markdown_table_line(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells)


def parse_markdown_table_line(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def is_code_map_row(row: dict[str, str]) -> bool:
    headers = " ".join(row.keys()).lower()
    return ("repo" in headers or "仓库" in headers) and ("入口" in headers or "路径" in headers or "entry" in headers)


def code_map_row_relevance(row: dict[str, str], row_text: str, lowered_terms: list[str], modules: list[str]) -> int:
    score = 0
    product_module = code_map_row_value(row, ["产品模块", "module"]).lower()
    capability = code_map_row_value(row, ["产品能力/场景", "产品能力", "场景", "capability"]).lower()
    judgement = code_map_row_value(row, ["当前导航判断", "对应状态", "状态"]).lower()
    module_scope_text = " ".join([product_module, capability, judgement])
    module_score = 0
    for module in modules:
        if not module:
            continue
        if module in product_module:
            module_score += 14
        elif module in capability:
            module_score += 8
        elif module in judgement:
            module_score += 4
        elif module in module_scope_text:
            module_score += 4
    topic_score = 0
    topic_match_count = 0
    strong_topic_matched = False
    normalized_modules = {module.lower() for module in modules if module}
    for term in lowered_terms:
        if not term:
            continue
        if term in normalized_modules:
            continue
        matched_values = [term, *CODE_MAP_TERM_ALIASES.get(term, [])]
        if any(value and value in row_text for value in matched_values):
            topic_match_count += 1
            if is_strong_chinese_topic_term(term):
                strong_topic_matched = True
            if len(term) >= 6:
                topic_score += 12
            elif len(term) >= 4:
                topic_score += 7
            else:
                topic_score += 3
    if topic_score <= 0:
        return 0
    strong_terms = [term for term in lowered_terms if term not in normalized_modules and is_strong_chinese_topic_term(term)]
    if strong_terms and not strong_topic_matched and topic_match_count < 2:
        return 0
    return module_score + topic_score


def is_strong_chinese_topic_term(term: str) -> bool:
    return bool(re.fullmatch(r"[\u4e00-\u9fff]+", term) and len(term) >= 4)


def code_map_row_matches_repo(row: dict[str, str], repo: dict) -> bool:
    repo_path = str(repo.get("path", "")).replace("\\", "/").strip("/")
    repo_id = str(repo.get("repo_id", "")).replace("\\", "/").strip("/")
    repo_name = repo_path.removeprefix("repos/") if repo_path.startswith("repos/") else repo_path
    row_values = " ".join(row.values()).replace("\\", "/").lower()
    repo_tokens = [token.lower() for token in re.split(r"[;；,，、\s`]+", row_values) if token.strip()]
    repo_segments = [segment.lower() for segment in repo_name.split("/") if segment]
    if repo_name and repo_name.lower() in row_values:
        return True
    if repo_id and repo_id.lower() in row_values:
        return True
    meaningful_repo_segments = [segment for segment in repo_segments if segment not in {"frontend", "backend", "src", "main"}]
    if meaningful_repo_segments and any(segment in repo_tokens for segment in meaningful_repo_segments):
        return True
    for value in code_map_candidate_paths(row):
        if path_refers_to_repo(value, repo_path):
            return True
    return False


def code_map_candidate_paths(row: dict[str, str]) -> list[str]:
    values: list[str] = []
    for cell in row.values():
        for match in re.finditer(r"\b(?:repos/)?[\w./-]+\.(?:java|kt|js|jsx|ts|tsx|vue|py|go|xml|yml|yaml|json|sql)\b", cell):
            values.append(match.group(0).strip("`.,;:，。；：)"))
    return values


def path_refers_to_repo(value: str, repo_path: str) -> bool:
    normalized_value = value.replace("\\", "/").strip("/")
    normalized_repo = repo_path.replace("\\", "/").strip("/")
    repo_without_prefix = normalized_repo.removeprefix("repos/")
    return bool(
        normalized_value
        and normalized_repo
        and (
            normalized_value.startswith(normalized_repo)
            or normalized_value.startswith(repo_without_prefix)
            or normalized_repo.startswith(normalized_value)
        )
    )

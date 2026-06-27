from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from knowledge_kit.errors import KnowledgeKitError

from .models import CodeRun
from .repo_map import language_for
from .workspace import mark_stage


class EvidenceError(KnowledgeKitError):
    code = "kcode_evidence_error"


def load_plan(run: CodeRun) -> dict:
    path = run.run_dir / "plan" / "analysis-plan.json"
    if not path.exists():
        raise EvidenceError("analysis_plan_missing")
    return json.loads(path.read_text(encoding="utf-8"))


def select_batch(plan: dict, batch_id: str | None) -> dict:
    batches = plan.get("batches", [])
    if not batches:
        raise EvidenceError("analysis_plan_has_no_batches")
    if not batch_id:
        return batches[0]
    for batch in batches:
        if batch.get("batch_id") == batch_id:
            return batch
    raise EvidenceError(f"batch_not_found:{batch_id}")


def batch_slug(batch: dict) -> str:
    return f"{batch.get('batch_id', 'B000')}-{batch.get('slug') or 'batch'}"


def collect_evidence(run: CodeRun, batch_id: str | None) -> dict:
    plan = load_plan(run)
    batch = select_batch(plan, batch_id)
    slug = batch_slug(batch)
    batch_dir = run.run_dir / "batches" / slug
    batch_dir.mkdir(parents=True, exist_ok=True)
    seeds = planned_files(batch)
    repo_roots = repo_roots_for(run, batch, seeds)
    expansion = expand_evidence(run, seeds, batch, repo_roots)
    files = expansion["files"]
    snippets = []
    file_entries = []
    for index, relative in enumerate(files, start=1):
        source = safe_workspace_path(run, relative)
        if not source.exists() or not source.is_file():
            continue
        lines = source.read_text(encoding="utf-8", errors="replace").splitlines()
        start, end = full_file_range(lines)
        text = "\n".join(lines[start - 1 : end])
        evidence_id = f"E-{batch.get('batch_id', 'B000')}-{index:03d}"
        file_entries.append(
            {
                "path": relative,
                "repo_id": repo_id_for(relative, repo_roots),
                "commit": "",
                "language": language_for(Path(relative)),
                "ranges": [{"start": start, "end": end, "reason": "implementation closure evidence"}],
                "symbols": [],
                "hash": f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}",
            }
        )
        snippets.append({"evidence_id": evidence_id, "file": relative, "start": start, "end": end, "text": text})
    payload = {
        "schema_version": "kcode.evidence.v1",
        "batch_id": batch.get("batch_id"),
        "repo_ids": batch.get("repo_ids", []),
        "closure": expansion["closure"],
        "files": file_entries,
        "snippets": snippets,
    }
    target = batch_dir / "evidence.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    mark_stage(run, "evidence", "completed", {f"batch_{batch.get('batch_id')}_evidence": target.relative_to(run.run_dir).as_posix()})
    return {"batch": batch, "batch_dir": batch_dir, "evidence": payload}


def planned_files(batch: dict) -> list[str]:
    values: list[str] = []
    for key in ("paths", "entrypoints"):
        for item in batch.get(key, []):
            value = str(item).split(":", 1)[0].replace("\\", "/")
            if value and value not in values:
                values.append(value)
    return values


def expand_evidence_files(run: CodeRun, seed_files: list[str], batch: dict, repo_roots: list[tuple[str, Path]] | None = None) -> list[str]:
    return expand_evidence(run, seed_files, batch, repo_roots)["files"]


def expand_evidence(run: CodeRun, seed_files: list[str], batch: dict, repo_roots: list[tuple[str, Path]] | None = None) -> dict:
    if repo_roots is None:
        repo_roots = repo_roots_for(run, batch, seed_files)
    file_index = build_file_index(repo_roots)
    endpoint_index = build_endpoint_index(repo_roots)
    frontend_api_index = build_frontend_api_index(repo_roots)
    queue = list(seed_files)
    seen: set[str] = set()
    ordered: list[str] = []
    references: list[dict] = []
    focus_symbols = focus_symbols_for(run, seed_files)
    while queue:
        relative = queue.pop(0)
        if relative in seen:
            continue
        seen.add(relative)
        source = safe_workspace_path(run, relative)
        if not source.exists() or not source.is_file():
            continue
        ordered.append(relative)
        if source.suffix.lower() in {".js", ".jsx", ".ts", ".tsx", ".vue"}:
            focus_symbols.update(api_call_symbols(source.read_text(encoding="utf-8", errors="replace")))
        for reference in referenced_files(source, relative, file_index, endpoint_index, frontend_api_index, run.workspace.workspace_root, focus_symbols):
            target = reference["target"]
            references.append(reference)
            if target not in seen and target not in queue:
                queue.append(target)
    return {
        "files": ordered,
        "closure": {
            "seed_files": seed_files,
            "focus_symbols": sorted(focus_symbols),
            "expansion_policy": "worklist_until_no_new_references_without_fixed_file_or_line_budget",
            "stopped_reason": "worklist_exhausted",
            "file_count": len(ordered),
            "reference_count": len(references),
            "followed_reference_kinds": sorted({item["kind"] for item in references}),
            "references": references,
        },
    }


def repo_roots_for(run: CodeRun, batch: dict, seed_files: list[str]) -> list[tuple[str, Path]]:
    roots: list[tuple[str, Path]] = []
    selectors = [str(item).replace("\\", "/").strip("/") for item in [*batch.get("repo_ids", []), *seed_files]]
    for name, repo_rel in inventory_repo_entries(run):
        if any(selector_matches_repo(selector, name, repo_rel) for selector in selectors):
            repo_abs = run.workspace.workspace_root / repo_rel
            if repo_abs.exists() and (repo_rel, repo_abs) not in roots:
                roots.append((repo_rel, repo_abs))
    if roots:
        return roots
    for item in seed_files:
        normalized = item.replace("\\", "/")
        parts = Path(normalized).parts
        if len(parts) >= 2 and parts[0] == "repos":
            repo_rel = f"repos/{parts[1]}"
            repo_abs = run.workspace.workspace_root / repo_rel
            if repo_abs.exists() and (repo_rel, repo_abs) not in roots:
                roots.append((repo_rel, repo_abs))
    return roots


def inventory_repo_entries(run: CodeRun) -> list[tuple[str, str]]:
    path = run.run_dir / "inventory" / "submodules.json"
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = []
    for item in payload.get("submodules", []):
        repo_path = str(item.get("path", "")).replace("\\", "/").strip("/")
        repo_name = str(item.get("name", "")).replace("\\", "/").strip("/")
        if repo_path:
            entries.append((repo_name or repo_path, repo_path))
    return sorted(entries, key=lambda item: len(item[1]), reverse=True)


def selector_matches_repo(selector: str, repo_name: str, repo_path: str) -> bool:
    if not selector:
        return False
    return (
        selector == repo_name
        or selector == repo_path
        or selector.startswith(f"{repo_path}/")
        or selector.startswith(f"{repo_name}/")
    )


def build_file_index(repo_roots: list[tuple[str, Path]]) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    suffixes = {".java", ".kt", ".js", ".jsx", ".ts", ".tsx", ".vue", ".py", ".go", ".xml", ".yml", ".yaml", ".json"}
    ignored_dirs = {".git", "node_modules", "target", "build", "dist", ".next", ".nuxt", ".venv", "__pycache__"}
    for repo_rel, repo_abs in repo_roots:
        for path in repo_abs.rglob("*"):
            if any(part in ignored_dirs for part in path.relative_to(repo_abs).parts[:-1]):
                continue
            if not path.is_file() or path.suffix.lower() not in suffixes:
                continue
            relative = f"{repo_rel}/{path.relative_to(repo_abs).as_posix()}"
            index.setdefault(path.stem, []).append(relative)
    return index


def build_endpoint_index(repo_roots: list[tuple[str, Path]]) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for repo_rel, repo_abs in repo_roots:
        for path in repo_abs.rglob("*"):
            if any(part in {".git", "node_modules", "target", "build", "dist"} for part in path.relative_to(repo_abs).parts[:-1]):
                continue
            if not path.is_file() or path.suffix.lower() not in {".java", ".kt"}:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            relative = f"{repo_rel}/{path.relative_to(repo_abs).as_posix()}"
            for token in spring_endpoint_tokens(text):
                index.setdefault(token, []).append(relative)
    return index


def build_frontend_api_index(repo_roots: list[tuple[str, Path]]) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    suffixes = {".js", ".jsx", ".ts", ".tsx"}
    ignored_dirs = {".git", "node_modules", "target", "build", "dist", ".next", ".nuxt"}
    for repo_rel, repo_abs in repo_roots:
        for path in repo_abs.rglob("*"):
            if any(part in ignored_dirs for part in path.relative_to(repo_abs).parts[:-1]):
                continue
            if not path.is_file() or path.suffix.lower() not in suffixes:
                continue
            relative = f"{repo_rel}/{path.relative_to(repo_abs).as_posix()}"
            text = path.read_text(encoding="utf-8", errors="replace")
            if not looks_like_frontend_api_module(relative, text):
                continue
            module = path.stem
            for symbol in frontend_api_exports(text):
                index.setdefault(f"{module}.{symbol}", []).append(relative)
                index.setdefault(symbol, []).append(relative)
    return index


def looks_like_frontend_api_module(relative: str, text: str) -> bool:
    normalized = relative.replace("\\", "/")
    if any(part in normalized for part in ["/http/modules/", "/http/moudules/", "/api/"]):
        return True
    return bool(re.search(r"\b(?:axios|request|\$axios)\s*\(", text) and re.search(r"\burl\s*:", text))


def frontend_api_exports(text: str) -> list[str]:
    symbols: list[str] = []
    for pattern in [
        r"\bexport\s+(?:const|function|async\s+function)\s+([A-Za-z_]\w*)\b",
        r"\b([A-Za-z_]\w*)\s*:\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_]\w*)\s*=>",
        r"\b([A-Za-z_]\w*)\s*\([^)]*\)\s*\{",
    ]:
        for match in re.finditer(pattern, text):
            symbol = match.group(1)
            if symbol not in {"if", "for", "while", "switch", "function"}:
                symbols.append(symbol)
    return unique_values(symbols)


def referenced_files(
    source: Path,
    relative: str,
    file_index: dict[str, list[str]],
    endpoint_index: dict[str, list[str]],
    frontend_api_index: dict[str, list[str]],
    workspace_root: Path,
    focus_symbols: set[str],
) -> list[dict]:
    text = source.read_text(encoding="utf-8", errors="replace")
    suffix = source.suffix.lower()
    refs: list[dict] = []
    if suffix in {".js", ".jsx", ".ts", ".tsx", ".vue"}:
        refs.extend(resolve_js_imports(source, text, workspace_root, relative))
        refs.extend(resolve_frontend_api_calls(text, frontend_api_index, relative))
        refs.extend(resolve_endpoint_refs(text, endpoint_index, relative, focus_symbols))
    if suffix in {".java", ".kt"}:
        refs.extend(resolve_java_refs(text, file_index, relative))
    return unique_existing_refs(refs)


def resolve_js_imports(source: Path, text: str, workspace_root: Path, relative: str) -> list[dict]:
    refs: list[dict] = []
    for match in re.finditer(r"""from\s+['"]([^'"]+)['"]|import\s*\(\s*['"]([^'"]+)['"]\s*\)|import\s+['"]([^'"]+)['"]""", text):
        spec = match.group(1) or match.group(2) or match.group(3)
        base = resolve_js_import_base(source, spec)
        if base is None:
            continue
        kind = "js_alias_import" if spec.startswith("@/") or spec.startswith("~@/") else "js_relative_import"
        for ext in ["", ".ts", ".tsx", ".js", ".jsx", ".vue", ".json", ".css", ".scss", "/index.ts", "/index.js", "/index.vue"]:
            candidate = Path(str(base) + ext)
            if candidate.exists() and candidate.is_file():
                try:
                    refs.append(
                        {
                            "from": relative,
                            "target": candidate.resolve().relative_to(workspace_root.resolve()).as_posix(),
                            "kind": kind,
                            "symbol": spec,
                        }
                    )
                except ValueError:
                    pass
                break
    return refs


def resolve_js_import_base(source: Path, spec: str) -> Path | None:
    if spec.startswith("."):
        return (source.parent / spec).resolve()
    normalized = spec[1:] if spec.startswith("~@/") else spec
    if normalized.startswith("@/"):
        src_root = nearest_src_root(source)
        if src_root is None:
            return None
        return (src_root / normalized[2:]).resolve()
    return None


def nearest_src_root(source: Path) -> Path | None:
    for parent in [source.parent, *source.parents]:
        if parent.name == "src":
            return parent
    for parent in [source.parent, *source.parents]:
        candidate = parent / "src"
        if candidate.exists() and candidate.is_dir():
            return candidate
    return None


def resolve_frontend_api_calls(text: str, frontend_api_index: dict[str, list[str]], relative: str) -> list[dict]:
    refs: list[dict] = []
    for module, method in api_call_pairs(text):
        keys = [f"{module}.{method}", method] if module else [method]
        for key in keys:
            found_for_pair = False
            for target in frontend_api_index.get(key, []):
                refs.append({"from": relative, "target": target, "kind": "frontend_api_module_call", "symbol": key})
                found_for_pair = True
            if found_for_pair and key == f"{module}.{method}":
                break
    return refs


def resolve_endpoint_refs(text: str, endpoint_index: dict[str, list[str]], relative: str, focus_symbols: set[str]) -> list[dict]:
    refs: list[dict] = []
    endpoint_text = focused_js_exports(text, focus_symbols)
    for endpoint in endpoint_paths(endpoint_text):
        for candidate in endpoint_candidates(endpoint):
            targets = endpoint_index.get(candidate, [])
            for target in targets:
                refs.append({"from": relative, "target": target, "kind": "http_endpoint_to_controller", "symbol": endpoint})
            if targets:
                break
    return refs


def resolve_java_refs(text: str, file_index: dict[str, list[str]], relative: str) -> list[dict]:
    names = java_reference_names(text)
    refs: list[dict] = []
    for name in sorted(names):
        if is_generic_java_role_name(name) or is_common_java_type_name(name):
            continue
        for target in java_file_targets(file_index.get(name, [])):
            if target == relative:
                continue
            refs.append({"from": relative, "target": target, "kind": "java_type_reference", "symbol": name})
        for stem, targets in java_file_index_items(file_index):
            if stem == name:
                continue
            if java_related_stem(name, stem):
                for target in targets:
                    if target == relative:
                        continue
                    refs.append({"from": relative, "target": target, "kind": "java_interface_or_contract_implementation", "symbol": name})
    return refs


def java_reference_names(text: str) -> set[str]:
    names: set[str] = set()
    for match in re.finditer(r"import\s+([\w.]+)\.([A-Z]\w+)\s*;", text):
        package = match.group(1)
        name = match.group(2)
        if package.startswith(("java.", "javax.", "jakarta.")):
            continue
        names.add(name)
    signature_text = "\n".join(java_signature_lines(text))
    for pattern in [
        r"\b(?:private|protected|public)\s+(?:static\s+)?(?:final\s+)?([A-Z]\w+)(?:<[^;=(){}]+>)?\s+\w+\s*(?:[;=,)]|\))",
        r"\b([A-Z]\w+)(?:<[^,(){}]+>)?\s+\w+\s*[,)]",
    ]:
        for match in re.finditer(pattern, signature_text):
            names.add(match.group(1))
    for match in re.finditer(r"\bimplements\s+([A-Z]\w+)|\bextends\s+([A-Z]\w+)", text):
        names.add(match.group(1) or match.group(2))
    return names


def java_signature_lines(text: str) -> list[str]:
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("*", "//")):
            continue
        if re.match(r"(?:private|protected|public)\s+", stripped) or re.search(r"\b(?:implements|extends)\b", stripped):
            lines.append(stripped)
    return lines


def focus_symbols_for(run: CodeRun, seed_files: list[str]) -> set[str]:
    symbols: set[str] = set()
    for relative in seed_files:
        source = safe_workspace_path(run, relative)
        if source.exists() and source.is_file() and source.suffix.lower() in {".js", ".jsx", ".ts", ".tsx", ".vue"}:
            symbols.update(api_call_symbols(source.read_text(encoding="utf-8", errors="replace")))
    return symbols


def api_call_symbols(text: str) -> set[str]:
    return {method for _module, method in api_call_pairs(text)}


def api_call_pairs(text: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for pattern in [
        r"(?:this\.)?\$api\.([A-Za-z_]\w*)\.([A-Za-z_]\w*)",
        r"(?:this\.)?\$api\[['\"]([^'\"]+)['\"]\]\.([A-Za-z_]\w*)",
        r"\bapi\.([A-Za-z_]\w*)\.([A-Za-z_]\w*)",
        r"\badpApi\.([A-Za-z_]\w*)",
    ]:
        for match in re.finditer(pattern, text):
            if len(match.groups()) == 1:
                pairs.append(("adpApi", match.group(1)))
            else:
                pairs.append((match.group(1), match.group(2)))
    return unique_pairs(pairs)


def focused_js_exports(text: str, focus_symbols: set[str]) -> str:
    if not focus_symbols:
        return text
    matches = list(re.finditer(r"^\s*export\s+(?:const|function)\s+([A-Za-z_]\w*)\b", text, re.MULTILINE))
    blocks: list[str] = []
    for index, match in enumerate(matches):
        symbol = match.group(1)
        if symbol not in focus_symbols:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        blocks.append(text[match.start() : end])
    return "\n".join(blocks) if blocks else text


def is_generic_java_role_name(name: str) -> bool:
    return name in {
        "Controller",
        "Service",
        "Repository",
        "Mapper",
        "Dao",
        "DAO",
        "Manager",
        "Client",
        "Config",
        "Properties",
        "DTO",
        "Dto",
        "VO",
        "Entity",
        "Model",
        "Job",
        "Task",
    }


def is_common_java_type_name(name: str) -> bool:
    return name in {
        "ArrayList",
        "Arrays",
        "BigDecimal",
        "BigInteger",
        "Boolean",
        "Class",
        "Collection",
        "Collections",
        "Date",
        "Double",
        "Exception",
        "Float",
        "HashMap",
        "HashSet",
        "Integer",
        "LinkedHashMap",
        "List",
        "LocalDate",
        "LocalDateTime",
        "Long",
        "Map",
        "Object",
        "Optional",
        "RuntimeException",
        "Set",
        "String",
        "Stream",
        "UUID",
    }


def java_file_targets(targets: list[str]) -> list[str]:
    return [target for target in targets if Path(target).suffix.lower() in {".java", ".kt"}]


def java_file_index_items(file_index: dict[str, list[str]]) -> list[tuple[str, list[str]]]:
    return [(stem, java_targets) for stem, targets in file_index.items() if (java_targets := java_file_targets(targets))]


def java_related_stem(name: str, stem: str) -> bool:
    if not name or name not in stem:
        return False
    role_suffixes = ("Service", "Repository", "Mapper", "Dao", "DAO", "Manager", "Client", "Config", "Properties")
    if stem.startswith(name) and name.endswith(role_suffixes) and stem.endswith(("Impl", "Implementation")):
        return True
    return stem.endswith(("Impl", "Implementation")) and any(
        name.endswith(suffix)
        for suffix in role_suffixes
    )


def spring_endpoint_tokens(text: str) -> list[str]:
    tokens = annotation_path_tokens(text)
    class_match = re.search(r"\b(?:class|interface)\s+\w+", text)
    if class_match:
        class_tokens = annotation_path_tokens(text[: class_match.start()])
        member_tokens = annotation_path_tokens(text[class_match.end() :])
        for base in class_tokens:
            for leaf in member_tokens:
                combined = combine_endpoint_tokens(base, leaf)
                if combined:
                    tokens.append(combined)
    return unique_values(tokens)


def annotation_path_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for match in re.finditer(
        r"@(?:RequestMapping|GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping)\s*(?:\((.*?)\))?",
        text,
        re.DOTALL,
    ):
        body = match.group(1) or ""
        for quoted in re.finditer(r"""['"]([^'"]+)['"]""", body):
            normalized = normalize_endpoint(quoted.group(1))
            if normalized:
                tokens.append(normalized)
    return unique_values(tokens)


def combine_endpoint_tokens(base: str, leaf: str) -> str:
    normalized_base = base.strip("/")
    normalized_leaf = leaf.strip("/")
    if not normalized_base or not normalized_leaf or normalized_base == normalized_leaf:
        return ""
    if normalized_leaf.startswith(f"{normalized_base}/"):
        return normalized_leaf
    return f"{normalized_base}/{normalized_leaf}"


def endpoint_paths(text: str) -> list[str]:
    paths: list[str] = []
    for match in re.finditer(r"""['"`](/(?:[A-Za-z0-9_$:{}.-]+/)+[A-Za-z0-9_$:{}.-]+)['"`]""", text):
        normalized = normalize_endpoint(match.group(1))
        if normalized:
            paths.append(normalized)
    return unique_values(paths)


def endpoint_candidates(endpoint: str) -> list[str]:
    parts = [part for part in endpoint.strip("/").split("/") if part]
    candidates: list[str] = []
    for length in range(len(parts), 0, -1):
        candidates.append("/".join(parts[:length]))
    return unique_values(candidates)


def normalize_endpoint(value: str) -> str:
    cleaned = value.strip().strip("/")
    if not cleaned or "://" in cleaned or "${" in cleaned:
        return ""
    cleaned = cleaned.split("?", 1)[0].strip("/")
    return cleaned


def unique_existing_refs(refs: list[dict]) -> list[dict]:
    result: list[dict] = []
    for ref in refs:
        target = Path(str(ref.get("target", "")).replace("\\", "/")).as_posix()
        if not target:
            continue
        normalized = {**ref, "target": target}
        key = (normalized.get("from"), normalized.get("target"), normalized.get("kind"), normalized.get("symbol"))
        if not any((item.get("from"), item.get("target"), item.get("kind"), item.get("symbol")) == key for item in result):
            result.append(normalized)
    return result


def unique_values(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def unique_pairs(values: list[tuple[str, str]]) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def safe_workspace_path(run: CodeRun, relative: str) -> Path:
    root = run.workspace.workspace_root.resolve()
    target = (root / relative).resolve()
    if root != target and root not in target.parents:
        raise EvidenceError(f"path_outside_workspace:{relative}")
    return target


def full_file_range(lines: list[str]) -> tuple[int, int]:
    if not lines:
        return 1, 1
    return 1, len(lines)


def repo_id_for(relative: str, repo_roots: list[tuple[str, Path]]) -> str:
    normalized = relative.replace("\\", "/")
    for repo_rel, _ in sorted(repo_roots, key=lambda item: len(item[0]), reverse=True):
        if normalized == repo_rel or normalized.startswith(f"{repo_rel}/"):
            return repo_rel
    parts = Path(normalized).parts
    if len(parts) >= 2 and parts[0] == "repos":
        return f"repos/{parts[1]}"
    return parts[0] if parts else ""

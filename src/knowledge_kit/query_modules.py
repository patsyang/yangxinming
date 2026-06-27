from __future__ import annotations

import re

from .wiki import IndexEntry


COMMON_UPPERCASE_NON_MODULE_TOKENS = {
    "api",
    "http",
    "https",
    "json",
    "xml",
    "sql",
    "jwt",
    "crud",
    "dto",
    "dao",
    "ui",
    "url",
    "uri",
    "id",
    "prd",
    "rbac",
    "sdk",
    "rpc",
    "rest",
    "yaml",
    "yml",
}


def infer_module_aliases(entries: list[IndexEntry]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for entry in entries:
        for value in module_alias_values(entry):
            aliases.setdefault(value.lower(), value)
    return aliases


def module_alias_values(entry: IndexEntry) -> list[str]:
    values: list[str] = []
    normalized_path = entry.path.replace("\\", "/").removeprefix("wiki/")
    parts = [part.removesuffix(".md") for part in normalized_path.split("/") if part]
    for part in parts:
        if module_path_segment_candidate(part):
            values.append(part)
    for text in [entry.title, entry.summary]:
        for token in re.findall(r"(?<![A-Za-z0-9])[A-Z][A-Z0-9_-]{1,11}(?![A-Za-z0-9])", text):
            lowered = token.lower()
            if lowered not in COMMON_UPPERCASE_NON_MODULE_TOKENS:
                values.append(token)
        for token in re.findall(r"\b[A-Z][A-Za-z0-9]+(?:/[A-Z][A-Za-z0-9]+)+\b", text):
            for part in token.split("/"):
                lowered = part.lower()
                if lowered not in COMMON_UPPERCASE_NON_MODULE_TOKENS:
                    values.append(part)
    return unique(values)


def module_path_segment_candidate(value: str) -> bool:
    cleaned = value.strip()
    lowered = cleaned.lower()
    if not cleaned or lowered in COMMON_UPPERCASE_NON_MODULE_TOKENS:
        return False
    if lowered in {"entities", "code", "product", "features", "modules", "sources", "concepts", "wiki"}:
        return False
    return bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{1,15}", cleaned) and (cleaned.isupper() or "-" not in cleaned))


def unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result

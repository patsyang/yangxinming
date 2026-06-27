from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .config import KnowledgeRoot
from .frontmatter import parse_frontmatter


@dataclass(frozen=True)
class WikiPage:
    path: Path
    repo_path: str
    title: str
    page_type: str
    summary: str
    body: str
    aliases: list[str]


@dataclass(frozen=True)
class IndexEntry:
    title: str
    path: str
    summary: str


@dataclass(frozen=True)
class PageLink:
    raw: str
    target: str
    label: str
    link_type: str
    anchor: str | None = None


def relative(root: KnowledgeRoot, path: Path) -> str:
    return path.relative_to(root.path).as_posix()


def iter_wiki_pages(root: KnowledgeRoot) -> list[WikiPage]:
    pages: list[WikiPage] = []
    if not root.wiki_dir.exists():
        return pages
    for path in sorted(root.wiki_dir.rglob("*.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        meta, body = parse_frontmatter(text)
        title = str(meta.get("title") or path.stem)
        page_type = str(meta.get("type") or "unknown")
        aliases = meta.get("aliases") if isinstance(meta.get("aliases"), list) else []
        pages.append(
            WikiPage(
                path=path,
                repo_path=relative(root, path),
                title=title,
                page_type=page_type,
                summary=first_sentence(body),
                body=body,
                aliases=[str(item) for item in aliases],
            )
        )
    return pages


def parse_index(root: KnowledgeRoot) -> list[IndexEntry]:
    index_path = root.wiki_dir / "index.md"
    if not index_path.exists():
        return []
    text = index_path.read_text(encoding="utf-8", errors="replace")
    entries: list[IndexEntry] = []
    pattern = re.compile(r"^\s*-\s*\[([^\]]+)\]\(([^)]+)\)\s*[—-]\s*(.*)$")
    for line in text.splitlines():
        match = pattern.match(line)
        if not match:
            continue
        title, path, summary = match.groups()
        if path.startswith(("http://", "https://", "#")):
            continue
        entries.append(IndexEntry(title=title.strip(), path=path.strip(), summary=summary.strip()))
    return entries


def read_wiki_page(root: KnowledgeRoot, index_path: str) -> WikiPage | None:
    candidate = (root.wiki_dir / index_path).resolve()
    try:
        candidate.relative_to(root.wiki_dir.resolve())
    except ValueError:
        return None
    if not candidate.exists() or not candidate.is_file():
        return None
    text = candidate.read_text(encoding="utf-8", errors="replace")
    meta, body = parse_frontmatter(text)
    return WikiPage(
        path=candidate,
        repo_path=relative(root, candidate),
        title=str(meta.get("title") or candidate.stem),
        page_type=str(meta.get("type") or "unknown"),
        summary=first_sentence(body),
        body=body,
        aliases=[str(item) for item in meta.get("aliases", [])] if isinstance(meta.get("aliases"), list) else [],
    )


def resolve_page_link(root: KnowledgeRoot, source: WikiPage, link: PageLink | str) -> WikiPage | None:
    raw_target = link.target if isinstance(link, PageLink) else str(link)
    normalized = raw_target.split("|", 1)[0].split("#", 1)[0].strip()
    if not normalized:
        return None
    if is_external_link(normalized) or normalized.startswith("#"):
        return None
    normalized = normalized.replace("\\", "/")
    if normalized.startswith("wiki/"):
        normalized = normalized.removeprefix("wiki/")
    candidates: list[Path] = []
    if normalized.endswith(".md"):
        candidates.append(source.path.parent / normalized)
        candidates.append(root.wiki_dir / normalized)
    else:
        candidates.append(source.path.parent / f"{normalized}.md")
        candidates.extend(root.wiki_dir.rglob(f"{normalized}.md"))
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
            resolved.relative_to(root.wiki_dir.resolve())
        except ValueError:
            continue
        if resolved.exists() and resolved.is_file():
            return read_wiki_page(root, resolved.relative_to(root.wiki_dir).as_posix())
    return None


def resolve_wikilink(root: KnowledgeRoot, source: WikiPage, target: str) -> WikiPage | None:
    return resolve_page_link(root, source, target)


def first_sentence(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return ""
    return cleaned[:240]


def extract_page_links(text: str) -> list[PageLink]:
    links: list[PageLink] = []
    seen: set[tuple[str, str]] = set()
    for match in re.finditer(r"\[\[([^\]]+)\]\]", text):
        raw_target = match.group(1).strip()
        target, label = split_wikilink(raw_target)
        add_page_link(links, seen, PageLink(raw=match.group(0), target=target, label=label, link_type="wikilink"))
    for match in re.finditer(r"(?<!!)\[([^\]]+)\]\(([^)]+)\)", text):
        label = match.group(1).strip()
        raw_target = match.group(2).strip()
        if is_external_link(raw_target) or raw_target.startswith("#"):
            continue
        target, anchor = split_anchor(raw_target)
        if not target.endswith(".md"):
            continue
        add_page_link(links, seen, PageLink(raw=match.group(0), target=target, label=label, link_type="markdown", anchor=anchor))
    return links


def split_wikilink(raw_target: str) -> tuple[str, str]:
    target, _, label = raw_target.partition("|")
    target = target.strip()
    return target, (label.strip() or Path(target).stem)


def split_anchor(raw_target: str) -> tuple[str, str | None]:
    target, separator, anchor = raw_target.partition("#")
    return target.strip(), anchor.strip() if separator and anchor.strip() else None


def add_page_link(links: list[PageLink], seen: set[tuple[str, str]], link: PageLink) -> None:
    key = (link.link_type, link.target)
    if key in seen:
        return
    seen.add(key)
    links.append(link)


def is_external_link(target: str) -> bool:
    lowered = target.lower()
    return lowered.startswith(("http://", "https://", "mailto:", "file:"))


def wikilink_targets(text: str) -> list[str]:
    return [link.target for link in extract_page_links(text) if link.link_type == "wikilink"]

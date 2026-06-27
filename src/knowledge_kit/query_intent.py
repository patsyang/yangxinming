from __future__ import annotations

import re

from .config import KitConfig, KnowledgeRoot

MODULE_CANONICAL: dict[str, str] = {}
MODULE_TOKENS: set[str] = set()
DATA_DICTIONARY_HINTS = {"字段", "表", "数据字典", "日志表", "field", "table", "dictionary"}
SOURCE_HINTS = {"来源", "原文", "文档", "手册", "材料"}
SOURCE_TOKEN_HINTS = {"source", "raw"}
REGULATION_HINTS = {"法规", "监管", "合规", "要求", "条例", "办法", "政策", "映射", "regulation", "compliance"}
CROSS_MODULE_HINTS = {"跨模块", "协同", "对比", "比较", "方案", "全景", "全部", "所有", "各模块", "cross-module"}
CODE_NAVIGATION_HINTS = {
    "code_map",
    "代码地图",
    "仓库导航",
    "仓库地图",
    "仓库入口",
    "代码仓库",
    "仓库归属",
    "哪个仓库",
    "哪些仓库",
    "哪个 submodule",
    "哪个submodule",
    "submodule",
    "子模块",
    "先探索",
    "继续探索",
    "不确定归属",
    "需求归属",
    "落在哪",
}
CODE_KNOWLEDGE_HINTS = {
    "代码",
    "实现",
    "新增",
    "字段",
    "筛选",
    "导出",
    "审批",
    "想改",
    "想做",
    "要改",
    "改造",
    "闭合",
    "定位",
    "编码",
    "coding",
    "agentic coding",
    "改动",
    "修改",
    "复用",
    "验证",
    "测试",
    "运行时",
    "生效",
    "下发",
    "配置",
    "PRD",
    "prd",
}
RUNTIME_BOUNDARY_QUERY_HINTS = {
    "运行时",
    "是否生效",
    "真正生效",
    "谁消费",
    "哪里消费",
    "消费链",
    "执行链",
    "执行端",
    "运行边界",
    "runtime",
    "consumer",
}
CODE_TOPIC_STOPWORDS = {
    "agentic",
    "code",
    "coding",
    "prd",
    "run",
    "true",
    "false",
    "repo",
    "repos",
    "repository",
    "udsp",
    "api",
    "如何",
    "怎么",
    "从",
    "帮我",
    "帮忙",
    "知识库",
    "梳理一下",
    "梳理",
    "一下",
    "应该",
    "哪些",
    "什么",
    "一个",
    "这个",
    "那个",
    "功能",
    "能力",
    "需求",
    "字段",
    "状态",
    "列表",
    "筛选",
    "条件",
    "改列表筛选",
    "改导出",
    "加审批字段",
    "审批字段",
    "改运行时生效",
    "设计",
    "实现",
    "开发",
    "编码",
    "要改",
    "改造",
    "修改",
    "新增",
    "查询",
    "查看",
    "是否",
    "闭合",
    "当前",
    "已在",
    "仓库",
    "后端",
    "前端",
    "是否生效",
    "真正生效",
    "运行时",
    "运行边界",
    "谁消费",
    "哪里消费",
    "消费",
    "执行链",
    "执行端",
    "代码",
    "知识",
    "支撑",
    "进行",
    "自动",
    "补齐",
    "基于",
    "现状",
    "以及",
    "或者",
    "和",
    "与",
    "的",
}

def tokens(query: str) -> list[str]:
    found = re.findall(r"[a-zA-Z0-9_-]+|[\u4e00-\u9fff]+", query)
    result: list[str] = []
    for item in found:
        if re.fullmatch(r"[a-zA-Z0-9_-]+", item):
            result.append(item.lower())
            continue
        result.append(item)
        for size in (4, 3, 2):
            for index in range(0, max(0, len(item) - size + 1)):
                result.append(item[index : index + size])
    seen: set[str] = set()
    unique: list[str] = []
    for item in result:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def wants_data_dictionary(query: str) -> bool:
    lowered = query.lower()
    return any(hint.lower() in lowered for hint in DATA_DICTIONARY_HINTS)


def wants_source_page(query: str) -> bool:
    lowered = query.lower()
    if any(hint.lower() in lowered for hint in SOURCE_HINTS):
        return True
    query_tokens = tokens(query)
    return any(hint in query_tokens for hint in SOURCE_TOKEN_HINTS)


def wants_regulation_page(query: str) -> bool:
    lowered = query.lower()
    return any(hint.lower() in lowered for hint in REGULATION_HINTS)


def wants_cross_module(query: str) -> bool:
    lowered = query.lower()
    return any(hint.lower() in lowered for hint in CROSS_MODULE_HINTS)


def wants_code_navigation(query: str) -> bool:
    lowered = query.lower()
    return any(hint.lower() in lowered for hint in CODE_NAVIGATION_HINTS)


def wants_code_knowledge(query: str) -> bool:
    lowered = query.lower()
    return wants_code_navigation(query) or any(hint.lower() in lowered for hint in CODE_KNOWLEDGE_HINTS)


def wants_runtime_boundary(query: str) -> bool:
    lowered = query.lower()
    return any(hint.lower() in lowered for hint in RUNTIME_BOUNDARY_QUERY_HINTS)


def is_code_knowledge_root(root: KnowledgeRoot) -> bool:
    identity = f"{root.id} {root.name}".lower()
    return "code" in identity or "代码" in identity


def has_configured_code_workspace(config: KitConfig, root: KnowledgeRoot) -> bool:
    code_config = config.data.get("code", {})
    workspaces = code_config.get("workspaces", {}) if isinstance(code_config, dict) else {}
    return isinstance(workspaces, dict) and root.id in workspaces


def canonical_module(value: str, module_aliases: dict[str, str] | None = None) -> str | None:
    cleaned = value.strip().removesuffix(".md").lower()
    aliases = module_aliases if module_aliases is not None else MODULE_CANONICAL
    return aliases.get(cleaned)


def module_key_matches_text(key: str, lowered_text: str) -> bool:
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])", lowered_text))


def detect_query_intent(query: str, module_aliases: dict[str, str] | None = None) -> dict:
    aliases = module_aliases if module_aliases is not None else MODULE_CANONICAL
    modules: list[str] = []
    for token in tokens(query):
        module = canonical_module(token, aliases)
        if module and module not in modules:
            modules.append(module)
    lowered = query.lower()
    for key, module in aliases.items():
        if module_key_matches_text(key, lowered) and module not in modules:
            modules.append(module)
    intents = ["feature_query"]
    if wants_data_dictionary(query):
        intents.append("data_dictionary_query")
    if wants_source_page(query):
        intents.append("source_query")
    if wants_regulation_page(query):
        intents.append("regulation_query")
    if wants_cross_module(query):
        intents.append("cross_module_query")
    if wants_code_navigation(query):
        intents.append("code_navigation_query")
    return {
        "query": query,
        "modules": modules,
        "intents": intents,
        "wants_source": wants_source_page(query),
        "wants_data_dictionary": wants_data_dictionary(query),
        "wants_regulation": wants_regulation_page(query),
        "wants_cross_module": wants_cross_module(query),
        "wants_code_navigation": wants_code_navigation(query),
        "wants_code_knowledge": wants_code_knowledge(query),
    }


def code_query_topic_terms(query: str, module_aliases: dict[str, str] | None = None) -> list[str]:
    aliases = module_aliases if module_aliases is not None else MODULE_CANONICAL
    result: list[str] = []
    chinese_stopwords = [word for word in CODE_TOPIC_STOPWORDS if re.fullmatch(r"[\u4e00-\u9fff]+", word)]
    splitter = re.compile("|".join(re.escape(word) for word in sorted(chinese_stopwords, key=len, reverse=True)))
    for raw in re.findall(r"[A-Za-z][A-Za-z0-9_-]*|[\u4e00-\u9fff]+", query):
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", raw):
            normalized = raw.lower().strip()
            if normalized in CODE_TOPIC_STOPWORDS or canonical_module(normalized, aliases) or len(normalized) < 3:
                continue
            if normalized not in result:
                result.append(normalized)
            continue
        for part in splitter.sub(" ", raw).split():
            normalized = part.strip()
            if len(normalized) < 2:
                continue
            for term in chinese_topic_variants(normalized):
                if term not in result:
                    result.append(term)
    return result


def chinese_topic_variants(value: str) -> list[str]:
    variants = [value]
    for size in (4, 3, 2):
        if len(value) <= size:
            continue
        for index in range(0, len(value) - size + 1):
            variants.append(value[index : index + size])
    return variants


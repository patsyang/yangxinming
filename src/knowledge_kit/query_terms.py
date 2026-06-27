from __future__ import annotations

import re


ALNUM_TOPIC_STOPWORDS = {"api", "prd", "udsp", "code", "coding", "agentic"}
CHINESE_TOPIC_STOPWORDS = {
    "从",
    "帮我",
    "帮忙",
    "知识库",
    "梳理一下",
    "梳理",
    "一下",
    "如何",
    "怎么",
    "应该",
    "有哪些",
    "哪些",
    "什么",
    "一个",
    "这个",
    "那个",
    "模块",
    "功能",
    "能力",
    "需求",
    "设计",
    "实现",
    "实现边界",
    "开发",
    "编码",
    "要改",
    "想做",
    "想改",
    "用户想做",
    "用户想改",
    "改造",
    "修改",
    "新增",
    "新增字段",
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
    "配置",
    "怎么写",
    "为什么",
    "为何",
    "原因",
    "问题",
    "查",
    "要查",
    "查询",
    "查看",
    "是否",
    "闭合",
    "为空",
    "未生效",
    "没生效",
    "保存后",
    "现有",
    "已有",
    "哪里",
    "代码",
    "知识",
    "支撑",
    "进行",
    "自动",
    "补齐",
    "基于",
    "现状",
    "边界",
    "以及",
    "或者",
    "和",
    "与",
    "的",
}
CHINESE_TOPIC_COMPOUNDS = {
    "数据源访问控制",
    "访问控制",
    "访问策略",
    "策略下发",
    "下发流程",
    "策略生效",
    "数据权限",
    "数据脱敏",
    "文件脱敏",
    "文件策略",
    "审计日志",
    "访问日志",
    "风险告警",
    "风险结果",
    "数据源接入",
    "敏感数据",
    "数据资产",
    "数据集市",
    "任务中心",
    "探针管理",
    "页面保护",
    "页面防护",
    "密钥管理",
    "报表导出",
    "历史导出",
    "授权审批",
    "数据授权",
    "权限申请",
    "资产关系",
}
CODE_SEARCH_ALIASES = {
    "策略": ["policy", "rule", "strategy", "tactic"],
    "生效": ["runtime", "effective", "effect", "consumer"],
    "运行时": ["runtime", "consumer"],
    "数据流": ["flow", "lineage", "trace"],
    "数据保护": ["protect", "protection"],
    "保护": ["protect", "protection"],
    "权限": ["auth", "permission", "scope"],
    "授权": ["auth", "authorization"],
    "脱敏": ["mask", "masking"],
    "风险": ["risk"],
    "日志": ["log", "audit"],
    "审计": ["audit"],
    "告警": ["alert"],
    "水印": ["watermark"],
}


def query_topic_terms(query: str) -> list[str]:
    terms: list[str] = []
    for raw in re.findall(r"[A-Za-z][A-Za-z0-9_-]*|[\u4e00-\u9fff]+", query):
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", raw):
            lowered = raw.lower()
            if lowered not in ALNUM_TOPIC_STOPWORDS and len(lowered) >= 2:
                terms.append(lowered)
            continue
        cleaned = raw
        for stop in sorted(CHINESE_TOPIC_STOPWORDS, key=len, reverse=True):
            cleaned = cleaned.replace(stop, " ")
        for part in re.split(r"\s+", cleaned.strip()):
            if len(part) < 2:
                continue
            terms.extend(chinese_topic_terms(part))
    return unique_terms(terms)


def chinese_topic_terms(value: str) -> list[str]:
    if len(value) <= 4:
        terms = [value]
        for alias_key in CODE_SEARCH_ALIASES:
            if alias_key != value and alias_key in value:
                terms.append(alias_key)
        return terms
    terms: list[str] = []
    if len(value) <= 8:
        terms.append(value)
    known_subterms: list[str] = []
    for compound in sorted(CHINESE_TOPIC_COMPOUNDS, key=len, reverse=True):
        if compound in value:
            known_subterms.append(compound)
    for alias_key in CODE_SEARCH_ALIASES:
        if alias_key != value and alias_key in value:
            known_subterms.append(alias_key)
    terms.extend(unique_terms(known_subterms))
    if known_subterms:
        return terms
    for size in (4, 3):
        for index in range(0, len(value) - size + 1):
            term = value[index : index + size]
            if len(term) >= 2:
                terms.append(term)
    return terms


def unique_terms(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(value.strip())
    return result


def evidence_covers_query_topic(topic_terms: list[str], code_feature_pages: list[dict]) -> bool:
    if not topic_terms:
        return True
    content = "\n".join(str(page.get("content", "")) for page in code_feature_pages).lower()
    compound_terms = [term for term in topic_terms if is_strong_chinese_topic_term(term)]
    if compound_terms and not any(term.lower() in content for term in compound_terms):
        return False
    matched = [term for term in topic_terms if term.lower() in content]
    required = len(topic_terms) if len(topic_terms) <= 2 else max(2, (len(topic_terms) + 2) // 3)
    return len(matched) >= required


def is_strong_chinese_topic_term(term: str) -> bool:
    return bool(term in CHINESE_TOPIC_COMPOUNDS or (re.fullmatch(r"[\u4e00-\u9fff]+", term) and len(term) >= 4))

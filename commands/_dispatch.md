# Slash Command Dispatch

用户消息以 `/` 开头时，视为项目命令调用。查下表定位目标，读取对应文件并按其指令执行。

| 命令 | 目标 |
|------|------|
| `/k query` | `contracts/k/query-workflow.md` |
| `/k code` | `contracts/k/code-workflow.md` |
| `/k update` | `contracts/k/update-workflow.md` |
| `/k init` | `contracts/k/command-contract.md` → `init` action |
| `/k lint` | `contracts/k/lint-validate-workflow.md` |
| `/k validate` | `contracts/k/lint-validate-workflow.md` |
| `/k ingest` | `contracts/k/ingest-workflow.md` |
| `/yxm-fp` | `.trae/skills/yxm-first-principles-decomposer/SKILL.md` |
| `/yxm-gd` | `.trae/skills/yxm-grill-with-docs/SKILL.md` |
| `/yxm-l` | `.trae/skills/yxm-learn/SKILL.md` |
| `/yxm-pca` | `.trae/skills/yxm-product-concept-audit/SKILL.md` |
| `/yxm-pcp` | `.trae/skills/yxm-product-concept-profile/SKILL.md` |
| `/yxm-pr` | `.trae/skills/yxm-product-research/SKILL.md` |
| `/yxm-ps` | `.trae/skills/yxm-product-structure/SKILL.md` |
| `/yxm-qa` | `.trae/skills/yxm-qa/SKILL.md` |
| `/yxm-k` | `.trae/skills/yxm-rank/SKILL.md` |
| `/yxm-repo` | `.trae/skills/yxm-research-repo/SKILL.md` |
| `/yxm-rt` | `.trae/skills/yxm-roundtable/SKILL.md` |
| `/yxm-sy` | `.trae/skills/yxm-synthesis/SKILL.md` |
| `/yxm-t` | `.trae/skills/yxm-think/SKILL.md` |
| `/yxm-w` | `.trae/skills/yxm-writes/SKILL.md` |
| `/yxm-ceo` | `.trae/skills/yxm-plan-ceo-review/SKILL.md` |
| `/yxm-prd` | `.trae/skills/yxm-prd-kit/SKILL.md` |
| `/yxm-pld` | `.trae/skills/yxm-product-landscape-discovery/SKILL.md` |
| `/yxm-sf` | `.trae/skills/yxm-skill-factory/SKILL.md` |
| `/yxm-sf2` | `.trae/skills/yxm-skill-factory-v2/SKILL.md` |
| `/yxm-ui` | `.trae/skills/yxm-ui-ux-pro-max/SKILL.md` |
| `/yxm-fund` | `.trae/skills/yxm-fund/SKILL.md` |

## 规则

- 命令后可带参数，由目标文件定义解析方式。
- `/k` 子命令必须带 action：`query`、`code`、`update`、`init`、`lint`、`validate`、`ingest`。
- `/k` 子命令执行前先运行 `python -m knowledge_kit <action>` 获取确定性输出，再按合同完成模型执行层。
- 不在表中的 `/` 开头输入按普通消息处理，不报错。

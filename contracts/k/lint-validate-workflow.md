# /k lint and validate Workflow

## /k lint

完整 Karpathy LINT 包含：

1. contradictions。
2. stale claims。
3. orphan pages。
4. missing concepts。
5. broken links。
6. data gaps。
7. thin pages。
8. 能修复的由 Codex 修复。
9. 不能修复的输出 review items。
10. 追加 `wiki/log.md`。
11. 判断 relations decision：`rebuild | noop`。

CLI：

```powershell
python -m knowledge_kit lint -k <knowledge_id>
python -m knowledge_kit lint --all
```

CLI 只输出 `mechanical_lint_only=true` 的机械检查子集：必需路径、frontmatter、broken wikilinks、index 覆盖、relation 文件存在性、source summary 薄弱页、代码 feature 页固定章节和 KCode source summary 追溯存在性，以及配置了 `code.workspaces[knowledge_id]` 的代码 knowledge readiness。

代码 feature 页机械检查验证固定二级标题、代码定位线索和 index 可召回摘要。它不替代 verifier 对 KCode evidence、`coding_context`、`blocking_gaps` 和 PRD 设计影响的语义检查。

## /k validate

校验 `knowledge_kit` 配置和外部 knowledge 结构：

- JSON 配置。
- knowledge id 唯一性。
- `enabled`、`mode`、`path`。
- enabled knowledge 的必需目录和核心 wiki 文件。
- 不修改文件。
- 不等同 Karpathy LINT。

CLI：

```powershell
python -m knowledge_kit validate
python -m knowledge_kit validate -k <knowledge_id>
```

# /k ingest Workflow

`/k ingest` 对一个明确指定的外部 knowledge 执行完整 Karpathy INGEST。

## 契约

- `-k` 必填。
- `--src` 必填。
- 目标必须 enabled 且 read_write。
- 单次命令只能写一个 knowledge。
- source 进入 selected knowledge root 的 `raw/`。

## Karpathy INGEST

1. 读取 `raw/` 中来源。
2. 写 source summary。
3. 创建或更新 concept pages。
4. 创建或更新 entity pages。
5. 更新 cross-references。
6. 必要时更新 overview。
7. 更新 index/log。
8. 判断 relations decision：`rebuild | noop`。
9. 调用 verifier handoff。

## CLI

```powershell
python -m knowledge_kit ingest -k <knowledge_id> --src <source_path>
```

CLI 只做 source registration：把来源复制或登记到 `raw/`，并输出后续 INGEST steps。不创建简化 source/concept/entity 正文页，不更新 `index.md` 或 `log.md`。

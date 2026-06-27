---
name: yxm-research-repo
description: 研究本地 third_party 仓库或 GitHub 仓库源码，并创建或更新 ai_docs/research 下的项目研究索引文档。Use when 用户要求 /pat-repo、research_repo、research-repo、研究 repo、研究 third_party 项目、为某个仓库生成研究文档，或提供 GitHub link 并要求先 clone 到 third_party 后分析。
---

# Research Repo

## 目标

研究一个仓库，并在 `ai_docs/research/` 下产出可长期复用的项目研究索引。

项目内 slash command 入口是 `/pat-repo`。

输入支持两种形式：

- 本地 repo 名，例如 `sandbox-runtime`，对应 `third_party/sandbox-runtime`
- GitHub URL，例如 `https://github.com/org/repo`

如果输入是 GitHub URL，先 clone 到 `third_party/<repo-name>`，再进行源码研究。

## 工作流程

1. 先检查工作区状态：
   - 运行 `git status`
   - 运行 `git status --porcelain`
   - 不覆盖、不回滚用户已有改动。

2. 解析研究对象：
   - 如果输入是 repo 名，读取 `third_party/<repo-name>`。
   - 如果输入是 GitHub URL，从 URL 推导 `<repo-name>`，clone 到 `third_party/<repo-name>`。
   - 如果目标目录已存在，直接研究已有目录；除非用户明确要求刷新，否则不要重新 clone。

3. 探索仓库：
   - 优先查看 `README*`、package/build 配置、源码目录、测试目录、示例、CI 配置。
   - 优先使用 `rg --files` 和定向 `rg` 搜索。
   - 重点识别：
     - 项目介绍
     - 目录结构
     - 架构
     - 关键模块
     - 技术栈
     - 入口文件
     - 构建和测试命令
     - 对本工作区的参考价值
     - 后续深挖问题

4. 创建或更新研究文档：
   - 路径格式：`ai_docs/research/{repo-name}-project-index.md`
   - 必须包含 front matter：
     - `topic`
     - `sources`
     - `date`
     - `last_verified`
     - `scope`
     - `tags`
   - 正文使用中文。
   - 文档定位是“后续研究索引”，不是执行日志。

5. 更新研究总索引：
   - 更新 `ai_docs/research/INDEX.md`
   - 在索引表顶部附近增加一行。
   - 保持既有表格格式。

6. 验证：
   - 运行 `git diff --check`
   - 运行 `git diff HEAD`
   - 确认变更只包含预期的研究文档、`INDEX.md`，以及在用户提供 GitHub URL 时可能新增的 `third_party/<repo-name>`。

7. 最终回复：
   - 给出研究文档路径。
   - 说明是否 clone 了 GitHub 仓库。
   - 简要总结关键发现。
   - 不自动提交，除非用户明确要求提交。

## 研究文档建议结构

除非目标仓库更适合其它结构，默认使用以下章节：

1. 项目定位
2. 快速结论
3. 目录结构
4. 技术栈
5. 配置与运行方式
6. 运行架构
7. 关键模块索引
8. 平台 / 部署 / 集成细节
9. 安全设计或关键设计点
10. 测试与验证入口
11. 与本项目的映射
12. 后续深挖路线
13. 待确认问题
14. 阅读入口清单

## 约束

- 不默认提交：本 skill 只负责研究、写文档和验证；只有用户明确要求提交时才执行 Git commit。
- GitHub clone 不默认纳入版本控制：clone 到 `third_party` 后可以研究，但是否把整个第三方仓库加入 Git，应由用户确认。
- 不读取 `ai_docs/hidden/`，除非用户明确指定该目录或具体文件。

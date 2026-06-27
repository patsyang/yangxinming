from __future__ import annotations

import json
import io
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from knowledge_kit.cli import main
from knowledge_kit.config import load_config
from knowledge_kit.bundle import run_query_bundle
from knowledge_kit.code_exploration import extract_code_anchors_from_evidence, regex_union, suggested_rg_commands_by_workspace
from knowledge_kit.code_map import code_map_row_relevance
from knowledge_kit.errors import KnowledgeDisabled, KnowledgeReadOnly, WriteTargetRequired
from knowledge_kit.init import run_init
from knowledge_kit.ingest import run_ingest
from knowledge_kit.lint import run_lint
from knowledge_kit.query_profiles import profile_evidence_gaps
from knowledge_kit.query_terms import query_topic_terms
from knowledge_kit.query_intent import code_query_topic_terms, detect_query_intent
from knowledge_kit.search import run_query
from knowledge_kit.semantic_plan import LIST_COLLECTION, LIST_ENTITY_ATTRIBUTE, LOCATE_IMPLEMENTATION, infer_operator
from knowledge_kit.update import parse_kcode_manager_request, parse_suggested_output_pages, run_update
from knowledge_kit.workflow_contract import INGEST_REGISTRATION_KIND, INIT_SCAFFOLD_KIND, MAINTENANCE_PREFLIGHT_KIND, QUERY_AGENTIC_CODING_REQUIREMENTS, QUERY_EVIDENCE_BUNDLE_KIND, QUERY_READ_PLAN_KIND


class BufferedStdout:
    def __init__(self) -> None:
        self.buffer = io.BytesIO()

    def write(self, text: str) -> int:
        data = text.encode("utf-8")
        self.buffer.write(data)
        return len(text)

    def flush(self) -> None:
        pass


def wiki_page(title: str, page_type: str, body: str, sources: list[str] | None = None) -> str:
    today = date.today().isoformat()
    source_values = ", ".join(f'"{item}"' for item in (sources or []))
    return (
        "---\n"
        f"title: {title}\n"
        f"type: {page_type}\n"
        "tags: []\n"
        f"created: {today}\n"
        f"updated: {today}\n"
        f"sources: [{source_values}]\n"
        "---\n\n"
        f"{body.rstrip()}\n"
    )


class KnowledgeKitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.project = self.root / "kit"
        self.project.mkdir()
        self.knowledge = self.root / "knowledge_a"
        self.disabled = self.root / "knowledge_b"
        self.read_only = self.root / "knowledge_c"
        self._write_config()
        for path in [self.knowledge, self.read_only]:
            path.mkdir()
        config = load_config(self.project)
        self._create_base_structure(config.get("alpha").path)
        self._create_base_structure(config.get("readonly").path)
        page = self.knowledge / "wiki" / "concepts" / "agentic-workflow.md"
        page.write_text(
            wiki_page(
                "智能体工作流",
                "concept",
                "智能体工作流协调 agent、工具和验证。相关执行者是 [[entities/codex-agent.md]]。",
                sources=[],
            ),
            encoding="utf-8",
        )
        related = self.knowledge / "wiki" / "entities" / "codex-agent.md"
        related.write_text(
            wiki_page(
                "Codex Agent",
                "entity",
                "Codex Agent 执行 Karpathy QUERY 后进行综合。",
                sources=[],
            ),
            encoding="utf-8",
        )
        index = self.knowledge / "wiki" / "index.md"
        index.write_text(
            "# 索引\n\n## Concepts\n- [智能体工作流](concepts/agentic-workflow.md) - 协调 agent、工具和验证的知识页面。\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_generic_layers_do_not_embed_project_specific_examples(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        scan_targets = [
            repo / "src" / "knowledge_kit",
            repo / "tests" / "test_knowledge_kit.py",
            repo / "contracts",
            repo / "commands",
            repo / ".trae" / "agents",
            repo / "README.md",
            repo / "tools" / "sync_ck_data_dictionary" / "config.example.json",
        ]
        forbidden_terms = [
            "p" + "m_udsp",
            "u" + "DSP",
            "D" + "DP",
            "A" + "DP",
            "D" + "Portal",
            "S" + "DI",
            "站" + "内",
            "Station" + "Message",
            "APPROVAL" + "_TODO",
            "TASK" + "_RESULT",
            "ACCOUNT" + "_CREDENTIAL",
            "COLLAB" + "_AUTHORIZATION",
        ]
        files: list[Path] = []
        for target in scan_targets:
            if target.is_dir():
                files.extend(path for path in target.rglob("*") if path.is_file() and path.suffix in {".json", ".py", ".md", ".toml"})
            elif target.exists():
                files.append(target)

        violations: list[str] = []
        for path in files:
            content = path.read_text(encoding="utf-8", errors="ignore")
            for term in forbidden_terms:
                if term in content:
                    violations.append(f"{path.relative_to(repo).as_posix()}: {term}")

        self.assertEqual([], violations)

    def _write_config(self) -> None:
        data = {
            "schema_version": "1.0",
            "knowledge_roots": [
                {
                    "id": "alpha",
                    "name": "甲知识库",
                    "path": str(self.knowledge),
                    "enabled": True,
                    "mode": "read_write",
                    "priority": 10,
                },
                {
                    "id": "disabled",
                    "name": "停用知识库",
                    "path": str(self.disabled),
                    "enabled": False,
                    "mode": "read_write",
                    "priority": 20,
                },
                {
                    "id": "readonly",
                    "name": "只读知识库",
                    "path": str(self.read_only),
                    "enabled": True,
                    "mode": "read_only",
                    "priority": 5,
                },
            ],
            "query": {"candidate_limit": 8, "evidence_budget": 8},
            "output": {"runs_dir": "output/knowledge-runs", "state_dir": "state"},
        }
        (self.project / "knowledge_kit.config.json").write_text(json.dumps(data), encoding="utf-8")

    def _create_base_structure(self, root: Path) -> None:
        for relative in [
            "raw",
            "wiki/concepts",
            "wiki/entities",
            "wiki/sources",
            "wiki/queries",
            "relations",
            "state",
        ]:
            (root / relative).mkdir(parents=True, exist_ok=True)
        (root / "wiki" / "schema.md").write_text("# Schema\n\n", encoding="utf-8")
        (root / "wiki" / "index.md").write_text("# 索引\n\n", encoding="utf-8")
        (root / "wiki" / "log.md").write_text("# 日志\n\n", encoding="utf-8")
        (root / "wiki" / "overview.md").write_text("# 总览\n\n", encoding="utf-8")

    def test_query_read_plan_fans_out_to_enabled_roots_only(self) -> None:
        config = load_config(self.project)
        result = run_query(config, "智能体工作流")
        ids = [item["knowledge_id"] for item in result["per_knowledge_read_plans"]]
        self.assertEqual(result["kind"], QUERY_READ_PLAN_KIND)
        self.assertIn("alpha", ids)
        self.assertIn("readonly", ids)
        self.assertNotIn("disabled", ids)
        self.assertNotIn("answer", result)
        alpha = next(item for item in result["per_knowledge_read_plans"] if item["knowledge_id"] == "alpha")
        self.assertEqual(alpha["query_mechanism"], "karpathy_query_index_first_read_plan")
        self.assertIn("wiki/index.md", alpha["consulted_pages"])
        self.assertEqual(alpha["index_hits"][0]["path"], "concepts/agentic-workflow.md")

    def test_load_config_uses_environment_config_from_unrelated_cwd(self) -> None:
        config_path = self.project / "knowledge_kit.config.json"
        unrelated = self.root / "unrelated"
        unrelated.mkdir()
        with mock.patch.dict(os.environ, {"KNOWLEDGE_KIT_CONFIG": str(config_path)}):
            config = load_config(unrelated)
        self.assertEqual(config.root, self.project.resolve())
        self.assertEqual(config.get("alpha").path, self.knowledge.resolve())

    def test_cli_accepts_config_before_or_after_subcommand(self) -> None:
        config_path = self.project / "knowledge_kit.config.json"
        for argv in [
            ["--config", str(config_path), "validate"],
            ["validate", "--config", str(config_path)],
        ]:
            stdout = BufferedStdout()
            with mock.patch("sys.stdout", stdout):
                exit_code = main(argv)
            payload = json.loads(stdout.buffer.getvalue().decode("utf-8"))
            self.assertEqual(exit_code, 0)
            self.assertTrue(payload["passed"])

    def test_query_uses_index_not_full_text_scan(self) -> None:
        hidden = self.knowledge / "wiki" / "concepts" / "hidden.md"
        hidden.write_text(
            wiki_page("隐藏页面", "concept", "这个页面包含唯一词：火星跳跃协议。", sources=[]),
            encoding="utf-8",
        )
        config = load_config(self.project)
        result = run_query(config, "火星跳跃协议", knowledge_id="alpha")
        plan = result["per_knowledge_read_plans"][0]
        self.assertEqual(plan["index_hits"], [])
        self.assertEqual(plan["candidate_page_paths"], [])

    def test_query_adds_wikilinks_from_hit_pages_to_related_candidates(self) -> None:
        config = load_config(self.project)
        result = run_query(config, "智能体工作流", knowledge_id="alpha")
        plan = result["per_knowledge_read_plans"][0]
        self.assertIn("wiki/entities/codex-agent.md", plan["candidate_page_paths"])
        self.assertIn(
            {"from": "wiki/concepts/agentic-workflow.md", "target": "entities/codex-agent.md", "resolved_path": "wiki/entities/codex-agent.md", "status": "resolved"},
            plan["related_wikilinks"],
        )

    def test_query_bundle_reads_only_planned_wiki_evidence(self) -> None:
        raw = self.knowledge / "raw" / "hidden.md"
        raw.write_text("火星跳跃协议只存在于 raw。", encoding="utf-8")
        config = load_config(self.project)
        result = run_query_bundle(config, "智能体工作流", knowledge_id="alpha")
        self.assertEqual(result["kind"], QUERY_EVIDENCE_BUNDLE_KIND)
        self.assertFalse(result["read_plan_only"])
        self.assertEqual(result["policy"]["forbidden_roots"], ["raw", "relations", "state"])
        self.assertTrue(result["evidence_pages"])
        self.assertTrue(all(page["path"].startswith("wiki/") for page in result["evidence_pages"]))
        self.assertTrue(all(page["source"] == "wiki" for page in result["evidence_pages"]))
        contents = "\n".join(page["content"] for page in result["evidence_pages"])
        self.assertIn("智能体工作流协调", contents)
        self.assertNotIn("火星跳跃协议只存在于 raw", contents)
        self.assertEqual(result["code_exploration"], {"enabled": False})

    def test_query_bundle_uses_index_not_wiki_or_raw_full_text_scan(self) -> None:
        hidden = self.knowledge / "wiki" / "concepts" / "hidden.md"
        hidden.write_text(
            wiki_page("隐藏页面", "concept", "这个页面包含唯一词：火星跳跃协议。", sources=[]),
            encoding="utf-8",
        )
        raw = self.knowledge / "raw" / "hidden.md"
        raw.write_text("火星跳跃协议也存在于 raw。", encoding="utf-8")
        config = load_config(self.project)
        result = run_query_bundle(config, "火星跳跃协议", knowledge_id="alpha")
        self.assertEqual(result["evidence_pages"], [])
        self.assertTrue(any(gap["code"] == "no_evidence_pages" for gap in result["gaps"]))

    def test_query_bundle_fans_out_to_enabled_roots_only(self) -> None:
        config = load_config(self.project)
        result = run_query_bundle(config, "智能体工作流")
        ids = [item["id"] for item in result["selected_knowledge_roots"]]
        self.assertIn("alpha", ids)
        self.assertIn("readonly", ids)
        self.assertNotIn("disabled", ids)

    def test_query_bundle_declares_answer_requirements(self) -> None:
        config = load_config(self.project)
        result = run_query_bundle(config, "智能体工作流", knowledge_id="alpha")
        requirements = result["answer_requirements"]
        self.assertEqual(requirements["must_use_only"], "evidence_pages")
        self.assertIn("答案", requirements["required_sections"])
        self.assertIn("引用", requirements["required_sections"])
        self.assertIn("置信度", requirements["required_sections"])
        self.assertIn("冲突", requirements["required_sections"])
        self.assertIn("缺口", requirements["required_sections"])
        self.assertEqual(requirements["citation_format"], "<knowledge_id>:<wiki_path>")
        self.assertIn("index_hits", requirements["forbidden_citation_sources"])
        self.assertIn("candidate_pages", requirements["forbidden_citation_sources"])
        self.assertIn("omitted_candidates", requirements["forbidden_citation_sources"])
        self.assertEqual(requirements["active_profiles"], [])
        self.assertNotIn("code_exploration_policy", requirements)
        self.assertEqual([block["section"] for block in requirements["required_answer_blocks"]], ["答案", "引用", "置信度", "冲突", "缺口"])

        coding_result = run_query_bundle(config, "智能体工作流如何实现并验证", knowledge_id="alpha")
        coding_requirements = coding_result["answer_requirements"]
        self.assertIn("agentic_coding", coding_requirements["active_profiles"])
        coding_sections = coding_requirements["profile_requirements"]["agentic_coding"]["required_sections"]
        self.assertIn("代码定位", coding_sections)
        self.assertIn("复用边界", coding_sections)
        self.assertIn("测试/验证路径", coding_sections)
        coding_blocks = {block["section"]: block for block in coding_requirements["required_answer_blocks"]}
        self.assertEqual(coding_blocks["代码定位"]["source"], "agentic_coding")
        self.assertIn("不得用推测补齐", coding_blocks["代码定位"]["missing_policy"])
        self.assertTrue(any(gap["code"] == "profile_required_section_missing" for gap in coding_result["gaps"]))
        self.assertEqual(coding_result["quality"]["confidence"], "low")

        prd_result = run_query_bundle(config, "智能体工作流 PRD 如何设计", knowledge_id="alpha")
        prd_requirements = prd_result["answer_requirements"]
        self.assertIn("prd_design_from_code", prd_requirements["active_profiles"])
        prd_sections = prd_requirements["profile_requirements"]["prd_design_from_code"]["required_sections"]
        self.assertIn("已有能力", prd_sections)
        self.assertIn("设计受限边界", prd_sections)
        prd_blocks = {block["section"]: block for block in prd_requirements["required_answer_blocks"]}
        self.assertEqual(prd_blocks["已有能力"]["source"], "prd_design_from_code")
        self.assertEqual(prd_requirements["missing_policy"], "mark_unknown_or_gap_do_not_infer_beyond_evidence_pages")

        generic_design_result = run_query_bundle(config, "智能体工作流设计原则", knowledge_id="alpha")
        self.assertNotIn("prd_design_from_code", generic_design_result["answer_requirements"]["active_profiles"])

    def test_query_bundle_checks_code_profile_evidence_sections(self) -> None:
        product_page = self.knowledge / "wiki" / "entities" / "product" / "features" / "agentic-workflow.md"
        product_page.parent.mkdir(parents=True, exist_ok=True)
        product_page.write_text(
            wiki_page(
                "智能体工作流产品说明",
                "entity",
                "## 现有实现\n产品材料描述当前能力。\n\n"
                "## 代码定位\n产品材料提到了代码定位但不是正式代码知识页。\n\n"
                "## 复用边界\n产品材料描述复用边界。\n\n"
                "## 改动点\n产品材料描述改动点。\n\n"
                "## 暂不应改动\n产品材料描述限制。\n\n"
                "## 数据/权限/运行约束\n产品材料描述约束。\n\n"
                "## 测试/验证路径\n产品材料描述测试。\n\n"
                "## PRD 设计影响\n产品材料描述设计影响。\n\n"
                "## 缺口与继续探索\n产品材料描述缺口。\n",
                sources=[],
            ),
            encoding="utf-8",
        )
        (self.knowledge / "wiki" / "index.md").write_text(
            "# 索引\n\n"
            "## Product\n"
            "- [智能体工作流产品说明](entities/product/features/agentic-workflow.md) - 智能体工作流的产品说明，包含代码定位、复用边界、改动点、约束和验证路径。\n",
            encoding="utf-8",
        )
        config = load_config(self.project)

        product_only = run_query_bundle(config, "智能体工作流如何实现并验证", knowledge_id="alpha")
        product_gap_codes = {gap["code"] for gap in product_only["gaps"]}
        self.assertIn("profile_code_feature_evidence_missing", product_gap_codes)
        self.assertEqual(product_only["quality"]["confidence"], "low")

        code_page = self.knowledge / "wiki" / "entities" / "code" / "features" / "agentic-workflow.md"
        code_page.parent.mkdir(parents=True, exist_ok=True)
        code_page.write_text(
            wiki_page(
                "智能体工作流代码空壳页",
                "entity",
                "## 现有实现\n当前实现。\n\n"
                "## 代码定位\n待补充。\n\n"
                "## 复用边界\n待补充。\n\n"
                "## 改动点\n待补充。\n\n"
                "## 暂不应改动\n待补充。\n\n"
                "## 数据/权限/运行约束\n待补充。\n\n"
                "## 测试/验证路径\n待补充。\n\n"
                "## PRD 设计影响\n待补充。\n\n"
                "## 缺口与继续探索\n待补充。\n",
                sources=[],
            ),
            encoding="utf-8",
        )
        (self.knowledge / "wiki" / "index.md").write_text(
            "# 索引\n\n"
            "## Code\n"
            "- [智能体工作流代码空壳页](entities/code/features/agentic-workflow.md) - 智能体工作流的代码实现、复用边界、改动点、约束、验证路径和 PRD 设计支撑。\n",
            encoding="utf-8",
        )

        thin_code = run_query_bundle(config, "智能体工作流如何实现并验证", knowledge_id="alpha")
        thin_gap_sections = {gap.get("section") for gap in thin_code["gaps"] if gap["code"] == "profile_required_section_missing"}
        self.assertIn("代码定位", thin_gap_sections)
        self.assertEqual(thin_code["quality"]["confidence"], "low")

        companion_page = self.knowledge / "wiki" / "entities" / "code" / "features" / "agentic-workflow-verification.md"
        code_page.write_text(
            wiki_page(
                "智能体工作流代码入口",
                "entity",
                "## 现有实现\n当前实现通过工作流协调 agent、工具和验证。\n\n"
                "## 代码定位\n相关代码位于 `src/workflow.py`。\n\n"
                "## 复用边界\n复用点是既有调度接口。\n\n"
                "## 改动点\n新增能力时修改 planner、executor 和 verifier 的协作点。\n\n"
                "## 数据/权限/运行约束\n数据约束、权限约束和运行约束都需要保留。\n",
                sources=[],
            ),
            encoding="utf-8",
        )
        companion_page.write_text(
            wiki_page(
                "智能体工作流验证说明",
                "entity",
                "## 测试/验证路径\n验证入口是 `python -m unittest`。\n\n"
                "## 缺口与继续探索\n缺口是生产部署脚本仍需继续探索。\n",
                sources=[],
            ),
            encoding="utf-8",
        )
        split_gaps = [
            gap
            for gap in profile_evidence_gaps(
                {
                    "active_profiles": ["agentic_coding"],
                    "profile_requirements": {"agentic_coding": QUERY_AGENTIC_CODING_REQUIREMENTS},
                },
                [
                    {
                        "path": "wiki/entities/code/features/agentic-workflow.md",
                        "content": code_page.read_text(encoding="utf-8"),
                    },
                    {
                        "path": "wiki/entities/code/features/agentic-workflow-verification.md",
                        "content": companion_page.read_text(encoding="utf-8"),
                    },
                ],
            )
            if gap["code"] == "profile_required_section_missing"
            and gap.get("reason") == "code_feature_page_section_missing_or_not_actionable"
        ]
        self.assertTrue(any(gap.get("path") == "wiki/entities/code/features/agentic-workflow.md" and gap.get("section") == "测试/验证路径" for gap in split_gaps))
        self.assertTrue(any(gap.get("path") == "wiki/entities/code/features/agentic-workflow-verification.md" and gap.get("section") == "代码定位" for gap in split_gaps))

        code_page.write_text(
            wiki_page(
                "智能体工作流代码实现与 PRD 设计支撑",
                "entity",
                "## 现有实现\n当前实现通过工作流协调 agent、工具和验证。\n\n"
                "## 代码定位\n相关代码位于 `src/workflow.py` 和 `tests/test_workflow.py`。\n\n"
                "## 复用边界\n复用点是既有调度接口；不要复用未验证的外部状态。\n\n"
                "## 改动点\n新增能力时修改 planner、executor 和 verifier 的协作点。\n\n"
                "## 暂不应改动\n不要绕过既有 verifier 和调度边界。\n\n"
                "## 数据/权限/运行约束\n数据约束、权限约束和运行约束都需要保留。\n\n"
                "## 测试/验证路径\n验证入口是 `python -m unittest`。\n\n"
                "## PRD 设计影响\nPRD 可以继承 agent 分工和 verifier loop；实现影响集中在 workflow 层。\n\n"
                "## 缺口与继续探索\n缺口是生产部署脚本仍需继续探索；需要新增或澄清用户确认策略。\n",
                sources=["wiki/sources/code/kcode-runs/run-001/H001-agentic-workflow.md"],
            ),
            encoding="utf-8",
        )
        source_summary = self.knowledge / "wiki" / "sources" / "code" / "kcode-runs" / "run-001" / "H001-agentic-workflow.md"
        source_summary.parent.mkdir(parents=True, exist_ok=True)
        source_summary.write_text(
            wiki_page(
                "智能体工作流 KCode 来源摘要",
                "source",
                "本来源摘要追溯 handoff shard、analysis、evidence 和 verified findings，供 feature 页 frontmatter sources 引用。",
            ),
            encoding="utf-8",
        )
        (self.knowledge / "wiki" / "index.md").write_text(
            "# 索引\n\n"
            "## Code\n"
            "- [智能体工作流代码实现与 PRD 设计支撑](entities/code/features/agentic-workflow.md) - 智能体工作流的代码实现、复用边界、改动点、约束、验证路径和 PRD 设计支撑。\n",
            encoding="utf-8",
        )
        config = load_config(self.project)

        coding = run_query_bundle(config, "智能体工作流如何实现并验证", knowledge_id="alpha")
        coding_gaps = [gap for gap in coding["gaps"] if gap["code"] == "profile_required_section_missing"]
        self.assertEqual(coding_gaps, [])
        self.assertNotIn("profile_code_feature_evidence_missing", {gap["code"] for gap in coding["gaps"]})
        self.assertEqual(coding["quality"]["confidence"], "high")

        prd = run_query_bundle(config, "智能体工作流 PRD 如何设计", knowledge_id="alpha")
        prd_gaps = [gap for gap in prd["gaps"] if gap["code"] == "profile_required_section_missing"]
        self.assertEqual(prd_gaps, [])
        self.assertEqual(prd["quality"]["confidence"], "high")

    def test_query_bundle_requires_code_feature_source_trace(self) -> None:
        code_page = self.knowledge / "wiki" / "entities" / "code" / "features" / "agentic-workflow.md"
        code_page.parent.mkdir(parents=True, exist_ok=True)
        complete_body = (
            "## 现有实现\n当前实现通过工作流协调 agent、工具和验证。\n\n"
            "## 代码定位\n相关代码位于 `src/workflow.py` 和 `tests/test_workflow.py`。\n\n"
            "## 复用边界\n复用点是既有调度接口；不要复用未验证的外部状态。\n\n"
            "## 改动点\n新增能力时修改 planner、executor 和 verifier 的协作点。\n\n"
            "## 暂不应改动\n不要绕过既有 verifier 和调度边界。\n\n"
            "## 数据/权限/运行约束\n数据约束、权限约束和运行约束都需要保留。\n\n"
            "## 测试/验证路径\n验证入口是 `python -m unittest`。\n\n"
            "## PRD 设计影响\nPRD 可以继承 agent 分工和 verifier loop；实现影响集中在 workflow 层。\n\n"
            "## 缺口与继续探索\n缺口是生产部署脚本仍需继续探索；需要新增或澄清用户确认策略。\n"
        )
        code_page.write_text(wiki_page("智能体工作流代码实现", "entity", complete_body, sources=[]), encoding="utf-8")
        (self.knowledge / "wiki" / "index.md").write_text(
            "# 索引\n\n"
            "- [智能体工作流代码实现](entities/code/features/agentic-workflow.md) - 智能体工作流入口在 `src/workflow.py`，包含复用边界、改动点、约束和验证路径。\n",
            encoding="utf-8",
        )
        config = load_config(self.project)

        missing_source = run_query_bundle(config, "智能体工作流如何实现并验证", knowledge_id="alpha")
        missing_codes = {gap["code"] for gap in missing_source["gaps"]}
        self.assertIn("profile_code_feature_source_trace_missing", missing_codes)
        self.assertEqual(missing_source["quality"]["confidence"], "low")

        code_page.write_text(
            wiki_page(
                "智能体工作流代码实现",
                "entity",
                complete_body,
                sources=["wiki/sources/code/kcode-runs/run-001/H001-agentic-workflow.md"],
            ),
            encoding="utf-8",
        )

        broken_trace = run_query_bundle(config, "智能体工作流如何实现并验证", knowledge_id="alpha")
        broken_codes = {gap["code"] for gap in broken_trace["gaps"]}
        self.assertIn("profile_code_feature_source_summary_missing", broken_codes)
        self.assertEqual(broken_trace["quality"]["confidence"], "low")

        source_summary = self.knowledge / "wiki" / "sources" / "code" / "kcode-runs" / "run-001" / "H001-agentic-workflow.md"
        source_summary.parent.mkdir(parents=True, exist_ok=True)
        source_summary.write_text(
            wiki_page(
                "智能体工作流 KCode 来源摘要",
                "source",
                "本来源摘要追溯 handoff/shards/H001-agentic-workflow.md、analysis.md、evidence.json 和 verified-findings.jsonl。",
            ),
            encoding="utf-8",
        )

        traced = run_query_bundle(config, "智能体工作流如何实现并验证", knowledge_id="alpha")
        self.assertNotIn("profile_code_feature_source_trace_missing", {gap["code"] for gap in traced["gaps"]})
        self.assertNotIn("profile_code_feature_source_summary_missing", {gap["code"] for gap in traced["gaps"]})
        self.assertEqual(traced["quality"]["confidence"], "high")

    def test_query_bundle_citations_only_reference_evidence_pages(self) -> None:
        config = load_config(self.project)
        result = run_query_bundle(config, "智能体工作流", knowledge_id="alpha")
        evidence_citations = {f"{page['knowledge_id']}:{page['path']}" for page in result["evidence_pages"]}
        self.assertEqual(set(result["citations"]), evidence_citations)

    def test_query_ranking_prefers_feature_page_over_generic_module_hit(self) -> None:
        supported = self.knowledge / "wiki" / "concepts" / "supported-databases.md"
        supported.parent.mkdir(parents=True, exist_ok=True)
        supported.write_text(wiki_page("supported-databases", "concept", "CATALOGX 与 MODA 当前支持的数据库类型清单。"), encoding="utf-8")
        risk = self.knowledge / "wiki" / "entities" / "product" / "features" / "MODA" / "示例风险能力.md"
        risk.parent.mkdir(parents=True, exist_ok=True)
        risk.write_text(wiki_page("示例风险能力", "entity", "MODA 示例风险能力识别访问异常、过度暴露和权限滥用风险。"), encoding="utf-8")
        (self.knowledge / "wiki" / "index.md").write_text(
            "# 索引\n\n"
            "## Concepts\n"
            "- [supported-databases](concepts/supported-databases.md) - 本页汇总 CATALOGX 与 MODA 当前支持的数据库类型清单。\n"
            "## Features\n"
            "- [示例风险能力](entities/product/features/MODA/示例风险能力.md) - 示例风险能力是 MODA 面向访问审计场景的风险识别能力。\n",
            encoding="utf-8",
        )
        config = load_config(self.project)
        result = run_query(config, "MODA示例风险能力有哪些能力", knowledge_id="alpha")
        plan = result["per_knowledge_read_plans"][0]
        self.assertEqual(plan["candidate_page_paths"][0], "wiki/entities/product/features/MODA/示例风险能力.md")

    def test_query_module_filter_allows_secondary_module_token(self) -> None:
        module_b_feature = self.knowledge / "wiki" / "entities" / "code" / "features" / "module-b" / "result-chain.md"
        module_b_feature.parent.mkdir(parents=True, exist_ok=True)
        module_b_feature.write_text(
            wiki_page(
                "MODB 结果实现链",
                "entity",
                "MODB 结果由 `SampleResultController.java` 和 `SampleResultService.java` 实现。",
            ),
            encoding="utf-8",
        )
        portal_feature = self.knowledge / "wiki" / "entities" / "code" / "features" / "portal-x" / "inventory.md"
        portal_feature.parent.mkdir(parents=True, exist_ok=True)
        portal_feature.write_text(
            wiki_page(
                "PORTALX 清单实现链",
                "entity",
                "PORTALX 清单由 `SampleInventoryController.java` 实现。",
            ),
            encoding="utf-8",
        )
        (self.knowledge / "wiki" / "index.md").write_text(
            "# 索引\n\n"
            "- [MODB 结果实现链](entities/code/features/module-b/result-chain.md) - MODB 结果由 `SampleResultController.java` 和 `SampleResultService.java` 支撑。\n"
            "- [PORTALX 清单实现链](entities/code/features/portal-x/inventory.md) - PORTALX 清单由 `SampleInventoryController.java` 支撑。\n",
            encoding="utf-8",
        )
        config = load_config(self.project)

        result = run_query(config, "MODB 结果如何实现", knowledge_id="alpha")
        plan = result["per_knowledge_read_plans"][0]
        module_b_candidate = next(item for item in plan["candidate_pages"] if item["path"] == "wiki/entities/code/features/module-b/result-chain.md")

        self.assertEqual(plan["selected_evidence_paths"][0], "wiki/entities/code/features/module-b/result-chain.md")
        self.assertEqual(module_b_candidate["module_fit"], "same_module")
        self.assertIn("MODB", module_b_candidate["modules"])

    def test_code_query_bundle_flags_topic_mismatch_and_keeps_code_map_fallback(self) -> None:
        source = self.knowledge / "wiki" / "sources" / "code" / "kcode-runs" / "run-001" / "management-console.md"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(wiki_page("管理台 handoff", "source", "管理台新增功能编码指引的 KCode 来源摘要。"), encoding="utf-8")
        management = self.knowledge / "wiki" / "entities" / "code" / "features" / "platform" / "management-console-coding-playbook.md"
        management.parent.mkdir(parents=True, exist_ok=True)
        management.write_text(
            wiki_page(
                "平台控制台新增功能编码指引",
                "entity",
                "## 现有实现\n平台控制台通过动态菜单、集中 HTTP 模块和后端 GenericController 暴露功能入口。\n\n"
                "## 代码定位\n入口在 `src/console/menu.ts`、`src/api/console.ts`、`ConsoleController` 和 `/console/menu/list`。\n\n"
                "## 实现链\n菜单配置进入前端路由，再调用 HTTP 模块，后端 controller 进入 service。\n\n"
                "## 复用边界\n复用动态菜单、HTTP client 和 GenericController，不复用未验证的跨模块状态。\n\n"
                "## 改动点\n新增管理台功能时修改菜单配置、前端 API 模块、controller/service 和验证入口。\n\n"
                "## 暂不应改动\n未继续探索前不要改权限模型、公共路由协议和跨模块 GenericController 行为。\n\n"
                "## 数据/权限/运行约束\n需要保留菜单权限、接口路径、DTO 字段和运行配置约束。\n\n"
                "## 测试/验证路径\n验证入口是 `tests/test_console.py` 和手工调用 `/console/menu/list`。\n\n"
                "## PRD 设计影响\nPRD 可以继承动态菜单和通用 controller 边界，新增字段需要澄清权限与数据合同。\n\n"
                "## 缺口与继续探索\n继续探索目标是具体业务 service、DTO 和权限配置。\n",
                sources=["wiki/sources/code/kcode-runs/run-001/management-console.md"],
            ),
            encoding="utf-8",
        )
        repo_map = self.knowledge / "wiki" / "entities" / "code" / "modules" / "repository-map.md"
        repo_map.parent.mkdir(parents=True, exist_ok=True)
        repo_map.write_text(
            wiki_page(
                "通用仓库导航图",
                "entity",
                "本页是 code_map 导航页，覆盖管理台、门户、策略和数据仓库入口以及继续探索路径。",
                sources=[],
            ),
            encoding="utf-8",
        )
        (self.knowledge / "wiki" / "index.md").write_text(
            "# 索引\n\n"
            "- [平台控制台新增功能编码指引](entities/code/features/platform/management-console-coding-playbook.md) - 平台控制台新增功能入口在 `src/console/menu.ts`、`ConsoleController` 和 `/console/menu/list`，说明复用边界、改动点、权限约束和验证路径。\n"
            "- [通用仓库导航图](entities/code/modules/repository-map.md) - code_map 导航页，覆盖管理台、门户、策略和数据仓库入口以及继续探索路径。\n",
            encoding="utf-8",
        )
        config = load_config(self.project)

        covered = run_query_bundle(config, "平台控制台新增功能如何实现", knowledge_id="alpha")
        self.assertNotIn("profile_query_topic_not_covered", {gap["code"] for gap in covered["gaps"]})
        self.assertEqual(covered["quality"]["confidence"], "high")

        uncovered = run_query_bundle(config, "外部审批链路如何实现和改造", knowledge_id="alpha")
        gap_codes = {gap["code"] for gap in uncovered["gaps"]}
        evidence_paths = [page["path"] for page in uncovered["evidence_pages"]]

        self.assertIn("profile_query_topic_not_covered", gap_codes)
        self.assertEqual(uncovered["quality"]["confidence"], "low")
        self.assertTrue(uncovered["semantic_review"]["enabled"])
        self.assertTrue(uncovered["semantic_review"]["required_before_final"])
        self.assertTrue(uncovered["semantic_review"]["not_evidence"])
        self.assertIn("profile_query_topic_not_covered", uncovered["semantic_review"]["reason_codes"])
        self.assertIn("rerun_query_bundle_with_refined_query", uncovered["semantic_review"]["allowed_actions"])
        self.assertEqual(uncovered["codex_next_step"]["status"], "requires_semantic_review")
        self.assertIn("contracts/k/query-workflow.md", uncovered["codex_next_step"]["contract_refs"])
        self.assertTrue(uncovered["codex_next_step"]["must_read_contract_refs_before_final"])
        self.assertIn("wiki/entities/code/modules/repository-map.md", evidence_paths)

        navigation = run_query_bundle(config, "收到一个不确定归属的新需求应该先探索哪个仓库", knowledge_id="alpha")
        navigation_paths = [page["path"] for page in navigation["evidence_pages"]]
        self.assertEqual(navigation_paths[0], "wiki/entities/code/modules/repository-map.md")
        self.assertNotIn("profile_query_topic_not_covered", {gap["code"] for gap in navigation["gaps"]})
        self.assertEqual(navigation["answer_requirements"]["active_profiles"], [])
        self.assertEqual(navigation["quality"]["confidence"], "high")

        state_dir = self.knowledge / "state" / "kcode"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "latest-snapshot.json").write_text(
            json.dumps(
                {
                    "schema_version": "kcode.snapshot.v1",
                    "repos": [
                        {
                            "repo_id": "repos/ddp/backend/sample-ddp",
                            "path": "repos/ddp/backend/sample-ddp",
                            "branch": "main",
                            "commit": "abc123",
                            "language_summary": {"java": 12},
                        },
                        {
                            "repo_id": "repos/mcc/frontend/sample-ui",
                            "path": "repos/mcc/frontend/sample-ui",
                            "branch": "main",
                            "commit": "def456",
                            "language_summary": {"vue": 8},
                        },
                        {
                            "repo_id": "repos/policy/backend/sample-policy",
                            "path": "repos/policy/backend/sample-policy",
                            "branch": "main",
                            "commit": "ghi789",
                            "language_summary": {"java": 10},
                        },
                        {
                            "repo_id": "repos/console/frontend/sample-console",
                            "path": "repos/console/frontend/sample-console",
                            "branch": "main",
                            "commit": "jkl012",
                            "language_summary": {"vue": 6},
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        data = json.loads((self.project / "knowledge_kit.config.json").read_text(encoding="utf-8"))
        code_workspace = self.root / "workspace_alpha"
        data["knowledge_roots"].append(
            {
                "id": "project_alpha",
                "name": "Project Alpha",
                "path": str(self.knowledge),
                "enabled": True,
                "mode": "read_write",
                "priority": 1,
            }
        )
        data["code"] = {
            "workspaces": {
                "project_alpha": {
                    "workspace_root": str(code_workspace),
                    "repos_dir": "repos",
                    "submodule_mode": True,
                }
            }
        }
        (self.project / "knowledge_kit.config.json").write_text(json.dumps(data), encoding="utf-8")
        code_config = load_config(self.project)

        covered_code_root = run_query_bundle(code_config, "平台控制台新增功能如何实现", knowledge_id="project_alpha")
        self.assertEqual(covered_code_root["status"], "requires_code_exploration")
        self.assertFalse(covered_code_root["continuation_policy"]["final_answer_allowed"])
        self.assertTrue(covered_code_root["continuation_policy"]["slash_command_must_continue"])
        self.assertEqual(covered_code_root["quality"]["confidence"], "high")
        self.assertTrue(covered_code_root["code_exploration"]["execution_policy"]["must_execute_before_final"])
        self.assertEqual(covered_code_root["codex_next_step"]["status"], "requires_code_exploration")
        self.assertEqual(covered_code_root["codex_next_step"]["required_output_block"], "代码验证结果")
        self.assertIn("contracts/k/query-code-exploration.md", covered_code_root["codex_next_step"]["contract_refs"])
        self.assertTrue(covered_code_root["codex_next_step"]["must_read_contract_refs_before_final"])
        self.assertIn("代码探索计划", [block["section"] for block in covered_code_root["answer_requirements"]["required_answer_blocks"]])
        self.assertIn("代码验证结果", [block["section"] for block in covered_code_root["answer_requirements"]["required_answer_blocks"]])
        self.assertEqual(covered_code_root["code_exploration"]["suggested_rg_cwd"], str(code_workspace.resolve()))

        product_code_index = self.knowledge / "wiki" / "entities" / "code" / "modules" / "product-code-index.md"
        product_code_index.write_text(
            wiki_page(
                "产品功能到代码仓库索引",
                "entity",
                "| 产品模块 | 产品能力/场景 | 对应 Repo | 经代码仓库验证的入口 |\n"
                "|---|---|---|---|\n"
                "| 示例策略 | 策略生效链路 | `sample-console`; `sample-policy` | `console/frontend/sample-console/src/views/Policy/index.vue`; `policy/backend/.../PolicyController.java` |\n"
                "| 示例门户 | 门户首页 | `sample-portal` | `portal/frontend/sample-portal/src/index.ts` |\n",
            ),
            encoding="utf-8",
        )
        (self.knowledge / "wiki" / "index.md").write_text(
            "# 索引\n\n"
            "- [平台控制台新增功能编码指引](entities/code/features/platform/management-console-coding-playbook.md) - 平台控制台新增功能入口在 `src/console/menu.ts`、`ConsoleController` 和 `/console/menu/list`，说明复用边界、改动点、权限约束和验证路径。\n"
            "- [通用仓库导航图](entities/code/modules/repository-map.md) - code_map 导航页，覆盖管理台、门户、策略和数据仓库入口以及继续探索路径。\n"
            "- [产品功能到代码仓库索引](entities/code/modules/product-code-index.md) - code_map 产品能力到 repo 和入口映射，覆盖示例策略生效链路、策略、控制台和策略后端入口。\n",
            encoding="utf-8",
        )
        code_map_match = run_query_bundle(code_config, "示例策略生效链路", knowledge_id="project_alpha")
        code_map_target_paths = {repo["path"] for repo in code_map_match["code_exploration"]["repo_targets"]}
        code_map_target_reasons = {repo["selection_reason"] for repo in code_map_match["code_exploration"]["repo_targets"]}
        self.assertEqual(code_map_match["code_exploration"]["repo_target_status"], "matched")
        self.assertIn("evidence_code_map_match", code_map_target_reasons)
        self.assertIn("repos/console/frontend/sample-console", code_map_target_paths)
        self.assertIn("repos/policy/backend/sample-policy", code_map_target_paths)
        code_map_anchor_values = {item["value"] for item in code_map_match["code_exploration"]["code_anchors"]}
        self.assertIn("PolicyController.java", code_map_anchor_values)
        self.assertTrue(any("repos/console/frontend/sample-console" in command for command in code_map_match["code_exploration"]["suggested_rg"]))

        default_content_query = run_query_bundle(code_config, "智能体工作流")
        self.assertEqual(default_content_query["status"], "ready_for_answer")
        self.assertEqual(default_content_query["completion_state"], "complete")
        self.assertTrue(default_content_query["continuation_policy"]["final_answer_allowed"])
        self.assertFalse(default_content_query["code_exploration"]["enabled"])
        self.assertNotIn("codex_next_step", default_content_query)
        self.assertNotIn("code_exploration_policy", default_content_query["answer_requirements"])
        self.assertNotIn("代码探索计划", [block["section"] for block in default_content_query["answer_requirements"]["required_answer_blocks"]])
        self.assertNotIn("代码验证结果", [block["section"] for block in default_content_query["answer_requirements"]["required_answer_blocks"]])

        prd_code_query = run_query_bundle(code_config, "基于现有代码补齐策略 PRD 设计")
        prd_contexts = {item["name"]: item for item in prd_code_query["code_exploration"]["result_contract"]["required_contexts"]}
        self.assertIn("prd_design_projection", prd_contexts)
        skeleton = prd_code_query["code_exploration"]["verification_result_skeleton"]
        self.assertEqual(skeleton["schema_version"], "query.code_verification_result_skeleton.v1")
        self.assertIn("wiki_evidence_assessment", skeleton)
        self.assertIn("agentic_coding_context", skeleton)
        self.assertIn("coding_execution_plan", skeleton)
        self.assertIn("prd_design_projection", skeleton)
        self.assertEqual(prd_code_query["codex_next_step"]["verification_result_skeleton"], skeleton)

    def test_focused_code_query_can_select_complementary_feature_pages(self) -> None:
        source_root = self.knowledge / "wiki" / "sources" / "code" / "kcode-runs" / "run-001"
        source_root.mkdir(parents=True, exist_ok=True)
        (source_root / "workbench.md").write_text(wiki_page("工作台 handoff", "source", "工作台新增功能的来源摘要。"), encoding="utf-8")
        (source_root / "report-asset.md").write_text(wiki_page("报表资产 handoff", "source", "报表资产管理的来源摘要。"), encoding="utf-8")
        (source_root / "generic-capability.md").write_text(wiki_page("通用能力 handoff", "source", "通用能力编码指引的来源摘要。"), encoding="utf-8")

        workbench = self.knowledge / "wiki" / "entities" / "code" / "features" / "platform" / "workbench.md"
        workbench.parent.mkdir(parents=True, exist_ok=True)
        workbench.write_text(
            wiki_page(
                "工作台新增功能编码指引",
                "entity",
                "## 现有实现\n工作台通过菜单入口、HTTP 模块和后端 controller 暴露扩展能力。\n\n"
                "## 代码定位\n入口在 `src/workbench/routes.ts`、`WorkbenchController` 和 `/workbench/menu/list`。\n\n"
                "## 实现链\n菜单进入路由，再调用 HTTP 模块，后端 controller 进入 service。\n\n"
                "## 复用边界\n复用菜单、HTTP client 和 controller/service 分层。\n\n"
                "## 改动点\n新增工作台功能时修改菜单、前端 API、controller、service 和验证入口。\n\n"
                "## 暂不应改动\n未继续探索前不要改公共权限模型。\n\n"
                "## 数据/权限/运行约束\n需要保留菜单权限、请求字段和运行配置。\n\n"
                "## 测试/验证路径\n运行 `tests/test_workbench.py` 或手工调用 `/workbench/menu/list`。\n\n"
                "## PRD 设计影响\nPRD 可以继承工作台扩展入口，但需要澄清具体业务对象。\n\n"
                "## 缺口与继续探索\n继续探索目标是具体业务 service 和 DTO。\n",
                sources=["wiki/sources/code/kcode-runs/run-001/workbench.md"],
            ),
            encoding="utf-8",
        )

        report_asset = self.knowledge / "wiki" / "entities" / "code" / "features" / "platform" / "report-asset.md"
        report_asset.write_text(
            wiki_page(
                "报表资产管理编码指引",
                "entity",
                "## 现有实现\n报表资产由列表页、资产 API、controller、service 和 repository 维护。\n\n"
                "## 代码定位\n入口在 `src/report/assets.ts`、`ReportAssetController` 和 `ReportAssetService`。\n\n"
                "## 实现链\n页面查询报表资产列表，API 进入 controller，再进入 service 和 repository。\n\n"
                "## 复用边界\n复用既有资产列表、标签和删除保护逻辑。\n\n"
                "## 改动点\n改报表资产时同步检查前端字段、DTO、service 校验和 repository 查询。\n\n"
                "## 暂不应改动\n不要绕过删除保护和权限过滤。\n\n"
                "## 数据/权限/运行约束\n需要保留资产字段、租户过滤、权限判断和审计要求。\n\n"
                "## 测试/验证路径\n运行 `tests/test_report_asset.py` 或手工调用 `/report/assets/list`。\n\n"
                "## PRD 设计影响\nPRD 应写清报表资产字段、筛选、权限和删除约束。\n\n"
                "## 缺口与继续探索\n继续探索目标是报表资产详情和导出链路。\n",
                sources=["wiki/sources/code/kcode-runs/run-001/report-asset.md"],
            ),
            encoding="utf-8",
        )
        generic = self.knowledge / "wiki" / "entities" / "code" / "features" / "platform" / "generic-capability.md"
        generic.write_text(
            wiki_page(
                "通用功能实现编码指引",
                "entity",
                "## 现有实现\n通用能力由公共页面、公共 API、controller 和 service 维护。\n\n"
                "## 代码定位\n入口在 `src/generic/capability.ts`、`GenericCapabilityController` 和 `GenericCapabilityService`。\n\n"
                "## 实现链\n页面调用公共 API，API 进入 controller，再进入 service。\n\n"
                "## 复用边界\n复用公共 API 和通用 service。\n\n"
                "## 改动点\n改通用能力时同步修改公共页面、controller、service 和测试。\n\n"
                "## 暂不应改动\n不要绕过公共权限模型。\n\n"
                "## 数据/权限/运行约束\n需要保留公共字段、权限和运行配置。\n\n"
                "## 测试/验证路径\n运行 `tests/test_generic_capability.py` 或手工调用 `/generic/capability/list`。\n\n"
                "## PRD 设计影响\nPRD 应写清公共能力边界。\n\n"
                "## 缺口与继续探索\n继续探索目标是具体业务对象。\n",
                sources=["wiki/sources/code/kcode-runs/run-001/generic-capability.md"],
            ),
            encoding="utf-8",
        )
        (self.knowledge / "wiki" / "index.md").write_text(
            "# 索引\n\n"
            "- [工作台新增功能编码指引](entities/code/features/platform/workbench.md) - 工作台新增功能入口在 `src/workbench/routes.ts`、`WorkbenchController` 和 `/workbench/menu/list`，说明复用边界、改动点和验证路径。\n"
            "- [报表资产管理编码指引](entities/code/features/platform/report-asset.md) - 报表资产管理入口在 `src/report/assets.ts`、`ReportAssetController` 和 `ReportAssetService`，说明资产字段、权限约束、改动点和验证路径。\n"
            "- [通用功能实现编码指引](entities/code/features/platform/generic-capability.md) - 通用功能如何实现和编码，说明公共 API、controller、service、复用边界、改动点和验证路径。\n",
            encoding="utf-8",
        )
        config = load_config(self.project)

        result = run_query_bundle(config, "工作台 报表资产 功能如何实现和编码", knowledge_id="alpha")
        evidence_paths = [page["path"] for page in result["evidence_pages"]]
        gap_codes = {gap["code"] for gap in result["gaps"]}

        self.assertIn("wiki/entities/code/features/platform/workbench.md", evidence_paths)
        self.assertIn("wiki/entities/code/features/platform/report-asset.md", evidence_paths)
        self.assertNotIn("wiki/entities/code/features/platform/generic-capability.md", evidence_paths)
        self.assertNotIn("profile_query_topic_not_covered", gap_codes)
        self.assertEqual(result["quality"]["confidence"], "high")

    def test_code_query_ranking_prefers_code_feature_page(self) -> None:
        product = self.knowledge / "wiki" / "entities" / "product" / "features" / "module-a" / "feature.md"
        product.parent.mkdir(parents=True, exist_ok=True)
        product.write_text(wiki_page("通用能力", "entity", "通用能力说明用户看到的产品能力和使用边界。"), encoding="utf-8")
        code = self.knowledge / "wiki" / "entities" / "code" / "features" / "module-a" / "feature.md"
        code.parent.mkdir(parents=True, exist_ok=True)
        code.write_text(
            wiki_page(
                "通用能力代码实现",
                "entity",
                "## 现有实现\n通用能力已有 controller、service 和 verifier 协作。\n\n"
                "## 代码定位\n入口在 `src/feature.py`，验证在 `tests/test_feature.py`。\n\n"
                "## 实现链\n页面调用 API，API 进入 controller，再进入 service。\n\n"
                "## 复用边界\n复用既有 service 和 verifier，不复用未验证的外部状态。\n\n"
                "## 改动点\n新增能力时修改 controller、service 和测试。\n\n"
                "## 暂不应改动\n不要绕过 verifier。\n\n"
                "## 数据/权限/运行约束\n保留既有字段、权限和运行配置。\n\n"
                "## 测试/验证路径\n执行 `python -m unittest`。\n\n"
                "## PRD 设计影响\nPRD 可以继承既有入口和验证边界。\n\n"
                "## 缺口与继续探索\n缺口是部署脚本需要继续探索。\n",
                sources=["wiki/sources/code/kcode-runs/run-001/feature.md"],
            ),
            encoding="utf-8",
        )
        source = self.knowledge / "wiki" / "sources" / "code" / "kcode-runs" / "run-001" / "feature.md"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(wiki_page("通用能力 handoff", "source", "通用能力的交接摘要。"), encoding="utf-8")
        management_source = self.knowledge / "wiki" / "sources" / "code" / "kcode-runs" / "run-001" / "management-console.md"
        management_source.write_text(wiki_page("管理台 handoff", "source", "管理台新增功能编码指引的 KCode 来源摘要。"), encoding="utf-8")
        management = self.knowledge / "wiki" / "entities" / "code" / "features" / "platform" / "management-console-coding-playbook.md"
        management.parent.mkdir(parents=True, exist_ok=True)
        management.write_text(
            wiki_page(
                "平台控制台新增功能编码指引",
                "entity",
                "## 现有实现\n平台控制台通过动态菜单、集中 HTTP 模块和后端 GenericController 暴露功能入口。\n\n"
                "## 代码定位\n入口在 `src/console/menu.ts`、`src/api/console.ts`、`ConsoleController` 和 `/console/menu/list`。\n\n"
                "## 实现链\n菜单配置进入前端路由，再调用 HTTP 模块，后端 controller 进入 service。\n\n"
                "## 复用边界\n复用动态菜单、HTTP client 和 GenericController，不复用未验证的跨模块状态。\n\n"
                "## 改动点\n新增管理台功能时修改菜单配置、前端 API 模块、controller/service 和验证入口。\n\n"
                "## 暂不应改动\n未继续探索前不要改权限模型、公共路由协议和跨模块 GenericController 行为。\n\n"
                "## 数据/权限/运行约束\n需要保留菜单权限、接口路径、DTO 字段和运行配置约束。\n\n"
                "## 测试/验证路径\n验证入口是 `tests/test_console.py` 和手工调用 `/console/menu/list`。\n\n"
                "## PRD 设计影响\nPRD 可以继承动态菜单和通用 controller 边界，新增字段需要澄清权限与数据合同。\n\n"
                "## 缺口与继续探索\n继续探索目标是具体业务 service、DTO 和权限配置。\n",
                sources=["wiki/sources/code/kcode-runs/run-001/management-console.md"],
            ),
            encoding="utf-8",
        )
        (self.knowledge / "wiki" / "index.md").write_text(
            "# 索引\n\n"
            "## Product\n"
            "- [通用能力](entities/product/features/module-a/feature.md) - 通用能力说明用户看到的产品能力和使用边界。\n"
            "## Code\n"
            "- [通用能力代码实现](entities/code/features/module-a/feature.md) - 通用能力入口在 `src/feature.py`，验证在 `tests/test_feature.py`，包含复用边界、改动点、约束和验证路径。\n"
            "- [平台控制台新增功能编码指引](entities/code/features/platform/management-console-coding-playbook.md) - 平台控制台新增功能入口在 `src/console/menu.ts`、`ConsoleController` 和 `/console/menu/list`，说明复用边界、改动点、权限约束和验证路径。\n"
            "- [通用能力 handoff](sources/code/kcode-runs/run-001/feature.md) - 通用能力的交接摘要。\n",
            encoding="utf-8",
        )
        config = load_config(self.project)

        generic = run_query(config, "通用能力有哪些", knowledge_id="alpha")
        generic_plan = generic["per_knowledge_read_plans"][0]
        self.assertEqual(generic_plan["candidate_page_paths"][0], "wiki/entities/product/features/module-a/feature.md")

        coding = run_query_bundle(config, "通用能力如何设计和实现", knowledge_id="alpha")
        coding_plan = coding["read_plan"]["per_knowledge_read_plans"][0]
        evidence_paths = [page["path"] for page in coding["evidence_pages"]]

        self.assertEqual(coding_plan["candidate_page_paths"][0], "wiki/entities/code/features/module-a/feature.md")
        self.assertEqual(evidence_paths[0], "wiki/entities/code/features/module-a/feature.md")
        self.assertNotIn("wiki/sources/code/kcode-runs/run-001/feature.md", evidence_paths)

        data = json.loads((self.project / "knowledge_kit.config.json").read_text(encoding="utf-8"))
        data["knowledge_roots"].append(
            {
                "id": "code_alpha",
                "name": "代码知识库",
                "path": str(self.knowledge),
                "enabled": True,
                "mode": "read_write",
                "priority": 1,
            }
        )
        (self.project / "knowledge_kit.config.json").write_text(json.dumps(data), encoding="utf-8")
        config = load_config(self.project)

        scoped = run_query_bundle(config, "通用能力新增功能", knowledge_id="code_alpha")
        scoped_plan = scoped["read_plan"]["per_knowledge_read_plans"][0]
        scoped_evidence_paths = [page["path"] for page in scoped["evidence_pages"]]

        self.assertTrue(scoped_plan["query_intent"]["wants_code_knowledge"])
        self.assertEqual(scoped_plan["candidate_page_paths"][0], "wiki/entities/code/features/module-a/feature.md")
        self.assertEqual(scoped_evidence_paths[0], "wiki/entities/code/features/module-a/feature.md")

        management_query = run_query_bundle(config, "平台控制台新增功能", knowledge_id="code_alpha")
        management_plan = management_query["read_plan"]["per_knowledge_read_plans"][0]
        management_evidence_paths = [page["path"] for page in management_query["evidence_pages"]]
        management_gap_codes = {gap["code"] for gap in management_query["gaps"]}

        self.assertEqual(management_plan["candidate_page_paths"][0], "wiki/entities/code/features/platform/management-console-coding-playbook.md")
        self.assertEqual(management_evidence_paths[0], "wiki/entities/code/features/platform/management-console-coding-playbook.md")
        self.assertNotIn("profile_no_evidence_pages", management_gap_codes)
        self.assertNotIn("profile_code_feature_evidence_missing", management_gap_codes)
        self.assertNotIn("profile_required_section_missing", management_gap_codes)
        self.assertEqual(management_query["quality"]["confidence"], "high")

    def test_runtime_boundary_query_prefers_runtime_boundary_feature(self) -> None:
        feature_dir = self.knowledge / "wiki" / "entities" / "code" / "features" / "module-a"
        feature_dir.mkdir(parents=True, exist_ok=True)
        module_dir = self.knowledge / "wiki" / "entities" / "code" / "modules"
        module_dir.mkdir(parents=True, exist_ok=True)
        base_sections = (
            "## 现有实现\n通用能力配置保存链路已存在。\n\n"
            "## 代码定位\n入口是 `src/feature.py`。\n\n"
            "## 实现链\n前端提交到后端保存服务。\n\n"
            "## 复用边界\n复用保存服务。\n\n"
            "## 改动点\n修改配置表单和保存接口。\n\n"
            "## 暂不应改动\n不要改未验证的执行器。\n\n"
            "## 数据/权限/运行约束\n保留配置字段和租户约束。\n\n"
            "## 测试/验证路径\n验证配置保存。\n\n"
            "## PRD 设计影响\n配置保存不等于运行时生效。\n\n"
            "## 缺口与继续探索\n继续探索运行时消费者。\n"
        )
        (feature_dir / "config-playbook.md").write_text(
            wiki_page("通用能力配置编码指引", "entity", base_sections),
            encoding="utf-8",
        )
        (feature_dir / "runtime-boundary.md").write_text(
            wiki_page(
                "通用能力运行时消费边界",
                "entity",
                base_sections.replace("配置保存链路已存在", "运行时消费边界说明 profileId 谁消费配置，是否真正生效，以及执行链缺口"),
            ),
            encoding="utf-8",
        )
        unrelated_feature_dir = self.knowledge / "wiki" / "entities" / "code" / "features" / "module-b"
        unrelated_feature_dir.mkdir(parents=True, exist_ok=True)
        (unrelated_feature_dir / "runtime-boundary.md").write_text(
            wiki_page(
                "另一个能力运行时消费边界",
                "entity",
                base_sections.replace("配置保存链路已存在", "另一个能力运行时谁消费配置、是否真正生效和执行链缺口"),
            ),
            encoding="utf-8",
        )
        (module_dir / "repository-map.md").write_text(
            wiki_page(
                "通用仓库导航图",
                "entity",
                "本页是 code_map 仓库导航页，覆盖通用能力所属仓库入口和继续探索路径。",
            ),
            encoding="utf-8",
        )
        (module_dir / "unrelated-runtime-module.md").write_text(
            wiki_page(
                "无关运行时模块线索",
                "entity",
                "本页是某个无关模块的运行时线索，不是仓库导航页，也不是当前通用能力的边界页。",
            ),
            encoding="utf-8",
        )
        (self.knowledge / "wiki" / "index.md").write_text(
            "# 索引\n\n"
            "- [通用能力配置编码指引](entities/code/features/module-a/config-playbook.md) - 通用能力配置保存、配置字段、配置页面和配置接口，适合查询通用能力配置如何实现。\n"
            "- [通用能力运行时消费边界](entities/code/features/module-a/runtime-boundary.md) - 通用能力 profileId 是否真正生效、运行时谁消费配置、执行链和消费边界，适合查询运行时生效和消费者缺口。\n"
            "- [另一个能力运行时消费边界](entities/code/features/module-b/runtime-boundary.md) - 另一个能力是否真正生效、运行时谁消费配置、执行链和消费边界。\n"
            "- [通用仓库导航图](entities/code/modules/repository-map.md) - code_map 仓库导航页，覆盖通用能力所属仓库入口和继续探索路径。\n"
            "- [无关运行时模块线索](entities/code/modules/unrelated-runtime-module.md) - 无关模块的运行时线索，不是仓库导航页，也不是当前通用能力的边界页。\n",
            encoding="utf-8",
        )
        config = load_config(self.project)

        result = run_query_bundle(config, "profileId 是否真正生效，运行时谁消费，代码如何实现", knowledge_id="alpha")
        evidence_paths = [page["path"] for page in result["evidence_pages"]]

        self.assertEqual(evidence_paths[0], "wiki/entities/code/features/module-a/runtime-boundary.md")
        self.assertIn("wiki/entities/code/modules/repository-map.md", evidence_paths)
        self.assertNotIn("wiki/entities/code/features/module-b/runtime-boundary.md", evidence_paths)
        self.assertNotIn("wiki/entities/code/modules/unrelated-runtime-module.md", evidence_paths)

    def test_exact_symbol_query_does_not_expand_to_unrelated_runtime_boundaries(self) -> None:
        source_root = self.knowledge / "wiki" / "sources" / "code" / "kcode-runs" / "run-001"
        source_root.mkdir(parents=True, exist_ok=True)
        (source_root / "action.md").write_text(wiki_page("动作 handoff", "source", "示例动作符号来源摘要。"), encoding="utf-8")
        (source_root / "boundary.md").write_text(wiki_page("边界 handoff", "source", "运行时边界来源摘要。"), encoding="utf-8")
        feature_dir = self.knowledge / "wiki" / "entities" / "code" / "features" / "module-a"
        feature_dir.mkdir(parents=True, exist_ok=True)
        sections = (
            "## 现有实现\n示例动作已有 `sampleAction` 保存入口，`execute=true` 当前未闭合。\n\n"
            "## 代码定位\n入口在 `src/sample_action_api.ts`、`SampleActionController` 和 `/sample/action`。\n\n"
            "## 实现链\n前端提交动作请求，后端 controller 保存示例动作。\n\n"
            "## 复用边界\n复用示例动作接口和 service。\n\n"
            "## 改动点\n需要补 controller 对保存并执行参数的处理。\n\n"
            "## 暂不应改动\n不要改无关运行时边界。\n\n"
            "## 数据/权限/运行约束\n保留示例字段和权限约束。\n\n"
            "## 测试/验证路径\n验证 `/sample/action` 保存和执行分支。\n\n"
            "## PRD 设计影响\nPRD 需要标记保存并执行当前未闭合。\n\n"
            "## 缺口与继续探索\n缺口是保存后立即执行语义未闭合。\n"
        )
        (feature_dir / "action-save.md").write_text(
            wiki_page("示例动作保存编码指引", "entity", sections, sources=["wiki/sources/code/kcode-runs/run-001/action.md"]),
            encoding="utf-8",
        )
        (feature_dir / "runtime-boundary.md").write_text(
            wiki_page(
                "无关能力运行时边界",
                "entity",
                sections.replace("`sampleAction` 保存入口，`execute=true` 当前未闭合", "另一个能力是否真正生效、运行时谁消费配置和执行端缺口"),
                sources=["wiki/sources/code/kcode-runs/run-001/boundary.md"],
            ),
            encoding="utf-8",
        )
        module_dir = self.knowledge / "wiki" / "entities" / "code" / "modules"
        module_dir.mkdir(parents=True, exist_ok=True)
        (module_dir / "repository-map.md").write_text(
            wiki_page("通用仓库导航图", "entity", "本页是 code_map 仓库导航页。"),
            encoding="utf-8",
        )
        (self.knowledge / "wiki" / "index.md").write_text(
            "# 索引\n\n"
            "- [示例动作保存编码指引](entities/code/features/module-a/action-save.md) - 示例动作保存入口在 `src/sample_action_api.ts`、`SampleActionController` 和 `/sample/action`，说明 `sampleAction?execute=true` 当前未闭合。\n"
            "- [无关能力运行时边界](entities/code/features/module-a/runtime-boundary.md) - 另一个能力是否真正生效、运行时谁消费配置、执行端和消费边界。\n"
            "- [通用仓库导航图](entities/code/modules/repository-map.md) - code_map 仓库导航页。\n",
            encoding="utf-8",
        )
        config = load_config(self.project)

        result = run_query_bundle(config, "sampleAction?execute=true 是否闭合", knowledge_id="alpha")
        evidence_paths = [page["path"] for page in result["evidence_pages"]]

        self.assertEqual(evidence_paths[0], "wiki/entities/code/features/module-a/action-save.md")
        self.assertNotIn("wiki/entities/code/features/module-a/runtime-boundary.md", evidence_paths)

    def test_short_module_aliases_do_not_match_inside_long_words(self) -> None:
        module_aliases = {"am": "AM"}
        embedded = detect_query_intent("example gamma capability", module_aliases)
        explicit = detect_query_intent("AM capability", module_aliases)

        self.assertNotIn("AM", embedded["modules"])
        self.assertIn("AM", explicit["modules"])

    def test_code_query_topic_terms_ignore_generic_current_repo_words(self) -> None:
        terms = code_query_topic_terms("sample_token 后端是否已在当前 repos 闭合")

        self.assertEqual(terms, ["sample_token"])

    def test_query_topic_terms_ignore_diagnostic_action_words(self) -> None:
        terms = query_topic_terms("示例流程保存后为什么没生效，要查哪些代码")

        self.assertIn("示例流程", terms)
        self.assertNotIn("保存后", terms)
        self.assertNotIn("没生效", terms)
        self.assertNotIn("要查", terms)

    def test_query_topic_terms_ignore_knowledge_query_wrapper_words(self) -> None:
        terms = query_topic_terms("从code知识库帮我梳理一下AlphaFlow策略生效的数据流")

        self.assertIn("alphaflow", terms)
        self.assertIn("策略", terms)
        self.assertIn("生效", terms)
        self.assertIn("数据流", terms)
        self.assertNotIn("code", terms)
        self.assertFalse(any("知识库" in term or "梳理" in term for term in terms))

    def test_query_topic_terms_keep_product_anchors_not_prd_boundary_words(self) -> None:
        terms = query_topic_terms("AlphaCore 配置 PRD 如何补齐实现边界")

        self.assertEqual(terms, ["alphacore"])

    def test_prd_code_query_terms_keep_business_terms_not_mechanical_ngrams(self) -> None:
        terms = query_topic_terms("基于现有代码补齐 AlphaFlow 策略生效数据流的 PRD 设计")

        self.assertIn("alphaflow", terms)
        self.assertIn("策略生效数据流", terms)
        self.assertIn("策略", terms)
        self.assertIn("生效", terms)
        self.assertIn("数据流", terms)
        self.assertNotIn("现有", terms)
        self.assertFalse(any(term in terms for term in ["略生效数", "生效数据", "效数据流"]))

    def test_query_topic_terms_keep_long_business_phrases_for_code_map_ranking(self) -> None:
        terms = query_topic_terms("用户想改数据源访问控制策略下发流程")

        self.assertIn("数据源访问控制", terms)
        self.assertIn("策略下发", terms)
        self.assertIn("策略", terms)
        self.assertNotEqual(terms, ["策略"])

    def test_code_map_ranking_uses_narrow_aliases_for_business_terms(self) -> None:
        focused = {"产品模块": "示例模块", "产品能力/场景": "数据服务访问管控", "对应 Repo": "repos/example/backend", "入口": "AccessController.java"}
        unrelated = {"产品模块": "示例模块", "产品能力/场景": "探针绑定", "对应 Repo": "repos/example/backend", "入口": "ProbeController.java"}
        module_only = {"产品模块": "示例模块", "产品能力/场景": "无关能力", "对应 Repo": "repos/example/backend", "入口": "OtherController.java"}

        focused_text = " ".join(focused.values()).lower()
        unrelated_text = " ".join(unrelated.values()).lower()
        module_only_text = " ".join(module_only.values()).lower()

        self.assertGreater(
            code_map_row_relevance(focused, focused_text, ["数据权限"], ["示例模块"]),
            code_map_row_relevance(unrelated, unrelated_text, ["数据权限"], ["示例模块"]),
        )
        self.assertEqual(code_map_row_relevance(module_only, module_only_text, ["数据权限"], ["示例模块"]), 0)

    def test_workspace_commands_are_scoped_to_each_code_workspace(self) -> None:
        commands = suggested_rg_commands_by_workspace(
            ["sample"],
            [{"kind": "path", "value": "SampleController.java", "evidence_page": "wiki/entities/code/features/sample.md"}],
            [
                {"knowledge_id": "alpha", "path": "repos/alpha/backend", "selection_reason": "evidence_code_path_match"},
                {"knowledge_id": "beta", "path": "repos/beta/backend", "selection_reason": "evidence_code_path_match"},
            ],
            [
                {"knowledge_id": "alpha", "command_cwd": "workspace-alpha"},
                {"knowledge_id": "beta", "command_cwd": "workspace-beta"},
            ],
        )

        self.assertIn("repos/alpha/backend", commands["alpha"][0])
        self.assertNotIn("repos/beta/backend", commands["alpha"][0])
        self.assertIn("repos/beta/backend", commands["beta"][0])
        self.assertNotIn("repos/alpha/backend", commands["beta"][0])

    def test_file_path_regex_matches_windows_and_posix_separators(self) -> None:
        pattern = regex_union(["repos/sample-ui/src/http/modules/sampleApi.js"], path_separators=True)

        self.assertRegex("repos/sample-ui/src/http/modules/sampleApi.js", pattern)
        self.assertRegex(r"repos/sample-ui\src\http\modules\sampleApi.js", pattern)

    def test_code_anchor_extraction_filters_internal_paths_and_generic_endpoints(self) -> None:
        anchors = extract_code_anchors_from_evidence(
            [
                {
                    "path": "wiki/entities/code/modules/map.md",
                    "content": (
                        "来源 wiki/sources/code/kcode-runs/run/H001.md，代码路径 "
                        "repos/sample/backend/pom.xml，目录路径 /sample/frontend/src/http/modules/，"
                        "泛路径 /api/ 和 /service 不应作为 endpoint。"
                        "真实接口 /sample/items/list 和 `SampleController` 应保留。"
                    ),
                }
            ]
        )
        endpoint_values = {item["value"] for item in anchors if item["kind"] == "endpoint"}

        self.assertIn("/sample/items/list", endpoint_values)
        self.assertNotIn("/sources/code/kcode-runs/run/H001.md", endpoint_values)
        self.assertNotIn("/sample/backend/pom.xml", endpoint_values)
        self.assertNotIn("/sample/frontend/src/http/modules", endpoint_values)
        self.assertNotIn("/api", endpoint_values)
        self.assertNotIn("/service", endpoint_values)

    def test_code_list_filter_wording_is_implementation_not_collection(self) -> None:
        code_intent = {"wants_code_knowledge": True}

        self.assertEqual(infer_operator("示例流程列表筛选", code_intent), LOCATE_IMPLEMENTATION)
        self.assertEqual(infer_operator("示例报表导出列表字段", code_intent), LOCATE_IMPLEMENTATION)
        self.assertEqual(infer_operator("示例模块有哪些功能", code_intent), LIST_COLLECTION)
        self.assertEqual(infer_operator("示例通知中心支持哪些事件类型", code_intent), LIST_ENTITY_ATTRIBUTE)
        self.assertEqual(infer_operator("示例通知中心接入了哪些类型的事件", code_intent), LIST_ENTITY_ATTRIBUTE)

    def test_datasource_query_does_not_request_source_page(self) -> None:
        code = self.knowledge / "wiki" / "entities" / "code" / "features" / "module-a" / "datasource-access.md"
        code.parent.mkdir(parents=True, exist_ok=True)
        code.write_text(
            wiki_page(
                "Datasource 接入代码实现",
                "entity",
                "## 现有实现\nDatasource 接入已有 controller、service 和 repository 协作。\n\n"
                "## 代码定位\n入口在 `src/datasource.py`，验证在 `tests/test_datasource.py`。\n\n"
                "## 实现链\n页面调用 API，API 进入 controller，再进入 service 和 repository。\n\n"
                "## 复用边界\n复用既有 service 和 repository，不复用未验证的外部状态。\n\n"
                "## 改动点\n新增 datasource 能力时修改 controller、service、repository 和测试。\n\n"
                "## 暂不应改动\n不要绕过既有权限校验和数据合同。\n\n"
                "## 数据/权限/运行约束\n保留既有字段、权限和运行配置。\n\n"
                "## 测试/验证路径\n执行 `python -m unittest`。\n\n"
                "## PRD 设计影响\nPRD 可以继承既有入口、权限和验证边界。\n\n"
                "## 缺口与继续探索\n缺口是部署脚本需要继续探索。\n",
                sources=["wiki/sources/code/kcode-runs/run-001/datasource-access.md"],
            ),
            encoding="utf-8",
        )
        source = self.knowledge / "wiki" / "sources" / "code" / "kcode-runs" / "run-001" / "datasource-access.md"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(wiki_page("Datasource 接入 handoff", "source", "Datasource 接入的交接摘要。"), encoding="utf-8")
        (self.knowledge / "wiki" / "index.md").write_text(
            "# 索引\n\n"
            "## Code\n"
            "- [Datasource 接入代码实现](entities/code/features/module-a/datasource-access.md) - Datasource 接入入口在 `src/datasource.py`，包含复用边界、改动点、约束和验证路径。\n"
            "- [Datasource 接入 handoff](sources/code/kcode-runs/run-001/datasource-access.md) - Datasource 接入的交接摘要。\n",
            encoding="utf-8",
        )
        data = json.loads((self.project / "knowledge_kit.config.json").read_text(encoding="utf-8"))
        data["knowledge_roots"].append(
            {
                "id": "code_alpha",
                "name": "代码知识库",
                "path": str(self.knowledge),
                "enabled": True,
                "mode": "read_write",
                "priority": 1,
            }
        )
        (self.project / "knowledge_kit.config.json").write_text(json.dumps(data), encoding="utf-8")
        config = load_config(self.project)

        result = run_query_bundle(config, "datasource 接入如何实现和改造", knowledge_id="code_alpha")
        plan = result["read_plan"]["per_knowledge_read_plans"][0]
        evidence_paths = [page["path"] for page in result["evidence_pages"]]
        gap_codes = {gap["code"] for gap in result["gaps"]}

        self.assertFalse(plan["query_intent"]["wants_source"])
        self.assertEqual(evidence_paths[0], "wiki/entities/code/features/module-a/datasource-access.md")
        self.assertNotIn("profile_code_feature_evidence_missing", gap_codes)

    def test_query_bundle_gates_single_module_evidence_without_hiding_candidates(self) -> None:
        self._create_module_a_risk_monitoring_corpus()
        config = load_config(self.project)
        result = run_query_bundle(config, "MODA 示例风险能力", knowledge_id="alpha", candidate_limit=20, evidence_budget=8)
        plan = result["read_plan"]["per_knowledge_read_plans"][0]
        evidence_paths = [page["path"] for page in result["evidence_pages"]]
        candidate_paths = plan["candidate_page_paths"]
        omitted_reasons = {item["path"]: item["reason"] for item in plan["omitted_candidates"]}

        self.assertIn("wiki/entities/product/features/MODA/示例风险能力.md", evidence_paths)
        self.assertIn("wiki/entities/product/modules/MODA/data-dictionary/sample_result_table.md", evidence_paths)
        self.assertIn("wiki/entities/product/features/MODB/相邻风险能力.md", candidate_paths)
        self.assertNotIn("wiki/entities/product/features/MODB/相邻风险能力.md", evidence_paths)
        self.assertEqual(omitted_reasons["wiki/entities/product/features/MODB/相邻风险能力.md"], "module_mismatch")
        self.assertIn("quality", result)
        self.assertIn("confidence", result["quality"])
        self.assertIn("conflicts", result["quality"])
        self.assertIn("gaps", result["quality"])

    def test_query_bundle_expands_markdown_links_from_primary_evidence(self) -> None:
        self._create_module_a_risk_monitoring_corpus()
        config = load_config(self.project)
        result = run_query_bundle(config, "MODA 示例风险能力", knowledge_id="alpha", candidate_limit=20, evidence_budget=8)
        plan = result["read_plan"]["per_knowledge_read_plans"][0]
        expansions = plan["relationship_expansion"]
        selected = {item["path"]: item for item in plan["selected_evidence"]}

        self.assertIn(
            {
                "from": "wiki/entities/product/features/MODA/示例风险能力.md",
                "target": "../../modules/MODA/data-dictionary/sample_result_table.md",
                "resolved_path": "wiki/entities/product/modules/MODA/data-dictionary/sample_result_table.md",
                "status": "resolved",
            },
            plan["related_wikilinks"],
        )
        self.assertTrue(any(item["link_type"] == "markdown" for item in expansions))
        self.assertEqual(selected["wiki/sources/product/platform/modules/MODA/features/示例风险能力-引擎能力说明.md"]["evidence_role"], "provenance")

    def test_query_bundle_promotes_source_pages_only_when_requested(self) -> None:
        self._create_module_a_risk_monitoring_corpus()
        config = load_config(self.project)
        normal = run_query_bundle(config, "MODA 示例风险能力", knowledge_id="alpha", candidate_limit=20, evidence_budget=8)
        requested = run_query_bundle(config, "MODA 示例风险能力 原文", knowledge_id="alpha", candidate_limit=20, evidence_budget=8)
        source_path = "wiki/sources/product/platform/modules/MODA/features/示例风险能力-引擎能力说明.md"
        normal_roles = {page["path"]: page["evidence_role"] for page in normal["evidence_pages"]}
        requested_roles = {page["path"]: page["evidence_role"] for page in requested["evidence_pages"]}

        self.assertEqual(normal_roles[source_path], "provenance")
        self.assertEqual(requested_roles[source_path], "primary")

    def test_query_bundle_collection_count_selects_owner_and_coverage(self) -> None:
        self._create_app_suite_collection_corpus()
        config = load_config(self.project)

        result = run_query_bundle(config, "APPSET有几个应用", knowledge_id="alpha", candidate_limit=20, evidence_budget=8)
        plan = result["read_plan"]["per_knowledge_read_plans"][0]
        evidence_paths = [page["path"] for page in result["evidence_pages"]]
        proof = result["coverage_proofs"][0]

        self.assertEqual(plan["semantic_plan"]["operator"], "COUNT_COLLECTION")
        self.assertEqual(evidence_paths[0], "wiki/entities/product/modules/APPSET.md")
        self.assertIn("wiki/entities/product/features/APPSET/示例变更审核.md", proof["member_paths"])
        self.assertIn("wiki/entities/product/features/APPSET/示例合规取用.md", proof["member_paths"])
        self.assertEqual(len(proof["member_paths"]), 3)
        self.assertTrue(proof["complete"])
        self.assertTrue(result["sufficiency"]["passed"])
        self.assertEqual(result["answer_requirements"]["must_use_only"], "evidence_pages_and_coverage_proof")
        self.assertEqual(result["quality"]["confidence"], "high")

    def test_query_bundle_collection_list_is_not_single_feature_search(self) -> None:
        self._create_module_a_risk_monitoring_corpus()
        config = load_config(self.project)

        result = run_query_bundle(config, "MODA有哪些风险能力", knowledge_id="alpha", candidate_limit=20, evidence_budget=8)
        plan = result["read_plan"]["per_knowledge_read_plans"][0]
        evidence_paths = [page["path"] for page in result["evidence_pages"]]
        proof = result["coverage_proofs"][0]

        self.assertEqual(plan["semantic_plan"]["operator"], "LIST_COLLECTION")
        self.assertEqual(evidence_paths[0], "wiki/entities/product/modules/MODA.md")
        self.assertIn("wiki/entities/product/features/MODA/示例风险能力.md", evidence_paths)
        self.assertIn("wiki/entities/product/features/MODA/示例风险能力.md", proof["member_paths"])
        self.assertTrue(result["sufficiency"]["passed"])
        self.assertNotIn("single_member_page_insufficient_for_count", {gap["code"] for gap in result["gaps"]})

    def test_query_bundle_entity_attribute_list_selects_feature_not_code_map(self) -> None:
        self._create_entity_attribute_code_corpus()
        config = load_config(self.project)

        result = run_query_bundle(config, "示例通知中心支持哪些事件类型", knowledge_id="code_alpha", candidate_limit=20, evidence_budget=8)
        plan = result["read_plan"]["per_knowledge_read_plans"][0]
        evidence_paths = [page["path"] for page in result["evidence_pages"]]
        evidence_reasons = {page["path"]: page["selection_reason"] for page in result["evidence_pages"]}
        gap_codes = {gap["code"] for gap in result["gaps"]}

        self.assertEqual(plan["semantic_plan"]["operator"], "LIST_ENTITY_ATTRIBUTE")
        self.assertEqual(evidence_paths[0], "wiki/entities/code/features/sample/notification-center-coding-playbook.md")
        self.assertEqual(
            evidence_reasons["wiki/entities/code/features/sample/notification-center-coding-playbook.md"],
            "entity_attribute_owner_page",
        )
        self.assertIn("wiki/entities/code/modules/sample-product-code-index.md", evidence_paths)
        self.assertNotIn("collection_owner_missing", gap_codes)
        self.assertNotIn("collection_members_missing", gap_codes)
        self.assertTrue(result["sufficiency"]["passed"])

    def test_query_bundle_collection_count_gaps_without_owner_page(self) -> None:
        feature = self.knowledge / "wiki" / "entities" / "product" / "features" / "APPSET" / "示例曝光评估.md"
        feature.parent.mkdir(parents=True, exist_ok=True)
        feature.write_text(wiki_page("示例曝光评估", "entity", "示例曝光评估是 APPSET 应用集合中的独立应用。"), encoding="utf-8")
        (self.knowledge / "wiki" / "index.md").write_text(
            "# 索引\n\n"
            "- [示例曝光评估](entities/product/features/APPSET/示例曝光评估.md) - 示例曝光评估是 APPSET 应用集合中的独立应用。\n",
            encoding="utf-8",
        )
        config = load_config(self.project)

        result = run_query_bundle(config, "APPSET有几个应用", knowledge_id="alpha", candidate_limit=20, evidence_budget=8)
        gap_codes = {gap["code"] for gap in result["gaps"]}

        self.assertIn("collection_owner_missing", gap_codes)
        self.assertIn("single_member_page_insufficient_for_count", gap_codes)
        self.assertEqual(result["quality"]["confidence"], "low")

    def _create_entity_attribute_code_corpus(self) -> None:
        data = json.loads((self.project / "knowledge_kit.config.json").read_text(encoding="utf-8"))
        data["knowledge_roots"].append(
            {
                "id": "code_alpha",
                "name": "代码知识库",
                "path": str(self.knowledge),
                "enabled": True,
                "mode": "read_write",
                "priority": 1,
            }
        )
        (self.project / "knowledge_kit.config.json").write_text(json.dumps(data), encoding="utf-8")
        feature = self.knowledge / "wiki" / "entities" / "code" / "features" / "sample" / "notification-center-coding-playbook.md"
        feature.parent.mkdir(parents=True, exist_ok=True)
        feature.write_text(
            wiki_page(
                "示例通知中心 Coding Playbook",
                "entity",
                "## 现有实现\n"
                "示例通知中心支持的事件类型包括 `TYPE_CREATED`、`TYPE_COMPLETED`、`TYPE_EXPIRED`、"
                "`TYPE_AUTH_CHANGED`。\n\n"
                "已接入的事件场景包括：\n"
                "1. 示例审批待办事件。\n"
                "2. 示例导出完成事件。\n"
                "3. 示例访问日志导出事件。\n"
                "4. 示例凭据过期提醒事件。\n"
                "5. 示例授权调整事件。\n\n"
                "## 代码定位\n入口在 `SampleNotificationController`、`SampleNotificationService` 和 `/sampleNotifications/events`。\n\n"
                "## 实现链\nproducer 提交事件，平台服务写消息表，consumer 查询 `/sampleNotifications/my/*`。\n\n"
                "## 复用边界\n新增 producer 复用平台消息合同。\n\n"
                "## 改动点\n修改事件类型从 `SampleNotificationConstants` 进入。\n\n"
                "## 暂不应改动\n不要绕过平台服务直接写表。\n\n"
                "## 数据/权限/运行约束\n保留租户、用户、入口和幂等约束。\n\n"
                "## 测试/验证路径\n验证事件提交、未读查询和点击已读。\n\n"
                "## PRD 设计影响\nPRD 需要区分技术事件类型和业务接入场景。\n\n"
                "## 缺口与继续探索\n`TYPE_FILE_AVAILABLE` producer 未补证。\n",
                sources=[],
            ),
            encoding="utf-8",
        )
        module = self.knowledge / "wiki" / "entities" / "code" / "modules" / "sample-product-code-index.md"
        module.parent.mkdir(parents=True, exist_ok=True)
        module.write_text(
            wiki_page(
                "示例产品能力到 Repo/入口索引",
                "entity",
                "平台横切 / 示例通知中心 的代码入口是 `SampleNotificationController`、"
                "`SampleNotificationService`，具体事件类型和接入场景继续读 [[../features/sample/notification-center-coding-playbook.md]]。",
            ),
            encoding="utf-8",
        )
        (self.knowledge / "wiki" / "index.md").write_text(
            "# 索引\n\n"
            "- [示例通知中心 Coding Playbook](entities/code/features/sample/notification-center-coding-playbook.md) - 示例通知中心支持哪些事件类型、通知事件接入场景、`TYPE_CREATED`、`TYPE_COMPLETED`、`TYPE_EXPIRED`、`TYPE_AUTH_CHANGED`、`SampleNotificationController`。\n"
            "- [示例产品能力到 Repo/入口索引](entities/code/modules/sample-product-code-index.md) - 平台横切 / 示例通知中心 的 code_map 导航入口，继续读示例通知中心 Coding Playbook。\n",
            encoding="utf-8",
        )

    def test_query_bundle_accepts_provided_semantic_plan(self) -> None:
        self._create_app_suite_collection_corpus()
        config = load_config(self.project)
        semantic_plan = {
            "operator": "COUNT_COLLECTION",
            "subjects": [{"type": "module", "canonical_id": "APPSET", "text": "APPSET"}],
            "target_collection": {"member_type": "application", "member_role": "feature", "relation": "contained_by_module", "scope": "APPSET"},
        }

        result = run_query_bundle(config, "应用集合数量", knowledge_id="alpha", candidate_limit=20, evidence_budget=8, semantic_plan=semantic_plan)

        self.assertEqual(result["semantic_plans"][0]["planner"], "provided")
        self.assertEqual(result["evidence_pages"][0]["path"], "wiki/entities/product/modules/APPSET.md")

    def _create_app_suite_collection_corpus(self) -> None:
        module = self.knowledge / "wiki" / "entities" / "product" / "modules" / "APPSET.md"
        module.parent.mkdir(parents=True, exist_ok=True)
        module.write_text(
            wiki_page(
                "APPSET 应用集合",
                "entity",
                "APPSET 应用集合以独立应用承载专项能力。\n\n"
                "## 功能清单\n\n"
                "| 功能名称 | 描述 |\n"
                "|------|------|\n"
                "| 示例曝光评估 | 前端页面暴露识别应用 |\n"
                "| 示例合规取用 | 授权数据源上的合规取用应用 |\n"
                "| 示例变更审核 | 变更治理应用 |\n\n"
                "## Related Pages\n"
                "- [示例曝光评估](../features/APPSET/示例曝光评估.md)\n"
                "- [示例合规取用](../features/APPSET/示例合规取用.md)\n"
                "- [示例变更审核](../features/APPSET/示例变更审核.md)\n",
            ),
            encoding="utf-8",
        )
        features = {
            "示例曝光评估.md": "示例曝光评估是 APPSET 应用集合中的独立专项治理应用。",
            "示例合规取用.md": "示例合规取用是 APPSET 应用集合中的独立数据取用与交付应用。",
            "示例变更审核.md": "示例变更审核是 APPSET 应用集合中的独立变更治理应用。",
        }
        feature_dir = self.knowledge / "wiki" / "entities" / "product" / "features" / "APPSET"
        feature_dir.mkdir(parents=True, exist_ok=True)
        for filename, body in features.items():
            (feature_dir / filename).write_text(wiki_page(filename.removesuffix(".md"), "entity", body), encoding="utf-8")
        (self.knowledge / "wiki" / "index.md").write_text(
            "# 索引\n\n"
            "- [APPSET 应用集合](entities/product/modules/APPSET.md) - APPSET 应用集合以独立应用承载专项能力，包含示例曝光评估、示例合规取用和示例变更审核。 (3 sources)\n"
            "- [示例曝光评估](entities/product/features/APPSET/示例曝光评估.md) - 示例曝光评估是 APPSET 应用集合中的独立专项治理应用。\n"
            "- [示例合规取用](entities/product/features/APPSET/示例合规取用.md) - 示例合规取用是 APPSET 应用集合中的独立数据取用与交付应用。\n"
            "- [示例变更审核](entities/product/features/APPSET/示例变更审核.md) - 示例变更审核是 APPSET 应用集合中的独立变更治理应用。\n",
            encoding="utf-8",
        )

    def _create_module_a_risk_monitoring_corpus(self) -> None:
        module_a_feature = self.knowledge / "wiki" / "entities" / "product" / "features" / "MODA" / "示例风险能力.md"
        module_a_feature.parent.mkdir(parents=True, exist_ok=True)
        module_a_feature.write_text(
            wiki_page(
                "示例风险能力",
                "entity",
                "示例风险能力是 MODA 面向访问审计场景的风险识别能力。\n\n"
                "## Related Pages\n"
                "- [MODA 示例模块](../../modules/MODA.md)\n"
                "- [sample_result_table](../../modules/MODA/data-dictionary/sample_result_table.md)\n"
                "- [MODA-示例风险能力-引擎能力说明](../../../../sources/product/platform/modules/MODA/features/示例风险能力-引擎能力说明.md)\n",
            ),
            encoding="utf-8",
        )
        module_a = self.knowledge / "wiki" / "entities" / "product" / "modules" / "MODA.md"
        module_a.parent.mkdir(parents=True, exist_ok=True)
        module_a.write_text(wiki_page("MODA 示例模块", "entity", "MODA 是访问审计和保护示例模块。"), encoding="utf-8")
        result_table = self.knowledge / "wiki" / "entities" / "product" / "modules" / "MODA" / "data-dictionary" / "sample_result_table.md"
        result_table.parent.mkdir(parents=True, exist_ok=True)
        result_table.write_text(wiki_page("sample_result_table", "entity", "MODA 示例结果表，用于记录示例风险能力结果。"), encoding="utf-8")
        source = self.knowledge / "wiki" / "sources" / "product" / "platform" / "modules" / "MODA" / "features" / "示例风险能力-引擎能力说明.md"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(wiki_page("MODA-示例风险能力-引擎能力说明", "source", "This page tracks the raw source.\n\n## Summary\n示例风险能力引擎能力说明。"), encoding="utf-8")
        module_b = self.knowledge / "wiki" / "entities" / "product" / "features" / "MODB" / "相邻风险能力.md"
        module_b.parent.mkdir(parents=True, exist_ok=True)
        module_b.write_text(wiki_page("相邻风险能力", "entity", "相邻风险能力是 MODB 面向 API 访问链路的风险监测能力。"), encoding="utf-8")
        app_suite = self.knowledge / "wiki" / "entities" / "product" / "features" / "APPSET" / "示例评估应用.md"
        app_suite.parent.mkdir(parents=True, exist_ok=True)
        app_suite.write_text(wiki_page("示例评估应用", "entity", "示例评估应用是 APPSET 中的风险评估应用。"), encoding="utf-8")
        (self.knowledge / "wiki" / "index.md").write_text(
            "# 索引\n\n"
            "- [示例风险能力](entities/product/features/MODA/示例风险能力.md) - 示例风险能力是 MODA 面向访问审计场景的风险识别能力。\n"
            "- [MODA-示例风险能力-引擎能力说明](sources/product/platform/modules/MODA/features/示例风险能力-引擎能力说明.md) - This page tracks the raw source raw/product/platform/modules/MODA/features/示例风险能力 引擎能力说明.md.\n"
            "- [sample_result_table](entities/product/modules/MODA/data-dictionary/sample_result_table.md) - 本页整理 MODA sample result table 表的数据字典，用于说明示例风险能力结果字段。\n"
            "- [相邻风险能力](entities/product/features/MODB/相邻风险能力.md) - 相邻风险能力是 MODB 面向 API 访问链路的风险监测能力。\n"
            "- [示例评估应用](entities/product/features/APPSET/示例评估应用.md) - 示例评估应用是 APPSET 中的风险评估应用。\n",
            encoding="utf-8",
        )

    def test_update_requires_write_target(self) -> None:
        config = load_config(self.project)
        with self.assertRaises(WriteTargetRequired):
            run_update(config, None, "写一条记录")

    def test_update_rejects_disabled_target(self) -> None:
        config = load_config(self.project)
        with self.assertRaises(KnowledgeDisabled):
            run_update(config, "disabled", "写一条记录")

    def test_update_rejects_read_only_target(self) -> None:
        config = load_config(self.project)
        with self.assertRaises(KnowledgeReadOnly):
            run_update(config, "readonly", "写一条记录")

    def test_update_outputs_preflight_package_without_wiki_writes(self) -> None:
        config = load_config(self.project)
        before_wiki_files = sorted(path.relative_to(self.knowledge).as_posix() for path in (self.knowledge / "wiki").rglob("*.md"))
        result = run_update(config, "alpha", "记录工作流维护笔记")
        after_wiki_files = sorted(path.relative_to(self.knowledge).as_posix() for path in (self.knowledge / "wiki").rglob("*.md"))
        self.assertEqual(result["kind"], MAINTENANCE_PREFLIGHT_KIND)
        self.assertEqual(result["status"], "requires_agent")
        self.assertEqual(result["knowledge_target"], "alpha")
        self.assertTrue(Path(result["preflight_artifact"]).exists())
        self.assertEqual(result["codex_next_step"]["preflight_artifact"], result["preflight_artifact"])
        self.assertFalse(result["continuation_policy"]["maintenance_preflight_package_is_final"])
        self.assertTrue(result["continuation_policy"]["slash_command_must_continue"])
        self.assertEqual(result["continuation_policy"]["continue_as"], "knowledge-manager")
        self.assertEqual(result["continuation_policy"]["human_readable_output_language"], "zh-CN")
        self.assertEqual(result["continuation_policy"]["language_policy"]["human_readable_fields"], "zh-CN")
        self.assertTrue(result["codex_next_step"]["must_continue"])
        self.assertFalse(result["codex_next_step"]["final_answer_allowed"])
        self.assertEqual(result["codex_next_step"]["completion_state"], "not_complete")
        self.assertEqual(result["codex_next_step"]["requires_agent_must_be_resolved_by"], "knowledge_manager_sub_agent")
        self.assertIn("contracts/k/update-workflow.md", result["codex_next_step"]["contract_refs"])
        self.assertTrue(result["codex_next_step"]["must_read_contract_refs_before_wiki_write"])
        self.assertEqual(result["codex_next_step"]["human_readable_output_language"], "zh-CN")
        self.assertEqual(result["codex_next_step"]["language_policy"]["human_readable_fields"], "zh-CN")
        self.assertTrue(result["codex_next_step"]["do_not_final_answer_at_preflight"])
        self.assertEqual(result["codex_next_step"]["agent"], "knowledge-manager")
        self.assertEqual(result["codex_next_step"]["agent_config"], ".trae/agents/knowledge-manager.md")
        self.assertNotIn("prompt", result["codex_next_step"])
        self.assertTrue(any("所有人读正文必须使用中文" in item for item in result["codex_next_step"]["required_actions"]))
        self.assertTrue(any(".trae/agents/knowledge-manager.md" in item for item in result["codex_next_step"]["required_actions"]))
        self.assertTrue(any("不得把 maintenance_preflight_package" in item for item in result["codex_next_step"]["required_actions"]))
        next_step_artifact = Path(result["codex_next_step"]["next_step_artifact"])
        self.assertTrue(next_step_artifact.exists())
        persisted_next_step = json.loads(next_step_artifact.read_text(encoding="utf-8"))
        self.assertFalse(persisted_next_step["final_answer_allowed"])
        self.assertEqual(persisted_next_step["preflight_artifact"], result["preflight_artifact"])
        self.assertEqual(persisted_next_step["human_readable_output_language"], "zh-CN")
        self.assertEqual(persisted_next_step["language_policy"]["human_readable_fields"], "zh-CN")
        self.assertEqual(result["quality_loop"]["final_status"], "blocked")
        self.assertIn("preflight_query_policy", result)
        self.assertIn("wiki_reconciliation", result)
        self.assertIn("relations_decision", result)
        self.assertEqual(before_wiki_files, after_wiki_files)
        self.assertFalse((self.knowledge / "wiki" / "queries" / "manual").exists())

    def test_update_analyzes_kcode_manager_request_without_wiki_writes(self) -> None:
        request = self.knowledge / "state" / "kcode-runs" / "run-001" / "handoff" / "knowledge-manager-request.md"
        request.parent.mkdir(parents=True, exist_ok=True)
        quality = request.parent / "handoff-quality.json"
        quality.write_text(
            json.dumps(
                {
                    "schema_version": "kcode.handoff_quality.v1",
                    "passed": True,
                    "issues": [],
                    "checked": {"shards": 1, "blueprints": 1},
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        manifest = request.parent / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "schema_version": "kcode.handoff_manifest.v1",
                    "knowledge_id": "alpha",
                    "knowledge_root": str(self.knowledge),
                    "run_id": "run-001",
                    "mode": "from-zero",
                    "knowledge_manager_request": "handoff/knowledge-manager-request.md",
                    "handoff_quality": "handoff/handoff-quality.json",
                    "human_readable_output_language": "zh-CN",
                    "language_policy": {"human_readable_fields": "zh-CN"},
                    "request": {"each_code_feature_page_must_independently_satisfy_query_profiles": True},
                    "required_fixed_headings": ["现有实现", "代码定位"],
                    "required_checks": ["preflight_QUERY", "query_bundle_profile_quality", "knowledge_verifier_handoff"],
                    "acceptance_commands": ["python -m knowledge_kit lint -k alpha"],
                    "acceptance_checks": ["每个被 query bundle 选中的 wiki/entities/code/features/** 页面都必须独立具备 Agentic Coding / PRD 设计所需章节。"],
                    "shards": [
                        {
                            "path": "handoff/shards/H001-feature.md",
                            "topic": "通用能力实现链",
                            "source_batch": "B001-feature",
                            "verified_findings": "batches/B001-feature/verified-findings.jsonl",
                            "analysis": "batches/B001-feature/analysis.md",
                            "evidence": "batches/B001-feature/evidence.json",
                            "source_summary_path": "wiki/sources/code/kcode-runs/run-001/H001-feature.md",
                            "source_summary_blueprint": "handoff/source-summary-blueprints/H001-feature.md",
                            "candidate_wiki_pages": [
                                "wiki/entities/code/features/module-c/feature.md",
                                "wiki/entities/code/features/module-c/alternate.md",
                            ],
                            "primary_wiki_pages": ["wiki/entities/code/features/module-c/feature.md"],
                            "knowledge_levels": ["feature_implementation"],
                            "page_blueprints": ["handoff/page-blueprints/B001-feature-01-feature.md"],
                        }
                    ],
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        request.write_text(
            "# Knowledge Manager 维护请求\n\n"
            "## 目标\n\n"
            "- knowledge_id: alpha\n"
            f"- knowledge_root: {self.knowledge}\n"
            "- kcode_run_id: run-001\n"
            "- manifest: handoff/manifest.json\n"
            "- human_readable_output_language: zh-CN\n"
            "- 任务类型: KCode handoff 整理维护\n\n"
            "## 输入分片\n\n"
            "| 分片 | 主题 | 来源批次 |\n"
            "| --- | --- | --- |\n"
            "| handoff/shards/H001-feature.md | 通用能力实现链 | B001-feature |\n\n"
            "## 建议输出页面\n\n"
            "| 分片 | 来源摘要页 | 候选正式代码页 | 知识层级 |\n"
            "| --- | --- | --- | --- |\n"
            "| handoff/shards/H001-feature.md | wiki/sources/code/kcode-runs/run-001/H001-feature.md | wiki/entities/code/features/module-a/feature.md | feature_implementation |\n",
            encoding="utf-8",
        )
        existing_page = self.knowledge / "wiki" / "entities" / "code" / "features" / "module-c" / "feature.md"
        existing_page.parent.mkdir(parents=True, exist_ok=True)
        existing_page.write_text(
            wiki_page(
                "通用能力实现链",
                "entity",
                "## 现有实现\n既有页面已经记录通用能力实现链。\n\n"
                "## 代码定位\n`src/module_c.py`\n\n"
                "## 实现链\n已有实现链。\n\n"
                "## 复用边界\n已有复用边界。\n\n"
                "## 改动点\n已有改动点。\n\n"
                "## 暂不应改动\n已有禁改边界。\n\n"
                "## 数据/权限/运行约束\n已有约束。\n\n"
                "## 测试/验证路径\n`python -m unittest`\n\n"
                "## PRD 设计影响\n已有 PRD 影响。\n\n"
                "## 缺口与继续探索\n已有缺口。\n",
                sources=["wiki/sources/code/kcode-runs/run-000/H000.md"],
            ),
            encoding="utf-8",
        )
        (self.knowledge / "wiki" / "index.md").write_text(
            "# 索引\n\n"
            "- [通用能力实现链](entities/code/features/module-c/feature.md) - 通用能力实现链入口在 `src/module_c.py`，复用边界和验证入口已记录。\n",
            encoding="utf-8",
        )
        config = load_config(self.project)
        before_wiki_files = sorted(path.relative_to(self.knowledge).as_posix() for path in (self.knowledge / "wiki").rglob("*.md"))

        result = run_update(config, "alpha", "按 KCode manager request 维护代码知识库", content="state/kcode-runs/run-001/handoff/knowledge-manager-request.md")

        after_wiki_files = sorted(path.relative_to(self.knowledge).as_posix() for path in (self.knowledge / "wiki").rglob("*.md"))
        analysis = result["content_analysis"]
        self.assertEqual(analysis["kind"], "file")
        self.assertEqual(analysis["knowledge_relative_path"], "state/kcode-runs/run-001/handoff/knowledge-manager-request.md")
        kcode = analysis["kcode_handoff"]
        self.assertTrue(kcode["detected"])
        self.assertEqual(kcode["source"], "manifest")
        self.assertEqual(kcode["manifest_path"], "state/kcode-runs/run-001/handoff/manifest.json")
        self.assertEqual(kcode["handoff_quality_path"], "state/kcode-runs/run-001/handoff/handoff-quality.json")
        self.assertTrue(kcode["handoff_quality"]["detected"])
        self.assertTrue(kcode["handoff_quality"]["passed"])
        self.assertEqual(kcode["handoff_quality"]["checked"]["blueprints"], 1)
        self.assertEqual(kcode["manager_request_path"], "state/kcode-runs/run-001/handoff/knowledge-manager-request.md")
        self.assertEqual(kcode["human_readable_output_language"], "zh-CN")
        self.assertEqual(kcode["kcode_run_id"], "run-001")
        self.assertEqual(kcode["shards"][0]["path"], "handoff/shards/H001-feature.md")
        self.assertEqual(kcode["shards"][0]["source_summary_blueprint"], "handoff/source-summary-blueprints/H001-feature.md")
        self.assertEqual(kcode["shards"][0]["primary_wiki_pages"], ["wiki/entities/code/features/module-c/feature.md"])
        self.assertEqual(kcode["shards"][0]["page_blueprints"], ["handoff/page-blueprints/B001-feature-01-feature.md"])
        self.assertEqual(kcode["suggested_output_pages"][0]["source_summary"], "wiki/sources/code/kcode-runs/run-001/H001-feature.md")
        self.assertEqual(kcode["suggested_output_pages"][0]["source_summary_blueprint"], "handoff/source-summary-blueprints/H001-feature.md")
        self.assertIn("wiki/entities/code/features/module-c/feature.md", kcode["suggested_output_pages"][0]["candidate_wiki_pages"])
        self.assertEqual(kcode["suggested_output_pages"][0]["primary_wiki_pages"], ["wiki/entities/code/features/module-c/feature.md"])
        self.assertEqual(kcode["suggested_output_pages"][0]["alternate_candidate_wiki_pages"], ["wiki/entities/code/features/module-c/alternate.md"])
        self.assertEqual(kcode["suggested_output_pages"][0]["page_blueprints"], ["handoff/page-blueprints/B001-feature-01-feature.md"])
        self.assertNotIn("wiki/entities/code/features/module-a/feature.md", kcode["suggested_output_pages"][0]["candidate_wiki_pages"])
        self.assertIn("现有实现", kcode["required_fixed_headings"])
        self.assertIn("knowledge_verifier_handoff", kcode["required_checks"])
        self.assertIn("query_bundle_profile_quality", kcode["required_checks"])
        self.assertIn("python -m knowledge_kit lint -k alpha", kcode["acceptance_commands"])
        self.assertTrue(kcode["request"]["each_code_feature_page_must_independently_satisfy_query_profiles"])
        self.assertTrue(any("独立具备 Agentic Coding / PRD 设计所需章节" in item for item in kcode["acceptance_checks"]))
        self.assertIn("通用能力实现链", result["preflight_query_policy"]["kcode_reconciliation_queries"])
        self.assertTrue(result["preflight_query_policy"]["kcode_reconciliation_read_plans"])
        self.assertTrue(result["codex_next_step"]["kcode_handoff_detected"])
        self.assertIn("source_trace.maintenance_materials", "\n".join(result["codex_next_step"]["required_actions"]))
        self.assertIn("wiki/entities/code/features/module-c/feature.md", result["wiki_reconciliation"]["matched_pages"])
        self.assertIn("wiki/entities/code/features/module-c/feature.md", result["wiki_reconciliation"]["canonical_path_candidates"])
        self.assertIn("wiki/sources/code/kcode-runs/run-001/H001-feature.md", result["wiki_reconciliation"]["canonical_path_candidates"])
        self.assertIn("wiki/entities/code/features/**", result["wiki_reconciliation"]["canonical_path_candidates"])
        self.assertIn("通用能力实现链", result["wiki_reconciliation"]["title_alias_candidates"])
        self.assertIn("wiki/index.md", result["source_trace"]["consulted_wiki_pages"])
        self.assertEqual(
            result["source_trace"]["maintenance_materials"],
            [
                "state/kcode-runs/run-001/handoff/knowledge-manager-request.md",
                "state/kcode-runs/run-001/handoff/manifest.json",
                "state/kcode-runs/run-001/handoff/handoff-quality.json",
                "state/kcode-runs/run-001/handoff/shards/H001-feature.md",
                "state/kcode-runs/run-001/batches/B001-feature/verified-findings.jsonl",
                "state/kcode-runs/run-001/batches/B001-feature/analysis.md",
                "state/kcode-runs/run-001/batches/B001-feature/evidence.json",
                "state/kcode-runs/run-001/handoff/source-summary-blueprints/H001-feature.md",
                "state/kcode-runs/run-001/handoff/page-blueprints/B001-feature-01-feature.md",
            ],
        )
        self.assertEqual(result["wiki_artifact_summary"], {"add": [], "update": [], "structural": []})
        self.assertEqual(before_wiki_files, after_wiki_files)

        manifest_result = run_update(
            config,
            "alpha",
            "按 KCode manifest 维护代码知识库",
            content="state/kcode-runs/run-001/handoff/manifest.json",
        )
        manifest_kcode = manifest_result["content_analysis"]["kcode_handoff"]
        self.assertTrue(manifest_kcode["detected"])
        self.assertEqual(manifest_kcode["request_path"], "handoff/knowledge-manager-request.md")

    def test_kcode_manager_request_table_parser_supports_primary_and_alternate_pages(self) -> None:
        rows = parse_suggested_output_pages(
            "# Knowledge Manager 维护请求\n\n"
            "## 建议输出页面\n\n"
            "| 分片 | 来源摘要页 | 主正式代码页 | 备选候选页 | 知识层级 | 落页蓝图 |\n"
            "| --- | --- | --- | --- | --- | --- |\n"
            "| handoff/shards/H001-feature.md | wiki/sources/code/kcode-runs/run-001/H001-feature.md | wiki/entities/code/features/module-a.md | wiki/entities/code/features/module-b.md<br>wiki/entities/code/features/module-c.md | coding_playbook | handoff/page-blueprints/B001-feature-01-module-a.md |\n"
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["primary_wiki_pages"], ["wiki/entities/code/features/module-a.md"])
        self.assertEqual(
            rows[0]["alternate_candidate_wiki_pages"],
            ["wiki/entities/code/features/module-b.md", "wiki/entities/code/features/module-c.md"],
        )
        self.assertEqual(
            rows[0]["candidate_wiki_pages"],
            [
                "wiki/entities/code/features/module-a.md",
                "wiki/entities/code/features/module-b.md",
                "wiki/entities/code/features/module-c.md",
            ],
        )
        self.assertEqual(rows[0]["knowledge_levels"], ["coding_playbook"])
        self.assertEqual(rows[0]["page_blueprints"], ["handoff/page-blueprints/B001-feature-01-module-a.md"])

    def test_kcode_manager_request_parser_merges_source_summary_blueprints(self) -> None:
        request = parse_kcode_manager_request(
            "# Knowledge Manager 维护请求\n\n"
            "## 目标\n\n"
            "- knowledge_id: alpha\n"
            "- kcode_run_id: run-001\n"
            "- manifest: handoff/manifest.json\n\n"
            "## 输入分片\n\n"
            "| 分片 | 主题 | 来源批次 |\n"
            "| --- | --- | --- |\n"
            "| handoff/shards/H001-feature.md | 通用能力实现链 | B001-feature |\n\n"
            "## 来源摘要页蓝图\n\n"
            "| 分片 | 来源摘要页 | 来源摘要蓝图 |\n"
            "| --- | --- | --- |\n"
            "| handoff/shards/H001-feature.md | wiki/sources/code/kcode-runs/run-001/H001-feature.md | handoff/source-summary-blueprints/H001-feature.md |\n\n"
            "## 建议输出页面\n\n"
            "| 分片 | 来源摘要页 | 主正式代码页 | 备选候选页 | 知识层级 | 落页蓝图 |\n"
            "| --- | --- | --- | --- | --- | --- |\n"
            "| handoff/shards/H001-feature.md | wiki/sources/code/kcode-runs/run-001/H001-feature.md | wiki/entities/code/features/module-a.md | 无 | coding_playbook | handoff/page-blueprints/B001-feature-01-module-a.md |\n",
            "state/kcode-runs/run-001/handoff/knowledge-manager-request.md",
        )

        self.assertTrue(request["detected"])
        self.assertEqual(request["shards"][0]["source_summary_blueprint"], "handoff/source-summary-blueprints/H001-feature.md")
        self.assertEqual(request["suggested_output_pages"][0]["source_summary_blueprint"], "handoff/source-summary-blueprints/H001-feature.md")

    def test_ingest_registers_source_without_fake_wiki_ingest(self) -> None:
        config = load_config(self.project)
        source = self.root / "source.md"
        source.write_text("# Source\n\nUDSP source text", encoding="utf-8")
        index_before = (self.knowledge / "wiki" / "index.md").read_text(encoding="utf-8")
        log_before = (self.knowledge / "wiki" / "log.md").read_text(encoding="utf-8")
        result = run_ingest(config, "alpha", str(source))
        raw_path = self.knowledge / result["source"]["raw_path"]
        self.assertEqual(result["kind"], INGEST_REGISTRATION_KIND)
        self.assertTrue(raw_path.exists())
        self.assertFalse((self.knowledge / "wiki" / "sources" / "imports").exists())
        self.assertEqual(index_before, (self.knowledge / "wiki" / "index.md").read_text(encoding="utf-8"))
        self.assertEqual(log_before, (self.knowledge / "wiki" / "log.md").read_text(encoding="utf-8"))

    def test_ingest_blocks_read_only_target(self) -> None:
        config = load_config(self.project)
        source = self.root / "source.md"
        source.write_text("# Source", encoding="utf-8")
        with self.assertRaises(KnowledgeReadOnly):
            run_ingest(config, "readonly", str(source))

    def test_init_creates_minimum_karpathy_structure(self) -> None:
        fresh = self.root / "fresh_knowledge"
        fresh_code = self.root / "fresh_code_knowledge"
        code_workspace = self.root / "fresh_code_workspace"
        data = json.loads((self.project / "knowledge_kit.config.json").read_text(encoding="utf-8"))
        data["knowledge_roots"].append(
            {
                "id": "fresh",
                "name": "新知识库",
                "path": str(fresh),
                "enabled": True,
                "mode": "read_write",
                "priority": 1,
            }
        )
        data["knowledge_roots"].append(
            {
                "id": "fresh_code",
                "name": "新代码知识库",
                "path": str(fresh_code),
                "enabled": True,
                "mode": "read_write",
                "priority": 1,
            }
        )
        data["code"] = {
            "workspaces": {
                "fresh_code": {
                    "workspace_root": str(code_workspace),
                    "repos_dir": "repos",
                    "submodule_mode": True,
                }
            }
        }
        (self.project / "knowledge_kit.config.json").write_text(json.dumps(data), encoding="utf-8")
        config = load_config(self.project)

        result = run_init(config, "fresh")

        self.assertEqual(result["kind"], INIT_SCAFFOLD_KIND)
        self.assertEqual(result["operation"], "INIT")
        self.assertTrue(result["validation"]["passed"])
        for relative in [
            "raw",
            "wiki/concepts",
            "wiki/entities",
            "wiki/sources",
            "wiki/queries",
            "wiki/schema.md",
            "wiki/index.md",
            "wiki/log.md",
            "wiki/overview.md",
            "relations/relation-graph.json",
            "relations/requirement-map.json",
            "relations/alias-lookup.json",
            "state",
        ]:
            self.assertTrue((fresh / relative).exists(), relative)
        self.assertNotIn("Code Knowledge", (fresh / "wiki" / "schema.md").read_text(encoding="utf-8"))

        code_result = run_init(config, "fresh_code")

        self.assertEqual(code_result["kind"], INIT_SCAFFOLD_KIND)
        for relative in [
            "wiki/entities/code/features",
            "wiki/entities/code/modules",
            "wiki/sources/code/kcode-runs",
        ]:
            self.assertTrue((fresh_code / relative).exists(), relative)
        code_schema = (fresh_code / "wiki" / "schema.md").read_text(encoding="utf-8")
        self.assertIn("Code Knowledge", code_schema)
        self.assertIn("coding_playbook", code_schema)
        self.assertIn("测试/验证路径", code_schema)
        self.assertIn("### 固定章节", code_schema)
        self.assertIn("## 现有实现", code_schema)
        self.assertEqual(code_result["updated"], [])

    def test_init_is_idempotent_and_does_not_overwrite_existing_files(self) -> None:
        config = load_config(self.project)
        index = self.knowledge / "wiki" / "index.md"
        before = index.read_text(encoding="utf-8")

        result = run_init(config, "alpha")

        self.assertEqual(index.read_text(encoding="utf-8"), before)
        self.assertEqual(result["overwritten"], [])
        self.assertIn("wiki/index.md", result["existing"])

    def test_init_appends_missing_code_schema_without_overwrite(self) -> None:
        data = json.loads((self.project / "knowledge_kit.config.json").read_text(encoding="utf-8"))
        data["code"] = {
            "workspaces": {
                "alpha": {
                    "workspace_root": str(self.root / "code_workspace"),
                    "repos_dir": "repos",
                    "submodule_mode": True,
                }
            }
        }
        (self.project / "knowledge_kit.config.json").write_text(json.dumps(data), encoding="utf-8")
        schema = self.knowledge / "wiki" / "schema.md"
        schema.write_text(
            "# Schema\n\n"
            "既有规则。\n\n"
            "## Code Knowledge\n\n"
            "- `feature_implementation`: 必须写当前实现、代码定位、实现链、数据/权限/运行约束、PRD 设计影响、缺口与继续探索。\n"
            "- 当前实现。\n",
            encoding="utf-8",
        )
        config = load_config(self.project)

        result = run_init(config, "alpha")

        text = schema.read_text(encoding="utf-8")
        self.assertIn("既有规则。", text)
        self.assertIn("## Code Knowledge", text)
        self.assertIn("### 固定章节", text)
        self.assertIn("必须写现有实现", text)
        self.assertNotIn("必须写当前实现", text)
        self.assertIn("wiki/schema.md", result["updated"])
        self.assertEqual(result["overwritten"], [])

        second = run_init(config, "alpha")
        self.assertEqual(second["updated"], [])
        self.assertEqual(schema.read_text(encoding="utf-8").count("## Code Knowledge"), 1)

    def test_init_blocks_read_only_target(self) -> None:
        config = load_config(self.project)
        with self.assertRaises(KnowledgeReadOnly):
            run_init(config, "readonly")

    def test_cli_init_outputs_scaffold_payload(self) -> None:
        config_path = self.project / "knowledge_kit.config.json"
        stdout = BufferedStdout()
        with mock.patch("sys.stdout", stdout):
            exit_code = main(["--config", str(config_path), "init", "-k", "alpha"])
        payload = json.loads(stdout.buffer.getvalue().decode("utf-8"))
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["kind"], INIT_SCAFFOLD_KIND)

    def test_lint_is_marked_as_mechanical_subset(self) -> None:
        config = load_config(self.project)
        result = run_lint(config, knowledge_id="alpha")
        self.assertTrue(result["mechanical_lint_only"])
        self.assertFalse(result["karpathy_lint"])

    def test_lint_reports_thin_source_summary(self) -> None:
        data = json.loads((self.project / "knowledge_kit.config.json").read_text(encoding="utf-8"))
        data["code"] = {
            "workspaces": {
                "alpha": {
                    "workspace_root": str(self.root / "code_workspace"),
                    "repos_dir": "repos",
                    "submodule_mode": True,
                }
            }
        }
        (self.project / "knowledge_kit.config.json").write_text(json.dumps(data), encoding="utf-8")
        source = self.knowledge / "wiki" / "sources" / "thin.md"
        source.write_text(
            wiki_page(
                "薄来源页",
                "source",
                "This page tracks the raw source `raw/thin.md`.\n\n## Source Snapshot\n- Format: `.md`\n\n## Summary\n太短。\n\n## Outline\n- One heading\n",
                sources=["raw/thin.md"],
            ),
            encoding="utf-8",
        )
        config = load_config(self.project)
        result = run_lint(config, knowledge_id="alpha")
        codes = {issue["code"] for issue in result["results"][0]["issues"]}
        self.assertIn("source_summary_too_thin", codes)
        self.assertIn("code_schema_missing", codes)
        self.assertIn("code_knowledge_pages_missing", codes)

        code_feature = self.knowledge / "wiki" / "entities" / "code" / "features" / "module-a" / "thin-feature.md"
        code_feature.parent.mkdir(parents=True, exist_ok=True)
        code_feature.write_text(
            wiki_page(
                "薄代码功能页",
                "entity",
                "这个页面只有一句泛泛说明。",
                sources=["state/kcode-runs/run/handoff/shards/H001.md"],
            ),
            encoding="utf-8",
        )
        result = run_lint(config, knowledge_id="alpha")
        codes = {issue["code"] for issue in result["results"][0]["issues"]}
        self.assertIn("source_summary_too_thin", codes)
        self.assertIn("code_schema_missing", codes)
        self.assertIn("code_feature_required_section_missing", codes)
        self.assertIn("code_feature_code_locator_missing", codes)
        self.assertIn("code_feature_source_trace_missing", codes)
        self.assertNotIn("code_knowledge_pages_missing", codes)

        code_feature.write_text(
            wiki_page(
                "空壳代码功能页",
                "entity",
                "## 现有实现\n待补充。\n\n"
                "## 代码定位\n待补充。\n\n"
                "## 实现链\n待补充。\n\n"
                "## 复用边界\n待补充。\n\n"
                "## 改动点\n待补充。\n\n"
                "## 暂不应改动\n待补充。\n\n"
                "## 数据/权限/运行约束\n待补充。\n\n"
                "## 测试/验证路径\n待补充。\n\n"
                "## PRD 设计影响\n待补充。\n\n"
                "## 缺口与继续探索\n待补充。\n",
                sources=["state/kcode-runs/run/handoff/shards/H001.md"],
            ),
            encoding="utf-8",
        )
        result = run_lint(config, knowledge_id="alpha")
        issues = [issue for issue in result["results"][0]["issues"] if issue["path"] == "wiki/entities/code/features/module-a/thin-feature.md"]
        codes = {issue["code"] for issue in issues}
        self.assertNotIn("code_feature_required_section_missing", codes)
        self.assertIn("code_feature_section_not_substantive", codes)
        self.assertIn("code_feature_code_locator_missing", codes)
        self.assertIn("code_feature_source_trace_missing", codes)

        code_feature.write_text(
            wiki_page(
                "完整代码功能页",
                "entity",
                "本页描述一个通用代码功能。\n\n"
                "## 现有实现\n"
                "入口由 `repos/repo-a/src/main/java/example/SampleController.java` 提供，页面路由可以包含 `/sample/todo-items` 这类示例路径。\n\n"
                "## 代码定位\n"
                "- `repos/repo-a/src/main/java/example/SampleController.java`\n"
                "- `SampleService`\n\n"
                "## 实现链\n"
                "- 页面或调用方进入 `SampleController`，再调用 `SampleService`。\n\n"
                "## 复用边界\n"
                "- 可复用既有 controller/service 分层，不复用未验证的外部依赖。\n\n"
                "## 改动点\n"
                "- 新增能力时改 controller、service 和验证样例。\n\n"
                "## 暂不应改动\n"
                "- 未继续探索前不要改权限和公共合同。\n\n"
                "## 数据/权限/运行约束\n"
                "- 需要保留请求字段、权限判断和运行配置。\n\n"
                "## 测试/验证路径\n"
                "- 运行对应模块测试或手工调用 `/sample/items/list`、`/sample/todo-items`。\n\n"
                "## PRD 设计影响\n"
                "- PRD 可以继承现有分层，但新增字段需要澄清。\n\n"
                "## 缺口与继续探索\n"
                "- 未发现阻断缺口。\n",
                sources=["wiki/sources/code/kcode-runs/run/H001.md"],
            ),
            encoding="utf-8",
        )
        (self.knowledge / "wiki" / "index.md").write_text(
            "# 索引\n\n"
            "- [完整代码功能页](entities/code/features/module-a/thin-feature.md) - 通用代码功能支持新增能力。\n",
            encoding="utf-8",
        )
        result = run_lint(config, knowledge_id="alpha")
        issues = [issue for issue in result["results"][0]["issues"] if issue["path"] == "wiki/entities/code/features/module-a/thin-feature.md"]
        codes = {issue["code"] for issue in issues}
        self.assertNotIn("code_feature_required_section_missing", codes)
        self.assertNotIn("code_feature_section_not_substantive", codes)
        self.assertNotIn("code_feature_code_locator_missing", codes)
        self.assertNotIn("code_feature_source_trace_missing", codes)
        self.assertIn("code_feature_source_summary_missing", codes)

        source_summary = self.knowledge / "wiki" / "sources" / "code" / "kcode-runs" / "run" / "H001.md"
        source_summary.parent.mkdir(parents=True, exist_ok=True)
        source_summary.write_text(
            wiki_page(
                "完整代码功能页来源摘要",
                "source",
                "本来源摘要追溯 handoff shard、analysis、evidence 和 verified findings，供 feature 页 frontmatter sources 引用。",
            ),
            encoding="utf-8",
        )

        result = run_lint(config, knowledge_id="alpha")
        issues = [issue for issue in result["results"][0]["issues"] if issue["path"] == "wiki/entities/code/features/module-a/thin-feature.md"]
        codes = {issue["code"] for issue in issues}
        self.assertNotIn("code_feature_source_summary_missing", codes)
        self.assertIn("code_feature_index_summary_not_actionable", codes)

        (self.knowledge / "wiki" / "index.md").write_text(
            "# 索引\n\n"
            "- [完整代码功能页](entities/code/features/module-a/thin-feature.md) - 通用代码功能入口在 `repos/repo-a/src/main/java/example/SampleController.java`，复用 `SampleService`，验证 `/sample/items/list`。\n",
            encoding="utf-8",
        )
        result = run_lint(config, knowledge_id="alpha")
        issues = [issue for issue in result["results"][0]["issues"] if issue["path"] == "wiki/entities/code/features/module-a/thin-feature.md"]
        codes = {issue["code"] for issue in issues}
        self.assertNotIn("code_feature_index_summary_not_actionable", codes)

class ContractStaticTests(unittest.TestCase):
    @property
    def repo(self) -> Path:
        return Path(__file__).resolve().parents[1]

    def read(self, relative: str) -> str:
        return (self.repo / relative).read_text(encoding="utf-8")

    def test_prompt_and_agent_contracts_do_not_reference_removed_control_plane(self) -> None:
        files = [
            "contracts/karpathy-wiki/workflow.md",
            ".trae/agents/knowledge-manager.md",
            ".trae/agents/knowledge-verifier.md",
            "contracts/k/command-contract.md",
            "README.md",
        ]
        combined = "\n".join(self.read(item) for item in files)
        forbidden_values = ["cross-" + "knowledge-links"]
        for forbidden in forbidden_values:
            self.assertNotIn(forbidden, combined)

    def test_karpathy_prompt_exposes_all_native_operations(self) -> None:
        text = self.read("contracts/karpathy-wiki/workflow.md")
        for operation in ["INIT", "INGEST", "QUERY", "LINT"]:
            self.assertIn(operation, text)
        self.assertIn("当前选中的外部 knowledge root", text)
        self.assertIn("全文扫库", text)

    def test_manager_contract_contains_required_handoffs(self) -> None:
        text = (
            self.read(".trae/agents/knowledge-manager.md")
            + self.read("contracts/k/command-contract.md")
            + self.read("contracts/karpathy-wiki/workflow.md")
        )
        for required in ["preflight QUERY", "wiki_reconciliation", "index/log/overview", "relations decision", "verifier handoff"]:
            self.assertIn(required, text)
        for required in [
            "KCode",
            "coding_context",
            "代码定位",
            "复用边界",
            "改动点",
            "测试/验证路径",
            "blocking_gaps",
            "index 是否可召回",
            "query-bundle 代码 profile 质量门",
            "profile_code_feature_evidence_missing",
            "profile_code_feature_source_trace_missing",
            "profile_code_feature_source_summary_missing",
            "profile_required_section_missing",
            "profile_query_topic_not_covered",
            "schema 是否包含 Code Knowledge",
            "实质内容",
            "frontmatter",
            "wiki/sources/code/kcode-runs",
            "独立支撑 Agentic Coding / PRD 设计查询",
            "不能用其他页面内容抵消",
            "primary_wiki_pages",
            "alternate_candidate_wiki_pages",
            "source-summary-blueprints",
            "source summary 只承载来源范围",
            "source_trace.maintenance_materials",
            "verifier_handoff",
            "verified-findings",
            "page-blueprints",
            "机械复制",
            "备选页",
        ]:
            self.assertIn(required, text)

    def test_kcode_new_session_language_contract_is_entrypoint_visible(self) -> None:
        text = (
            self.read("AGENTS.md")
            + self.read("contracts/k/command-contract.md")
            + self.read(".trae/agents/knowledge-manager.md")
            + self.read("prompts/kcode-planner.md")
            + self.read("prompts/kcode-analyzer.md")
            + self.read("prompts/kcode-verifier.md")
            + self.read(".trae/agents/kcode-planner.md")
            + self.read(".trae/agents/kcode-analyzer.md")
            + self.read(".trae/agents/kcode-verifier.md")
        )
        for required in [
            "human_readable_output_language",
            "language_policy",
            "新会话",
            "All Markdown and human-readable JSON fields you write must be Chinese",
            "All Markdown and human-readable JSON/JSONL fields you write must be Chinese",
            "All human-readable JSON fields you write must be Chinese",
        ]:
            self.assertIn(required, text)

    def test_kcode_requires_llm_contract_is_not_terminal(self) -> None:
        text = (
            self.read("contracts/k/command-contract.md")
            + self.read("contracts/k/code-workflow.md")
            + self.read("src/knowledge_kit/workflow_contract.py")
            + self.read("src/knowledge_kit/code/workspace.py")
        )
        for required in [
            "requires_llm",
            "requires_llm_is_final",
            "slash_command_must_continue",
            "completion_state",
            "not_complete",
            "final_answer_allowed",
            "requires_llm_must_be_resolved_by",
            "current_session_or_named_kcode_agent",
            "codex-next-step.json",
            "不得把 requires_llm 当作最终回答",
            "contracts/k/code-workflow.md",
        ]:
            self.assertIn(required, text)

    def test_ku_contract_requires_manager_continuation_after_preflight(self) -> None:
        text = (
            self.read("AGENTS.md")
            + self.read("contracts/k/command-contract.md")
            + self.read("contracts/k/update-workflow.md")
            + self.read("src/knowledge_kit/workflow_contract.py")
            + self.read("src/knowledge_kit/update.py")
            + self.read(".trae/agents/knowledge-manager.md")
        )
        for required in [
            "maintenance_preflight_package",
            "status=requires_agent",
            "preflight_artifact",
            "slash_command_must_continue",
            "codex_next_step",
            "completion_state",
            "not_complete",
            "final_answer_allowed",
            "requires_agent_must_be_resolved_by",
            "knowledge_manager_sub_agent",
            "ku-next-step.json",
            "knowledge-manager",
            "不得只运行 CLI 后停止",
            "最终回答不得停在",
            "不得把 maintenance_preflight_package",
            "source_trace.maintenance_materials",
            "verifier handoff",
            "新会话",
            "human_readable_output_language",
            "language_policy",
            "所有人读正文必须使用中文",
        ]:
            self.assertIn(required, text)
        self.assertIn(".trae/agents/knowledge-manager.md", text)
        self.assertNotIn("prompts/" + "knowledge-manager.md", text)

    def test_k_query_contract_uses_query_bundle_and_forbids_raw_reads(self) -> None:
        command_text = self.read("contracts/k/command-contract.md")
        text = (
            command_text
            + self.read("contracts/k/query-workflow.md")
            + self.read("contracts/k/query-code-exploration.md")
            + self.read("AGENTS.md")
            + self.read("README.md")
        )
        self.assertLessEqual(len(command_text.splitlines()), 140)
        for ref in [
            "contracts/k/command-contract.md",
            "contracts/k/query-workflow.md",
            "contracts/k/query-code-exploration.md",
            "contracts/k/code-workflow.md",
            "contracts/k/update-workflow.md",
        ]:
            self.assertIn(ref, command_text)
        self.assertIn("query-bundle", text)
        self.assertIn("raw", text)
        self.assertNotIn("Get-Content raw", text)
        for required in [
            "result_contract",
            "verification_result_skeleton",
            "quality_gate",
            "代码验证质量门",
            "本地代码路径",
            "pre_code_semantic_review_required",
            "execution_sequence",
            "不能停在语义复核",
        ]:
            self.assertIn(required, text)

    def test_verifier_contract_contains_framework_and_output_fields(self) -> None:
        text = self.read(".trae/agents/knowledge-verifier.md")
        for required in ["知识一致性", "知识库完整性", "知识关联", "变更影响", "Workflow 对齐"]:
            self.assertIn(required, text)
        for field in ["passed", "confidence", "issues", "suggestions", "verification_scope"]:
            self.assertIn(field, text)
        for required in [
            "KCode / 代码知识页",
            "Code Knowledge",
            "state/kcode-runs/**",
            "blocking_gaps",
            "代码定位",
            "复用边界",
            "改动点",
            "测试/验证路径",
            "coding_context",
            "index.md 是否包含可召回摘要",
            "profile_code_feature_evidence_missing",
            "profile_code_feature_source_trace_missing",
            "profile_code_feature_source_summary_missing",
            "profile_required_section_missing",
            "profile_query_topic_not_covered",
            "wiki/entities/code/features/**",
            "实质内容",
            "frontmatter",
            "wiki/sources/code/kcode-runs",
            "source-summary-blueprints",
            "source-summary-blueprint",
            "maintenance_materials",
            "handoff shard",
            "verified findings",
            "主要 evidence",
            "独立具备 Agentic Coding / PRD 设计查询",
            "不能用其他页面内容抵消",
        ]:
            self.assertIn(required, text)


if __name__ == "__main__":
    unittest.main()


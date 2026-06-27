from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from knowledge_kit.code import run_code
from knowledge_kit.code.handoff import page_blueprint_filename
from knowledge_kit.config import load_config


class KCodeContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.project = self.root / "kit"
        self.project.mkdir()
        self.knowledge = self.root / "knowledge"
        self.workspace = self.root / "workspace"
        self._create_knowledge()
        self._create_workspace()
        self._write_config()
        self.config = load_config(self.project)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_page_blueprint_filename_stays_short_for_long_paths(self) -> None:
        filename = page_blueprint_filename(
            "B001-very-long-batch-name-with-many-feature-and-module-segments",
            1,
            "wiki/entities/code/features/very/deep/path/with/a/long/feature-name.md",
        )

        self.assertLessEqual(len(filename), 90)
        self.assertNotIn("/", filename)
        self.assertNotIn("\\", filename)
        self.assertTrue(filename.endswith(".md"))

    def _create_knowledge(self) -> None:
        for relative in ["raw", "wiki", "relations", "state"]:
            (self.knowledge / relative).mkdir(parents=True, exist_ok=True)
        for name in ["schema.md", "index.md", "log.md", "overview.md"]:
            (self.knowledge / "wiki" / name).write_text(f"# {name}\n", encoding="utf-8")

    def _create_workspace(self) -> None:
        repo = self.workspace / "repos" / "repo-a"
        repo.mkdir(parents=True)
        (self.workspace / ".gitmodules").write_text(
            '[submodule "repo-a"]\n\tpath = repos/repo-a\n\turl = https://example.com/repo-a.git\n',
            encoding="utf-8",
        )
        (repo / "app.py").write_text(
            "from framework import app\n\n"
            "@app.route('/items')\n"
            "def list_items():\n"
            "    return []\n",
            encoding="utf-8",
        )
        (repo / "src" / "main" / "java" / "example").mkdir(parents=True)
        (repo / "src" / "api").mkdir(parents=True)
        (repo / "src" / "views").mkdir(parents=True)
        (repo / "src" / "components").mkdir(parents=True)
        (repo / "src" / "http" / "modules").mkdir(parents=True)
        (repo / "src" / "api" / "sampleApi.js").write_text(
            "export function listItems() {\n"
            "  return request.post('/sample/items/list')\n"
            "}\n",
            encoding="utf-8",
        )
        (repo / "src" / "views" / "Feature.vue").write_text(
            "<template><Helper /></template>\n"
            "<script>\n"
            "import Helper from '@/components/Helper.vue'\n"
            "export default {\n"
            "  methods: {\n"
            "    load() {\n"
            "      return this.$api.sample.listItems()\n"
            "    }\n"
            "  }\n"
            "}\n"
            "</script>\n",
            encoding="utf-8",
        )
        (repo / "src" / "views" / "List.vue").write_text(
            "<template><span>list view should not be a Java type target</span></template>\n",
            encoding="utf-8",
        )
        (repo / "src" / "components" / "Helper.vue").write_text(
            "<template><span>helper</span></template>\n"
            "<script>export default {}</script>\n",
            encoding="utf-8",
        )
        (repo / "src" / "http" / "modules" / "sample.js").write_text(
            "import request from '../request'\n\n"
            "export const listItems = () => {\n"
            "  return request({\n"
            "    url: '/sample/items/list',\n"
            "    method: 'post'\n"
            "  })\n"
            "}\n",
            encoding="utf-8",
        )
        (repo / "src" / "main" / "java" / "example" / "SampleController.java").write_text(
            "package example;\n\n"
            "import java.util.List;\n"
            "import example.Database;\n\n"
            "@RequestMapping(\"sample\")\n"
            "public class SampleController {\n"
            "    private final SampleService service;\n\n"
            "    private final Database database = new Database();\n\n"
            "    public SampleController(SampleService service) {\n"
            "        this.service = service;\n"
            "    }\n\n"
            "    @PostMapping(value=\"/items/list\")\n"
            "    public List<String> list() {\n"
            "        String ignored = \"UnrelatedService\";\n"
            "        return service.list();\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )
        (repo / "src" / "main" / "java" / "example" / "Database.java").write_text(
            "package example;\n\n"
            "public class Database {}\n",
            encoding="utf-8",
        )
        (repo / "src" / "main" / "java" / "example" / "DatabaseBackupServiceImpl.java").write_text(
            "package example;\n\n"
            "public class DatabaseBackupServiceImpl {}\n",
            encoding="utf-8",
        )
        (repo / "src" / "main" / "java" / "example" / "UnrelatedServiceImpl.java").write_text(
            "package example;\n\n"
            "public class UnrelatedServiceImpl {}\n",
            encoding="utf-8",
        )
        (repo / "src" / "main" / "java" / "example" / "SampleService.java").write_text(
            "package example;\n\n"
            "public interface SampleService {\n"
            "    java.util.List<String> list();\n"
            "}\n",
            encoding="utf-8",
        )
        (repo / "src" / "main" / "java" / "example" / "SampleServiceImpl.java").write_text(
            "package example;\n\n"
            "public class SampleServiceImpl implements SampleService {\n"
            "    public java.util.List<String> list() {\n"
            "        return java.util.List.of(\"ok\");\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )
        (repo / "config.json").write_text('{"enabled": true}\n', encoding="utf-8")

    def _write_config(self) -> None:
        data = {
            "schema_version": "1.0",
            "knowledge_roots": [
                {
                    "id": "fixture_code_kb",
                    "name": "Fixture Code KB",
                    "path": str(self.knowledge),
                    "enabled": True,
                    "mode": "read_write",
                    "priority": 1,
                }
            ],
            "code": {
                "runs_dir": "state/kcode-runs",
                "workspaces": {
                    "fixture_code_kb": {
                        "workspace_root": str(self.workspace),
                        "repos_dir": "repos",
                        "submodule_mode": True,
                    }
                },
            },
        }
        (self.project / "knowledge_kit.config.json").write_text(json.dumps(data), encoding="utf-8")

    def test_inventory_writes_generic_artifacts(self) -> None:
        result = run_code(self.config, "fixture_code_kb", stage="inventory", mode="from-zero")

        run_dir = self.knowledge / "state" / "kcode-runs" / result["run_id"]
        submodules = json.loads((run_dir / "inventory" / "submodules.json").read_text(encoding="utf-8"))
        repo_map = json.loads((run_dir / "inventory" / "repo-map.json").read_text(encoding="utf-8"))

        self.assertEqual(result["repo_count"], 1)
        self.assertEqual(submodules["submodules"][0]["path"], "repos/repo-a")
        self.assertEqual(repo_map["repos"][0]["entrypoints"][0]["file"], "repos/repo-a/app.py")

    def test_plan_stage_returns_llm_package(self) -> None:
        inventory = run_code(self.config, "fixture_code_kb", stage="inventory", mode="from-zero")

        result = run_code(self.config, "fixture_code_kb", stage="plan", resume=inventory["run_id"])

        self.assertEqual(result["status"], "requires_llm")
        self.assertEqual(result["agent"], "kcode-planner")
        self.assertFalse(result["continuation_policy"]["requires_llm_is_final"])
        self.assertTrue(result["continuation_policy"]["slash_command_must_continue"])
        self.assertEqual(result["continuation_policy"]["language_policy"]["human_readable_fields"], "zh-CN")
        self.assertEqual(result["language_policy"]["human_readable_fields"], "zh-CN")
        self.assertEqual(result["run_dir"], str(self.knowledge / "state" / "kcode-runs" / inventory["run_id"]))
        self.assertEqual(result["codex_next_step"]["schema_version"], "kcode.codex_next_step.v1")
        self.assertTrue(result["codex_next_step"]["must_continue"])
        self.assertFalse(result["codex_next_step"]["final_answer_allowed"])
        self.assertEqual(result["codex_next_step"]["completion_state"], "not_complete")
        self.assertEqual(result["codex_next_step"]["requires_llm_must_be_resolved_by"], "current_session_or_named_kcode_agent")
        self.assertIn("contracts/k/code-workflow.md", result["codex_next_step"]["contract_refs"])
        self.assertTrue(result["codex_next_step"]["must_read_contract_refs_before_writing_outputs"])
        self.assertTrue(result["codex_next_step"]["do_not_final_answer_at_requires_llm"])
        self.assertEqual(result["codex_next_step"]["after_writing_outputs_command"], f"python -m knowledge_kit code -k fixture_code_kb --stage plan-verify --resume {inventory['run_id']}")
        self.assertEqual(result["codex_next_step"]["next_step_artifact"], "codex-next-step.json")
        self.assertTrue(any("不得把 requires_llm 当作最终回答" in item for item in result["codex_next_step"]["required_actions"]))
        self.assertIn("plan/analysis-plan.json", result["expected_outputs"])
        run_dir = self.knowledge / "state" / "kcode-runs" / inventory["run_id"]
        persisted_next_step = json.loads((run_dir / "codex-next-step.json").read_text(encoding="utf-8"))
        self.assertFalse(persisted_next_step["final_answer_allowed"])
        self.assertEqual(persisted_next_step["after_writing_outputs_command"], result["codex_next_step"]["after_writing_outputs_command"])
        persisted_run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(persisted_run["current_codex_next_step"], "codex-next-step.json")
        self.assertEqual(persisted_run["artifacts"]["codex_next_step"], "codex-next-step.json")
        planner_input = json.loads((run_dir / "plan" / "planner-input.json").read_text(encoding="utf-8"))
        self.assertEqual(planner_input["coverage_contract"]["contract_id"], "kcode.agentic_coding.v1")
        self.assertEqual(planner_input["human_readable_output_language"], "zh-CN")
        self.assertEqual(planner_input["language_policy"]["human_readable_fields"], "zh-CN")
        self._write_legacy_plan(run_dir)

        blocked = run_code(self.config, "fixture_code_kb", stage="plan-verify", resume=inventory["run_id"])

        self.assertEqual(blocked["status"], "failed")
        blocked_codes = {issue["code"] for issue in blocked["deterministic"]["issues"]}
        self.assertIn("legacy_evidence_budget", blocked_codes)
        self._write_invalid_coding_plan(run_dir)

        blocked = run_code(self.config, "fixture_code_kb", stage="plan-verify", resume=inventory["run_id"])

        blocked_codes = {issue["code"] for issue in blocked["deterministic"]["issues"]}
        self.assertIn("required_claims_missing", blocked_codes)
        self._write_plan(run_dir)

        verifier = run_code(self.config, "fixture_code_kb", stage="plan-verify", resume=inventory["run_id"])

        self.assertEqual(verifier["status"], "requires_llm")
        self.assertEqual(verifier["agent"], "kcode-verifier")
        self.assertEqual(verifier["human_readable_output_language"], "zh-CN")
        self.assertEqual(verifier["language_policy"]["human_readable_fields"], "zh-CN")
        self.assertEqual(verifier["codex_next_step"]["after_writing_outputs_command"], f"python -m knowledge_kit code -k fixture_code_kb --stage plan-verify --resume {inventory['run_id']}")
        self.assertTrue(verifier["continuation_policy"]["slash_command_must_continue"])
        self.assertIn("verifier/plan-verification.json", verifier["expected_outputs"])
        plan_verifier_input = json.loads((run_dir / "verifier" / "plan-verifier-input.json").read_text(encoding="utf-8"))
        self.assertEqual(plan_verifier_input["human_readable_output_language"], "zh-CN")
        self.assertEqual(plan_verifier_input["language_policy"]["human_readable_fields"], "zh-CN")
        (run_dir / "verifier" / "plan-verification.json").write_text(
            json.dumps({"schema_version": "kcode.verification.plan.v1", "passed": True, "confidence": 0.9, "required_repairs": []}),
            encoding="utf-8",
        )

        completed = run_code(self.config, "fixture_code_kb", stage="plan-verify", resume=inventory["run_id"])

        self.assertEqual(completed["status"], "completed")

    def test_verify_reports_invalid_evidence_ref(self) -> None:
        inventory = run_code(self.config, "fixture_code_kb", stage="inventory", mode="from-zero")
        run_dir = self.knowledge / "state" / "kcode-runs" / inventory["run_id"]
        self._write_plan(run_dir)
        run_code(self.config, "fixture_code_kb", stage="evidence", resume=inventory["run_id"], batch="B001")
        evidence = json.loads((run_dir / "batches" / "B001-module-a" / "evidence.json").read_text(encoding="utf-8"))
        evidence_files = {item["path"] for item in evidence["files"]}
        self.assertIn("repos/repo-a/src/main/java/example/SampleController.java", evidence_files)
        self.assertIn("repos/repo-a/src/main/java/example/SampleService.java", evidence_files)
        self.assertIn("repos/repo-a/src/main/java/example/SampleServiceImpl.java", evidence_files)
        self.assertIn("repos/repo-a/src/main/java/example/Database.java", evidence_files)
        self.assertNotIn("repos/repo-a/src/views/List.vue", evidence_files)
        self.assertNotIn("repos/repo-a/src/main/java/example/DatabaseBackupServiceImpl.java", evidence_files)
        self.assertNotIn("repos/repo-a/src/main/java/example/UnrelatedServiceImpl.java", evidence_files)
        self.assertIn("http_endpoint_to_controller", evidence["closure"]["followed_reference_kinds"])
        self.assertIn("java_interface_or_contract_implementation", evidence["closure"]["followed_reference_kinds"])
        (run_dir / "batches" / "B001-module-a" / "analysis.md").write_text("# 分析\n\n已读取 fixture 的入口与实现链。\n", encoding="utf-8")
        findings = run_dir / "batches" / "B001-module-a" / "findings.jsonl"
        findings.write_text(
            json.dumps(
                {
                    "finding_id": "F-B001-001",
                    "batch_id": "B001",
                    "kind": "capability",
                    "title": "通用能力",
                    "current_state": "fixture 暴露了路由入口。",
                    "knowledge_level": "code_map",
                    "evidence_refs": [
                        "repos/repo-a/src/main/java/example/SampleController.java:1-14",
                        "repos/repo-a/app.py:1-5",
                    ],
                    "coverage_claims": [
                        {
                            "item": "entrypoints",
                            "status": "covered",
                            "evidence_refs": ["repos/repo-a/src/main/java/example/SampleController.java:1-14"],
                        }
                    ],
                    "confidence": 0.8,
                    "blocking_gaps": [],
                    "non_blocking_gaps": [],
                    "exploration_hints": [],
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

        result = run_code(self.config, "fixture_code_kb", stage="verify", resume=inventory["run_id"], batch="B001")

        self.assertEqual(result["status"], "failed")
        codes = {issue["code"] for issue in result["deterministic"]["issues"]}
        self.assertEqual(codes, {"invalid_evidence_ref"})

        evidence.pop("closure", None)
        (run_dir / "batches" / "B001-module-a" / "evidence.json").write_text(json.dumps(evidence), encoding="utf-8")
        self._write_feature_findings(findings)

        result = run_code(self.config, "fixture_code_kb", stage="verify", resume=inventory["run_id"], batch="B001")

        codes = {issue["code"] for issue in result["deterministic"]["issues"]}
        self.assertIn("evidence_closure_missing", codes)
        run_code(self.config, "fixture_code_kb", stage="evidence", resume=inventory["run_id"], batch="B001")
        self._write_feature_findings(findings)

        result = run_code(self.config, "fixture_code_kb", stage="verify", resume=inventory["run_id"], batch="B001")

        codes = {issue["code"] for issue in result["deterministic"]["issues"]}
        self.assertIn("coverage_claims_not_layer_specific", codes)
        feature_payload = json.loads(findings.read_text(encoding="utf-8"))
        feature_payload["knowledge_object_candidates"] = ["wiki/entities/code/features/module-a.md"]
        findings.write_text(json.dumps(feature_payload, ensure_ascii=False) + "\n", encoding="utf-8")

        result = run_code(self.config, "fixture_code_kb", stage="verify", resume=inventory["run_id"], batch="B001")

        codes = {issue["code"] for issue in result["deterministic"]["issues"]}
        self.assertIn("coverage_claims_not_layer_specific", codes)
        self._write_coding_playbook_findings(findings, include_context=False)
        missing_candidate_payload = json.loads(findings.read_text(encoding="utf-8"))
        missing_candidate_payload.pop("knowledge_object_candidates", None)
        findings.write_text(json.dumps(missing_candidate_payload, ensure_ascii=False) + "\n", encoding="utf-8")

        result = run_code(self.config, "fixture_code_kb", stage="verify", resume=inventory["run_id"], batch="B001")

        codes = {issue["code"] for issue in result["deterministic"]["issues"]}
        self.assertIn("knowledge_object_candidates_missing", codes)
        self.assertIn("coding_context_missing", codes)
        self._write_coding_playbook_findings(findings, include_context=True)

        result = run_code(self.config, "fixture_code_kb", stage="verify", resume=inventory["run_id"], batch="B001")

        self.assertEqual(result["status"], "requires_llm")

    def test_evidence_expands_vue_alias_and_global_api_module_calls(self) -> None:
        inventory = run_code(self.config, "fixture_code_kb", stage="inventory", mode="from-zero")
        run_dir = self.knowledge / "state" / "kcode-runs" / inventory["run_id"]
        self._write_vue_feature_plan(run_dir)

        run_code(self.config, "fixture_code_kb", stage="evidence", resume=inventory["run_id"], batch="B010")

        evidence = json.loads((run_dir / "batches" / "B010-vue-feature" / "evidence.json").read_text(encoding="utf-8"))
        evidence_files = {item["path"] for item in evidence["files"]}
        self.assertIn("repos/repo-a/src/views/Feature.vue", evidence_files)
        self.assertIn("repos/repo-a/src/components/Helper.vue", evidence_files)
        self.assertIn("repos/repo-a/src/http/modules/sample.js", evidence_files)
        self.assertIn("repos/repo-a/src/main/java/example/SampleController.java", evidence_files)
        self.assertIn("repos/repo-a/src/main/java/example/SampleService.java", evidence_files)
        self.assertIn("repos/repo-a/src/main/java/example/SampleServiceImpl.java", evidence_files)
        self.assertIn("repos/repo-a/src/main/java/example/Database.java", evidence_files)
        self.assertNotIn("repos/repo-a/src/views/List.vue", evidence_files)
        self.assertNotIn("repos/repo-a/src/main/java/example/DatabaseBackupServiceImpl.java", evidence_files)
        self.assertNotIn("repos/repo-a/src/main/java/example/UnrelatedServiceImpl.java", evidence_files)
        followed = set(evidence["closure"]["followed_reference_kinds"])
        self.assertIn("js_alias_import", followed)
        self.assertIn("frontend_api_module_call", followed)
        self.assertIn("http_endpoint_to_controller", followed)
        self.assertIn("java_interface_or_contract_implementation", followed)

    def test_verify_blocks_non_chinese_analysis_markdown(self) -> None:
        inventory = run_code(self.config, "fixture_code_kb", stage="inventory", mode="from-zero")
        run_dir = self.knowledge / "state" / "kcode-runs" / inventory["run_id"]
        self._write_plan(run_dir)
        run_code(self.config, "fixture_code_kb", stage="evidence", resume=inventory["run_id"], batch="B001")
        batch_dir = run_dir / "batches" / "B001-module-a"
        (batch_dir / "analysis.md").write_text("# Analysis\n\nThe route is implemented by the sample controller.\n", encoding="utf-8")
        self._write_coding_playbook_findings(batch_dir / "findings.jsonl", include_context=True)

        result = run_code(self.config, "fixture_code_kb", stage="verify", resume=inventory["run_id"], batch="B001")

        self.assertEqual(result["status"], "failed")
        codes = {issue["code"] for issue in result["deterministic"]["issues"]}
        self.assertIn("human_text_not_chinese", codes)

    def test_plan_verify_blocks_non_chinese_human_json_field(self) -> None:
        inventory = run_code(self.config, "fixture_code_kb", stage="inventory", mode="from-zero")
        run_dir = self.knowledge / "state" / "kcode-runs" / inventory["run_id"]
        self._write_plan(run_dir)
        ledger_path = run_dir / "plan" / "coverage-ledger.json"
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        ledger["items"][0]["note"] = "Need route owner before analysis."
        ledger_path.write_text(json.dumps(ledger, ensure_ascii=False), encoding="utf-8")

        result = run_code(self.config, "fixture_code_kb", stage="plan-verify", resume=inventory["run_id"])

        self.assertEqual(result["status"], "failed")
        issues = result["deterministic"]["issues"]
        self.assertTrue(
            any(
                issue["code"] == "human_text_not_chinese"
                and issue.get("artifact") == "plan/coverage-ledger.json"
                and issue.get("field") == "items[0].note"
                for issue in issues
            )
        )

    def test_verify_blocks_non_chinese_nested_finding_human_json_field(self) -> None:
        inventory = run_code(self.config, "fixture_code_kb", stage="inventory", mode="from-zero")
        run_dir = self.knowledge / "state" / "kcode-runs" / inventory["run_id"]
        self._write_plan(run_dir)
        run_code(self.config, "fixture_code_kb", stage="evidence", resume=inventory["run_id"], batch="B001")
        batch_dir = run_dir / "batches" / "B001-module-a"
        (batch_dir / "analysis.md").write_text("# 分析\n\nfixture 具备可定位的实现链。\n", encoding="utf-8")
        findings_path = batch_dir / "findings.jsonl"
        self._write_coding_playbook_findings(findings_path, include_context=True)
        finding = json.loads(findings_path.read_text(encoding="utf-8"))
        finding["coverage_claims"][0]["reason"] = "This claim is explained in English."
        findings_path.write_text(json.dumps(finding, ensure_ascii=False) + "\n", encoding="utf-8")

        result = run_code(self.config, "fixture_code_kb", stage="verify", resume=inventory["run_id"], batch="B001")

        self.assertEqual(result["status"], "failed")
        issues = result["deterministic"]["issues"]
        self.assertTrue(
            any(
                issue["code"] == "human_text_not_chinese"
                and issue.get("artifact") == "finding"
                and issue.get("field") == "coverage_claims[0].reason"
                for issue in issues
            )
        )

    def test_handoff_quality_blocks_english_human_markdown(self) -> None:
        inventory = run_code(self.config, "fixture_code_kb", stage="inventory", mode="from-zero")
        run_dir = self.knowledge / "state" / "kcode-runs" / inventory["run_id"]
        self._write_plan(run_dir)
        batch_dir = run_dir / "batches" / "B001-module-a"
        batch_dir.mkdir(parents=True)
        (batch_dir / "analysis.md").write_text("# 分析\n\nfixture 具备可定位的实现链。\n", encoding="utf-8")
        (batch_dir / "evidence.json").write_text(
            json.dumps({"schema_version": "kcode.evidence.v1", "files": [], "snippets": []}),
            encoding="utf-8",
        )
        findings = batch_dir / "verified-findings.jsonl"
        self._write_coding_playbook_findings(findings, include_context=True)
        payload = json.loads(findings.read_text(encoding="utf-8"))
        payload["current_state"] = "The route is implemented by the sample controller and service layer."
        findings.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")

        result = run_code(self.config, "fixture_code_kb", stage="handoff", resume=inventory["run_id"])

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"], "handoff_quality_failed")
        codes = {issue["code"] for issue in result["quality"]["issues"]}
        self.assertIn("handoff_human_text_not_chinese", codes)

    def test_handoff_blocks_unverified_planned_batches(self) -> None:
        inventory = run_code(self.config, "fixture_code_kb", stage="inventory", mode="from-zero")
        run_dir = self.knowledge / "state" / "kcode-runs" / inventory["run_id"]
        self._write_two_batch_plan(run_dir)
        batch_dir = run_dir / "batches" / "B001-module-a"
        batch_dir.mkdir(parents=True)
        (batch_dir / "analysis.md").write_text("# 分析\n\nfixture 具备可定位的实现链。\n", encoding="utf-8")
        (batch_dir / "evidence.json").write_text(
            json.dumps({"schema_version": "kcode.evidence.v1", "files": [], "snippets": []}),
            encoding="utf-8",
        )
        self._write_coding_playbook_findings(batch_dir / "verified-findings.jsonl", include_context=True)
        handoff_dir = run_dir / "handoff"
        handoff_dir.mkdir()
        stale_index = handoff_dir / "index.md"
        stale_index.write_text("# 旧 handoff\n", encoding="utf-8")

        result = run_code(self.config, "fixture_code_kb", stage="handoff", resume=inventory["run_id"])

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"], "handoff_unverified_batches")
        self.assertEqual(result["issue"], "planned_batch_completion_mismatch")
        self.assertEqual(result["unverified_batches"], [{"batch_id": "B002", "slug": "B002-module-b", "reason": "verified_findings_missing"}])
        self.assertFalse(stale_index.exists())

    def test_synthetic_e2e_reaches_handoff(self) -> None:
        inventory = run_code(self.config, "fixture_code_kb", stage="inventory", mode="from-zero")
        run_dir = self.knowledge / "state" / "kcode-runs" / inventory["run_id"]
        self._write_plan(run_dir)
        (run_dir / "verifier").mkdir(exist_ok=True)
        (run_dir / "verifier" / "plan-verification.json").write_text(
            json.dumps({"schema_version": "kcode.verification.plan.v1", "passed": True, "confidence": 0.9, "required_repairs": []}),
            encoding="utf-8",
        )
        self.assertEqual(run_code(self.config, "fixture_code_kb", stage="plan-verify", resume=inventory["run_id"])["status"], "completed")
        run_code(self.config, "fixture_code_kb", stage="evidence", resume=inventory["run_id"], batch="B001")
        analyze = run_code(self.config, "fixture_code_kb", stage="analyze", resume=inventory["run_id"], batch="B001")
        self.assertEqual(analyze["status"], "requires_llm")
        self.assertEqual(analyze["codex_next_step"]["after_writing_outputs_command"], f"python -m knowledge_kit code -k fixture_code_kb --stage verify --resume {inventory['run_id']} --batch B001")
        batch_dir = run_dir / "batches" / "B001-module-a"
        analyzer_input = json.loads((batch_dir / "analyzer-input.json").read_text(encoding="utf-8"))
        self.assertEqual(analyzer_input["coverage_contract"]["contract_id"], "kcode.agentic_coding.v1")
        self.assertEqual(analyzer_input["human_readable_output_language"], "zh-CN")
        self.assertEqual(analyze["language_policy"]["human_readable_fields"], "zh-CN")
        self.assertEqual(analyzer_input["language_policy"]["human_readable_fields"], "zh-CN")
        (batch_dir / "analysis.md").write_text("# 分析\n\nfixture 暴露了类似 controller 的入口。\n", encoding="utf-8")
        self._write_findings(batch_dir)
        verify = run_code(self.config, "fixture_code_kb", stage="verify", resume=inventory["run_id"], batch="B001")
        self.assertEqual(verify["status"], "requires_llm")
        self.assertFalse(verify["continuation_policy"]["requires_llm_is_final"])
        self.assertEqual(verify["codex_next_step"]["after_writing_outputs_command"], f"python -m knowledge_kit code -k fixture_code_kb --stage verify --resume {inventory['run_id']} --batch B001")
        semantic_input = json.loads((batch_dir / "semantic-verifier-input.json").read_text(encoding="utf-8"))
        self.assertEqual(semantic_input["coverage_contract"]["contract_id"], "kcode.agentic_coding.v1")
        self.assertEqual(semantic_input["human_readable_output_language"], "zh-CN")
        self.assertEqual(verify["language_policy"]["human_readable_fields"], "zh-CN")
        self.assertEqual(semantic_input["language_policy"]["human_readable_fields"], "zh-CN")
        (batch_dir / "semantic-verification.json").write_text(
            json.dumps(
                {
                    "schema_version": "kcode.verification.analysis.v1",
                    "passed": True,
                    "confidence": 0.9,
                    "required_repairs": [],
                }
            ),
            encoding="utf-8",
        )
        missing_ids = run_code(self.config, "fixture_code_kb", stage="verify", resume=inventory["run_id"], batch="B001")
        self.assertEqual(missing_ids["status"], "failed")
        self.assertEqual(missing_ids["error"], "verified_finding_ids_missing")
        (batch_dir / "semantic-verification.json").write_text(
            json.dumps(
                {
                    "schema_version": "kcode.verification.analysis.v1",
                    "passed": True,
                    "confidence": 0.9,
                    "required_repairs": [],
                    "verified_finding_ids": ["F-B001-001"],
                }
            ),
            encoding="utf-8",
        )
        completed_verify = run_code(self.config, "fixture_code_kb", stage="verify", resume=inventory["run_id"], batch="B001")
        self.assertEqual(completed_verify["status"], "completed")
        self.assertIn("next_command_if_all_batches_verified", completed_verify)

        result = run_code(self.config, "fixture_code_kb", stage="handoff", resume=inventory["run_id"])

        index = Path(result["handoff_index"])
        self.assertTrue(index.exists())
        manager_request = Path(result["knowledge_manager_request"])
        self.assertTrue(manager_request.exists())
        manifest = Path(result["handoff_manifest"])
        self.assertTrue(manifest.exists())
        quality = Path(result["handoff_quality"])
        self.assertTrue(quality.exists())
        self.assertTrue(result["quality"]["passed"])
        quality_data = json.loads(quality.read_text(encoding="utf-8"))
        self.assertTrue(quality_data["passed"])
        self.assertEqual(quality_data["schema_version"], "kcode.handoff_quality.v1")
        manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest_data["schema_version"], "kcode.handoff_manifest.v1")
        self.assertEqual(manifest_data["handoff_index"], "handoff/index.md")
        self.assertEqual(manifest_data["handoff_quality"], "handoff/handoff-quality.json")
        self.assertEqual(manifest_data["knowledge_manager_request"], "handoff/knowledge-manager-request.md")
        self.assertEqual(manifest_data["human_readable_output_language"], "zh-CN")
        self.assertEqual(manifest_data["language_policy"]["human_readable_fields"], "zh-CN")
        self.assertIn("contracts/k/update-workflow.md", manifest_data["contract_refs"])
        self.assertIn(".trae/agents/knowledge-manager.md", manifest_data["contract_refs"])
        self.assertIn("knowledge-manager 维护后的 wiki Markdown 正文", manifest_data["language_policy"]["applies_to"])
        self.assertTrue(manifest_data["request"]["each_code_feature_page_must_independently_satisfy_query_profiles"])
        self.assertIn("acceptance_commands", manifest_data)
        self.assertIn("required_fixed_headings", manifest_data)
        self.assertTrue(any("独立具备 Agentic Coding / PRD 设计所需章节" in item for item in manifest_data["acceptance_checks"]))
        self.assertEqual(manifest_data["shards"][0]["candidate_wiki_pages"], ["wiki/entities/code/features/module-a.md"])
        self.assertEqual(manifest_data["shards"][0]["source_summary_blueprint"], "handoff/source-summary-blueprints/handoff-shards-h001-b001-module-a.md")
        self.assertEqual(len(manifest_data["shards"][0]["page_blueprints"]), 1)
        source_blueprint = index.parent.parent / manifest_data["shards"][0]["source_summary_blueprint"]
        self.assertTrue(source_blueprint.exists())
        source_blueprint_text = source_blueprint.read_text(encoding="utf-8")
        self.assertIn("KCode 来源摘要蓝图", source_blueprint_text)
        self.assertIn("frontmatter sources", source_blueprint_text)
        blueprint = index.parent.parent / manifest_data["shards"][0]["page_blueprints"][0]
        self.assertTrue(blueprint.exists())
        blueprint_text = blueprint.read_text(encoding="utf-8")
        self.assertIn("这是交接蓝图，不是正式 wiki 正文", blueprint_text)
        self.assertIn("正式页 frontmatter `sources` 必须包含", blueprint_text)
        self.assertIn("wiki/sources/code/kcode-runs/", blueprint_text)
        for heading in ["## 现有实现", "## 代码定位", "## 实现链", "## 复用边界", "## 改动点", "## 测试/验证路径", "## PRD 设计影响"]:
            self.assertIn(heading, blueprint_text)
        index_text = index.read_text(encoding="utf-8")
        self.assertIn("KCode 交接索引", index_text)
        self.assertIn("通用编码指引", index_text)
        self.assertIn("page-blueprints", index_text)
        request_text = manager_request.read_text(encoding="utf-8")
        self.assertIn("Knowledge Manager 维护请求", request_text)
        self.assertIn("- manifest: handoff/manifest.json", request_text)
        self.assertIn("- human_readable_output_language: zh-CN", request_text)
        self.assertIn("正式 wiki Markdown 正文", request_text)
        self.assertIn("handoff/page-blueprints", request_text)
        self.assertIn("handoff/source-summary-blueprints", request_text)
        self.assertIn("frontmatter `sources` 必须包含对应 `source_summary_path`", request_text)
        self.assertIn("preflight QUERY", request_text)
        self.assertIn("## 现有实现", request_text)
        self.assertIn("固定章节必须有实质内容", request_text)
        self.assertIn("profile_no_evidence_pages", request_text)
        self.assertIn("profile_code_feature_evidence_missing", request_text)
        self.assertIn("profile_required_section_missing", request_text)
        self.assertIn("profile_query_topic_not_covered", request_text)
        self.assertIn("独立支撑 Agentic Coding / PRD 设计查询", request_text)
        self.assertIn("不能用其他页面内容抵消", request_text)
        self.assertIn("wiki/entities/code/features/**", request_text)
        self.assertIn("## 建议输出页面", request_text)
        self.assertIn("wiki/entities/code/features/module-a.md", request_text)
        self.assertIn("wiki/sources/code/kcode-runs/", request_text)
        self.assertIn("candidate_wiki_pages", result["shards"][0])
        shard = index.parent / result["shards"][0]["path"].split("/", 1)[1]
        shard_text = shard.read_text(encoding="utf-8")
        self.assertIn("## 已验证发现", shard_text)
        self.assertIn("- 当前状态:", shard_text)
        self.assertIn("#### 编码上下文", shard_text)
        self.assertIn("- 改动点:", shard_text)
        self.assertEqual(result["shards"][0]["findings"], 1)

    def test_handoff_limits_blueprints_to_primary_candidate_pages(self) -> None:
        inventory = run_code(self.config, "fixture_code_kb", stage="inventory", mode="from-zero")
        run_dir = self.knowledge / "state" / "kcode-runs" / inventory["run_id"]
        self._write_plan(run_dir)
        batch_dir = run_dir / "batches" / "B001-module-a"
        batch_dir.mkdir(parents=True)
        (batch_dir / "analysis.md").write_text("# 分析\n\nfixture 具备多个候选落页。\n", encoding="utf-8")
        (batch_dir / "evidence.json").write_text(
            json.dumps({"schema_version": "kcode.evidence.v1", "files": [], "snippets": []}),
            encoding="utf-8",
        )
        self._write_coding_playbook_findings(
            batch_dir / "verified-findings.jsonl",
            include_context=True,
            finding_id="F-B001-001",
            candidates=[
                "wiki/entities/code/features/module-a.md",
                "wiki/entities/code/features/module-b.md",
            ],
        )

        result = run_code(self.config, "fixture_code_kb", stage="handoff", resume=inventory["run_id"])

        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["quality"]["passed"])
        manifest = json.loads(Path(result["handoff_manifest"]).read_text(encoding="utf-8"))
        shard = manifest["shards"][0]
        self.assertEqual(
            shard["candidate_wiki_pages"],
            [
                "wiki/entities/code/features/module-a.md",
                "wiki/entities/code/features/module-b.md",
            ],
        )
        self.assertEqual(shard["primary_wiki_pages"], ["wiki/entities/code/features/module-a.md"])
        self.assertEqual(len(shard["page_blueprints"]), 1)
        self.assertEqual(result["quality"]["checked"]["blueprints"], 1)
        self.assertEqual(result["quality"]["checked"]["source_summary_blueprints"], 1)
        request_text = Path(result["knowledge_manager_request"]).read_text(encoding="utf-8")
        self.assertIn("备选候选页", request_text)
        self.assertIn("不得把同一条 finding 机械复制成多个重复正式页", request_text)
        stale = Path(result["handoff_manifest"]).parent / "page-blueprints" / "stale.md"
        stale.write_text("# 旧蓝图\n", encoding="utf-8")
        rerun = run_code(self.config, "fixture_code_kb", stage="handoff", resume=inventory["run_id"])
        self.assertEqual(rerun["status"], "completed")
        self.assertFalse(stale.exists())

    def test_handoff_code_map_blueprint_stays_navigation_only(self) -> None:
        inventory = run_code(self.config, "fixture_code_kb", stage="inventory", mode="from-zero")
        run_dir = self.knowledge / "state" / "kcode-runs" / inventory["run_id"]
        self._write_plan(run_dir)
        batch_dir = run_dir / "batches" / "B001-module-a"
        batch_dir.mkdir(parents=True)
        (batch_dir / "analysis.md").write_text("# 分析\n\nfixture 只提供仓库导航入口。\n", encoding="utf-8")
        (batch_dir / "evidence.json").write_text(
            json.dumps({"schema_version": "kcode.evidence.v1", "files": [], "snippets": []}),
            encoding="utf-8",
        )
        self._write_code_map_findings(batch_dir / "verified-findings.jsonl")

        result = run_code(self.config, "fixture_code_kb", stage="handoff", resume=inventory["run_id"])

        self.assertEqual(result["status"], "completed")
        manifest = json.loads(Path(result["handoff_manifest"]).read_text(encoding="utf-8"))
        shard = manifest["shards"][0]
        self.assertEqual(shard["candidate_wiki_pages"], ["wiki/entities/code/modules/module-a.md"])
        blueprint = Path(result["handoff_manifest"]).parent.parent / shard["page_blueprints"][0]
        blueprint_text = blueprint.read_text(encoding="utf-8")
        self.assertIn("本页是 `code_map` 导航页", blueprint_text)
        self.assertIn("不得把本页当作功能实现复用边界", blueprint_text)
        self.assertIn("正式页 frontmatter `sources` 必须包含", blueprint_text)
        self.assertNotIn("本页是 `feature_implementation` 现有实现页", blueprint_text)
        source_blueprint = Path(result["handoff_manifest"]).parent.parent / shard["source_summary_blueprint"]
        source_blueprint_text = source_blueprint.read_text(encoding="utf-8")
        self.assertIn("正式代码知识页 frontmatter sources", source_blueprint_text)
        self.assertNotIn("正式 feature 页 frontmatter sources", source_blueprint_text)

    def _write_legacy_plan(self, run_dir: Path) -> None:
        plan_dir = run_dir / "plan"
        plan_dir.mkdir(parents=True, exist_ok=True)
        (plan_dir / "analysis-plan.json").write_text(
            json.dumps(
                {
                    "schema_version": "kcode.analysis_plan.v1",
                    "batches": [
                        {
                            "batch_id": "B001",
                            "slug": "module-a",
                            "repo_ids": ["repo-a"],
                            "paths": ["repos/repo-a/src/main/java/example/SampleController.java"],
                            "entrypoints": ["repos/repo-a/src/main/java/example/SampleController.java:3"],
                            "expected_outputs": ["code_map_findings"],
                            "evidence_budget": 1,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (plan_dir / "analysis-plan.md").write_text("# 分析计划\n\n", encoding="utf-8")
        (plan_dir / "coverage-ledger.json").write_text(
            json.dumps({"schema_version": "kcode.coverage_ledger.v1", "items": []}),
            encoding="utf-8",
        )

    def _write_plan(self, run_dir: Path) -> None:
        plan_dir = run_dir / "plan"
        plan_dir.mkdir(parents=True, exist_ok=True)
        (plan_dir / "analysis-plan.json").write_text(
            json.dumps(
                {
                    "schema_version": "kcode.analysis_plan.v1",
                    "batches": [
                        {
                            "batch_id": "B001",
                            "slug": "module-a",
                            "repo_ids": ["repo-a"],
                            "knowledge_level": "code_map",
                            "paths": ["repos/repo-a/src/api/sampleApi.js"],
                            "entrypoints": ["repos/repo-a/src/api/sampleApi.js:1"],
                            "expected_outputs": ["code_map_findings"],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (plan_dir / "analysis-plan.md").write_text("# 分析计划\n\n", encoding="utf-8")
        (plan_dir / "coverage-ledger.json").write_text(
            json.dumps(
                {
                    "schema_version": "kcode.coverage_ledger.v1",
                    "items": [
                        {
                            "item_id": "entrypoint:repo-a:app",
                            "kind": "entrypoint",
                            "repo_id": "repo-a",
                            "path": "repos/repo-a/app.py",
                            "status": "planned",
                            "batch_id": "B001",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

    def _write_two_batch_plan(self, run_dir: Path) -> None:
        plan_dir = run_dir / "plan"
        plan_dir.mkdir(parents=True, exist_ok=True)
        (plan_dir / "analysis-plan.json").write_text(
            json.dumps(
                {
                    "schema_version": "kcode.analysis_plan.v1",
                    "batches": [
                        {
                            "batch_id": "B001",
                            "slug": "module-a",
                            "repo_ids": ["repo-a"],
                            "knowledge_level": "code_map",
                            "paths": ["repos/repo-a/src/api/sampleApi.js"],
                            "entrypoints": ["repos/repo-a/src/api/sampleApi.js:1"],
                            "expected_outputs": ["code_map_findings"],
                        },
                        {
                            "batch_id": "B002",
                            "slug": "module-b",
                            "repo_ids": ["repo-a"],
                            "knowledge_level": "code_map",
                            "paths": ["repos/repo-a/app.py"],
                            "entrypoints": ["repos/repo-a/app.py:1"],
                            "expected_outputs": ["code_map_findings"],
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        (plan_dir / "analysis-plan.md").write_text("# 分析计划\n\n", encoding="utf-8")
        (plan_dir / "coverage-ledger.json").write_text(
            json.dumps({"schema_version": "kcode.coverage_ledger.v1", "items": []}),
            encoding="utf-8",
        )

    def _write_vue_feature_plan(self, run_dir: Path) -> None:
        plan_dir = run_dir / "plan"
        plan_dir.mkdir(parents=True, exist_ok=True)
        (plan_dir / "analysis-plan.json").write_text(
            json.dumps(
                {
                    "schema_version": "kcode.analysis_plan.v1",
                    "batches": [
                        {
                            "batch_id": "B010",
                            "slug": "vue-feature",
                            "repo_ids": ["repo-a"],
                            "knowledge_level": "feature_implementation",
                            "paths": ["repos/repo-a/src/views/Feature.vue"],
                            "entrypoints": ["repos/repo-a/src/views/Feature.vue:1"],
                            "expected_outputs": ["feature_implementation_findings"],
                            "required_layers": [
                                "user_surface_or_calling_entrypoint",
                                "frontend_route_or_page_when_present",
                                "api_client_or_external_interface_when_present",
                                "backend_controller_or_message_handler_when_present",
                                "service_or_domain_logic",
                                "repository_mapper_dao_or_external_dependency",
                                "domain_model_dto_schema_or_persistent_fields",
                                "permission_config_feature_flag_or_runtime_wiring_when_present",
                                "tests_fixtures_or_manual_verification_path_when_present",
                            ],
                            "blocking_gap_rules": ["missing_required_layer_for_claimed_feature_implementation"],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (plan_dir / "analysis-plan.md").write_text("# 分析计划\n\n从 Vue 页面入口闭合前后端实现链。\n", encoding="utf-8")
        (plan_dir / "coverage-ledger.json").write_text(
            json.dumps({"schema_version": "kcode.coverage_ledger.v1", "items": []}),
            encoding="utf-8",
        )

    def _write_invalid_coding_plan(self, run_dir: Path) -> None:
        plan_dir = run_dir / "plan"
        plan_dir.mkdir(parents=True, exist_ok=True)
        (plan_dir / "analysis-plan.json").write_text(
            json.dumps(
                {
                    "schema_version": "kcode.analysis_plan.v1",
                    "batches": [
                        {
                            "batch_id": "B001",
                            "slug": "module-a",
                            "repo_ids": ["repo-a"],
                            "knowledge_level": "coding_playbook",
                            "paths": ["repos/repo-a/src/api/sampleApi.js"],
                            "entrypoints": ["repos/repo-a/src/api/sampleApi.js:1"],
                            "expected_outputs": ["coding_playbook"],
                            "required_layers": ["where_to_change"],
                            "blocking_gap_rules": ["missing_code_path_for_claimed_change_point"],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (plan_dir / "analysis-plan.md").write_text("# 分析计划\n\n", encoding="utf-8")
        (plan_dir / "coverage-ledger.json").write_text(
            json.dumps({"schema_version": "kcode.coverage_ledger.v1", "items": []}),
            encoding="utf-8",
        )

    def _write_findings(self, batch_dir: Path) -> None:
        self._write_coding_playbook_findings(batch_dir / "findings.jsonl", include_context=True, finding_id="F-B001-001")

    def _write_code_map_findings(self, findings: Path) -> None:
        findings.write_text(
            json.dumps(
                {
                    "schema_version": "kcode.finding.v1",
                    "finding_id": "F-B001-001",
                    "batch_id": "B001",
                    "kind": "code_map",
                    "title": "模块导航",
                    "current_state": "fixture 只证明仓库入口和继续探索路径。",
                    "knowledge_level": "code_map",
                    "knowledge_object_candidates": ["wiki/entities/code/modules/module-a.md"],
                    "evidence_refs": ["repos/repo-a/app.py:1-5"],
                    "coverage_claims": [
                        {"item": "repository purpose", "status": "covered", "evidence_refs": ["repos/repo-a/app.py:1-5"]},
                        {"item": "module boundaries", "status": "covered", "evidence_refs": ["repos/repo-a/app.py:1-5"]},
                        {"item": "entrypoints", "status": "covered", "evidence_refs": ["repos/repo-a/app.py:1-5"]},
                        {"item": "navigation hints", "status": "covered", "evidence_refs": ["repos/repo-a/app.py:1-5"]},
                    ],
                    "confidence": 0.8,
                    "blocking_gaps": [],
                    "non_blocking_gaps": [],
                    "exploration_hints": [],
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

    def _write_feature_findings(self, findings: Path) -> None:
        refs = ["repos/repo-a/src/main/java/example/SampleController.java:1-14"]
        claims = [
            "user_surface_or_calling_entrypoint",
            "frontend_route_or_page_when_present",
            "api_client_or_external_interface_when_present",
            "backend_controller_or_message_handler_when_present",
            "service_or_domain_logic",
            "repository_mapper_dao_or_external_dependency",
            "domain_model_dto_schema_or_persistent_fields",
            "permission_config_feature_flag_or_runtime_wiring_when_present",
            "tests_fixtures_or_manual_verification_path_when_present",
        ]
        findings.write_text(
            json.dumps(
                {
                    "finding_id": "F-B001-002",
                    "batch_id": "B001",
                    "kind": "capability",
                    "title": "通用功能实现",
                    "current_state": "fixture 具备用于确定性闭合验证的结构。",
                    "knowledge_level": "feature_implementation",
                    "knowledge_object_candidates": ["wiki/entities/code/features/module-a.md"],
                    "evidence_refs": refs,
                    "coverage_claims": [
                        {"item": item, "status": "covered", "evidence_refs": refs}
                        for item in claims
                    ],
                    "confidence": 0.8,
                    "blocking_gaps": [],
                    "non_blocking_gaps": [],
                    "exploration_hints": [],
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

    def _write_coding_playbook_findings(
        self,
        findings: Path,
        *,
        include_context: bool,
        finding_id: str = "F-B001-003",
        candidates: list[str] | None = None,
    ) -> None:
        refs = ["repos/repo-a/src/main/java/example/SampleController.java:1-14"]
        claims = [
            "where_to_change",
            "what_to_reuse",
            "what_not_to_change_without_extra_exploration",
            "data_contract_constraints",
            "runtime_or_deployment_constraints",
            "test_or_verification_entrypoints",
        ]
        finding = {
            "finding_id": finding_id,
            "batch_id": "B001",
            "kind": "capability",
            "title": "通用编码指引",
            "current_state": "fixture 提供了可定位的改动入口和验证引用。",
            "knowledge_level": "coding_playbook",
            "knowledge_object_candidates": candidates or ["wiki/entities/code/features/module-a.md"],
            "evidence_refs": refs,
            "coverage_claims": [
                {"item": item, "status": "covered", "evidence_refs": refs}
                for item in claims
            ],
            "confidence": 0.8,
            "design_implications": [],
            "blocking_gaps": [],
            "non_blocking_gaps": [],
            "exploration_hints": [],
        }
        if include_context:
            item = {"summary": "使用 fixture 中已收集的入口证据。", "evidence_refs": refs}
            finding["coding_context"] = {
                "change_points": [item],
                "reuse_points": [item],
                "do_not_change_without_extra_exploration": [item],
                "data_contracts": [item],
                "runtime_constraints": [item],
                "verification_entrypoints": [item],
            }
        findings.write_text(json.dumps(finding, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PRD_KIT_ROOT = REPO_ROOT / ".trae" / "skills" / "yxm-prd-kit"
RUNTIME = PRD_KIT_ROOT / "executors" / "prd_kit_runtime.py"
WF = PRD_KIT_ROOT / "references" / "prd-kit.wf"


def run_runtime(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RUNTIME), *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


class PrdKitMigrationTests(unittest.TestCase):
    def test_prd_kit_is_project_local_and_inspectable(self) -> None:
        proc = run_runtime("inspect-wf", "--wf", str(WF))
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        result = json.loads(proc.stdout)

        self.assertEqual(result["stage_count"], 12)
        self.assertIn("W10_plan_ceo_review", result["stage_order"])
        self.assertIn("W11_engineering_prd_projection", result["stage_order"])
        self.assertEqual(
            result["engineering_prd_template"],
            ".trae/skills/yxm-prd-kit/references/engineering-prd-template.md",
        )
        self.assertEqual(
            result["adapter_sources"],
            ["karpathy-wiki", "yxm-first-principles-decomposer", "yxm-grill-with-docs", "yxm-plan-ceo-review"],
        )
        self.assertNotIn("dispatch_receipt", result["adapter_review_ledger_fields"])

    def test_quota_counting_does_not_require_host_turn_receipt(self) -> None:
        process_markdown = "\n\n".join(
            [
                "# 示例能力过程文件",
                "\n".join(
                    [
                        "## Workflow State",
                        "| current_stage | artifact_stage | gate | next_stage | stage_exit_criteria_status | updated_at |",
                        "| --- | --- | --- | --- | --- | --- |",
                        "| W1_value_alignment | process_file | blocked | W2_scenario_roles | test | 2026-06-12 00:00:00 |",
                    ]
                ),
                "\n".join(
                    [
                        "## PRD Kit Configuration",
                        "| key | value |",
                        "| --- | --- |",
                        "| challenge_quota.target_total | 0 |",
                        "| challenge_quota.quality_score_min | 0 |",
                        "| concept_alignment.enforcement | migration_warning |",
                    ]
                ),
                "\n".join(
                    [
                        "## Effective Challenge Ledger",
                        "| challenge_id | stage | perspective | category | question | why_matters | affected_section | answer_summary | answer_status | acceptance_type | user_acceptance_ref | invalidation_reason | quality_score | backfill_location | asked_at | answered_at |",
                        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
                        "| EC-001 | W1_value_alignment | 产品经理 | 价值边界 | 是否值得做？ | 避免无价值建设 | 价值主张 | 已确认 | confirmed | answer | - | - | 5 | 价值主张 | 2026-06-12 | 2026-06-12 |",
                    ]
                ),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            process_path = Path(tmp) / "sample-process.md"
            process_path.write_text(process_markdown, encoding="utf-8")

            proc = run_runtime("check-status", "--wf", str(WF), "--process-file", str(process_path))
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            result = json.loads(proc.stdout)

        self.assertEqual(result["challenge_quota"]["total_counted"], 1)
        self.assertEqual(result["challenge_quota"]["stage_counts"]["W1_value_alignment"], 1)
        self.assertNotIn("invalid user_acceptance_ref", proc.stdout)

    def test_engineering_prd_requires_w10_passed_and_project_template(self) -> None:
        inspect = json.loads(run_runtime("inspect-wf", "--wf", str(WF)).stdout)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            process_path = root / "示例能力-过程文件.md"
            formal_path = root / "示例能力-PRD.md"
            engineering_path = root / "示例能力-研发版PRD-20260612-120000.md"

            process_path.write_text(
                "\n\n".join(
                    [
                        "# 示例能力过程文件",
                        "\n".join(
                            [
                                "## Workflow State",
                                "| current_stage | artifact_stage | gate | next_stage | stage_exit_criteria_status | updated_at |",
                                "| --- | --- | --- | --- | --- | --- |",
                                "| W11_engineering_prd_projection | engineering_prd | pass |  | final_release_status=passed | 2026-06-12 12:00:00 |",
                            ]
                        ),
                        "\n".join(
                            [
                                "## Stage Ledger",
                                "| stage | entered_at | exit_status | exit_evidence | next_stage |",
                                "| --- | --- | --- | --- | --- |",
                                "| W10_plan_ceo_review | 2026-06-12 11:00:00 | passed | final_release_status=passed | W11_engineering_prd_projection |",
                            ]
                        ),
                    ]
                ),
                encoding="utf-8",
            )
            formal_path.write_text("# 示例能力 PRD\n\n## 文档信息\n", encoding="utf-8")
            engineering_path.write_text(
                "# 示例能力 研发版 PRD\n\n"
                + "\n\n".join(f"## {section}\n已确认。" for section in inspect["required_engineering_prd_sections"]),
                encoding="utf-8",
            )

            proc = run_runtime(
                "check-engineering-prd",
                "--wf",
                str(WF),
                "--engineering-prd",
                str(engineering_path),
                "--formal-prd",
                str(formal_path),
                "--process-file",
                str(process_path),
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            result = json.loads(proc.stdout)

        self.assertEqual(
            result["engineering_prd_template"],
            ".trae/skills/yxm-prd-kit/references/engineering-prd-template.md",
        )
        self.assertTrue(result["filename_valid"])

    def test_commands_and_docs_do_not_reference_source_control_plane(self) -> None:
        paths = [
            REPO_ROOT / "AGENTS.md",
            PRD_KIT_ROOT / "SKILL.md",
            PRD_KIT_ROOT / "references" / "prd-kit.wf",
            REPO_ROOT / ".trae" / "skills" / "yxm-plan-ceo-review" / "SKILL.md",
            REPO_ROOT / ".trae" / "agents" / "conclusion-verifier.md",
            REPO_ROOT / ".trae" / "agents" / "context" / "verifier-style-profiles.md",
            REPO_ROOT / ".trae" / "workflows" / "conclusion-verification-workflow.yaml",
        ]
        combined = "\n".join(path.read_text(encoding="utf-8") for path in paths)

        self.assertIn(".trae", combined)
        self.assertNotIn("/c:", combined)
        self.assertNotIn("host-turn", combined)
        self.assertNotIn("user_turn_receipts", combined)
        self.assertNotIn("multi_turn_sticky", combined)
        self.assertNotIn("会话绑定", combined)

    def test_conclusion_verifier_config_is_project_local(self) -> None:
        agent = REPO_ROOT / ".trae" / "agents" / "conclusion-verifier.md"
        profiles = REPO_ROOT / ".trae" / "agents" / "context" / "verifier-style-profiles.md"
        workflow = REPO_ROOT / ".trae" / "workflows" / "conclusion-verification-workflow.yaml"

        self.assertTrue(agent.exists())
        self.assertTrue(profiles.exists())
        self.assertTrue(workflow.exists())

        agent_text = agent.read_text(encoding="utf-8")
        profiles_text = profiles.read_text(encoding="utf-8")
        workflow_text = workflow.read_text(encoding="utf-8")

        self.assertIn('name: conclusion-verifier', agent_text)
        self.assertIn(".trae/agents/context/verifier-style-profiles.md", agent_text)
        self.assertIn("plan_ceo_review", profiles_text)
        self.assertIn("design_plan", profiles_text)
        self.assertIn("conclusion-verifier", workflow_text)
        self.assertIn(".trae/agents/context/verifier-style-profiles.md", workflow_text)


if __name__ == "__main__":
    unittest.main()

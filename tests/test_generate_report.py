import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cache import JsonCache  # noqa: E402
from graph.nodes import generate_report  # noqa: E402
from graph.reporting import workflow as report_workflow  # noqa: E402
from graph.reporting.llm_cache import LlmOutputCache  # noqa: E402
from graph.reporting.prompts import CATEGORY_GUIDE  # noqa: E402
from graph.state import EnrichedRepo  # noqa: E402


def _repo(name: str, readme: str = "") -> EnrichedRepo:
    return {
        "owner": "acme",
        "repo": name,
        "name": f"acme/{name}",
        "url": f"https://github.com/acme/{name}",
        "description": f"English description for {name}.",
        "language": "Python",
        "total_stars": "100",
        "forks": "10",
        "period_stars": "10 stars this week",
        "built_by": [],
        "topics": ["ai", "developer-tools"],
        "readme": readme,
        "relevant_images": [],
    }


class _FakeModel:
    def __init__(self) -> None:
        self.call_count = 0
        self.analyzed_repos: list[str] = []

    def invoke(self, messages: list[dict]) -> SimpleNamespace:
        self.call_count += 1
        system = messages[0]["content"]
        content = messages[1]["content"]
        payload = json.loads(content.split("\n", 1)[1] if "\n" in content else content)
        if "项目分析编辑" in system:
            self.analyzed_repos.extend(item["repo"] for item in payload)
            items = [
                {
                    "repo": item["repo"],
                    "part_index": item["part_index"],
                    "summary": f"{item['repo']} 的中文压缩概述。",
                    "plain_explanation": f"{item['repo']} 的大白话说明。",
                    "tags": [],
                }
                for item in payload
            ]
            return SimpleNamespace(
                content=json.dumps({"items": items}, ensure_ascii=False)
            )

        if "周刊列表卡片" in system:
            return SimpleNamespace(
                content=json.dumps(
                    {
                        "overview": (
                            f"本期周刊共收录 {payload['project_count']} 个项目。"
                            "开发工具领域主要围绕代码审查和工作流自动化展开。"
                        )
                    },
                    ensure_ascii=False,
                )
            )

        items = [
            {
                "repo": item["repo"],
                "summary": item["summary_material"],
                "plain_explanation": item["plain_explanation_material"],
                "tags": item["tags"],
            }
            for item in payload
        ]
        return SimpleNamespace(
            content=json.dumps(
                {"categories": [{"name": "开发工具与平台", "items": items}]},
                ensure_ascii=False,
            )
        )


class GenerateReportTests(unittest.TestCase):
    def test_smart_batches_respect_limit_and_split_large_repo(self) -> None:
        readme = (
            "# 第一部分\n\n"
            + "a" * 9_000
            + "\n\n# 第二部分\n\n"
            + "b" * 9_000
            + "\n\n# 第三部分\n\n"
            + "c" * 9_000
        )
        batches = generate_report._build_report_batches(
            [_repo("large", readme)],
            limit=10_000,
        )

        self.assertGreater(len(batches), 1)
        self.assertTrue(all(batch["char_count"] <= 10_000 for batch in batches))
        parts = [item for batch in batches for item in batch["items"]]
        self.assertEqual([part["part_index"] for part in parts], [1, 2, 3])
        self.assertTrue(all(part["part_total"] == 3 for part in parts))

    def test_empty_tags_fall_back_to_topics(self) -> None:
        repos = [_repo("tool")]
        raw = {
            "categories": [
                {
                    "name": "开发工具与平台",
                    "items": [
                        {
                            "repo": "acme/tool",
                            "summary": "中文摘要。",
                            "plain_explanation": "大白话说明。",
                            "tags": [],
                        }
                    ],
                }
            ]
        }

        report = generate_report._normalize_report_json(raw, repos)
        item = report["categories"][0]["items"][0]
        self.assertEqual(item["tags"], ["ai", "developer-tools"])

    def test_category_guide_allows_new_categories(self) -> None:
        self.assertIn("不是固定枚举", CATEGORY_GUIDE)
        self.assertIn("自行创建", CATEGORY_GUIDE)

        report = generate_report._normalize_report_json(
            {
                "categories": [
                    {
                        "name": "机器人 / 硬件",
                        "items": [
                            {
                                "repo": "acme/robot",
                                "summary": "机器人开发套件。",
                                "plain_explanation": "用于控制真实硬件。",
                                "tags": ["robotics"],
                            }
                        ],
                    }
                ]
            },
            [_repo("robot")],
        )

        self.assertEqual(report["categories"][0]["name"], "机器人 / 硬件")

    def test_markdown_hides_english_description(self) -> None:
        repos = [_repo("tool")]
        repos[0]["relevant_images"] = ["assets/tool.png"]
        raw = {
            "categories": [
                {
                    "name": "开发工具与平台",
                    "items": [
                        {
                            "repo": "acme/tool",
                            "summary": "这是中文压缩概述。",
                            "plain_explanation": "它帮助开发者更快完成工作。",
                            "tags": ["developer-tools"],
                        }
                    ],
                }
            ]
        }

        report = generate_report._normalize_report_json(raw, repos)
        report["overview"] = (
            "本期周刊共收录 1 个项目。开发工具领域主要关注研发流程自动化。"
        )
        markdown = generate_report._render_markdown(report)
        self.assertEqual(
            report["categories"][0]["items"][0]["description"],
            "English description for tool.",
        )
        self.assertNotIn("English description", markdown)
        self.assertIn("这是中文压缩概述。", markdown)
        self.assertIn("**简单说：** 它帮助开发者更快完成工作。", markdown)
        self.assertIn("> 本期周刊共收录 1 个项目。", markdown)
        self.assertIn("- ⭐ 累计 Star：100", markdown)
        self.assertIn("- 🔥 本周新增 Star：10", markdown)
        self.assertNotIn("stars this week", markdown)
        self.assertIn("![acme/tool 项目截图](assets/tool.png)", markdown)

    def test_top_categories_are_sorted_by_project_count(self) -> None:
        report = {
            "categories": [
                {"name": "第一类", "items": [{"repo": "a/1"}]},
                {
                    "name": "第二类",
                    "items": [{"repo": "b/1"}, {"repo": "b/2"}, {"repo": "b/3"}],
                },
                {
                    "name": "第三类",
                    "items": [{"repo": "c/1"}, {"repo": "c/2"}],
                },
                {
                    "name": "第四类",
                    "items": [
                        {"repo": "d/1"},
                        {"repo": "d/2"},
                        {"repo": "d/3"},
                        {"repo": "d/4"},
                    ],
                },
            ]
        }

        top = generate_report._top_categories(report)
        self.assertEqual(
            [category["name"] for category in top],
            ["第四类", "第二类", "第三类"],
        )
        self.assertEqual(
            [category["project_count"] for category in top],
            [4, 3, 2],
        )

    def test_overview_is_normalized_and_limited_to_200_characters(self) -> None:
        overview = generate_report._normalize_overview(
            "本期共收录 99 个项目。" + "这是客观的分类概述；" * 30,
            project_count=23,
        )

        self.assertTrue(overview.startswith("本期周刊共收录 23 个项目。"))
        self.assertLessEqual(len(overview), 200)
        self.assertNotIn("99 个项目", overview)

    def test_report_workflow_fans_out_and_collects_all_repos(self) -> None:
        repos = [
            _repo("one", "a" * 260),
            _repo("two", "b" * 260),
            _repo("three", "c" * 260),
        ]
        model = _FakeModel()

        with TemporaryDirectory() as temp_dir:
            llm_cache = LlmOutputCache(
                JsonCache("llm_outputs", directory=Path(temp_dir))
            )
            workflow = generate_report.build_report_workflow(llm_cache)
            with (
                patch.object(report_workflow, "get_llm", return_value=model),
                patch.dict(
                    os.environ,
                    {"REPORT_BATCH_CHARS": "500", "REPORT_CONCURRENCY": "5"},
                ),
            ):
                input_state: report_workflow.ReportState = {"enriched": repos}
                result = workflow.invoke(
                    input_state,
                    {"max_concurrency": generate_report.report_concurrency()},
                )
                first_run_calls = model.call_count
                cached_result = workflow.invoke(
                    input_state,
                    {"max_concurrency": generate_report.report_concurrency()},
                )

        items = [
            item
            for category in result["report_json"]["categories"]
            for item in category["items"]
        ]
        self.assertEqual(result["report_json"]["version"], 2)
        self.assertTrue(
            result["report_json"]["overview"].startswith("本期周刊共收录 3 个项目。")
        )
        self.assertEqual(
            [item["repo"] for item in items],
            [f"acme/{r.get('repo', '')}" for r in repos],
        )
        self.assertTrue(all(item["plain_explanation"] for item in items))
        self.assertNotIn("English description", result["report_md"])
        self.assertGreater(first_run_calls, 0)
        self.assertEqual(model.call_count, first_run_calls)
        self.assertEqual(cached_result["report_json"], result["report_json"])

    def test_report_workflow_reuses_projects_when_batch_composition_changes(
        self,
    ) -> None:
        model = _FakeModel()
        first_repos = [_repo("one"), _repo("two")]
        second_repos = [_repo("two"), _repo("three")]

        with TemporaryDirectory() as temp_dir:
            llm_cache = LlmOutputCache(
                JsonCache("llm_outputs", directory=Path(temp_dir))
            )
            workflow = generate_report.build_report_workflow(llm_cache)
            with (
                patch.object(report_workflow, "get_llm", return_value=model),
                patch.dict(
                    os.environ,
                    {"REPORT_BATCH_CHARS": "20000", "REPORT_CONCURRENCY": "5"},
                ),
            ):
                workflow.invoke(
                    {"enriched": first_repos},
                    {"max_concurrency": generate_report.report_concurrency()},
                )
                workflow.invoke(
                    {"enriched": second_repos},
                    {"max_concurrency": generate_report.report_concurrency()},
                )

        self.assertEqual(
            model.analyzed_repos,
            ["acme/one", "acme/two", "acme/three"],
        )


if __name__ == "__main__":
    unittest.main()

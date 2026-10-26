"""在临时 Git 仓库验证失败运行只提交缓存，成功运行一并提交报告。"""

import os
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

ROOT = Path(__file__).resolve().parents[1]


class WeeklyWorkflowTests(unittest.TestCase):
    def test_commit_step_only_publishes_reports_after_success(self) -> None:
        workflow = yaml.safe_load(
            (ROOT / ".github/workflows/weekly.yml").read_text(encoding="utf-8")
        )
        commit_step = next(
            step
            for step in workflow["jobs"]["generate"]["steps"]
            if step["name"] == "Commit report and cache"
        )
        for outcome in ("success", "failure"):
            with self.subTest(outcome=outcome), TemporaryDirectory() as temp_dir:
                directory = Path(temp_dir)
                checkout = directory / "checkout"
                checkout.mkdir()
                env = {
                    **os.environ,
                    "GIT_CONFIG_GLOBAL": os.devnull,
                    "GIT_CONFIG_NOSYSTEM": "1",
                    "HUSKY": "0",
                    "REPORT_OUTCOME": outcome,
                }

                def git(*args: str) -> str:
                    return subprocess.run(
                        ["git", *args],
                        cwd=checkout,
                        env=env,
                        check=True,
                        capture_output=True,
                        text=True,
                    ).stdout.strip()

                git("init", "--bare", str(directory / "origin.git"))
                git("init", "-b", "master")
                git("config", "user.name", "test")
                git("config", "user.email", "test@example.test")
                git("config", "commit.gpgsign", "false")
                git("remote", "add", "origin", str(directory / "origin.git"))
                for name in (
                    "README.md",
                    "feed.xml",
                    "reports/report.md",
                    "cache/llm_outputs.json",
                ):
                    path = checkout / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("old\n", encoding="utf-8")
                git("add", ".")
                git("commit", "-m", "initial")
                git("push", "--set-upstream", "origin", "master")

                for name in (
                    "README.md",
                    "feed.xml",
                    "reports/report.md",
                    "cache/llm_outputs.json",
                ):
                    (checkout / name).write_text("new\n", encoding="utf-8")
                subprocess.run(
                    ["bash", "-e", "-c", commit_step["run"]],
                    cwd=checkout,
                    env=env,
                    check=True,
                    capture_output=True,
                    text=True,
                )

                committed = set(
                    git(
                        "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"
                    ).splitlines()
                )
                expected = {"cache/llm_outputs.json"}
                if outcome == "success":
                    expected.update({"README.md", "feed.xml", "reports/report.md"})
                self.assertEqual(committed, expected)
                self.assertEqual(
                    git("rev-parse", "HEAD"),
                    git("rev-parse", "origin/master"),
                )


if __name__ == "__main__":
    unittest.main()

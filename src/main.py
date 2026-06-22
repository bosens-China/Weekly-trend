import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]

# 本地运行时自动读取项目根目录的 .env（CI 用 secrets/vars，没有 .env 也不报错）
load_dotenv(ROOT / ".env")

from graph.build import build_graph  # noqa: E402  （需在 load_dotenv 之后导入）
from graph.nodes.output_report import current_week_has_report  # noqa: E402
from log import log  # noqa: E402


def _refresh_index() -> None:
    """生成后刷新 README 往期列表与 feed.xml（失败不影响周刊本身）。"""
    try:
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "build_index.py")], check=True
        )
    except Exception as e:  # noqa: BLE001
        log("main", f"刷新 README/RSS 失败：{e}", "warn")


def main():
    """
    入口：跑完整的「抓取 -> 补全 -> 图片过滤 -> 生成 -> 写盘」流程。
    供本地与 CI 调用。
    """
    # 未配置 LLM 凭证则直接跳过，不执行后续任何步骤
    if not os.getenv("OPENAI_API_KEY"):
        log(
            "main",
            "未检测到 OPENAI_API_KEY，跳过本次周刊生成。"
            "（本地请在 .env 配置，CI 请在 Secrets 配置）",
            "warn",
        )
        return None

    # push 触发：本 ISO 周已生成过就跳过，只在「本周缺报告」时补生成。
    # （定时 schedule / 手动 workflow_dispatch / 本地运行不受此限制，总是生成）
    if os.getenv("GITHUB_EVENT_NAME") == "push" and current_week_has_report():
        log("main", "本周报告已存在，push 触发不重复生成，跳过。", "warn")
        return None

    log("main", "开始生成本周周刊…")
    graph = build_graph()
    result = graph.invoke({})
    path = result.get("output_path")
    if path:
        log("main", f"周刊已生成：{path}（第 {result.get('issue_number')} 期）", "ok")
        _refresh_index()
    else:
        log("main", "未生成周刊，请检查日志。", "warn")
    return result


if __name__ == "__main__":
    main()

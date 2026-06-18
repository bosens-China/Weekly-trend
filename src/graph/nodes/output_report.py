from datetime import datetime, timezone
from pathlib import Path
from typing import Tuple

from graph.state import WeeklyState

# reports 目录：相对项目根（src 的上一级）
REPORTS_DIR = Path(__file__).resolve().parents[3] / "reports"


def _next_issue_number() -> int:
    """期数 = reports/ 下已有的 .md 周刊数量 + 1（不含 assets 子目录）。"""
    if not REPORTS_DIR.exists():
        return 1
    return len(list(REPORTS_DIR.glob("*.md"))) + 1


def compute_issue_and_date() -> Tuple[int, str]:
    """统一计算「第几期 + 日期串」，截图节点与输出节点共用。"""
    now = datetime.now(timezone.utc).astimezone()
    return _next_issue_number(), now.strftime("%Y_%m_%d")


def output_report_node(state: WeeklyState) -> dict:
    """
    LangGraph 节点：把周刊正文写入 reports/yyyy_mm_dd.md，
    带上「第 N 期 + 日期」头部。期数/日期优先复用 state 中已确定的值。
    """
    body = state.get("report_md", "")
    issue = state.get("issue_number")
    date_str = state.get("date_str")
    if issue is None or not date_str:
        i, d = compute_issue_and_date()
        issue = issue or i
        date_str = date_str or d

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS_DIR / f"{date_str}.md"

    header = (
        f"# GitHub Trending 周刊 · 第 {issue} 期\n\n"
        f"> 📅 {date_str.replace('_', '-')} ｜ 数据来源：GitHub Trending（本周）\n\n"
        "---\n\n"
    )
    out_path.write_text(header + body + "\n", encoding="utf-8")

    print(f"[output_report] 已写入 {out_path}（第 {issue} 期）")
    return {
        "issue_number": issue,
        "date_str": date_str,
        "output_path": str(out_path),
    }

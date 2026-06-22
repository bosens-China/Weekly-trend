import json
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Tuple
from zoneinfo import ZoneInfo

from graph.state import WeeklyState
from log import log

# 全项目以北京时间为准：定时任务、日期目录、期数都按这个时区算，
# 避免 CI（runner 默认 UTC）把「北京周一」算成「UTC 周日」。
BEIJING = ZoneInfo("Asia/Shanghai")

# reports 目录：相对项目根（src 的上一级）
REPORTS_DIR = Path(__file__).resolve().parents[3] / "reports"

# 每期一个以日期命名的文件夹：reports/2026_06_21/{README.md, assets/}
_DATE_RE = re.compile(r"^\d{4}_\d{2}_\d{2}$")
REPORT_MD_NAME = "README.md"  # 用 README.md，GitHub 浏览该文件夹时会自动渲染
INDEX_JSON = REPORTS_DIR / "index.json"  # 期数台账（源头）+ 往期清单


def _load_manifest() -> List[dict]:
    try:
        data = json.loads(INDEX_JSON.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _next_issue_number() -> int:
    """
    期数以 reports/index.json 台账为准：next = 已有最大期数 + 1（删文件夹也不会重号）。
    台账缺失时（首次/迁移）回退到「数日期文件夹 + 1」。
    """
    manifest = _load_manifest()
    if manifest:
        return max((int(e.get("issue", 0)) for e in manifest), default=0) + 1
    if not REPORTS_DIR.exists():
        return 1
    n = sum(1 for p in REPORTS_DIR.iterdir() if p.is_dir() and _DATE_RE.match(p.name))
    return n + 1


def _update_manifest(issue: int, date_str: str, repos: int) -> None:
    """把本期写入台账：同期号/同日期视为重跑，覆盖旧条目；按期号排序。"""
    manifest = [
        e
        for e in _load_manifest()
        if e.get("issue") != issue and e.get("date") != date_str
    ]
    manifest.append(
        {
            "issue": issue,
            "date": date_str,
            "dir": date_str,
            "repos": repos,
            "generated_at": datetime.now(BEIJING).isoformat(timespec="seconds"),
        }
    )
    manifest.sort(key=lambda e: int(e.get("issue", 0)))
    INDEX_JSON.parent.mkdir(parents=True, exist_ok=True)
    INDEX_JSON.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _week_monday_str() -> str:
    """本期日期 = 北京时间「本周周一」的 yyyy_mm_dd。

    不论周几跑（定时周一、或周中手动 push 补生成），同一 ISO 周都落在同一个
    周一日期目录，保证「一周一期、日期恒为周一」。weekday(): 周一=0。
    """
    today = datetime.now(BEIJING).date()
    monday = today - timedelta(days=today.weekday())
    return monday.strftime("%Y_%m_%d")


def compute_issue_and_date() -> Tuple[int, str]:
    """统一计算「第几期 + 日期串」，图片节点与输出节点共用。"""
    date_str = _week_monday_str()
    # 本周重跑：沿用台账里已有的期号，避免期号虚增
    for e in _load_manifest():
        if e.get("date") == date_str and e.get("issue"):
            return int(e["issue"]), date_str
    return _next_issue_number(), date_str


def _iso_week_key(date_str: str):
    """把 yyyy_mm_dd 日期串转成 (ISO 年, ISO 周) 元组；解析失败返回 None。"""
    try:
        d = datetime.strptime(date_str, "%Y_%m_%d").date()
    except (TypeError, ValueError):
        return None
    iso = d.isocalendar()
    return (iso[0], iso[1])


def current_week_has_report() -> bool:
    """
    台账里是否已存在「本 ISO 周（周一为起点）」的报告。
    用于 push 触发时判断：本周已生成过就跳过，没有才补生成。
    """
    today = datetime.now(BEIJING).date()
    cur = (today.isocalendar()[0], today.isocalendar()[1])
    return any(_iso_week_key(e.get("date", "")) == cur for e in _load_manifest())


def _referenced_assets(body: str) -> List[str]:
    """从正文里解析出被引用的本地图片文件名（assets/xxx.png）。"""
    names: List[str] = []
    for path in re.findall(r"!\[[^\]]*\]\(\s*assets/([^)\s]+)\s*\)", body):
        names.append(path.strip())
    return names


def output_report_node(state: WeeklyState) -> dict:
    """
    LangGraph 节点：把周刊写入 reports/<日期>/README.md，并把**被正文引用到的**图片
    从临时目录移入 reports/<日期>/assets/（未被引用的临时图直接丢弃）。
    """
    # 没抓到任何仓库时不写盘，避免 CI 把一份空周刊 commit 回仓库
    if not state.get("enriched") and not state.get("repos"):
        log("output_report", "本周无任何仓库数据，跳过写盘（不生成空周刊）", "warn")
        return {}

    body = state.get("report_md", "")
    issue = state.get("issue_number")
    date_str = state.get("date_str")
    if issue is None or not date_str:
        i, d = compute_issue_and_date()
        issue = issue or i
        date_str = date_str or d

    date_dir = REPORTS_DIR / date_str
    assets_dir = date_dir / "assets"
    date_dir.mkdir(parents=True, exist_ok=True)

    # 只把正文真正引用到的图片移入正式 assets 目录
    tmp_raw = state.get("tmp_assets_dir")
    tmp_dir = Path(tmp_raw) if tmp_raw else None
    moved = 0
    if tmp_dir and tmp_dir.exists():
        wanted = _referenced_assets(body)
        if wanted:
            assets_dir.mkdir(parents=True, exist_ok=True)
        for name in wanted:
            src = tmp_dir / name
            if src.exists():
                shutil.move(str(src), str(assets_dir / name))
                moved += 1
            else:
                log("output_report", f"正文引用了图片但临时文件不存在: {name}", "warn")
        # 清理临时目录（含未被引用的候选图）
        shutil.rmtree(tmp_dir, ignore_errors=True)
    log("output_report", f"移入 {moved} 张被引用的图片到 assets/", "dim")

    header = (
        f"# GitHub 一周热点 · 第 {issue} 期\n\n"
        f"> 📅 {date_str.replace('_', '-')} ｜ 数据来源：GitHub Trending（本周）\n\n"
        "---\n\n"
    )
    out_path = date_dir / REPORT_MD_NAME
    out_path.write_text(header + body + "\n", encoding="utf-8")

    # 更新期数台账（同时作为往期清单）
    _update_manifest(issue, date_str, len(state.get("enriched", []) or []))

    log("output_report", f"已写入 {out_path}（第 {issue} 期）", "ok")
    return {
        "issue_number": issue,
        "date_str": date_str,
        "output_path": str(out_path),
    }

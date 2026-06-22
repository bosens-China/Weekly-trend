#!/usr/bin/env python3
"""扫描 reports/ 下的各期周刊，重建期数台账（清单）reports/index.json。

每期一个以日期命名的文件夹：reports/<YYYY_MM_DD>/README.md。
本脚本从磁盘反推清单，便于在手动增删某期、或台账丢失后重新生成；
已有 index.json 里的 generated_at 会被沿用，仅对新发现的期数补上文件 mtime。

用法：uv run python scripts/build_manifest.py
"""

import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# 与 output_report 保持一致：全项目时间口径统一为北京时间
BEIJING = ZoneInfo("Asia/Shanghai")

REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports"
INDEX_JSON = REPORTS_DIR / "index.json"

_DATE_RE = re.compile(r"^\d{4}_\d{2}_\d{2}$")
_ISSUE_RE = re.compile(r"第\s*(\d+)\s*期")  # 从 README 一级标题里解析期号
_ENTRY_RE = re.compile(r"^###\s", re.MULTILINE)  # 每个项目条目以 ### 开头


def _load_existing() -> dict:
    """读出现有台账，按日期建索引，用于沿用 generated_at。"""
    try:
        data = json.loads(INDEX_JSON.read_text(encoding="utf-8"))
        return {e["date"]: e for e in data if isinstance(e, dict) and e.get("date")}
    except Exception:
        return {}


def _iso_mtime(path: Path) -> str:
    ts = datetime.fromtimestamp(path.stat().st_mtime, tz=BEIJING)
    return ts.isoformat(timespec="seconds")


def build_manifest() -> list[dict]:
    existing = _load_existing()
    entries: list[dict] = []

    for date_dir in sorted(REPORTS_DIR.iterdir() if REPORTS_DIR.exists() else []):
        if not (date_dir.is_dir() and _DATE_RE.match(date_dir.name)):
            continue
        readme = date_dir / "README.md"
        if not readme.exists():
            continue

        text = readme.read_text(encoding="utf-8")
        m = _ISSUE_RE.search(text)
        issue = int(m.group(1)) if m else 0
        repos = len(_ENTRY_RE.findall(text))
        prev = existing.get(date_dir.name)

        entries.append(
            {
                "issue": issue,
                "date": date_dir.name,
                "dir": date_dir.name,
                "repos": repos,
                # 沿用已有生成时间；新发现的期数退回文件 mtime
                "generated_at": (prev or {}).get("generated_at") or _iso_mtime(readme),
            }
        )

    entries.sort(key=lambda e: (e["issue"], e["date"]))
    return entries


def write_manifest(manifest: list[dict]) -> None:
    """把清单写回 reports/index.json（供其它脚本复用）。"""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_JSON.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    manifest = build_manifest()
    write_manifest(manifest)
    print(f"已写入 {INDEX_JSON.relative_to(REPORTS_DIR.parent)}：共 {len(manifest)} 期")
    for e in manifest:
        print(f"  第 {e['issue']:>3} 期  {e['date']}  ({e['repos']} 个项目)")


if __name__ == "__main__":
    main()

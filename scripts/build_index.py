#!/usr/bin/env python3
"""根据期数台账，刷新 README 的「往期周刊」列表，并生成 RSS 订阅文件 feed.xml。

数据源是磁盘上的 reports/<日期>/README.md（经 build_manifest 反推），因此 README
列表、feed.xml、reports/index.json 三者始终一致。每次生成新一期后自动调用，也可手动跑：

    uv run python scripts/build_index.py
"""

import os
from datetime import datetime, timezone
from email.utils import format_datetime

from build_manifest import REPORTS_DIR, build_manifest, write_manifest

ROOT = REPORTS_DIR.parent
README = ROOT / "README.md"
FEED = ROOT / "feed.xml"

# 仓库信息（可用环境变量覆盖，CI 里 GITHUB_REPOSITORY 形如 owner/repo）
REPO = (
    os.getenv("REPO_SLUG")
    or os.getenv("GITHUB_REPOSITORY")
    or "bosens-China/Weekly-trend"
)
BRANCH = os.getenv("REPO_BRANCH", "master")
SITE = f"https://github.com/{REPO}"
RAW = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}"
FEED_URL = f"{RAW}/feed.xml"

TITLE = "GitHub 一周热点周刊"
DESC = "每周自动抓取 GitHub Trending，用 LLM 整理成分类、带图的中文周刊。"

# README 里这两个标记之间的内容由本脚本托管，请勿手动编辑
START = "<!-- ISSUES:START -->"
END = "<!-- ISSUES:END -->"


def _issue_url(date: str) -> str:
    return f"{SITE}/blob/{BRANCH}/reports/{date}/README.md"


def _parse_dt(entry: dict) -> datetime:
    """把 generated_at 解析成带时区的 datetime；失败时退回日期文件夹名。"""
    raw = entry.get("generated_at") or ""
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return datetime.strptime(entry["date"], "%Y_%m_%d").replace(tzinfo=timezone.utc)


def render_readme_block(entries: list[dict]) -> str:
    """渲染「往期周刊」表格（按期号倒序，最新在上）。"""
    if not entries:
        return "_暂无往期，生成第一期后会自动出现在这里。_"

    rows = ["| 期号 | 日期 | 收录项目 | 链接 |", "| :--: | :--: | :--: | :-- |"]
    for e in sorted(entries, key=lambda x: x["issue"], reverse=True):
        date = e["date"].replace("_", "-")
        rows.append(
            f"| 第 {e['issue']} 期 | {date} | {e.get('repos', 0)} 个 "
            f"| [阅读]({_issue_url(e['date'])}) |"
        )
    return "\n".join(rows)


def inject_readme(block: str) -> bool:
    """把 block 注入 README 的标记之间；README 缺标记时追加一节。返回是否写盘。"""
    section = f"{START}\n{block}\n{END}"
    text = README.read_text(encoding="utf-8") if README.exists() else ""
    if START in text and END in text:
        head, _, rest = text.partition(START)
        _, _, tail = rest.partition(END)
        new = head + section + tail
    else:
        new = text.rstrip() + f"\n\n## 📰 往期周刊\n\n{section}\n"
    if new != text:
        README.write_text(new, encoding="utf-8")
        return True
    return False


def _escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_feed(entries: list[dict], now: datetime) -> str:
    """生成 RSS 2.0 订阅内容（按时间倒序）。"""
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">',
        "  <channel>",
        f"    <title>{_escape(TITLE)}</title>",
        f"    <link>{SITE}</link>",
        f'    <atom:link href="{FEED_URL}" rel="self" type="application/rss+xml"/>',
        f"    <description>{_escape(DESC)}</description>",
        "    <language>zh-CN</language>",
        f"    <lastBuildDate>{format_datetime(now)}</lastBuildDate>",
    ]
    for e in sorted(entries, key=lambda x: x["issue"], reverse=True):
        link = _issue_url(e["date"])
        title = f"第 {e['issue']} 期 · {e['date'].replace('_', '-')}"
        summary = f"本期收录 {e.get('repos', 0)} 个项目"
        lines += [
            "    <item>",
            f"      <title>{_escape(title)}</title>",
            f"      <link>{link}</link>",
            f'      <guid isPermaLink="true">{link}</guid>',
            f"      <pubDate>{format_datetime(_parse_dt(e))}</pubDate>",
            f"      <description>{_escape(summary)}</description>",
            "    </item>",
        ]
    lines += ["  </channel>", "</rss>", ""]
    return "\n".join(lines)


def main() -> None:
    entries = build_manifest()
    write_manifest(entries)  # 顺手保证 index.json 与磁盘一致

    changed = inject_readme(render_readme_block(entries))
    now = datetime.now(timezone.utc).astimezone()
    FEED.write_text(render_feed(entries, now), encoding="utf-8")

    print(
        f"往期 {len(entries)} 期：README {'已更新' if changed else '无变化'}，feed.xml 已生成"
    )


if __name__ == "__main__":
    main()

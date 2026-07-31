"""把稳定的报告 JSON 渲染为周刊 Markdown。"""

import re
from typing import List

from graph.reporting.common import clean_tags, clean_text


def _star_count(value: object) -> str:
    """移除 GitHub Trending 数值后的英文时间范围，避免中英文重复。"""
    text = clean_text(value)
    return re.sub(
        r"\s+stars?\s+(?:today|this\s+(?:week|month))$",
        "",
        text,
        flags=re.IGNORECASE,
    )


def _render_item(item: dict) -> str:
    title = clean_text(item.get("repo")) or clean_text(item.get("url")) or "未知项目"
    url = clean_text(item.get("url"))
    lines = [f"### [{title}]({url})" if url else f"### {title}", ""]

    if item.get("total_stars"):
        lines.append(f"- ⭐ 累计 Star：{_star_count(item['total_stars'])}")
    if item.get("period_stars"):
        lines.append(f"- 🔥 本周新增 Star：{_star_count(item['period_stars'])}")
    if item.get("language"):
        lines.append(f"- 💻 {item['language']}")
    if item.get("homepage"):
        lines.append(f"- 🔗 官网：{item['homepage']}")

    if item.get("image"):
        lines.extend(["", f"![{title} 项目截图]({item['image']})"])
    if item.get("summary"):
        lines.extend(["", clean_text(item["summary"])])
    if item.get("plain_explanation"):
        lines.extend(["", f"**简单说：** {clean_text(item['plain_explanation'])}"])

    tags = clean_tags(item.get("tags"), [])
    if tags:
        lines.extend(["", " ".join(f"`#{tag}`" for tag in tags)])
    return "\n".join(lines).strip()


def render_markdown(report_json: dict) -> str:
    sections: List[str] = []
    overview = clean_text(report_json.get("overview"))
    if overview:
        sections.append(f"> {overview}")
    for category in report_json.get("categories", []):
        items = category.get("items", [])
        if not items:
            continue
        body = "\n\n".join(_render_item(item) for item in items)
        sections.append(f"## {category.get('name') or '本周热点'}\n\n{body}")
    return "\n\n".join(sections).strip() or "_本周未抓取到任何 Trending 仓库。_"

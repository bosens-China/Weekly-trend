"""报告结构处理的通用小工具。"""

import json
import re
from typing import List

from graph.state import EnrichedRepo


def repo_key(repo: EnrichedRepo) -> str:
    owner, name = repo.get("owner", ""), repo.get("repo", "")
    key = f"{owner}/{name}" if owner and name else ""
    return key or repo.get("name", "") or repo.get("url", "")


def parse_json_object(text: str) -> dict:
    """解析模型输出的 JSON；兼容偶发代码块或前后解释文字。"""
    raw = text.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if not match:
            raise
        data = json.loads(match.group(0))
    return data if isinstance(data, dict) else {}


def clean_text(value: object) -> str:
    return str(value or "").strip()


def clean_int(value: object, default: int = 0) -> int:
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        return default
    try:
        return int(value)
    except ValueError:
        return default


def clean_tags(value: object, fallback: List[str]) -> List[str]:
    """清洗标签；模型未给出有效标签时使用 GitHub topics。"""
    candidate = value if isinstance(value, list) else []
    raw = candidate if any(clean_text(item) for item in candidate) else fallback
    tags: List[str] = []
    seen = set()
    for item in raw:
        tag = re.sub(r"^#+", "", clean_text(item)).strip()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        tags.append(tag)
        if len(tags) >= 6:
            break
    return tags


def count_items(report_json: dict) -> int:
    return sum(
        len(category.get("items", [])) for category in report_json.get("categories", [])
    )

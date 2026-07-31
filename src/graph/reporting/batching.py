"""仓库材料的字符预算、智能拆分与批次装箱。"""

import json
import os
import re
from typing import List

from graph.reporting.common import repo_key
from graph.state import EnrichedRepo
from log import log

DEFAULT_BATCH_CHARS = 20_000
DEFAULT_CONCURRENCY = 5


def _positive_int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name) or default))
    except ValueError:
        log("generate_report", f"{name} 不是有效整数，使用默认值 {default}", "warn")
        return default


def report_concurrency() -> int:
    """报告批次最大并发数，默认 5。"""
    return _positive_int_env("REPORT_CONCURRENCY", DEFAULT_CONCURRENCY)


def batch_chars() -> int:
    return _positive_int_env("REPORT_BATCH_CHARS", DEFAULT_BATCH_CHARS)


def _compact(repo: EnrichedRepo) -> dict:
    """裁剪成报告模型所需字段；图片和 star 等元信息由程序补回。"""
    return {
        "repo": repo_key(repo),
        "description": repo.get("description", ""),
        "language": repo.get("language", ""),
        "topics": repo.get("topics", []),
        "readme": repo.get("readme", ""),
    }


def _json_chars(items: List[dict]) -> int:
    return len(json.dumps(items, ensure_ascii=False, separators=(",", ":")))


def _markdown_blocks(text: str) -> List[str]:
    """优先沿 Markdown 标题和段落边界拆分，保留原有阅读结构。"""
    return [
        block.strip()
        for block in re.split(r"\n(?=#{1,6}\s)|\n{2,}", text)
        if block.strip()
    ]


def _unit_fits(base: dict, text: str, limit: int) -> bool:
    probe = {
        **base,
        "readme": text,
        "part_index": 9999,
        "part_total": 9999,
    }
    return _json_chars([probe]) <= limit


def _largest_fitting_prefix(base: dict, text: str, limit: int) -> int:
    """二分找到不会突破批次字符上限的最大前缀。"""
    low, high = 1, len(text)
    best = 0
    while low <= high:
        mid = (low + high) // 2
        if _unit_fits(base, text[:mid], limit):
            best = mid
            low = mid + 1
        else:
            high = mid - 1
    return best


def _split_repo_payload(repo: EnrichedRepo, limit: int) -> List[dict]:
    """仓库材料超限时按 Markdown 结构拆分，必要时再安全硬切。"""
    payload = _compact(repo)
    readme = str(payload.pop("readme", "") or "")
    full = {**payload, "readme": readme, "part_index": 1, "part_total": 1}
    if _json_chars([full]) <= limit:
        return [full]

    if not _unit_fits(payload, "", limit):
        raise ValueError(f"{repo_key(repo)} 的基础元数据已超过 {limit} 字符")

    parts: List[str] = []
    current = ""
    for block in _markdown_blocks(readme):
        candidate = f"{current}\n\n{block}".strip() if current else block
        if _unit_fits(payload, candidate, limit):
            current = candidate
            continue
        if current:
            parts.append(current)
            current = ""

        remaining = block
        while remaining and not _unit_fits(payload, remaining, limit):
            cut = _largest_fitting_prefix(payload, remaining, limit)
            if cut <= 0:
                raise ValueError(f"{repo_key(repo)} 无法按 {limit} 字符拆分")
            parts.append(remaining[:cut].strip())
            remaining = remaining[cut:].lstrip()
        current = remaining

    if current:
        parts.append(current)
    if not parts:
        parts = [""]

    total = len(parts)
    return [
        {
            **payload,
            "readme": part,
            "part_index": index,
            "part_total": total,
        }
        for index, part in enumerate(parts, 1)
    ]


def build_report_batches(
    enriched: List[EnrichedRepo], limit: int | None = None
) -> List[dict]:
    """保持 Trending 顺序，将仓库材料装箱到不超过字符上限的批次。"""
    max_chars = limit or batch_chars()
    units = [unit for repo in enriched for unit in _split_repo_payload(repo, max_chars)]
    batches: List[dict] = []
    current: List[dict] = []
    for unit in units:
        if current and _json_chars([*current, unit]) > max_chars:
            batches.append(
                {
                    "batch_index": len(batches),
                    "char_count": _json_chars(current),
                    "items": current,
                }
            )
            current = []
        current.append(unit)
    if current:
        batches.append(
            {
                "batch_index": len(batches),
                "char_count": _json_chars(current),
                "items": current,
            }
        )
    return batches

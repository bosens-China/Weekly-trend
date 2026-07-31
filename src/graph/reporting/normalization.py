"""将并发模型输出归一化为稳定的周刊 JSON 结构。"""

import re
from typing import List

from graph.reporting.common import clean_int, clean_tags, clean_text, repo_key
from graph.state import EnrichedRepo
from log import log


def normalize_batch_json(raw: dict, batch: dict) -> dict:
    """按输入逐项对齐模型结果，确保并发批次不丢材料。"""
    returned: dict[tuple[str, int], dict] = {}
    for item in raw.get("items", []):
        if not isinstance(item, dict):
            continue
        key = (clean_text(item.get("repo")), clean_int(item.get("part_index"), 1))
        returned.setdefault(key, item)

    items: List[dict] = []
    for source in batch.get("items", []):
        repo = clean_text(source.get("repo"))
        part_index = clean_int(source.get("part_index"), 1)
        item = returned.get((repo, part_index), {})
        items.append(
            {
                "repo": repo,
                "part_index": part_index,
                "part_total": clean_int(source.get("part_total"), 1),
                "summary": clean_text(item.get("summary")),
                "plain_explanation": clean_text(item.get("plain_explanation")),
                "tags": clean_tags(item.get("tags"), source.get("topics", [])),
                "source_description": clean_text(source.get("description")),
            }
        )
    return {
        "batch_index": clean_int(batch.get("batch_index")),
        "items": items,
    }


def _unique_texts(values: List[str]) -> List[str]:
    seen = set()
    result: List[str] = []
    for value in values:
        text = clean_text(value)
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def merge_batch_results(
    batch_results: List[dict], enriched: List[EnrichedRepo]
) -> List[dict]:
    """合并乱序并发结果，并按原始 Trending 顺序生成全局整理草稿。"""
    grouped: dict[str, List[dict]] = {}
    for result in sorted(batch_results, key=lambda item: item.get("batch_index", 0)):
        for item in result.get("items", []):
            repo = clean_text(item.get("repo"))
            if repo:
                grouped.setdefault(repo, []).append(item)

    drafts: List[dict] = []
    for repo in enriched:
        key = repo_key(repo)
        parts = sorted(grouped.get(key, []), key=lambda item: item.get("part_index", 0))
        summaries = _unique_texts([item.get("summary", "") for item in parts])
        explanations = _unique_texts(
            [item.get("plain_explanation", "") for item in parts]
        )
        tags = [
            tag for item in parts for tag in item.get("tags", []) if clean_text(tag)
        ]
        drafts.append(
            {
                "repo": key,
                "language": repo.get("language", ""),
                "source_description": repo.get("description", ""),
                "summary_material": "\n".join(summaries),
                "plain_explanation_material": "\n".join(explanations),
                "tags": clean_tags(tags, repo.get("topics", [])),
            }
        )
    return drafts


def _repo_map(enriched: List[EnrichedRepo]) -> dict[str, EnrichedRepo]:
    mapping: dict[str, EnrichedRepo] = {}
    for repo in enriched:
        key = repo_key(repo)
        if key:
            mapping[key] = repo
        url = repo.get("url", "")
        if url:
            mapping[url] = repo
    return mapping


def _draft_map(drafts: List[dict]) -> dict[str, dict]:
    return {
        clean_text(draft.get("repo")): draft
        for draft in drafts
        if clean_text(draft.get("repo"))
    }


def _full_item(
    repo: EnrichedRepo,
    summary: str,
    plain_explanation: str,
    tags: List[str],
) -> dict:
    """生成 report.json 完整项目对象，保留原始 description。"""
    images = repo.get("relevant_images", [])
    return {
        "repo": repo_key(repo),
        "url": repo.get("url", ""),
        "description": repo.get("description", ""),
        "language": repo.get("language", ""),
        "total_stars": repo.get("total_stars", ""),
        "period_stars": repo.get("period_stars", ""),
        "homepage": repo.get("homepage", ""),
        "topics": repo.get("topics", []),
        "image": images[0] if images else "",
        "summary": summary,
        "plain_explanation": plain_explanation,
        "tags": tags,
    }


def normalize_report_json(
    raw: dict,
    enriched: List[EnrichedRepo],
    drafts: List[dict] | None = None,
) -> dict:
    """归一化全局分类结果，并用批次草稿补回模型遗漏仓库。"""
    repos = _repo_map(enriched)
    fallback = _draft_map(drafts or [])
    used: set[str] = set()
    categories: List[dict] = []

    for category in raw.get("categories", []):
        if not isinstance(category, dict):
            continue
        name = clean_text(category.get("name")) or "其他项目"
        items: List[dict] = []
        for item in category.get("items", []):
            if not isinstance(item, dict):
                continue
            key = clean_text(item.get("repo"))
            repo = repos.get(key)
            canonical = repo_key(repo) if repo else ""
            if not repo or canonical in used:
                continue
            used.add(canonical)
            draft = fallback.get(canonical, {})
            summary = clean_text(item.get("summary")) or clean_text(
                draft.get("summary_material")
            )
            explanation = clean_text(item.get("plain_explanation")) or clean_text(
                draft.get("plain_explanation_material")
            )
            tags = clean_tags(
                item.get("tags"),
                draft.get("tags") or repo.get("topics", []),
            )
            items.append(_full_item(repo, summary, explanation, tags))
        if items:
            categories.append({"name": name, "items": items})

    missing = [repo for repo in enriched if repo_key(repo) not in used]
    if missing:
        fallback_items = []
        for repo in missing:
            draft = fallback.get(repo_key(repo), {})
            fallback_items.append(
                _full_item(
                    repo,
                    clean_text(draft.get("summary_material")),
                    clean_text(draft.get("plain_explanation_material")),
                    clean_tags(draft.get("tags"), repo.get("topics", [])),
                )
            )
        categories.append({"name": "其他项目", "items": fallback_items})
        log(
            "generate_report",
            f"用批次草稿补回 {len(missing)} 个遗漏仓库: "
            + ", ".join(repo_key(repo) for repo in missing),
            "warn",
        )

    return {
        "version": 2,
        "source": "GitHub Trending（本周）",
        "categories": categories,
    }


def top_categories(report_json: dict, limit: int = 3) -> List[dict]:
    """按项目数稳定排序；数量相同时保留全局分类节点的原始顺序。"""
    categories = [
        (index, category)
        for index, category in enumerate(report_json.get("categories", []))
        if category.get("items")
    ]
    categories.sort(key=lambda pair: (-len(pair[1].get("items", [])), pair[0]))
    return [
        {
            "name": clean_text(category.get("name")) or "其他项目",
            "project_count": len(category.get("items", [])),
            "items": [
                {
                    "repo": item.get("repo", ""),
                    "summary": item.get("summary", ""),
                    "plain_explanation": item.get("plain_explanation", ""),
                    "tags": item.get("tags", []),
                }
                for item in category.get("items", [])
            ],
        }
        for _, category in categories[:limit]
    ]


def normalize_overview(value: object, project_count: int) -> str:
    """固定项目数句式并限制在 200 字符内，避免异常输出破坏 Blog 卡片。"""
    if project_count <= 0:
        return ""
    prefix = f"本期周刊共收录 {project_count} 个项目。"
    text = re.sub(r"\s+", " ", clean_text(value))
    text = re.sub(
        r"^本期(?:周刊)?共(?:收录)?\s*\d+\s*个项目[。；，]?\s*",
        "",
        text,
    )
    overview = prefix + text
    if len(overview) <= 200:
        return overview

    candidate = overview[:200]
    last_break = max(candidate.rfind(mark) for mark in "。！？；")
    if last_break >= len(prefix):
        return candidate[: last_break + 1]
    return candidate[:199].rstrip("，；、 ") + "。"

import json
import re
from typing import List

from graph.state import EnrichedRepo, WeeklyState
from llm import get_llm
from log import log

_SYSTEM = """你是 GitHub Trending 周刊的主编。读者是中文开发者。
你会收到本周 GitHub Trending（weekly）上的仓库数据（JSON 数组）。

请只输出一个 JSON 对象，不要输出 Markdown，不要用代码块包裹。格式如下：
{
  "categories": [
    {
      "name": "分类名，如 AI / 大模型、开发工具、Web 前端、基础设施",
      "items": [
        {
          "repo": "owner/repo",
          "summary": "1 到 3 句中文简介，说明项目做什么、为什么本周值得关注",
          "tags": ["tag1", "tag2"]
        }
      ]
    }
  ]
}

要求：
0. 必须覆盖输入数组里的每一个仓库，一个都不能遗漏、跳过或合并；每个仓库只能出现一次。
1. 按主题给项目分类，只输出确实有项目的类目；不要输出空类目、占位类目或“暂无”。
2. 每个 item 的 repo 必须严格使用输入中的 owner/repo。
3. summary 按以下取材优先级写：优先依据 readme，其次 description；如果两者都为空则给空字符串，不要编造。
4. tags 使用项目 topics 或你从 README 中提炼出的短标签，不要超过 6 个；只写标签文本，不要带 #。
5. 中文写作规范：中文与英文、数字之间留一个半角空格；中文句子用全角标点；语气平实克制。
6. JSON 必须可被 json.loads 直接解析。"""


# ----------------------------- LLM 输入与 JSON 解析 -----------------------------


def _repo_key(repo: EnrichedRepo) -> str:
    owner, name = repo.get("owner", ""), repo.get("repo", "")
    key = f"{owner}/{name}" if owner and name else ""
    return key or repo.get("name", "") or repo.get("url", "")


def _compact(repo: EnrichedRepo) -> dict:
    """裁剪成喂给 LLM 的精简结构，图片/元信息由程序拼接。"""
    return {
        "repo": _repo_key(repo),
        "owner": repo.get("owner", ""),
        "name": repo.get("repo", ""),
        "description": repo.get("description", ""),
        "language": repo.get("language", ""),
        "topics": repo.get("topics", []),
        "readme": repo.get("readme", ""),
    }


def _parse_json_object(text: str) -> dict:
    """解析模型输出的 JSON；兼容偶发 ```json 包裹或前后解释文字。"""
    raw = text.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if not m:
            raise
        data = json.loads(m.group(0))
    return data if isinstance(data, dict) else {}


# ----------------------------- 结构归一化与兜底 -----------------------------


def _clean_text(value: object) -> str:
    return str(value or "").strip()


def _clean_tags(value: object, fallback: List[str]) -> List[str]:
    raw = value if isinstance(value, list) else fallback
    tags: List[str] = []
    seen = set()
    for item in raw:
        tag = re.sub(r"^#+", "", _clean_text(item)).strip()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        tags.append(tag)
        if len(tags) >= 6:
            break
    return tags


def _repo_map(enriched: List[EnrichedRepo]) -> dict[str, EnrichedRepo]:
    mapping: dict[str, EnrichedRepo] = {}
    for repo in enriched:
        key = _repo_key(repo)
        if key:
            mapping[key] = repo
        url = repo.get("url", "")
        if url:
            mapping[url] = repo
    return mapping


def _fallback_summary(repo: EnrichedRepo) -> str:
    return _clean_text(repo.get("description", ""))


def _full_item(repo: EnrichedRepo, summary: str, tags: List[str]) -> dict:
    """生成对外 report.json 中的完整项目对象，Markdown 也从这里渲染。"""
    images = repo.get("relevant_images", [])
    return {
        "repo": _repo_key(repo),
        "url": repo.get("url", ""),
        "description": repo.get("description", ""),
        "language": repo.get("language", ""),
        "total_stars": repo.get("total_stars", ""),
        "period_stars": repo.get("period_stars", ""),
        "homepage": repo.get("homepage", ""),
        "topics": repo.get("topics", []),
        "image": images[0] if images else "",
        "summary": summary,
        "tags": tags,
    }


def _normalize_report_json(raw: dict, enriched: List[EnrichedRepo]) -> dict:
    """把模型 JSON 归一化成稳定结构，并补回遗漏仓库。"""
    repos = _repo_map(enriched)
    used: set[str] = set()
    categories: List[dict] = []

    for category in raw.get("categories", []):
        if not isinstance(category, dict):
            continue
        name = _clean_text(category.get("name")) or "本周热点"
        items: List[dict] = []
        for item in category.get("items", []):
            if not isinstance(item, dict):
                continue
            key = _clean_text(item.get("repo"))
            repo = repos.get(key)
            canonical = _repo_key(repo) if repo else ""
            if not repo or canonical in used:
                continue
            used.add(canonical)
            tags = _clean_tags(item.get("tags"), repo.get("topics", []))
            summary = _clean_text(item.get("summary")) or _fallback_summary(repo)
            items.append(_full_item(repo, summary, tags))
        if items:
            categories.append({"name": name, "items": items})

    missing = [repo for repo in enriched if _repo_key(repo) not in used]
    if missing:
        fallback_items = [
            _full_item(
                repo, _fallback_summary(repo), _clean_tags([], repo.get("topics", []))
            )
            for repo in missing
        ]
        categories.append({"name": "其他项目", "items": fallback_items})
        log(
            "generate_report",
            f"用 JSON 兜底补回 {len(missing)} 个遗漏仓库: "
            + ", ".join(_repo_key(repo) for repo in missing),
            "warn",
        )

    if not categories:
        categories = [{"name": "本周热点", "items": []}]
    return {"version": 1, "source": "GitHub Trending（本周）", "categories": categories}


# ----------------------------- Markdown 渲染 -----------------------------


def _render_item(item: dict) -> str:
    title = _clean_text(item.get("repo")) or _clean_text(item.get("url")) or "未知项目"
    url = _clean_text(item.get("url"))
    lines = [f"### [{title}]({url})" if url else f"### {title}", ""]

    if item.get("total_stars"):
        lines.append(f"- ⭐ 总 star {item['total_stars']}")
    if item.get("period_stars"):
        lines.append(f"- 🔥 本周 star {item['period_stars']}")
    if item.get("language"):
        lines.append(f"- 💻 {item['language']}")
    if item.get("homepage"):
        lines.append(f"- 🔗 官网：{item['homepage']}")

    if item.get("image"):
        lines.extend(["", f"![]({item['image']})"])

    if item.get("summary"):
        lines.extend(["", _clean_text(item["summary"])])

    tags = _clean_tags(item.get("tags"), [])
    if tags:
        lines.extend(["", " ".join(f"`#{tag}`" for tag in tags)])
    return "\n".join(lines).strip()


def _render_markdown(report_json: dict) -> str:
    sections: List[str] = []
    for category in report_json.get("categories", []):
        items = category.get("items", [])
        if not items:
            continue
        body = "\n\n".join(_render_item(item) for item in items)
        sections.append(f"## {category.get('name') or '本周热点'}\n\n{body}")
    return "\n\n".join(sections).strip() or "_本周未抓取到任何 Trending 仓库。_"


def _count_items(report_json: dict) -> int:
    return sum(
        len(category.get("items", [])) for category in report_json.get("categories", [])
    )


# ----------------------------- LangGraph 节点 -----------------------------


def generate_report_node(state: WeeklyState) -> dict:
    """
    LangGraph 节点：先由 LLM 生成结构化 report_json，再由程序拼接 Markdown。
    """
    enriched: List[EnrichedRepo] = state.get("enriched", [])
    if not enriched:
        report_json = {
            "version": 1,
            "source": "GitHub Trending（本周）",
            "categories": [],
        }
        return {
            "report_json": report_json,
            "report_md": "_本周未抓取到任何 Trending 仓库。_",
        }

    payload = [_compact(repo) for repo in enriched]
    model = get_llm(temperature=0.3)
    msg = model.invoke(
        [
            {"role": "system", "content": _SYSTEM},
            {
                "role": "user",
                "content": f"本周共 {len(payload)} 个仓库，请确保全部覆盖。数据如下：\n"
                + json.dumps(payload, ensure_ascii=False),
            },
        ]
    )
    text = msg.content if isinstance(msg.content, str) else str(msg.content)

    try:
        raw_json = _parse_json_object(text)
    except Exception as e:  # noqa: BLE001
        log("generate_report", f"模型 JSON 解析失败，改用兜底结构: {e}", "warn")
        raw_json = {"categories": []}

    report_json = _normalize_report_json(raw_json, enriched)
    body = _render_markdown(report_json)
    covered = _count_items(report_json)
    log(
        "generate_report",
        f"生成 JSON 分类 {len(report_json.get('categories', []))} 个，"
        f"覆盖 {covered}/{len(enriched)} 个仓库，Markdown {len(body)} 字",
        "ok" if covered == len(enriched) else "warn",
    )
    return {"report_json": report_json, "report_md": body}


# 供轻量测试直接调用
__all__ = [
    "generate_report_node",
    "_normalize_report_json",
    "_render_markdown",
    "_parse_json_object",
]

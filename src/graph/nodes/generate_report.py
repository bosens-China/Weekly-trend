import json
from typing import List

from graph.state import EnrichedRepo, WeeklyState
from llm import get_llm

_SYSTEM = """你是 GitHub Trending 周刊的主编。读者是中文开发者。
你会收到本周 GitHub Trending（weekly）上的仓库数据（JSON 数组）。

请输出一份**中文 Markdown 周刊正文**，要求：
1. 先按主题给项目**分类**（如「AI / 大模型」「开发工具」「Web 前端」「基础设施」等，类目由你根据实际数据归纳，不要生造空类目）。
2. 每个项目用 `### [owner/repo](url)` 作为小标题，紧跟一行徽章式信息：⭐ 总 star、🔥 本周 star、💻 语言。
3. 用 1~3 句话中文介绍项目是做什么的、为什么本周火（结合 README 概括，不要直接翻译堆砌）。
4. 如果该项目的 `relevant_images` 非空，挑最有代表性的 1 张用 `![](路径)` 嵌入到介绍下方。这些是相对 reports 目录的本地图片路径（形如 `assets/12/owner__repo__0.png`），必须**原样使用**，不要改写、不要拼接域名。
5. 如果有 `homepage`，附一行 `🔗 官网: <homepage>`。
6. 适当用 `topics` 作为标签点缀，但不要喧宾夺主。

只输出正文，不要包含一级标题(# )和日期（这些会由程序补充）。不要输出代码块包裹整篇内容。"""


def _compact(repo: EnrichedRepo) -> dict:
    """裁剪成喂给 LLM 的精简结构。"""
    return {
        "owner": repo.get("owner", ""),
        "repo": repo.get("repo", ""),
        "name": repo.get("name", ""),
        "url": repo.get("url", ""),
        "description": repo.get("description", ""),
        "language": repo.get("language", ""),
        "total_stars": repo.get("total_stars", ""),
        "period_stars": repo.get("period_stars", ""),
        "homepage": repo.get("homepage", ""),
        "topics": repo.get("topics", []),
        "readme": repo.get("readme", ""),
        "relevant_images": repo.get("relevant_images", []),
    }


def generate_report_node(state: WeeklyState) -> dict:
    """
    LangGraph 节点：由 LLM 把仓库数据整合成分类的中文周刊 markdown 正文。
    """
    enriched: List[EnrichedRepo] = state.get("enriched", [])
    if not enriched:
        return {"report_md": "_本周未抓取到任何 Trending 仓库。_"}

    payload = [_compact(r) for r in enriched]
    model = get_llm(temperature=0.4)

    msg = model.invoke(
        [
            {"role": "system", "content": _SYSTEM},
            {
                "role": "user",
                "content": "本周仓库数据如下：\n```json\n"
                + json.dumps(payload, ensure_ascii=False)
                + "\n```",
            },
        ]
    )
    body = msg.content if isinstance(msg.content, str) else str(msg.content)
    print(f"[generate_report] 生成正文 {len(body)} 字")
    return {"report_md": body}

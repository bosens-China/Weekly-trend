import json
import re
from typing import List

from graph.state import EnrichedRepo, WeeklyState
from llm import get_llm
from log import log

_SYSTEM = """你是 GitHub Trending 周刊的主编。读者是中文开发者。
你会收到本周 GitHub Trending（weekly）上的仓库数据（JSON 数组）。

请输出一份**中文 Markdown 周刊正文**，要求：
0. **必须为输入数组里的每一个仓库都生成一个条目，一个都不能遗漏、跳过或合并**（即使你觉得某个项目不重要、冷门或与别的相似，也要保留）。输出的条目数必须等于输入仓库数。
1. 先按主题给项目**分类**（如「AI / 大模型」「开发工具」「Web 前端」「基础设施」等，类目由你根据实际数据归纳）。**只输出确实有项目的类目；严禁输出空类目，也不要写「(本周无新增项目)」「暂无」之类的占位行。**
2. 每个项目用 `### [owner/repo](url)` 作为小标题。小标题下先用 Markdown 无序列表（每项独占一行、以 `- ` 开头）按顺序列出元信息：
   - `- ⭐ 总 star <total_stars>`
   - `- 🔥 本周 star <period_stars>`
   - `- 💻 <language>`（`language` 为空则省略此项）
   - `- 🔗 官网：<homepage>`（仅当 `homepage` 非空时才输出此项）
3. 元信息列表之后，如果该项目的 `relevant_images` 非空，挑最有代表性的 1 张用 `![](路径)` 嵌入。这些是相对周刊 md 的本地图片路径（形如 `assets/owner__repo__0.png`），必须**原样使用**，不要改写、不要拼接域名。
4. 图片之后是项目简介，按以下取材优先级用 1~3 句中文概括（不要直接翻译堆砌）：
   - 优先依据 `readme` 概括项目是做什么的、为什么本周火；
   - `readme` 为空时，退而用 `description` 概括；
   - `readme` 和 `description` **都为空时，不要编造，直接省略简介**（该项目只保留小标题和元信息列表即可）。
5. 简介之后，适当用 `topics` 作为标签点缀（形如 `` `#tag` `` 排成一行），但不要喧宾夺主。
6. 中文写作规范（务必遵守）：
   - 中文与英文、数字之间留一个半角空格（如「基于 Rust 实现」「12 个项目」），但紧贴全角标点时不留（如「MacBook。」）。
   - 中文句子用全角标点（，。：、；），并列项之间用顿号「、」而非逗号；英文句子内部才用半角标点。
   - 语气平实克制，避免感叹号和「太强了」「炸裂」这类夸张口语；同一术语全文保持同一种写法。

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
                "content": f"本周共 {len(payload)} 个仓库，请确保这 {len(payload)} 个全部覆盖。"
                "数据如下：\n```json\n"
                + json.dumps(payload, ensure_ascii=False)
                + "\n```",
            },
        ]
    )
    body = msg.content if isinstance(msg.content, str) else str(msg.content)

    body, dropped = _strip_empty_sections(body)
    if dropped:
        log("generate_report", f"清理了 {dropped} 个空类目", "dim")

    body = _normalize_card_spacing(body)

    missing = _missing_repos(enriched, body)
    if missing:
        log(
            "generate_report",
            f"{len(missing)} 个仓库未出现在正文中: {', '.join(missing)}",
            "warn",
        )

    covered = len(enriched) - len(missing)
    log(
        "generate_report",
        f"生成正文 {len(body)} 字，覆盖 {covered}/{len(enriched)} 个仓库",
        "ok" if not missing else "info",
    )
    return {"report_md": body}


def _strip_empty_sections(body: str) -> tuple[str, int]:
    """
    删掉「下面没有任何 `###` 项目」的 `##` 类目（及其占位行），兜底模型不听话的情况。
    返回 (清洗后的正文, 删除的空类目数)。
    """
    lines = body.split("\n")
    # 按 `## ` 二级标题切段；segs[0] 是首个标题前的内容（通常为空）
    segs: List[List[str]] = [[]]
    for line in lines:
        if line.startswith("## "):
            segs.append([line])
        else:
            segs[-1].append(line)

    out: List[str] = list(segs[0])
    dropped = 0
    for seg in segs[1:]:
        if any(ln.startswith("### ") for ln in seg):
            out.extend(seg)
        else:
            dropped += 1  # 整段（含 `## ` 标题）丢弃

    cleaned = "\n".join(out)
    # 收敛多余空行（删段后可能留下 3 连空行）
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, dropped


# 卡片内的结构性标记行：小标题、图片、标签等各自独立成段；
# 以 `- ` 开头的元信息列表项彼此相邻成紧凑列表；其余视作简介正文，连续多行保持同段。
_MARKER_PREFIXES = ("#", "![", "`", ">")
_LIST_PREFIXES = ("- ", "* ")


def _normalize_card_spacing(body: str) -> str:
    """
    GitHub 渲染 .md 时单个换行会被并成空格，导致各行连成一段。这里在相邻行之间补空行
    让它们各自成块；但「两行都是简介正文」或「两行都是列表项」时不拆——前者避免切碎多行
    简介，后者保持元信息列表为紧凑列表（中间插空行会被渲染成松散列表，行距过大）。
    """

    def joinable(prev: str, cur: str) -> bool:
        p, c = prev.lstrip(), cur.lstrip()
        both_list = p.startswith(_LIST_PREFIXES) and c.startswith(_LIST_PREFIXES)
        both_prose = not p.startswith(
            _MARKER_PREFIXES + _LIST_PREFIXES
        ) and not c.startswith(_MARKER_PREFIXES + _LIST_PREFIXES)
        return both_list or both_prose

    out: List[str] = []
    for line in body.split("\n"):
        if out and line.strip() and out[-1].strip() and not joinable(out[-1], line):
            out.append("")
        out.append(line)

    # 合并删段/补空行可能产生的连续空行
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def _missing_repos(enriched: List[EnrichedRepo], body: str) -> List[str]:
    """校验每个仓库是否都出现在正文里（按 url 或 owner/repo 匹配），返回遗漏列表。"""
    missing: List[str] = []
    for r in enriched:
        url = r.get("url", "")
        owner, repo = r.get("owner", ""), r.get("repo", "")
        key = f"{owner}/{repo}" if owner and repo else ""
        if (url and url in body) or (key and key in body):
            continue
        missing.append(key or url or r.get("name", "?"))
    return missing

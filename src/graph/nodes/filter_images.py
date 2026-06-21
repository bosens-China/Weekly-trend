import base64
import json
import os
import re
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import httpx

from cache import JsonCache, make_key
from graph.nodes.output_report import REPORTS_DIR, compute_issue_and_date
from graph.state import EnrichedRepo, WeeklyState
from llm import get_llm
from log import log

MAX_CANDIDATES_PER_REPO = 8  # 单仓库最多处理多少张图，控成本
README_CONTEXT_CHARS = 1500  # 喂给视觉模型的 README 上下文长度，帮助判断图片相关性

# Content-Type -> 本地扩展名（仅保留视觉模型支持的格式：JPEG/PNG/GIF/WebP/BMP）
_MIME_TO_EXT = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/bmp": "bmp",
}
# 扩展名 -> data URL 用的 MIME
_EXT_TO_MIME = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "bmp": "image/bmp",
}

_DL_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def _concurrency() -> int:
    return int(os.getenv("WEEKLY_CONCURRENCY") or 8)


_SYSTEM = (
    "你是技术内容审核助手。下面会给出某开源项目的 README 摘要，以及若干张按顺序从该 "
    "README 中提取的图片。请挑出能帮助读者理解【这个项目本身】的图片：产品界面截图、"
    "功能演示、架构/流程图、项目 Logo/Banner。"
    "排除：徽章(badge/shields)、贡献者头像、与项目无关的表情包/广告/打赏二维码、"
    "纯装饰分割线、加载失败的空白图。"
    '只返回 JSON，格式为 {"relevant_indices": [序号列表]}，序号从 1 开始；'
    "若没有任何相关图片，返回 {\"relevant_indices\": []}。不要输出多余文字。"
)


def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", s or "")


def _data_url(path: Path) -> str:
    """读取本地图片并编码成 data URL，MIME 按扩展名决定。"""
    mime = _EXT_TO_MIME.get(path.suffix.lstrip(".").lower(), "image/png")
    data = path.read_bytes()
    return f"data:{mime};base64," + base64.b64encode(data).decode()


# ----------------------------- 下载（线程并发） -----------------------------


def _download_one(client: httpx.Client, url: str, out_base: Path) -> Optional[Path]:
    """
    下载单张图片，按响应的 Content-Type 决定扩展名/MIME。
    非图片（如 404 的 HTML 错误页、防盗链占位图）直接跳过，返回保存路径或 None。
    """
    try:
        resp = client.get(url, headers=_DL_HEADERS)
        resp.raise_for_status()
        ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
        ext = _MIME_TO_EXT.get(ctype)
        if ext is None:
            log("filter_images", f"跳过非图片/不支持类型 [{ctype or '未知'}]: {url}", "dim")
            return None
        out_path = out_base.with_suffix("." + ext)
        out_path.write_bytes(resp.content)
        return out_path
    except Exception as e:
        log("filter_images", f"下载失败 {url}: {e}", "warn")
        return None


# ----------------------------- LLM 相关性判定 -----------------------------


def _parse_indices(text: str, n: int) -> List[int]:
    """
    从模型输出里解析 relevant_indices。不依赖 provider 的 structured-output 实现，
    手写 JSON 解析 + 兜底，换任何 OpenAI 兼容模型（如 mimo-v2.5）都稳。
    """
    raw = text.strip()
    # 去掉 ```json ... ``` 代码块包裹
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw).strip()

    data = None
    try:
        data = json.loads(raw)
    except Exception:
        m = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(0))
            except Exception:
                data = None

    idxs: List[int] = []
    if isinstance(data, dict) and isinstance(data.get("relevant_indices"), list):
        for i in data["relevant_indices"]:
            if isinstance(i, bool):
                continue
            if isinstance(i, int):
                idxs.append(i)
            elif isinstance(i, float) and i.is_integer():
                idxs.append(int(i))
            elif isinstance(i, str) and i.strip().isdigit():
                idxs.append(int(i.strip()))

    # 去重 + 边界过滤
    seen = set()
    out: List[int] = []
    for i in idxs:
        if 1 <= i <= n and i not in seen:
            seen.add(i)
            out.append(i)
    return out


def _select(model, shots: List[Path], readme: str) -> List[Path]:
    """让视觉模型结合 README 上下文，从下载的图里挑出项目相关的，返回被选中的本地路径。"""
    content: List[dict] = []
    if readme:
        content.append(
            {
                "type": "text",
                "text": "项目 README 摘要（仅供判断上下文）：\n" + readme[:README_CONTEXT_CHARS],
            }
        )
    content.append(
        {
            "type": "text",
            "text": (
                f"以下按顺序是从该项目 README 提取的 {len(shots)} 张图片，"
                "第 i 张对应序号 i（从 1 开始）。请返回其中项目相关图片的序号。"
            ),
        }
    )
    for s in shots:
        content.append({"type": "image_url", "image_url": {"url": _data_url(s)}})

    try:
        msg = model.invoke(
            [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": content}]
        )
        text = msg.content if isinstance(msg.content, str) else str(msg.content)
        idxs = _parse_indices(text, len(shots))
        return [shots[i - 1] for i in idxs]
    except Exception as e:
        log("filter_images", f"视觉判定失败: {e}", "warn")
        return []


def filter_images_node(state: WeeklyState) -> dict:
    """
    LangGraph 节点：
    1. 仅对 README 确有图片的仓库，下载候选图到**临时目录**（按 Content-Type 定格式）；
    2. 用视觉模型结合 README 上下文挑出项目相关图片，删掉其余；
    3. relevant_images 写成相对周刊目录的路径（assets/xxx），真正被引用的图片由
       output_report 节点再从临时目录移入正式 assets/。

    视觉判定带本地缓存：key = hash(prompt + README 上下文 + 候选图 URL 列表)。
    命中时**跳过模型调用**，且只下载被判为相关的图（连带省下载带宽）。
    """
    enriched: List[EnrichedRepo] = state.get("enriched", [])
    issue, date_str = compute_issue_and_date()

    # 候选图先落到临时目录；被正文引用的才会在 output_report 里移入正式 assets/
    tmp_dir = REPORTS_DIR / ".tmp"
    shutil.rmtree(tmp_dir, ignore_errors=True)  # 清掉上次残留

    # 视觉判定缓存放共享目录 cache/（提交进仓库），让 CI 跨周复用、省钱
    cache = JsonCache("vision", shared=True)

    # 1. 为每个仓库规划：候选图、缓存 key、缓存里记录的「相关图 URL」
    plans: List[dict] = []  # 每个 ri 一项：{"cands", "key", "cached"}
    for ri, repo in enumerate(enriched):
        repo["relevant_images"] = []
        cands = repo.get("image_candidates", [])[:MAX_CANDIDATES_PER_REPO]
        readme_ctx = (repo.get("readme") or "")[:README_CONTEXT_CHARS]
        key = make_key("vision:v1", _SYSTEM, readme_ctx, *cands) if cands else ""
        cached = cache.get(key) if key else None
        plans.append({"cands": cands, "key": key, "cached": cached})

    # 2. 收集下载任务：命中缓存的只下「相关图」，未命中的下全部候选
    jobs: List[Tuple[int, str, Path]] = []  # (repo_index, url, out_base)
    for ri, plan in enumerate(plans):
        cands = plan["cands"]
        if not cands:
            continue
        owner = _safe(enriched[ri].get("owner", ""))
        repo_name = _safe(enriched[ri].get("repo", ""))
        cached = plan["cached"]
        wanted = (
            [(ci, u) for ci, u in enumerate(cands) if u in cached]
            if cached is not None
            else list(enumerate(cands))
        )
        for ci, url in wanted:
            jobs.append((ri, url, tmp_dir / f"{owner}__{repo_name}__{ci}"))

    hit_repos = sum(1 for p in plans if p["cands"] and p["cached"] is not None)

    if not jobs:
        log("filter_images", f"无需下载（{hit_repos} 个命中缓存，其余无图）", "info")
        cache.save()
        return {
            "enriched": enriched,
            "issue_number": issue,
            "date_str": date_str,
            "tmp_assets_dir": str(tmp_dir),
        }

    # 3. 并发下载到临时目录（记录每张图的 url，供命中时回写缓存用）
    tmp_dir.mkdir(parents=True, exist_ok=True)
    log(
        "filter_images",
        f"下载 {len(jobs)} 张候选图到临时目录…（{hit_repos} 个仓库命中视觉缓存）",
        "info",
    )
    per_repo: Dict[int, List[Tuple[str, Path]]] = {}  # ri -> [(url, path)]
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        with ThreadPoolExecutor(max_workers=_concurrency()) as pool:
            for ri, url, path in pool.map(
                lambda j: (j[0], j[1], _download_one(client, j[1], j[2])), jobs
            ):
                if path is not None:
                    per_repo.setdefault(ri, []).append((url, path))

    # 4. 未命中缓存的仓库：并行跑视觉判定，并把结果（相关图 URL）写回缓存
    model = get_llm(temperature=0)
    miss_ris = [
        ri
        for ri, p in enumerate(plans)
        if p["cands"] and p["cached"] is None and per_repo.get(ri)
    ]

    def _judge(ri: int) -> Tuple[int, List[Path]]:
        files = per_repo.get(ri, [])  # [(url, path)]
        shots = [path for _u, path in files]
        readme = enriched[ri].get("readme", "")
        chosen = _select(model, shots, readme) if shots else []
        chosen_set = set(chosen)
        relevant_urls = [u for u, path in files if path in chosen_set]
        cache.set(plans[ri]["key"], relevant_urls)
        for _u, path in files:
            if path not in chosen_set:
                path.unlink(missing_ok=True)
        return ri, chosen

    judged: Dict[int, List[Path]] = {}
    if miss_ris:
        with ThreadPoolExecutor(max_workers=_concurrency()) as pool:
            for ri, chosen in pool.map(_judge, miss_ris):
                judged[ri] = chosen

    # 5. 汇总：命中缓存的仓库其下载下来的就是相关图；未命中的用判定结果
    total_relevant = 0
    for ri, plan in enumerate(plans):
        if not plan["cands"]:
            continue
        files = per_repo.get(ri, [])
        if plan["cached"] is not None:
            chosen = [path for _u, path in files]
            src = "缓存"
        else:
            chosen = judged.get(ri, [])
            src = "判定"
        enriched[ri]["relevant_images"] = [f"assets/{p.name}" for p in chosen]
        total_relevant += len(chosen)
        if files or chosen:
            log(
                "filter_images",
                f"{enriched[ri].get('owner')}/{enriched[ri].get('repo')}: "
                f"{len(files)} 图 -> {len(chosen)} 相关（{src}）",
                "dim",
            )

    cache.save()
    log("filter_images", f"共筛出 {total_relevant} 张项目相关图片", "ok")
    return {
        "enriched": enriched,
        "issue_number": issue,
        "date_str": date_str,
        "tmp_assets_dir": str(tmp_dir),
    }

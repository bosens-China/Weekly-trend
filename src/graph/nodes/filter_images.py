import asyncio
import base64
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Tuple

from pydantic import BaseModel, Field

from graph.nodes.output_report import REPORTS_DIR, compute_issue_and_date
from graph.state import EnrichedRepo, WeeklyState
from llm import get_llm

MAX_CANDIDATES_PER_REPO = 8  # 单仓库最多截多少张图，控成本


def _concurrency() -> int:
    return int(os.getenv("WEEKLY_CONCURRENCY") or 8)


class _RelevantImages(BaseModel):
    """视觉模型结构化输出：挑出与项目相关的截图序号（从 1 开始）。"""

    relevant_indices: List[int] = Field(
        default_factory=list,
        description="判定为项目相关（产品截图 / 架构图 / 演示图 / Logo/Banner）的图片序号，从 1 开始",
    )


_SYSTEM = (
    "你是技术内容审核助手。下面按顺序给出若干张从某开源项目 README 中截取的图片。"
    "请挑出能帮助读者理解【这个项目本身】的图片：产品界面截图、功能演示、"
    "架构/流程图、项目 Logo/Banner。"
    "排除：徽章(badge/shields)、贡献者头像、与项目无关的表情包/广告/打赏二维码、"
    "纯装饰分割线、加载失败的空白图。返回相关图片的序号（从 1 开始）。"
)


def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", s or "")


def _png_data_url(path: Path) -> str:
    data = path.read_bytes()
    return "data:image/png;base64," + base64.b64encode(data).decode()


# ----------------------------- 截图（异步并发） -----------------------------


async def _shot_one(context, sem: asyncio.Semaphore, url: str, out_path: Path) -> bool:
    """渲染单张图片 URL 并截图保存为 PNG。"""
    async with sem:
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="load", timeout=20000)
            target = page.locator("img, svg").first
            try:
                if await target.count() > 0:
                    await target.screenshot(path=str(out_path), timeout=10000)
                else:
                    await page.screenshot(path=str(out_path))
            except Exception:
                await page.screenshot(path=str(out_path))
            return True
        except Exception as e:
            print(f"[screenshot] 失败 {url}: {e}")
            return False
        finally:
            await page.close()


async def _capture_all(jobs: List[Tuple[str, Path]], concurrency: int) -> List[bool]:
    """并发渲染并截图所有 (url, out_path)。"""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900}, device_scale_factor=2
        )
        sem = asyncio.Semaphore(concurrency)
        try:
            return await asyncio.gather(
                *[_shot_one(context, sem, url, out) for url, out in jobs]
            )
        finally:
            await browser.close()


# ----------------------------- LLM 相关性判定 -----------------------------


def _select(model, shots: List[Path]) -> List[Path]:
    """让视觉模型从截图里挑出项目相关的，返回被选中的本地路径。"""
    content: List[dict] = [
        {
            "type": "text",
            "text": "以下按顺序是从 README 截取的图片，请返回其中项目相关图片的序号（从 1 开始）：",
        }
    ]
    for s in shots:
        content.append({"type": "image_url", "image_url": {"url": _png_data_url(s)}})

    try:
        structured = model.with_structured_output(_RelevantImages)
        res: _RelevantImages = structured.invoke(
            [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": content}]
        )
        idxs = [i for i in res.relevant_indices if 1 <= i <= len(shots)]
        return [shots[i - 1] for i in idxs]
    except Exception as e:
        print(f"[filter_images] 视觉判定失败: {e}")
        return []


def filter_images_node(state: WeeklyState) -> dict:
    """
    LangGraph 节点：
    1. 仅对 README 确有图片的仓库，启动无头浏览器逐张截图存为本地 PNG；
    2. 用 GPT-4o 视觉从截图里挑出项目相关图片，删掉其余；
    3. relevant_images 写成相对 reports 目录的本地路径，供周刊嵌入。
    """
    enriched: List[EnrichedRepo] = state.get("enriched", [])
    issue, date_str = compute_issue_and_date()
    assets_dir = REPORTS_DIR / "assets" / str(issue)

    # 1. 收集截图任务（README 有图才进入）
    jobs: List[Tuple[int, str, Path]] = []  # (repo_index, url, out_path)
    for ri, repo in enumerate(enriched):
        repo["relevant_images"] = []
        cands = repo.get("image_candidates", [])[:MAX_CANDIDATES_PER_REPO]
        for ci, url in enumerate(cands):
            fname = f"{_safe(repo.get('owner', ''))}__{_safe(repo.get('repo', ''))}__{ci}.png"
            jobs.append((ri, url, assets_dir / fname))

    if not jobs:
        print("[filter_images] 所有仓库 README 均无图片，跳过浏览器")
        return {"enriched": enriched, "issue_number": issue, "date_str": date_str}

    # 2. 启动浏览器并发截图
    assets_dir.mkdir(parents=True, exist_ok=True)
    print(f"[filter_images] 启动浏览器，对 {len(jobs)} 张候选图截图…")
    oks = asyncio.run(_capture_all([(u, o) for _, u, o in jobs], _concurrency()))

    per_repo: Dict[int, List[Path]] = {}
    for (ri, _url, out), ok in zip(jobs, oks):
        if ok and out.exists():
            per_repo.setdefault(ri, []).append(out)

    # 3. LLM 从截图里挑相关图（并行），删掉未选中的
    model = get_llm(temperature=0)

    def _judge(ri: int) -> Tuple[int, List[Path]]:
        shots = per_repo.get(ri, [])
        chosen = _select(model, shots) if shots else []
        for s in shots:
            if s not in chosen:
                s.unlink(missing_ok=True)
        return ri, chosen

    with ThreadPoolExecutor(max_workers=_concurrency()) as pool:
        for ri, chosen in pool.map(_judge, list(per_repo.keys())):
            enriched[ri]["relevant_images"] = [f"assets/{issue}/{p.name}" for p in chosen]
            print(
                f"[filter_images] {enriched[ri].get('owner')}/{enriched[ri].get('repo')}: "
                f"{len(per_repo.get(ri, []))} 截图 -> {len(chosen)} 相关"
            )

    return {"enriched": enriched, "issue_number": issue, "date_str": date_str}

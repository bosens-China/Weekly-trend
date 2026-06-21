import os
import re
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import httpx

from cache import JsonCache, make_key
from graph.state import EnrichedRepo, WeeklyState
from log import log

API_BASE = "https://api.github.com"


def _readme_max_chars() -> int:
    """README 截断长度，由 README_MAX_CHARS 环境变量控制，默认 32k 字符。"""
    return int(os.getenv("README_MAX_CHARS") or 32000)


def _concurrency() -> int:
    """并行抓取仓库的线程数，由 WEEKLY_CONCURRENCY 控制，默认 8。"""
    return int(os.getenv("WEEKLY_CONCURRENCY") or 8)

# 启发式：这些一看就不是「项目相关」的图片（徽章/统计/打赏等），直接丢弃
_BADGE_HOST_HINTS = (
    "shields.io",
    "badge.fury.io",
    "travis-ci",
    "circleci.com",
    "codecov.io",
    "coveralls.io",
    "app.codacy.com",
    "github.com/.*/workflows",  # actions badge
    "img.buymeacoffee.com",
    "api.star-history.com",  # star 曲线，非项目图
    "visitor-badge",
    "hits.dwyl.com",
)
_BADGE_KEYWORDS = ("badge", "shield", "license", "/actions/workflows")


def _split_owner_repo(url: str) -> Optional[Tuple[str, str]]:
    """从 https://github.com/owner/repo 解析出 (owner, repo)。"""
    path = urlparse(url).path.strip("/")
    parts = path.split("/")
    if len(parts) >= 2 and parts[0] and parts[1]:
        return parts[0], parts[1]
    return None


def _auth_headers() -> dict:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "weekly-trend-bot"}
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _is_badge(url: str) -> bool:
    low = url.lower()
    if any(h in low for h in _BADGE_HOST_HINTS):
        return True
    if any(k in low for k in _BADGE_KEYWORDS):
        return True
    # svg 基本都是徽章/图标，项目截图很少用 svg
    if low.split("?")[0].endswith(".svg"):
        return True
    return False


def _extract_image_urls(markdown: str, raw_base: str) -> List[str]:
    """
    从 README 中提取图片 URL，包含 markdown ![](url) 与 HTML <img src="">。
    相对路径基于 raw_base 解析为 raw.githubusercontent 绝对地址。
    """
    found: List[str] = []

    # markdown 图片语法 ![alt](url "title")
    for m in re.findall(r"!\[[^\]]*\]\(([^)\s]+)", markdown):
        found.append(m)
    # HTML <img src="...">
    for m in re.findall(r"<img[^>]+src=[\"']([^\"']+)[\"']", markdown, flags=re.IGNORECASE):
        found.append(m)

    result: List[str] = []
    seen = set()
    for raw in found:
        url = raw.strip()
        if url.startswith("//"):
            url = "https:" + url
        elif not url.startswith("http"):
            url = urljoin(raw_base, url)  # 相对路径 -> 绝对
        if url in seen or _is_badge(url):
            continue
        seen.add(url)
        result.append(url)
    return result


def _fetch_repo(client: httpx.Client, owner: str, repo: str) -> EnrichedRepo:
    """调用 GitHub API 获取 README、homepage、topics 等。"""
    enriched: EnrichedRepo = {"owner": owner, "repo": repo}  # type: ignore[typeddict-item]

    # 1. 仓库基础信息：homepage（右上角链接）/ topics / 默认分支
    try:
        info = client.get(f"{API_BASE}/repos/{owner}/{repo}", headers=_auth_headers())
        info.raise_for_status()
        data = info.json()
        enriched["homepage"] = data.get("homepage") or ""
        enriched["topics"] = data.get("topics") or []
        default_branch = data.get("default_branch", "main")
    except Exception as e:
        log("enrich", f"{owner}/{repo} 基础信息获取失败: {e}", "warn")
        default_branch = "main"
        enriched["homepage"] = ""
        enriched["topics"] = []

    # 2. README 正文 + 用于解析相对图片的 raw base
    try:
        readme_resp = client.get(
            f"{API_BASE}/repos/{owner}/{repo}/readme", headers=_auth_headers()
        )
        readme_resp.raise_for_status()
        readme_json = readme_resp.json()
        download_url = readme_json.get("download_url") or ""
        # 直接用 download_url 拿原文（已是解码后的纯文本）
        text = client.get(download_url).text if download_url else ""
        raw_base = (
            download_url.rsplit("/", 1)[0] + "/"
            if download_url
            else f"https://raw.githubusercontent.com/{owner}/{repo}/{default_branch}/"
        )
    except Exception as e:
        log("enrich", f"{owner}/{repo} README 获取失败: {e}", "warn")
        text = ""
        raw_base = f"https://raw.githubusercontent.com/{owner}/{repo}/{default_branch}/"

    enriched["image_candidates"] = _extract_image_urls(text, raw_base) if text else []
    enriched["readme"] = text[: _readme_max_chars()]
    return enriched


def _enrich_one(
    client: httpx.Client, repo: dict, cache: JsonCache
) -> Tuple[EnrichedRepo, bool]:
    """补全单个仓库（供并行调用）。返回 (结果, 是否命中缓存)。"""
    base: EnrichedRepo = dict(repo)  # type: ignore[assignment]
    parsed = _split_owner_repo(repo["url"])
    if not parsed:
        base["image_candidates"] = []
        base["readme"] = ""
        return base, False
    owner, name = parsed

    # 缓存 key 含 owner/repo + README 截断长度；任一变化则自然失效
    key = make_key("enrich:v1", f"{owner}/{name}", str(_readme_max_chars()))
    cached = cache.get(key)
    if cached is not None:
        base.update(cached)
        return base, True

    fetched = _fetch_repo(client, owner, name)
    # 只缓存「确实抓到 README」的结果；失败/限流导致的空结果不写缓存，下次重试
    if fetched.get("readme"):
        cache.set(key, fetched)
    base.update(fetched)
    return base, False


def enrich_node(state: WeeklyState) -> dict:
    """
    LangGraph 节点：并行对每个 repo 抓取 README / 主页链接 / topics / 图片候选。
    """
    repos = state.get("repos", [])
    # 提交进仓库（cache/），让 CI 跨周复用，避免每次冷启动重抓 README
    cache = JsonCache("enrich", shared=True)

    # httpx.Client 线程安全，多线程共享一个连接池即可
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        with ThreadPoolExecutor(max_workers=_concurrency()) as pool:
            # executor.map 保序，输出顺序与 trending 排名一致
            results = list(pool.map(lambda r: _enrich_one(client, r, cache), repos))

    cache.save()
    enriched_list: List[EnrichedRepo] = [e for e, _ in results]
    hits = sum(1 for _, hit in results if hit)
    log(
        "enrich",
        f"完成 {len(enriched_list)} 个仓库的信息补全（缓存命中 {hits}，实抓 {len(enriched_list) - hits}）",
        "ok",
    )
    return {"enriched": enriched_list}

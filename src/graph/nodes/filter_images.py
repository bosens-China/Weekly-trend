import os
import re
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple
from urllib.parse import urlparse

import httpx
from PIL import Image, UnidentifiedImageError

from graph.nodes.output_report import REPORTS_DIR, compute_issue_and_date
from graph.state import EnrichedRepo, ImageCandidate, WeeklyState
from log import log

MAX_CANDIDATES_PER_REPO = 12  # 只处理 README 前若干张，避免周刊生成拖太久
MAX_IMAGES_PER_REPO = 1  # 周刊卡片保持克制：每个项目最多一张代表图
MIN_BYTES = 700
MIN_SIDE = 48
MIN_AREA = 4096

# Content-Type -> 本地扩展名（SVG 可由 GitHub Markdown 直接渲染）
_MIME_TO_EXT = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/bmp": "bmp",
    "image/svg+xml": "svg",
}
_EXT_ALLOWLIST = {"png", "jpg", "jpeg", "gif", "webp", "bmp", "svg"}

_DL_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

_POSITIVE_HINTS = (
    "screenshot",
    "screen-shot",
    "preview",
    "demo",
    "showcase",
    "example",
    "architecture",
    "diagram",
    "workflow",
    "flow",
    "ui",
    "interface",
    "dashboard",
    "app",
    "logo",
    "banner",
    "hero",
)
_NEGATIVE_HINTS = (
    "badge",
    "shield",
    "license",
    "coverage",
    "codecov",
    "actions/workflows",
    "build status",
    "version",
    "pypi",
    "npm",
    "downloads",
    "visitor",
    "stars history",
    "star-history",
    "sponsor",
    "donate",
    "buymeacoffee",
    "avatar",
    "contributor",
)


class DownloadedImage(NamedTuple):
    repo_index: int
    candidate: ImageCandidate
    path: Path
    size: Tuple[int, int]
    score: int


def _concurrency() -> int:
    return int(os.getenv("WEEKLY_CONCURRENCY") or 8)


def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", s or "")


def _coerce_candidate(raw: object, index: int) -> Optional[ImageCandidate]:
    """兼容旧缓存/手写测试里可能仍是字符串的图片候选。"""
    if isinstance(raw, dict) and raw.get("url"):
        return {
            "url": str(raw.get("url") or ""),
            "alt": str(raw.get("alt") or ""),
            "context": str(raw.get("context") or ""),
            "index": int(raw.get("index") or index),
        }
    if isinstance(raw, str) and raw:
        return {"url": raw, "alt": "", "context": "", "index": index}
    return None


def _url_ext(url: str) -> str:
    path = urlparse(url).path.lower()
    suffix = Path(path).suffix.lstrip(".")
    return "jpg" if suffix == "jpeg" else suffix


def _response_ext(resp: httpx.Response, url: str) -> Optional[str]:
    ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
    ext = _MIME_TO_EXT.get(ctype)
    if ext:
        return ext
    # 有些源站返回 application/octet-stream，但 URL 本身带图片扩展名。
    guessed = _url_ext(url)
    return guessed if guessed in _EXT_ALLOWLIST else None


def _text_for(candidate: ImageCandidate) -> str:
    return " ".join(
        [
            candidate.get("url", ""),
            candidate.get("alt", ""),
            candidate.get("context", ""),
        ]
    ).lower()


def _looks_bad_before_download(candidate: ImageCandidate) -> bool:
    text = f"{candidate.get('url', '')} {candidate.get('alt', '')}".lower()
    if any(h in text for h in _NEGATIVE_HINTS):
        return True
    if re.search(r"github\.com/.+/workflows/.+/badge\.svg", text):
        return True
    return False


def _svg_size(path: Path) -> Optional[Tuple[int, int]]:
    text = path.read_text(encoding="utf-8", errors="ignore")[:12000]
    if "<svg" not in text.lower():
        return None
    if any(h in text.lower() for h in ("shields.io", "badge", "coverage")):
        return None

    def parse_attr(name: str) -> Optional[float]:
        m = re.search(rf"\b{name}=[\"']([0-9.]+)", text, flags=re.IGNORECASE)
        return float(m.group(1)) if m else None

    width = parse_attr("width")
    height = parse_attr("height")
    if width and height:
        return int(width), int(height)

    viewbox = re.search(
        r"\bviewBox=[\"']\s*[0-9.]+\s+[0-9.]+\s+([0-9.]+)\s+([0-9.]+)",
        text,
        flags=re.IGNORECASE,
    )
    if viewbox:
        return int(float(viewbox.group(1))), int(float(viewbox.group(2)))
    # 没有尺寸的 SVG 仍可能是 logo/架构图，给一个保守尺寸让后续可选。
    return (160, 90)


def _image_size(path: Path) -> Optional[Tuple[int, int]]:
    if path.suffix.lower() == ".svg":
        return _svg_size(path)
    try:
        with Image.open(path) as img:
            return int(img.width), int(img.height)
    except (UnidentifiedImageError, OSError):
        return None


def _validate(path: Path) -> Optional[Tuple[int, int]]:
    if path.stat().st_size < MIN_BYTES:
        return None
    size = _image_size(path)
    if size is None:
        return None
    width, height = size
    if width < MIN_SIDE or height < MIN_SIDE:
        return None
    if width * height < MIN_AREA:
        return None
    return size


def _score(candidate: ImageCandidate, path: Path, size: Tuple[int, int]) -> int:
    """确定性打分：README 顺序为主，语义提示和尺寸为辅。"""
    text = _text_for(candidate)
    identity_text = f"{candidate.get('url', '')} {candidate.get('alt', '')}".lower()
    index = int(candidate.get("index") or 1)
    width, height = size
    area = width * height
    ratio = width / max(height, 1)

    score = 1000 - index * 18
    score += sum(85 for hint in _POSITIVE_HINTS if hint in text)
    score -= sum(140 for hint in _NEGATIVE_HINTS if hint in identity_text)

    if path.suffix.lower() == ".gif":
        score += 55
    if path.suffix.lower() == ".svg":
        score += 15
    if 1.25 <= ratio <= 4.5:
        score += 80  # README 里的截图、banner、架构图通常偏横向
    elif 0.8 <= ratio <= 1.25 and width >= 120:
        score += 35  # logo 常见为方图
    if area >= 160_000:
        score += 35
    if width < 120 or height < 80:
        score -= 90
    return score


def _download_one(
    client: httpx.Client, job: Tuple[int, ImageCandidate, Path]
) -> Optional[DownloadedImage]:
    """下载、验证并打分单张图片，失败返回 None。"""
    repo_index, candidate, out_base = job
    url = candidate["url"]
    try:
        resp = client.get(url, headers=_DL_HEADERS)
        resp.raise_for_status()
        ext = _response_ext(resp, url)
        if ext is None:
            ctype = resp.headers.get("content-type", "").split(";")[0].strip()
            log(
                "filter_images",
                f"跳过非图片/未知类型 [{ctype or '未知'}]: {url}",
                "dim",
            )
            return None

        out_path = out_base.with_suffix("." + ext)
        out_path.write_bytes(resp.content)
        size = _validate(out_path)
        if size is None:
            out_path.unlink(missing_ok=True)
            log("filter_images", f"跳过无效或过小图片: {url}", "dim")
            return None

        return DownloadedImage(
            repo_index, candidate, out_path, size, _score(candidate, out_path, size)
        )
    except Exception as e:
        log("filter_images", f"下载失败 {url}: {e}", "warn")
        return None


def filter_images_node(state: WeeklyState) -> dict:
    """
    LangGraph 节点：用确定性规则为每个仓库选择 README 代表图。

    不再调用多模态模型做相关性判断：先过滤明显 badge/统计/打赏图，下载真实图片并校验尺寸，
    再按 README 顺序、alt/context/URL 关键词与图片尺寸打分，每个项目保留 1 张代表图。
    """
    enriched: List[EnrichedRepo] = state.get("enriched", [])
    issue, date_str = compute_issue_and_date()

    tmp_dir = REPORTS_DIR / ".tmp"
    shutil.rmtree(tmp_dir, ignore_errors=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    jobs: List[Tuple[int, ImageCandidate, Path]] = []
    for ri, repo in enumerate(enriched):
        repo["relevant_images"] = []
        raw_candidates = repo.get("image_candidates", [])[:MAX_CANDIDATES_PER_REPO]
        owner = _safe(repo.get("owner", ""))
        repo_name = _safe(repo.get("repo", ""))
        for ci, raw in enumerate(raw_candidates):
            candidate = _coerce_candidate(raw, ci + 1)
            if candidate is None or _looks_bad_before_download(candidate):
                continue
            jobs.append((ri, candidate, tmp_dir / f"{owner}__{repo_name}__{ci}"))

    if not jobs:
        log("filter_images", "无可用图片候选", "info")
        return {
            "enriched": enriched,
            "issue_number": issue,
            "date_str": date_str,
            "tmp_assets_dir": str(tmp_dir),
        }

    log("filter_images", f"下载并校验 {len(jobs)} 张 README 图片候选…", "info")
    per_repo: Dict[int, List[DownloadedImage]] = {}
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        with ThreadPoolExecutor(max_workers=_concurrency()) as pool:
            for item in pool.map(lambda job: _download_one(client, job), jobs):
                if item is not None:
                    per_repo.setdefault(item.repo_index, []).append(item)

    total_selected = 0
    for ri, images in per_repo.items():
        ranked = sorted(images, key=lambda item: item.score, reverse=True)
        chosen = ranked[:MAX_IMAGES_PER_REPO]
        chosen_paths = {item.path for item in chosen}
        for item in images:
            if item.path not in chosen_paths:
                item.path.unlink(missing_ok=True)

        enriched[ri]["relevant_images"] = [
            f"assets/{item.path.name}" for item in chosen
        ]
        total_selected += len(chosen)
        if images:
            best = chosen[0] if chosen else ranked[0]
            w, h = best.size
            log(
                "filter_images",
                f"{enriched[ri].get('owner')}/{enriched[ri].get('repo')}: "
                f"{len(images)} 张有效图 -> {len(chosen)} 张代表图 "
                f"({best.path.name}, {w}x{h}, score={best.score})",
                "dim",
            )

    log("filter_images", f"共选出 {total_selected} 张代表图", "ok")
    return {
        "enriched": enriched,
        "issue_number": issue,
        "date_str": date_str,
        "tmp_assets_dir": str(tmp_dir),
    }

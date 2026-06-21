"""
极简的本地 JSON 文件缓存，用于避免重复浪费（重跑/跨周复现时少打 GitHub API、少调视觉模型）。

设计要点：
- 两个位置：
  - 共享缓存 `cache/`（提交进仓库，shared=True）：希望 CI 跨周复用的（enrich、视觉判定）。
    不提交的话 CI 每次全新 checkout 都会冷启动，缓存等于白做。
  - 本地缓存 `.cache/`（gitignored，shared=False）：可选，仅本地复用、不想进仓库时用。
- 每个命名空间一个文件 `<dir>/<name>.json`，结构为 {key: {"value": ..., "ts": <秒>}}。
- key 由调用方用 make_key(*parts) 生成：把「身份 + 关键参数 + prompt」拼起来做 sha256，
  这样一旦 prompt / 参数变化，旧缓存自然失效，不会读到「用旧逻辑算出来的结果」。
- TTL 默认 30 天（环境变量 CACHE_TTL_DAYS 可调）；**每次加载时直接丢弃超期条目**，
  防止 key 无限累加导致文件越来越大。
- 线程安全（enrich / filter_images 都是多线程跑的）。
"""

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parents[1]
LOCAL_CACHE_DIR = _ROOT / ".cache"  # gitignored，纯本地
SHARED_CACHE_DIR = _ROOT / "cache"  # 提交进仓库，供 CI 跨周复用


def _ttl_seconds() -> int:
    days = float(os.getenv("CACHE_TTL_DAYS") or 30)
    return int(days * 86400)


def make_key(*parts: str) -> str:
    """把若干字符串拼成一个稳定的缓存 key（sha256）。"""
    raw = "\x1f".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class JsonCache:
    def __init__(self, name: str, shared: bool = False):
        base = SHARED_CACHE_DIR if shared else LOCAL_CACHE_DIR
        self.path = base / f"{name}.json"
        self._lock = threading.Lock()
        self._data: dict[str, dict] = {}
        self._load_and_prune()

    def _load_and_prune(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            raw = {}
        now = time.time()
        ttl = _ttl_seconds()
        # 加载即清理：丢弃超过 TTL 的条目，控制文件大小
        self._data = {
            k: v
            for k, v in raw.items()
            if isinstance(v, dict) and (now - float(v.get("ts", 0))) <= ttl
        }

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._data.get(key)
            return entry.get("value") if entry else None

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = {"value": value, "ts": time.time()}

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self._data, ensure_ascii=False), encoding="utf-8"
            )

"""共享 JSON 缓存的底层存储。

当前缓存只用于保存 LLM 输出，并提交到 ``cache/`` 供 CI 跨周复用。业务层负责
把 Prompt、模型参数、输入和输出结构版本组成缓存 key；本模块只处理 TTL、
线程安全与原子落盘。
"""

import copy
import hashlib
import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

_ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = _ROOT / "cache"


def _ttl_seconds() -> int:
    days = float(os.getenv("CACHE_TTL_DAYS") or 30)
    return int(days * 86400)


def make_key(*parts: str) -> str:
    """把若干字符串拼成一个稳定的缓存 key（sha256）。"""
    raw = "\x1f".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class JsonCache:
    """一个命名空间对应一个 JSON 文件的线程安全 TTL 缓存。"""

    def __init__(self, name: str, directory: Path | None = None):
        base = directory or CACHE_DIR
        self.path = base / f"{name}.json"
        self._lock = threading.Lock()
        self._data: dict[str, dict[str, Any]] = {}
        self._load_and_prune()

    def _load_and_prune(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        now = time.time()
        ttl = _ttl_seconds()
        valid: dict[str, dict[str, Any]] = {}
        for key, entry in raw.items():
            if not isinstance(key, str) or not isinstance(entry, dict):
                continue
            try:
                age = now - float(entry.get("ts", 0))
            except (TypeError, ValueError):
                continue
            if age <= ttl:
                valid[key] = entry
        self._data = valid

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._data.get(key)
            return copy.deepcopy(entry.get("value")) if entry else None

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = {"value": copy.deepcopy(value), "ts": time.time()}

    def set_many_and_save(self, values: dict[str, Any]) -> None:
        """在同一把锁内批量覆盖并原子落盘。"""
        if not values:
            return
        with self._lock:
            now = time.time()
            for key, value in values.items():
                self._data[key] = {"value": copy.deepcopy(value), "ts": now}
            self._save_unlocked()

    def merge_many_and_save(
        self,
        values: dict[str, Any],
        merger: Callable[[Any, Any], Any],
    ) -> None:
        """原子合并多个 key，供并发批次更新同一项目的不同分片。"""
        if not values:
            return
        with self._lock:
            now = time.time()
            for key, value in values.items():
                entry = self._data.get(key)
                current = copy.deepcopy(entry.get("value")) if entry else None
                merged = merger(current, copy.deepcopy(value))
                self._data[key] = {"value": merged, "ts": now}
            self._save_unlocked()

    def save(self) -> None:
        """使用同目录临时文件原子替换，避免中途退出留下半个 JSON。"""
        with self._lock:
            self._save_unlocked()

    def _save_unlocked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = (
            json.dumps(self._data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        )
        fd, temp_name = tempfile.mkstemp(
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            text=True,
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as temp_file:
                temp_file.write(payload)
                temp_file.flush()
                os.fsync(temp_file.fileno())
            os.replace(temp_path, self.path)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

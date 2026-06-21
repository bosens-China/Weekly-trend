"""
统一的彩色日志小工具，供各节点使用。

- 默认开启 ANSI 颜色（GitHub Actions 日志也支持 ANSI）；
- 设置环境变量 NO_COLOR 可关闭颜色（纯文本输出）。
"""

import os

_ENABLE = os.getenv("NO_COLOR") is None

_C = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "cyan": "\033[36m",
}

# 每个阶段一个主色，方便扫日志时区分
_STAGE_COLOR = {
    "crawler": "cyan",
    "enrich": "blue",
    "filter_images": "magenta",
    "generate_report": "green",
    "output_report": "yellow",
    "main": "bold",
}


def _wrap(color: str, text: str) -> str:
    if not _ENABLE or not color:
        return text
    return f"{_C.get(color, '')}{text}{_C['reset']}"


def log(stage: str, msg: str, level: str = "info") -> None:
    """
    打印一行带阶段标签的日志。
    level: info（默认）/ ok（绿）/ warn（黄，自动加 ⚠️）/ error（红）/ dim（灰）。
    """
    tag = _wrap(_STAGE_COLOR.get(stage, "cyan"), f"[{stage}]")
    if level == "ok":
        msg = _wrap("green", msg)
    elif level == "warn":
        msg = _wrap("yellow", "⚠️ " + msg)
    elif level == "error":
        msg = _wrap("red", msg)
    elif level == "dim":
        msg = _wrap("dim", msg)
    print(f"{tag} {msg}")

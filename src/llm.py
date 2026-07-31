import os
from typing import TypedDict

from langchain_openai import ChatOpenAI


class LlmSettings(TypedDict):
    """会影响 LLM 输出、因此也必须参与缓存 key 的配置。"""

    model: str
    base_url: str
    temperature: float


def get_llm_settings(temperature: float = 0.3) -> LlmSettings:
    """读取统一的模型配置，供模型工厂与缓存键共同使用。"""
    return {
        "model": os.getenv("OPENAI_MODEL") or "gpt-4o",
        "base_url": os.getenv("OPENAI_BASE_URL") or "",
        "temperature": temperature,
    }


def get_llm(temperature: float = 0.3) -> ChatOpenAI:
    """
    统一的 ChatOpenAI 工厂。

    通过环境变量配置：
    - OPENAI_API_KEY : 必填
    - OPENAI_MODEL   : 模型名，默认 gpt-4o（自带视觉能力）
    - OPENAI_BASE_URL: 可选，走代理/自建网关时设置
    """
    settings = get_llm_settings(temperature)

    kwargs: dict = {
        "model": settings["model"],
        "temperature": settings["temperature"],
    }
    if settings["base_url"]:
        kwargs["base_url"] = settings["base_url"]

    return ChatOpenAI(**kwargs)

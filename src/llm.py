import os

from langchain_openai import ChatOpenAI


def get_llm(temperature: float = 0.3) -> ChatOpenAI:
    """
    统一的 ChatOpenAI 工厂。

    通过环境变量配置：
    - OPENAI_API_KEY : 必填
    - OPENAI_MODEL   : 模型名，默认 gpt-4o（自带视觉能力）
    - OPENAI_BASE_URL: 可选，走代理/自建网关时设置
    """
    # 注意用 `or` 兜底：CI 里未配置的变量会注入空字符串，getenv 的默认值不会生效
    model = os.getenv("OPENAI_MODEL") or "gpt-4o"
    base_url = os.getenv("OPENAI_BASE_URL")  # 为空则用官方地址

    kwargs: dict = {"model": model, "temperature": temperature}
    if base_url:
        kwargs["base_url"] = base_url

    return ChatOpenAI(**kwargs)

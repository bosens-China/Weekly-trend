import os
from pathlib import Path

from dotenv import load_dotenv

# 本地运行时自动读取项目根目录的 .env（CI 用 secrets/vars，没有 .env 也不报错）
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from graph.build import build_graph  # noqa: E402  （需在 load_dotenv 之后导入）
from log import log  # noqa: E402


def main():
    """
    入口：跑完整的「抓取 -> 补全 -> 图片过滤 -> 生成 -> 写盘」流程。
    供本地与 CI 调用。
    """
    # 未配置 LLM 凭证则直接跳过，不执行后续任何步骤
    if not os.getenv("OPENAI_API_KEY"):
        log("main", "未检测到 OPENAI_API_KEY，跳过本次周刊生成。"
                    "（本地请在 .env 配置，CI 请在 Secrets 配置）", "warn")
        return None

    log("main", "开始生成本周周刊…")
    graph = build_graph()
    result = graph.invoke({})
    path = result.get("output_path")
    if path:
        log("main", f"周刊已生成：{path}（第 {result.get('issue_number')} 期）", "ok")
    else:
        log("main", "未生成周刊，请检查日志。", "warn")
    return result


if __name__ == "__main__":
    main()

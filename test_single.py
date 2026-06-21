"""
单仓库冒烟测试：把完整链路在「一个仓库」上跑一遍，逐步打印结果，方便排查。

用法：
    uv run python test_single.py            # 默认取 trending 第 1 个仓库
    uv run python test_single.py 3          # 取第 4 个（下标从 0 起）
    uv run python test_single.py langchain  # 按 owner/repo 模糊匹配第一个命中的

会做：crawler 抓列表 -> 取 1 个 -> enrich -> filter_images（下载+识图）-> generate_report
不会做：不写正式周刊文件（只打印正文）。被选中的图片会落在 reports/assets/<期数>/ 供预览。
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))


def _hr(title: str) -> None:
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def main() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        print("❌ 未检测到 OPENAI_API_KEY，请先在 .env 配置后再跑。")
        return

    from graph.nodes.crawler import crawler
    from graph.nodes.enrich import enrich_node
    from graph.nodes.filter_images import filter_images_node
    from graph.nodes.generate_report import generate_report_node
    from graph.state import WeeklyState

    # ---------- 1. 抓 trending 列表，挑一个仓库 ----------
    _hr("1) crawler 抓取 trending")
    repos = crawler()
    if not repos:
        print("❌ 没抓到任何仓库（可能被限流/网络问题），无法继续。")
        return
    print(f"共抓到 {len(repos)} 个仓库。")

    arg = sys.argv[1] if len(sys.argv) > 1 else "0"
    if arg.isdigit():
        idx = int(arg)
        if idx >= len(repos):
            print(f"❌ 下标 {idx} 越界（共 {len(repos)} 个）。")
            return
        chosen = repos[idx]
    else:
        match = [r for r in repos if arg.lower() in r["name"].lower()]
        if not match:
            print(f"❌ 没有匹配 '{arg}' 的仓库。")
            return
        chosen = match[0]

    print(f"👉 选中：{chosen['name']}  ({chosen['url']})")
    print(f"   {chosen['description']}")
    print(f"   ⭐ {chosen['total_stars']} | 🔥 {chosen['period_stars']} | 💻 {chosen['language']}")

    # 单仓库 state，后续节点逐个加工
    state: WeeklyState = {"repos": [chosen]}

    # ---------- 2. enrich：补 README / homepage / topics / 图片候选 ----------
    _hr("2) enrich 补全信息")
    enriched_out = enrich_node(state)
    state.update(enriched_out)
    e = enriched_out["enriched"][0]
    print(f"homepage : {e.get('homepage') or '(无)'}")
    print(f"topics   : {e.get('topics') or '(无)'}")
    print(f"readme   : {len(e.get('readme', ''))} 字")
    cands = e.get("image_candidates", [])
    print(f"图片候选 : {len(cands)} 张")
    for i, u in enumerate(cands[:10], 1):
        print(f"   {i}. {u}")

    # ---------- 3. filter_images：下载 + 多模态识图 ----------
    _hr("3) filter_images 下载并识别项目相关图")
    filtered_out = filter_images_node(state)
    state.update(filtered_out)
    rel = filtered_out["enriched"][0].get("relevant_images", [])
    tmp_dir = filtered_out.get("tmp_assets_dir", "")
    print(f"\n判定为项目相关的图片：{len(rel)} 张（临时目录 {tmp_dir}，正式运行时被正文引用的才会移入 assets/）")
    for p in rel:
        name = p.split("/")[-1]
        print(f"   ✅ {tmp_dir}/{name}")

    # ---------- 4. generate_report：生成中文正文 ----------
    _hr("4) generate_report 生成中文正文")
    state.update(generate_report_node(state))
    print("\n----- 周刊正文（单仓库）-----\n")
    print(state.get("report_md", "(空)"))
    print("\n----------------------------")
    print("\n✅ 测试结束（未写正式周刊；如有相关图片见 reports/assets/）。")


if __name__ == "__main__":
    main()

from typing import List, TypedDict

from graph.nodes.crawler import RepoData


class EnrichedRepo(RepoData, total=False):
    """在 RepoData 基础上补充：从仓库主页/README 拉取的信息。"""

    owner: str  # 仓库所有者
    repo: str  # 仓库名（不含 owner）
    homepage: str  # 右上角的项目主页链接（About -> Website）
    topics: List[str]  # 仓库 topics 标签
    readme: str  # README 正文（已截断）
    image_candidates: List[str]  # 从 README 提取、启发式初筛后的图片 URL
    relevant_images: List[str]  # 多模态判定为「项目相关」的图片 URL


class WeeklyState(TypedDict, total=False):
    """贯穿整个 LangGraph 流程的状态。"""

    repos: List[RepoData]  # crawler 节点产出的原始列表
    enriched: List[EnrichedRepo]  # enrich / filter_images 逐步补全
    report_md: str  # generate_report 产出的 markdown 正文
    issue_number: int  # 第几期
    date_str: str  # 报告日期 yyyy_mm_dd
    output_path: str  # 最终写入的文件路径

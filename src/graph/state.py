from typing import List, TypedDict

from graph.nodes.crawler import RepoData


class ImageCandidate(TypedDict):
    """从 README 中提取的图片候选，保留用于规则选图的上下文。"""

    url: str
    alt: str
    context: str
    index: int


class EnrichedRepo(RepoData, total=False):
    """在 RepoData 基础上补充：从仓库主页/README 拉取的信息。"""

    owner: str  # 仓库所有者
    repo: str  # 仓库名（不含 owner）
    homepage: str  # 右上角的项目主页链接（About -> Website）
    topics: List[str]  # 仓库 topics 标签
    readme: str  # README 正文（已截断）
    image_candidates: List[ImageCandidate]  # README 图片 URL 与上下文
    relevant_images: List[str]  # 确定性规则选出的代表图片路径（assets/xxx）


class WeeklyState(TypedDict, total=False):
    """贯穿整个 LangGraph 流程的状态。"""

    repos: List[RepoData]  # crawler 节点产出的原始列表
    enriched: List[EnrichedRepo]  # enrich / filter_images 逐步补全
    report_json: dict  # generate_report 产出的结构化周刊数据
    report_md: str  # generate_report 产出的 markdown 正文
    issue_number: int  # 第几期
    date_str: str  # 报告日期 yyyy_mm_dd
    tmp_assets_dir: str  # 候选图片的临时目录（被正文引用的才会移入正式 assets）
    output_path: str  # 最终写入的文件路径

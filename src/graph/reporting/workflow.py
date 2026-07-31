"""LangGraph 报告子工作流的节点与编排。"""

import json
import operator
from functools import partial
from typing import Annotated, List, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import RetryPolicy, Send

from graph.reporting.batching import (
    SPLIT_STRATEGY_VERSION,
    batch_chars,
    build_report_units,
    compact_repo_payload,
    pack_report_units,
    report_concurrency,
)
from graph.reporting.common import count_items, parse_json_object
from graph.reporting.llm_cache import (
    CacheStage,
    LlmOutputCache,
    ProjectCacheRef,
    ProjectPartsWrite,
)
from graph.reporting.normalization import (
    merge_batch_results,
    normalize_batch_json,
    normalize_overview,
    normalize_report_json,
    top_categories,
)
from graph.reporting.prompts import ANALYZE_SYSTEM, ORGANIZE_SYSTEM, OVERVIEW_SYSTEM
from graph.reporting.rendering import render_markdown
from graph.state import EnrichedRepo, WeeklyState
from llm import get_llm
from log import log


class ReportState(TypedDict, total=False):
    """报告生成子工作流状态。"""

    enriched: List[EnrichedRepo]
    report_batches: List[dict]
    report_batch: dict
    batch_results: Annotated[List[dict], operator.add]
    project_cache_refs: dict[str, ProjectCacheRef]
    report_json: dict
    report_md: str


class LlmOutputParseError(ValueError):
    """LLM 返回内容不是预期 JSON；与可重试的网络错误区分。"""


ANALYZE_USER_TEMPLATE = "本批共 {count} 条材料：\n{items}"


def _invoke_json(
    llm_cache: LlmOutputCache,
    stage: CacheStage,
    system_prompt: str,
    user_content: str,
    temperature: float = 0.2,
) -> dict:
    """优先读取缓存；未命中时调用模型，并只缓存解析成功的 JSON。"""
    cached = llm_cache.get(stage, system_prompt, user_content, temperature)
    if cached is not None:
        log("generate_report", f"{stage} 命中 LLM 输出缓存", "ok")
        return cached

    raw = _invoke_uncached_json(system_prompt, user_content, temperature)
    llm_cache.set(stage, system_prompt, user_content, temperature, raw)
    return raw


def _invoke_uncached_json(
    system_prompt: str,
    user_content: str,
    temperature: float = 0.2,
) -> dict:
    """调用模型并解析 JSON；网络错误交给 LangGraph RetryPolicy 处理。"""
    model = get_llm(temperature=temperature)
    msg = model.invoke(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
    )
    text = msg.content if isinstance(msg.content, str) else str(msg.content)
    try:
        return parse_json_object(text)
    except Exception as exc:  # noqa: BLE001
        raise LlmOutputParseError(str(exc)) from exc


def _project_cache_content(repo: EnrichedRepo, split_limit: int) -> str:
    """生成项目级缓存输入；完整 README 只参与哈希，不进入缓存文件。"""
    return json.dumps(
        {
            "analysis_user_template": ANALYZE_USER_TEMPLATE,
            "split_strategy": SPLIT_STRATEGY_VERSION,
            "split_limit": split_limit,
            "project": compact_repo_payload(repo),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _analysis_user_content(items: list[dict]) -> str:
    """生成批次分析的用户消息，模板本身同时参与项目级缓存 key。"""
    return ANALYZE_USER_TEMPLATE.format(
        count=len(items),
        items=json.dumps(items, ensure_ascii=False),
    )


def prepare_report_batches_node(
    state: ReportState,
    llm_cache: LlmOutputCache | None = None,
) -> dict:
    """先按项目查缓存，只把未命中的项目分片装入 LLM 批次。"""
    enriched = state.get("enriched", [])
    cache = llm_cache or LlmOutputCache()
    max_chars = batch_chars()
    units = build_report_units(enriched, max_chars)
    units_by_repo: dict[str, list[dict]] = {}
    for unit in units:
        units_by_repo.setdefault(str(unit.get("repo", "")), []).append(unit)

    cached_items: list[dict] = []
    pending_units: list[dict] = []
    refs: dict[str, ProjectCacheRef] = {}
    complete_hits = 0
    partial_hits = 0
    for repo in enriched:
        payload = compact_repo_payload(repo)
        repo_name = str(payload["repo"])
        project_units = units_by_repo.get(repo_name, [])
        part_total = len(project_units)
        ref = cache.project_ref(
            repo_name,
            ANALYZE_SYSTEM,
            _project_cache_content(repo, max_chars),
            0.2,
            part_total,
        )
        refs[repo_name] = ref
        cached_parts = cache.get_project_parts(ref)
        if len(cached_parts) == part_total and part_total > 0:
            complete_hits += 1
        elif cached_parts:
            partial_hits += 1
        for unit in project_units:
            part_index = int(unit.get("part_index", 1))
            cached = cached_parts.get(part_index)
            if cached is not None:
                cached_items.append(cached)
            else:
                pending_units.append(unit)

    batches = pack_report_units(pending_units, max_chars)
    if batches:
        sizes = [batch["char_count"] for batch in batches]
        log(
            "generate_report",
            f"{len(enriched)} 个项目中完整缓存命中 {complete_hits} 个、"
            f"部分命中 {partial_hits} 个；其余材料拆成 {len(batches)} 批，"
            f"每批 {min(sizes)}～{max(sizes)} 字符，并发上限 {report_concurrency()}",
        )
    else:
        log(
            "generate_report",
            f"{len(enriched)} 个项目全部命中项目级 LLM 缓存",
            "ok",
        )
    cached_result = [{"batch_index": -1, "items": cached_items}] if cached_items else []
    return {
        "report_batches": batches,
        "batch_results": cached_result,
        "project_cache_refs": refs,
    }


def dispatch_report_batches(state: ReportState) -> List[Send] | str:
    batches = state.get("report_batches", [])
    if not batches:
        return "organize_report"
    refs = state.get("project_cache_refs", {})
    sends: list[Send] = []
    for batch in batches:
        repo_names = {str(item.get("repo", "")) for item in batch.get("items", [])}
        batch_refs = {name: refs[name] for name in repo_names if name in refs}
        sends.append(
            Send(
                "analyze_report_batch",
                {
                    "report_batch": batch,
                    "project_cache_refs": batch_refs,
                },
            )
        )
    return sends


def analyze_report_batch_node(
    state: ReportState,
    llm_cache: LlmOutputCache | None = None,
) -> dict:
    batch = state.get("report_batch")
    if batch is None:
        raise ValueError("analyze_report_batch 缺少 report_batch")
    cache = llm_cache or LlmOutputCache()
    items = batch.get("items", [])
    user_content = _analysis_user_content(items)
    try:
        raw = _invoke_uncached_json(ANALYZE_SYSTEM, user_content)
    except LlmOutputParseError as exc:
        log(
            "generate_report",
            f"第 {batch['batch_index'] + 1} 批 JSON 解析失败，保留 topics 兜底: {exc}",
            "warn",
        )
        raw = {"items": []}

    normalized = normalize_batch_json(raw, batch)
    refs = state.get("project_cache_refs", {})
    outputs_by_repo: dict[str, list[dict]] = {}
    for output in normalized["items"]:
        # 解析失败时两个说明字段都为空，不缓存兜底结果。
        if output.get("summary") or output.get("plain_explanation"):
            outputs_by_repo.setdefault(str(output.get("repo", "")), []).append(output)
    writes: list[ProjectPartsWrite] = [
        {"ref": refs[repo_name], "parts": outputs}
        for repo_name, outputs in outputs_by_repo.items()
        if repo_name in refs
    ]
    cache.merge_project_parts(writes)
    log(
        "generate_report",
        f"第 {batch['batch_index'] + 1} 批完成后写入 {len(writes)} 个项目缓存",
        "ok",
    )
    return {"batch_results": [normalized]}


def organize_report_node(
    state: ReportState,
    llm_cache: LlmOutputCache | None = None,
) -> dict:
    enriched = state.get("enriched", [])
    if not enriched:
        return {
            "report_json": {
                "version": 2,
                "source": "GitHub Trending（本周）",
                "categories": [],
            }
        }

    drafts = merge_batch_results(state.get("batch_results", []), enriched)
    cache = llm_cache or LlmOutputCache()
    user_content = f"本周共 {len(drafts)} 个仓库，请确保全部覆盖：\n" + json.dumps(
        drafts, ensure_ascii=False
    )
    try:
        raw = _invoke_json(
            cache,
            "organize_report",
            ORGANIZE_SYSTEM,
            user_content,
        )
    except LlmOutputParseError as exc:
        log("generate_report", f"全局分类 JSON 解析失败，使用批次草稿: {exc}", "warn")
        raw = {"categories": []}
    return {"report_json": normalize_report_json(raw, enriched, drafts)}


def generate_overview_node(
    state: ReportState,
    llm_cache: LlmOutputCache | None = None,
) -> dict:
    report_json = state.get(
        "report_json",
        {"version": 2, "source": "GitHub Trending（本周）", "categories": []},
    )
    project_count = count_items(report_json)
    if project_count <= 0:
        return {"report_json": {**report_json, "overview": ""}}

    featured_categories = top_categories(report_json)
    payload = {
        "project_count": project_count,
        "top_categories": featured_categories,
    }
    cache = llm_cache or LlmOutputCache()
    user_content = json.dumps(payload, ensure_ascii=False)
    try:
        raw = _invoke_json(
            cache,
            "generate_overview",
            OVERVIEW_SYSTEM,
            user_content,
        )
    except LlmOutputParseError as exc:
        log("generate_report", f"周刊导语 JSON 解析失败，使用数量兜底: {exc}", "warn")
        raw = {}
    overview = normalize_overview(raw.get("overview"), project_count)
    log(
        "generate_report",
        f"生成 {len(overview)} 字周刊导语，依据分类: "
        + "、".join(category["name"] for category in featured_categories),
        "ok",
    )
    return {"report_json": {**report_json, "overview": overview}}


def render_report_node(state: ReportState) -> dict:
    report_json = state.get(
        "report_json",
        {"version": 2, "source": "GitHub Trending（本周）", "categories": []},
    )
    body = render_markdown(report_json)
    covered = count_items(report_json)
    total = len(state.get("enriched", []))
    log(
        "generate_report",
        f"生成 JSON 分类 {len(report_json.get('categories', []))} 个，"
        f"覆盖 {covered}/{total} 个仓库，Markdown {len(body)} 字",
        "ok" if covered == total else "warn",
    )
    return {"report_md": body}


def build_report_workflow(
    llm_cache: LlmOutputCache | None = None,
) -> CompiledStateGraph[ReportState, None, ReportState, ReportState]:
    """构建智能分块、并发分析、分类、导语与渲染子工作流。"""
    cache = llm_cache or LlmOutputCache()
    builder = StateGraph(ReportState)
    builder.add_node(
        "prepare_report_batches",
        partial(prepare_report_batches_node, llm_cache=cache),
    )
    builder.add_node(
        "analyze_report_batch",
        partial(analyze_report_batch_node, llm_cache=cache),
        retry_policy=RetryPolicy(max_attempts=3, initial_interval=1.0),
    )
    builder.add_node(
        "organize_report",
        partial(organize_report_node, llm_cache=cache),
        retry_policy=RetryPolicy(max_attempts=3, initial_interval=1.0),
    )
    builder.add_node(
        "generate_overview",
        partial(generate_overview_node, llm_cache=cache),
        retry_policy=RetryPolicy(max_attempts=3, initial_interval=1.0),
    )
    builder.add_node("render_report", render_report_node)

    builder.add_edge(START, "prepare_report_batches")
    builder.add_conditional_edges(
        "prepare_report_batches",
        dispatch_report_batches,
        ["analyze_report_batch", "organize_report"],
    )
    builder.add_edge("analyze_report_batch", "organize_report")
    builder.add_edge("organize_report", "generate_overview")
    builder.add_edge("generate_overview", "render_report")
    builder.add_edge("render_report", END)
    return builder.compile()


def generate_report_node(state: WeeklyState) -> dict:
    """兼容单仓库冒烟测试：直接执行报告子工作流。"""
    result = build_report_workflow().invoke(
        {"enriched": state.get("enriched", [])},
        {"max_concurrency": report_concurrency()},
    )
    return {
        "report_json": result.get("report_json", {}),
        "report_md": result.get("report_md", ""),
    }

"""LangGraph 报告子工作流的节点与编排。"""

import json
import operator
from typing import Annotated, List, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import RetryPolicy, Send

from graph.reporting.batching import build_report_batches, report_concurrency
from graph.reporting.common import count_items, parse_json_object
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
    report_json: dict
    report_md: str


def prepare_report_batches_node(state: ReportState) -> dict:
    enriched = state.get("enriched", [])
    batches = build_report_batches(enriched)
    if batches:
        sizes = [batch["char_count"] for batch in batches]
        log(
            "generate_report",
            f"将 {len(enriched)} 个仓库拆成 {len(batches)} 批，"
            f"每批 {min(sizes)}～{max(sizes)} 字符，并发上限 {report_concurrency()}",
        )
    return {"report_batches": batches, "batch_results": []}


def dispatch_report_batches(state: ReportState) -> List[Send] | str:
    batches = state.get("report_batches", [])
    if not batches:
        return "organize_report"
    return [Send("analyze_report_batch", {"report_batch": batch}) for batch in batches]


def analyze_report_batch_node(state: ReportState) -> dict:
    batch = state.get("report_batch")
    if batch is None:
        raise ValueError("analyze_report_batch 缺少 report_batch")
    model = get_llm(temperature=0.2)
    msg = model.invoke(
        [
            {"role": "system", "content": ANALYZE_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"这是第 {batch['batch_index'] + 1} 批，共 "
                    f"{len(batch.get('items', []))} 条材料：\n"
                    + json.dumps(batch.get("items", []), ensure_ascii=False)
                ),
            },
        ]
    )
    text = msg.content if isinstance(msg.content, str) else str(msg.content)
    try:
        raw = parse_json_object(text)
    except Exception as exc:  # noqa: BLE001
        log(
            "generate_report",
            f"第 {batch['batch_index'] + 1} 批 JSON 解析失败，保留 topics 兜底: {exc}",
            "warn",
        )
        raw = {"items": []}
    return {"batch_results": [normalize_batch_json(raw, batch)]}


def organize_report_node(state: ReportState) -> dict:
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
    model = get_llm(temperature=0.2)
    msg = model.invoke(
        [
            {"role": "system", "content": ORGANIZE_SYSTEM},
            {
                "role": "user",
                "content": f"本周共 {len(drafts)} 个仓库，请确保全部覆盖：\n"
                + json.dumps(drafts, ensure_ascii=False),
            },
        ]
    )
    text = msg.content if isinstance(msg.content, str) else str(msg.content)
    try:
        raw = parse_json_object(text)
    except Exception as exc:  # noqa: BLE001
        log("generate_report", f"全局分类 JSON 解析失败，使用批次草稿: {exc}", "warn")
        raw = {"categories": []}
    return {"report_json": normalize_report_json(raw, enriched, drafts)}


def generate_overview_node(state: ReportState) -> dict:
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
    model = get_llm(temperature=0.2)
    msg = model.invoke(
        [
            {"role": "system", "content": OVERVIEW_SYSTEM},
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False),
            },
        ]
    )
    text = msg.content if isinstance(msg.content, str) else str(msg.content)
    try:
        raw = parse_json_object(text)
    except Exception as exc:  # noqa: BLE001
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


def build_report_workflow() -> CompiledStateGraph[
    ReportState, None, ReportState, ReportState
]:
    """构建智能分块、并发分析、分类、导语与渲染子工作流。"""
    builder = StateGraph(ReportState)
    builder.add_node("prepare_report_batches", prepare_report_batches_node)
    builder.add_node(
        "analyze_report_batch",
        analyze_report_batch_node,
        retry_policy=RetryPolicy(max_attempts=3, initial_interval=1.0),
    )
    builder.add_node(
        "organize_report",
        organize_report_node,
        retry_policy=RetryPolicy(max_attempts=3, initial_interval=1.0),
    )
    builder.add_node(
        "generate_overview",
        generate_overview_node,
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

"""报告子工作流的兼容入口。

具体职责已拆分到 ``graph.reporting`` 包；主图和既有调用方继续从本模块导入。
"""

from graph.reporting.batching import (
    build_report_batches as _build_report_batches,
)
from graph.reporting.batching import (
    report_concurrency,
)
from graph.reporting.common import parse_json_object as _parse_json_object
from graph.reporting.normalization import (
    normalize_overview as _normalize_overview,
)
from graph.reporting.normalization import (
    normalize_report_json as _normalize_report_json,
)
from graph.reporting.normalization import (
    top_categories as _top_categories,
)
from graph.reporting.rendering import render_markdown as _render_markdown
from graph.reporting.workflow import (
    analyze_report_batch_node,
    build_report_workflow,
    dispatch_report_batches,
    generate_overview_node,
    generate_report_node,
    organize_report_node,
    prepare_report_batches_node,
    render_report_node,
)

__all__ = [
    "analyze_report_batch_node",
    "build_report_workflow",
    "dispatch_report_batches",
    "generate_report_node",
    "generate_overview_node",
    "organize_report_node",
    "prepare_report_batches_node",
    "render_report_node",
    "report_concurrency",
    "_build_report_batches",
    "_normalize_report_json",
    "_normalize_overview",
    "_parse_json_object",
    "_render_markdown",
    "_top_categories",
]

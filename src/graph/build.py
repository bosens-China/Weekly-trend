from langgraph.graph import END, START, StateGraph

from graph.nodes.crawler import crawler_node
from graph.nodes.enrich import enrich_node
from graph.nodes.filter_images import filter_images_node
from graph.nodes.generate_report import generate_report_node
from graph.nodes.output_report import output_report_node
from graph.state import WeeklyState


def build_graph():
    """
    构建周刊生成流程：
    crawler -> enrich -> filter_images -> generate_report -> output_report
    """
    builder = StateGraph(WeeklyState)

    builder.add_node("crawler", crawler_node)
    builder.add_node("enrich", enrich_node)
    builder.add_node("filter_images", filter_images_node)
    builder.add_node("generate_report", generate_report_node)
    builder.add_node("output_report", output_report_node)

    builder.add_edge(START, "crawler")
    builder.add_edge("crawler", "enrich")
    builder.add_edge("enrich", "filter_images")
    builder.add_edge("filter_images", "generate_report")
    builder.add_edge("generate_report", "output_report")
    builder.add_edge("output_report", END)

    return builder.compile()

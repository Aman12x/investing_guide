import logging

from langgraph.graph import StateGraph, END

from agent.nodes.analyst import analyst_node
from agent.nodes.formatter import FormatterError, formatter_node, formatter_router
from agent.nodes.planner import planner_node
from agent.nodes.reflector import reflector_node
from agent.nodes.sufficiency import check_sufficiency, sufficiency_router
from agent.nodes.tools import fetch_node
from agent.state import AgentState

logger = logging.getLogger(__name__)


def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("planner", planner_node)
    graph.add_node("fetch", fetch_node)
    graph.add_node("sufficiency", check_sufficiency)
    graph.add_node("analyst", analyst_node)
    graph.add_node("reflector", reflector_node)
    graph.add_node("formatter", formatter_node)

    graph.set_entry_point("planner")
    graph.add_edge("planner", "fetch")
    graph.add_edge("fetch", "sufficiency")
    graph.add_conditional_edges(
        "sufficiency",
        sufficiency_router,
        {"proceed": "analyst", "fetch_more": "fetch"},
    )
    graph.add_edge("analyst", "reflector")
    graph.add_edge("reflector", "formatter")
    graph.add_conditional_edges(
        "formatter",
        formatter_router,
        {"end": END, "retry_analyst": "analyst"},
    )

    return graph.compile()


agent = build_graph()

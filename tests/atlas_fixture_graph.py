"""Opt-in native API fixture: real graphs, deterministic model/search substitutes.

Use tests/atlas_fixture_server.py with tests/atlas-langgraph.json, or the isolated
recovery fixture. No production .env is loaded and no model or search request is
made by this graph.
"""

import os
from types import SimpleNamespace

# Set the test environment BEFORE importing any module that constructs models.
for role in (
    "SCOPING",
    "SUPERVISOR",
    "RESEARCHER",
    "SUMMARIZATION",
    "COMPRESSION",
    "FINAL_REPORT",
):
    os.environ[f"{role}_MODEL"] = "fixture/model"
    os.environ[f"{role}_PROVIDER"] = "openai"
    os.environ[f"{role}_API_KEY"] = "fixture-not-a-real-key"
os.environ["LLM_API_KEY"] = "fixture-not-a-real-key"
os.environ["TAVILY_API_KEY"] = "fixture-not-a-real-key"
os.environ["LANGSMITH_TRACING"] = "false"

from langchain_core.messages import AIMessage, ToolMessage
from deep_research import research_agent_full as full
from deep_research import research_agent_scope as scope
from deep_research import multi_agent_supervisor as supervisor
from deep_research import research_agent_skills as researcher
from deep_research.utils import format_search_output


REPORT = """# Python 对比报告（API 测试替身）

本报告验证接口和状态传递，内容来自固定测试替身，不是实际研究结论。
默认构建与 free-threaded 构建需要分别核对运行方式、C 扩展支持和当前限制。[1]
真实产品使用时应以官方文档为依据。本例验证澄清问题、同会话补充回答、研究简报、
协调器委派、研究工具结果、笔记压缩、最终报告及刷新回读的完整流程。

## Sources
[1] [Python 文档](https://docs.python.org/3.13/howto/free-threading-python.html)
"""


def structured(_model, schema, prompt):
    if schema is scope.ResearchQuestion:
        return schema(
            research_brief="Python 3.13 free-threaded 与默认构建的比较（测试替身）"
        )
    ready = "Python 3.13" in prompt
    return schema(
        need_clarification=not ready,
        question="请补充比较对象和范围。" if not ready else "",
        verification="范围已明确，开始研究。" if ready else "",
    )


async def plan(messages):
    done = any(
        isinstance(message, ToolMessage) and message.name == "ConductResearch"
        for message in messages
    )
    return AIMessage(
        content="",
        tool_calls=[
            {
                "id": "finished" if done else "delegate",
                "name": "ResearchComplete" if done else "ConductResearch",
                "args": {}
                if done
                else {"research_topic": "Python 3.13 free-threading 官方资料"},
            }
        ],
    )


def research(messages):
    if any(
        isinstance(message, ToolMessage) and message.name == "tavily_search"
        for message in messages
    ):
        return AIMessage(content="已取得资料，开始汇总。（测试替身）")
    return AIMessage(
        content="",
        tool_calls=[
            {
                "id": "search",
                "name": "tavily_search",
                "args": {"query": "Python free-threading"},
            }
        ],
    )


async def write(messages):
    return AIMessage(content=REPORT)


scope.invoke_with_structured_output_fallback = structured
supervisor.supervisor_model_with_tools = SimpleNamespace(ainvoke=plan)
researcher.model_with_tools = SimpleNamespace(invoke=research)
researcher.compress_model = SimpleNamespace(
    invoke=lambda messages: AIMessage(content=REPORT)
)
researcher.tools_by_name["tavily_search"] = SimpleNamespace(
    invoke=lambda args: format_search_output(
        {
            "https://docs.python.org/3.13/howto/free-threading-python.html": {
                "title": "Python free-threading documentation (fixture)",
                "content": "Deterministic test evidence, not a live search.",
            }
        }
    )
)
full.writer_model = SimpleNamespace(ainvoke=write)
agent = full.agent

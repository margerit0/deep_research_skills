
"""研究辅助工具 (Research Utilities and Tools)。

本模块为研究智能体提供搜索与内容处理相关的工具函数，
包括网页搜索能力与内容摘要工具。
"""

import os
import logging
import sys
import time
from contextvars import copy_context

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from datetime import datetime
from typing_extensions import Annotated, List, Literal

import requests
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool, InjectedToolArg
from tavily import TavilyClient
from tavily.errors import TimeoutError as TavilyTimeoutError

from deep_research.model_config import get_chat_model, get_agent_rate_limiter
from deep_research.run_configuration import selected_model
from deep_research.structured_output_fallback import (
    invoke_with_structured_output_fallback,
    model_connection,
    should_disable_thinking_for_json_fallback,
)
from deep_research.state_research import Summary
from deep_research.source_evidence import record_source_evidence
from deep_research.prompts import summarize_webpage_prompt
from deep_research.research_requirements import filter_search_results, has_source_restriction, retrieve_specified_sources
from deep_research.workflow_contract import log_node_failure

# ===== 工具函数 (UTILITY FUNCTIONS) =====

def get_today_str() -> str:
    """以人类可读的格式获取当前日期。"""
    # %-d (去掉前导零) 仅 glibc 支持，在 Windows 上会抛出 ValueError；
    # 这里直接用 int 拼出"日"的部分，以保证格式可跨平台使用。
    now = datetime.now()
    return f"{now:%a %b} {now.day}, {now.year}"

def get_current_dir() -> Path:
    """获取本模块所在的当前目录。

    当 __file__ 不可用时回退到当前工作目录。

    Returns:
        表示当前目录的 Path 对象
    """
    try:
        return Path(__file__).resolve().parent
    except NameError:  # __file__ 未定义
        return Path.cwd()

# ===== 配置 (CONFIGURATION) =====

# 摘要 (Summarization) 与研究员 (researcher) 共用 agent 侧的 RPM 预算 (同一个网关端点)；
# 每次 tavily_search 最多会并行发起 5 个这样的摘要请求，正是这个共享限流器
# 把这种并发扇出控制在 AGENT_RPM 之内，避免触发 WAF 封禁。
summarization_model = get_chat_model("SUMMARIZATION", rate_limiter=get_agent_rate_limiter())
# 配置了 TAVILY_API_URL 环境变量时走第三方网关, 未配置时 api_base_url 为 None,
# TavilyClient 内部回落到官方 https://api.tavily.com; key 仍从 TAVILY_API_KEY 读取.
tavily_client = TavilyClient(api_base_url=os.getenv("TAVILY_API_URL") or None)

# 第三方网关偶发瞬时故障 (5xx proxy_error / 断连 / 超时) 的重试间隔, 从短到长
# 互不相同; 长度即最大重试次数 —— 6 次重试耗尽后把原异常抛出 (共 7 次尝试)。
TAVILY_RETRY_DELAYS: tuple[int, ...] = (2, 5, 10, 30, 60, 120)


def _is_transient_tavily_error(exc: Exception) -> bool:
    """判断 tavily 调用异常是否属于"稍后重试即恢复"的瞬时故障。

    - 网络层断连/超时 (含 tavily 自定义 TimeoutError) → 瞬时;
    - tavily-python 对 5xx 走 raise_for_status 抛 HTTPError → 瞬时;
    - 4xx (配额耗尽 ForbiddenError/UsageLimitExceededError、鉴权、参数错误
      等 tavily 自定义异常, 以及 4xx HTTPError) 是请求本身的问题 → 不重试。
    """
    if isinstance(exc, (
        requests.exceptions.ConnectionError,  # 含子类 SSLError
        requests.exceptions.Timeout,
        TavilyTimeoutError,
    )):
        return True
    if isinstance(exc, requests.exceptions.HTTPError):
        status = getattr(exc.response, "status_code", None)
        return status is None or status >= 500
    return False


def _tavily_search_with_retry(query: str, **kwargs) -> dict:
    """对单条查询调用 tavily_client.search, 瞬时故障按 TAVILY_RETRY_DELAYS 退避重试。"""
    for attempt in range(len(TAVILY_RETRY_DELAYS) + 1):
        try:
            return tavily_client.search(query, **kwargs)
        except Exception as exc:
            if attempt >= len(TAVILY_RETRY_DELAYS) or not _is_transient_tavily_error(exc):
                raise
            delay = TAVILY_RETRY_DELAYS[attempt]
            print(
                f"[tavily-retry] attempt {attempt + 1} failed "
                f"({type(exc).__name__}: {exc}); sleeping {delay}s...",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(delay)

# ===== 搜索函数 (SEARCH FUNCTIONS) =====

def tavily_search_multiple(
    search_queries: List[str], 
    max_results: int = 3, 
    topic: Literal["general", "news", "finance"] = "general", 
    include_raw_content: bool = True, 
) -> List[dict]:
    """使用 Tavily API 对多个查询执行搜索。

    Args:
        search_queries: 待执行的搜索查询列表
        max_results: 每个查询返回结果的最大数量
        topic: 搜索结果的主题过滤器
        include_raw_content: 是否包含网页原始内容

    Returns:
        搜索结果字典组成的列表
    """

    # 顺序执行各个搜索。注意：可以使用 AsyncTavilyClient 将这一步并行化。
    search_docs = []
    for query in search_queries:
        result = _tavily_search_with_retry(
            query,
            max_results=max_results,
            include_raw_content=include_raw_content,
            topic=topic
        )
        search_docs.append(result)

    return search_docs

def summarize_webpage_content(webpage_content: str) -> str:
    """使用配置好的摘要模型对网页内容进行摘要。

    Args:
        webpage_content: 待摘要的网页原始内容

    Returns:
        包含关键摘录的格式化摘要
    """
    try:
        # 为摘要任务设置结构化输出模型。
        # method="function_calling" 是必需的: langchain-openai 1.x 默认的
        # method="json_schema" 会把请求走成 OpenAI Responses API 的
        # text.format 路径, 当前网关/模型 (gpt-5.4 @ cafecode) 对其报
        # `Missing required parameter: 'text.format.name'` (确定性 400),
        # 导致每次摘要都失败并回落到原文截断。改走 Chat Completions 的
        # tool-calling 路径后稳定成功 (2026-06-13 实测三 method 仅此可用)。
        selected = selected_model("SUMMARIZATION", summarization_model)
        prompt = summarize_webpage_prompt.format(webpage_content=webpage_content, date=get_today_str())
        base_url, api_key = model_connection(selected)
        if should_disable_thinking_for_json_fallback(selected, base_url=base_url):
            summary = invoke_with_structured_output_fallback(selected, Summary, prompt, base_url=base_url, api_key=api_key)
        else:
            structured_model = selected.with_structured_output(Summary, method="function_calling")
            messages = [HumanMessage(content=prompt)]
            if callable(getattr(structured_model, "stream", None)):
                # Consume structured chunks locally. This avoids waiting for the
                # complete summary before the gateway can send response headers.
                summary = None
                chunks = structured_model.stream(messages)
                try:
                    for value in chunks:
                        if value is not None:
                            summary = value
                finally:
                    if callable(getattr(chunks, "close", None)):
                        chunks.close()
                if summary is None:
                    raise ValueError("Empty webpage summary stream")
            else:
                summary = structured_model.invoke(messages)

        # 以清晰的结构格式化摘要
        formatted_summary = (
            f"<summary>\n{summary.summary}\n</summary>\n\n"
            f"<key_excerpts>\n{summary.key_excerpts}\n</key_excerpts>"
        )

        return formatted_summary

    except Exception as e:
        log_node_failure(logging.getLogger(__name__), "summarize_webpage_content", e)
        # A provider outage must not silently erase a short source's conditions
        # and limitations (often near its end). Keep bounded actual evidence.
        limit = 24000
        notice = "网页摘要调用失败，以下为实际来源原文。"
        if len(webpage_content) > limit:
            notice += "原文超过长度上限，以下仅为前段；未覆盖部分不能据此推断。"
        return notice + "\n" + webpage_content[:limit]

def deduplicate_search_results(search_results: List[dict]) -> dict:
    """按 URL 对搜索结果去重，避免重复处理相同内容。

    Args:
        search_results: 搜索结果字典组成的列表

    Returns:
        URL 到去重后唯一结果的映射字典
    """
    unique_results = {}

    for response in search_results:
        for result in response['results']:
            url = result['url']
            if url not in unique_results:
                unique_results[url] = result

    return unique_results

def process_search_results(unique_results: dict) -> dict:
    """处理搜索结果，对带有原始内容的条目进行摘要。

    Args:
        unique_results: 去重后的搜索结果字典

    Returns:
        带摘要的处理后结果字典
    """
    def _process_one(item: tuple) -> tuple:
        url, result = item
        record_source_evidence(url, result)
        if not result.get("raw_content"):
            content = result["content"]
        else:
            content = summarize_webpage_content(result["raw_content"])
        return url, {"title": result["title"], "content": content,
                     **({"retrieval": result["retrieval"]} if result.get("retrieval") else {})}

    items = list(unique_results.items())
    if not items:
        return {}

    # 每个 URL 的 summarize 调用独立 (各自一个 LLM 请求), 并行跑可把单次
    # tavily_search 从 ~3*N s 压到 ~N s. 上限 5 防止 max_results 配大时
    # 失控. summarization_model / httpx.Client 均线程安全.
    with ThreadPoolExecutor(max_workers=min(len(items), 5)) as ex:
        futures = [ex.submit(copy_context().run, _process_one, item) for item in items]
        processed = [future.result() for future in futures]

    return dict(processed)

def format_search_output(summarized_results: dict) -> str:
    """将搜索结果格式化为结构清晰的字符串输出。

    Args:
        summarized_results: 处理后的搜索结果字典

    Returns:
        来源之间分隔清晰的搜索结果格式化字符串
    """
    if not summarized_results:
        return "No valid search results found. Please try different search queries or use a different search API."

    formatted_output = "Search results: \n\n"

    for i, (url, result) in enumerate(summarized_results.items(), 1):
        formatted_output += f"\n\n--- SOURCE {i}: {result['title']} ---\n"
        formatted_output += f"URL: {url}\n"
        if result.get("retrieval") == "specified_url":
            formatted_output += "RETRIEVAL: specified_url\n"
        formatted_output += "\n"
        formatted_output += f"SUMMARY:\n{result['content']}\n\n"
        formatted_output += "-" * 80 + "\n"

    return formatted_output

# ===== 研究工具 (RESEARCH TOOLS) =====

@tool(parse_docstring=True)
def tavily_search(
    query: str,
    max_results: Annotated[int, InjectedToolArg] = 3,
    topic: Annotated[Literal["general", "news", "finance"], InjectedToolArg] = "general",
) -> str:
    """调用 Tavily 搜索 API 获取结果并进行内容摘要。

    Args:
        query: 要执行的单条搜索查询
        max_results: 返回结果的最大数量
        topic: 用于过滤结果的主题 ('general', 'news', 'finance')

    Returns:
        带摘要的搜索结果格式化字符串
    """
    # 对单条查询执行搜索
    search_results = tavily_search_multiple(
        [query],  # 将单条查询转为列表以适配内部函数
        max_results=max_results,
        topic=topic,
        include_raw_content=True,
    )

    # 按 URL 对结果去重，避免重复处理相同内容
    unique_results = deduplicate_search_results(filter_search_results(search_results))
    if has_source_restriction():
        unique_results.update(deduplicate_search_results(retrieve_specified_sources(
            max_results - len(unique_results), excluded_urls=unique_results,
        )))

    # 对结果进行摘要处理
    summarized_results = process_search_results(unique_results)
    if not summarized_results and has_source_restriction():
        return ("No valid search results found within the user's allowed sources. "
                "证据不足；只能在允许范围内调整查询，不得补入其他来源或自行构造链接。")

    # 格式化输出以供消费使用
    return format_search_output(summarized_results)

    
"""
  llm_call ──► (LLM 决定调用 tavily_search) ──► tool_node 执行搜索
     ▲                                              │
     │                                              ▼
     └── (LLM 决定调用 think_tool 反思) ◄── 把搜索结果喂回模型
                    │
                    ▼
     think_tool 把 reflection 回显成 ToolMessage
                    │
                    ▼
     下一轮 llm_call：基于反思决定 "再搜一次" 还是 "停下来回答"
     (无 tool_calls 时 should_continue → compress_research → END)
"""
@tool(parse_docstring=True)
def think_tool(reflection: str) -> str:
    """用于对研究进度和决策进行策略性反思的工具。

    在每次搜索后使用此工具系统地分析结果并规划后续步骤。
    这在研究流程中创造了一个有意的停顿，以确保决策质量。

    适用场景：
    - 收到搜索结果后：我发现了哪些关键信息？
    - 决定下一步行动前：我掌握的信息是否足以进行全面回答？
    - 评估研究空白时：我还缺少哪些具体信息？
    - 结束研究工作前：我现在能提供一个完整的回答吗？

    反思应涵盖以下内容：
    1. 当前发现分析——我收集到了哪些具体信息？
    2. 空白评估——还缺少哪些关键信息？
    3. 质量评估——我是否有足够的证据/案例来提供合理的回答？
    4. 策略决策——我应该继续搜索还是直接提供回答？

    Args:
        reflection: 你对研究进度、发现、信息空白及后续步骤的详细反思。

    Returns:
        确认反思已被记录以供决策参考。
    """
    return f"Reflection 记录: {reflection}"

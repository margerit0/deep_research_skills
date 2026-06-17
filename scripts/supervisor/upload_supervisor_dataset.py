"""创建并上传 deep_research_supervisor_parallelism 数据集到 LangSmith。

准备 10 个测试用例:

每条用例的 inputs 是一段预置的 ``supervisor_messages`` 三段式消息历史:

    1) HumanMessage  - 用户的研究问题 (research brief)
    2) AIMessage     - supervisor 发起的 think_tool 调用 (含对任务结构的反思)
    3) ToolMessage   - think_tool 的响应 ("Reflection 记录: ...")

预置 think_tool 交换是为了把 supervisor 推过 "先思考" 步骤, 让它的下一步
就是并行决策本身 —— outputs 的 ``num_expected_threads`` 记录这一步应当发出的
ConductResearch 调用数 (对比类任务每个对比元素一个子智能体; 排名/事实/单主题
任务只用一个子智能体, 见 lead_researcher_prompt 的 Scaling Rules)。

用法::

    cd deep_research_skills
    python -m scripts.supervisor.upload_supervisor_dataset            # 数据集已存在则提示
    python -m scripts.supervisor.upload_supervisor_dataset --recreate # 先删除再重建

环境变量::

    LANGSMITH_API_KEY   必填
    LANGSMITH_DATASET   可选, 默认 "deep_research_supervisor_parallelism"
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import TypedDict

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langsmith import Client


class TestCase(TypedDict):
    """单个评估用例: 研究问题 + 预置反思 + 期望的并行研究线程数。"""

    research_brief: str
    reflection: str
    num_expected_threads: int


# ============================================================
# 10 条评估用例 (全部中文)
# ------------------------------------------------------------
# 期望线程数分布: 1 线程 ×5 / 2 线程 ×3 / 3 线程 ×2
#
#   1. 对比 2   OpenAI vs Gemini Deep Research                           → 2
#   2. 排名     曼哈顿 Chelsea 中餐厅前三                                → 1
#   3. 对比 3   AWS / GCP / Azure serverless                              → 3
#   4. 对比 2   Notion vs Obsidian                                        → 2
#   5. 事实     LangGraph interrupt 功能                                  → 1
#   6. 对比 2   M4 vs M4 Pro Mac mini                                     → 2
#   7. 旅游     京都 5 天赏樱 (单一目的地)                                → 1
#   8. 对比 3   DeepSeek / Kimi / 智谱 GLM API                            → 3
#   9. 医疗     老年骨质疏松一线用药 (单一主题)                           → 1
#   10. 人物    Mira Murati 新公司 (单一信息线)                           → 1
#
# reflection 只客观刻画任务结构 (任务类型 + 涉及的
# 独立实体), 不直接给出 "应该开 N 个线程" 的答案 —— 从结构到委托数量的
# 转换正是被评估的决策。
# ============================================================

TEST_CASES: list[TestCase] = [
    # --- 1. OpenAI vs Gemini Deep Research (对比 2) ---
    {
        "research_brief": (
            "请对比 OpenAI 与 Google Gemini 各自的 Deep Research 深度研究产品, "
            "包括功能形态、底层模型与订阅定价。"
        ),
        "reflection": (
            "这是一个对比类任务, 涉及两个独立的 AI 产品: OpenAI 的 Deep Research "
            "与 Google Gemini 的 Deep Research。两者各自的功能形态、底层模型与"
            "订阅定价可以独立调研。"
        ),
        "num_expected_threads": 2,
    },

    # --- 2. 曼哈顿 Chelsea 中餐厅 (排名/列表) ---
    {
        "research_brief": (
            "请帮我找出纽约曼哈顿 Chelsea 街区评价最高的三家中餐厅, "
            "给出每家的特色菜和大致人均价格。"
        ),
        "reflection": (
            "这是一个针对特定地理区域 (曼哈顿 Chelsea 街区) 中餐厅的排名/列表类"
            "任务, 需要查找评价类网站的榜单信息, 主题集中在同一个区域的同一类目。"
        ),
        "num_expected_threads": 1,
    },

    # --- 3. 三家云厂商 serverless (对比 3) ---
    {
        "research_brief": (
            "请比较 AWS Lambda、Google Cloud Functions 和 Azure Functions "
            "三家 serverless 计算平台在冷启动性能、计费方式和支持的编程语言上的差异。"
        ),
        "reflection": (
            "这是一个对比类任务, 涉及三家相互独立的云厂商 serverless 平台: "
            "AWS Lambda、Google Cloud Functions 与 Azure Functions, "
            "每家的冷启动性能、计费方式和语言支持可以独立调研。"
        ),
        "num_expected_threads": 3,
    },

    # --- 4. Notion vs Obsidian (对比 2) ---
    {
        "research_brief": (
            "请对比 Notion 与 Obsidian 这两款知识管理工具在核心功能、协作能力、"
            "离线使用和订阅价格方面的差异, 帮我判断哪款更适合搭建个人知识库。"
        ),
        "reflection": (
            "这是一个对比类任务, 涉及两款独立的个人知识管理工具: Notion 与 "
            "Obsidian, 两者的核心功能、协作能力、离线使用和订阅价格可以独立调研。"
        ),
        "num_expected_threads": 2,
    },

    # --- 5. LangGraph interrupt (事实查找) ---
    {
        "research_brief": (
            "请帮我调研 LangGraph 框架中 interrupt 功能的用途、"
            "典型的 human-in-the-loop 使用方式和官方推荐的最佳实践。"
        ),
        "reflection": (
            "这是一个针对单一框架特性 (LangGraph 的 interrupt 功能) 的事实查找"
            "任务, 主题单一, 用途/用法/最佳实践高度关联, 没有可拆分的独立子主题。"
        ),
        "num_expected_threads": 1,
    },

    # --- 6. M4 vs M4 Pro Mac mini (对比 2) ---
    {
        "research_brief": (
            "苹果 2024 年 10 月发布的 Mac mini 有 M4 和 M4 Pro 两个版本, "
            "请对比它们在 CPU/GPU 核心数、内存带宽、接口规格和起售价上的差异。"
        ),
        "reflection": (
            "这是一个对比类任务, 涉及同一产品线的两个具体型号: M4 版与 M4 Pro 版 "
            "Mac mini, 两个型号的核心数、内存带宽、接口规格与起售价可以独立调研。"
        ),
        "num_expected_threads": 2,
    },

    # --- 7. 京都赏樱 (单一目的地旅游) ---
    {
        "research_brief": (
            "我计划 2025 年 4 月去京都看樱花, 行程 5 天, 请帮我调研值得去的"
            "赏樱景点、各景点的最佳观赏时间以及推荐的住宿区域。"
        ),
        "reflection": (
            "这是一个针对单一目的地 (京都) 的旅行规划任务, 赏樱景点、观赏时间与"
            "住宿区域信息高度关联, 适合作为一个整体调研。"
        ),
        "num_expected_threads": 1,
    },

    # --- 8. 国产大模型 API (对比 3) ---
    {
        "research_brief": (
            "请比较 DeepSeek、月之暗面 Kimi 和智谱 GLM 三家国产大模型开放平台 API "
            "的定价 (每百万 token 输入/输出价格) 和最大上下文长度。"
        ),
        "reflection": (
            "这是一个对比类任务, 涉及三家独立的国产大模型厂商开放平台: DeepSeek、"
            "月之暗面 Kimi 与智谱 GLM, 每家的 API 定价与最大上下文长度可以独立调研。"
        ),
        "num_expected_threads": 3,
    },

    # --- 9. 老年骨质疏松一线用药 (单一医学主题) ---
    {
        "research_brief": (
            "请整理目前老年人骨质疏松症的一线药物治疗方案, 包括代表药物、"
            "给药方式、常见副作用和需要联合补充的营养素。"
        ),
        "reflection": (
            "这是一个针对单一医学主题 (老年人骨质疏松症一线药物治疗方案) 的资料"
            "整理任务, 各药物类别同属一个治疗体系且互相关联, 适合作为一个整体调研。"
        ),
        "num_expected_threads": 1,
    },

    # --- 10. Mira Murati 新公司 (单一人物动态) ---
    {
        "research_brief": (
            "OpenAI 前 CTO Mira Murati 离职后创办了一家新公司, 请调研这家公司的"
            "名称、研究方向、已公开的融资情况和关键团队成员。"
        ),
        "reflection": (
            "这是一个针对单一人物动态 (Mira Murati 离开 OpenAI 后创办的新公司) 的"
            "事实调查任务, 公司名称、方向、融资和团队属于同一条信息线。"
        ),
        "num_expected_threads": 1,
    },
]


DATASET_DESCRIPTION = (
    "用于评估 supervisor agent 并行研究决策的数据集。每个样本的 inputs 是预置了"
    " think_tool 交换的 supervisor_messages 消息历史, outputs 的 num_expected_threads"
    " 是 supervisor 下一步应当发出的 ConductResearch 调用数 —— 对比类任务每个对比"
    "元素一个子智能体, 排名/事实/单主题任务只用一个子智能体。"
)


def build_supervisor_messages(
    research_brief: str, reflection: str, call_id: str
) -> list[BaseMessage]:
    """按三段式构造预置的 supervisor 消息历史。

    ToolMessage 内容复用 utils.think_tool 的真实返回格式 ("Reflection 记录: ...")。
    """
    return [
        HumanMessage(content=research_brief),
        AIMessage(
            content="让我先分析这个研究请求的结构, 判断是否存在可并行的独立子主题。",
            tool_calls=[
                {
                    "name": "think_tool",
                    "args": {"reflection": reflection},
                    "id": call_id,
                }
            ],
        ),
        ToolMessage(
            content=f"Reflection 记录: {reflection}",
            tool_call_id=call_id,
            name="think_tool",
        ),
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="如果数据集已存在, 先删除再重建",
    )
    parser.add_argument(
        "--dataset-name",
        default=os.getenv("LANGSMITH_DATASET", "deep_research_supervisor_parallelism"),
        help="LangSmith 数据集名称 (默认 deep_research_supervisor_parallelism)",
    )
    return parser.parse_args()


def build_examples(test_cases: list[TestCase]) -> list[dict]:
    return [
        {
            "inputs": {
                "supervisor_messages": build_supervisor_messages(
                    tc["research_brief"],
                    tc["reflection"],
                    f"call_think_{idx}",
                ),
            },
            "outputs": {"num_expected_threads": tc["num_expected_threads"]},
        }
        for idx, tc in enumerate(test_cases, 1)
    ]


def main() -> int:
    load_dotenv()
    args = parse_args()

    api_key = os.getenv("LANGSMITH_API_KEY")
    if not api_key:
        print("ERROR: LANGSMITH_API_KEY 环境变量未设置", file=sys.stderr)
        return 1

    client = Client(api_key=api_key)
    dataset_name = args.dataset_name

    if client.has_dataset(dataset_name=dataset_name):
        if args.recreate:
            existing = client.read_dataset(dataset_name=dataset_name)
            client.delete_dataset(dataset_id=existing.id)
            print(f"已删除旧的数据集 '{dataset_name}'")
        else:
            print(
                f"数据集 '{dataset_name}' 已存在。\n"
                f"  - 如需追加新示例, 请到 LangSmith UI 手动操作\n"
                f"  - 如需重建, 请加上 --recreate 重新运行本脚本",
                file=sys.stderr,
            )
            return 0

    dataset = client.create_dataset(
        dataset_name=dataset_name,
        description=DATASET_DESCRIPTION,
    )
    examples = build_examples(TEST_CASES)
    client.create_examples(dataset_id=dataset.id, examples=examples)

    print(f"已创建数据集 '{dataset_name}' (id={dataset.id})")
    print(f"已上传 {len(examples)} 条示例")
    return 0


if __name__ == "__main__":
    sys.exit(main())

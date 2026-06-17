"""创建并上传 deep_research_agent_quality 数据集到 LangSmith。

每条用例包含:
- ``research_brief`` (中文研究简报, 一段话) — 直接作为 HumanMessage 输入 researcher_agent
- ``criteria`` (6-8 条) — 研究输出应覆盖的子问题 / 维度, 供 LLM judge 逐条评分

用法::

    cd deep_research_skills
    python -m scripts.research_agent.upload_research_dataset           # 数据集已存在则提示
    python -m scripts.research_agent.upload_research_dataset --recreate # 先删除再重建

环境变量::

    LANGSMITH_API_KEY   必填
    LANGSMITH_DATASET   可选, 默认 "deep_research_agent_quality"
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import TypedDict

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langsmith import Client


class TestCase(TypedDict):
    """单个评估用例的输入简报与评分标准。"""

    research_brief: str
    criteria: list[str]


# ============================================================
# 10 条评估用例 (全部中文, 研究原生主题)
# ------------------------------------------------------------
# 主题分布:
#   1. 对比         Llama 3 vs Qwen 2
#   2. 排名         5 家 LLM API 价格 / 限速
#   3. 推荐         家用 NAS 选型
#   4. 事实         LangGraph 核心抽象
#   5. 人物         Mira Murati 新公司
#   6. 学术         2024 RAG 评估基准论文
#   7. 产品         M4 vs M4 Pro Mac mini
#   8. 旅游         京都赏樱
#   9. 医疗信息     老年人骨质疏松一线用药
#   10. 投资        TIPS vs 普通国债
#
# 每条 criteria 项颗粒度: 单一可独立判定是否被覆盖, 避免笼统
# (例如 "全面对比两个系列" 这类无法判定的项).
# ============================================================

TEST_CASES: list[TestCase] = [
    # --- 1. Llama 3 vs Qwen 2 对比 ---
    {
        "research_brief": (
            "我想详细对比 Meta 的 Llama 3 系列与阿里巴巴的 Qwen 2 系列大语言模型, "
            "从开源协议、模型规模、上下文窗口三个角度看哪一方更适合开发者集成。"
        ),
        "criteria": [
            "列出 Llama 3 各模型的参数规模 (如 8B、70B、Llama 3.1 405B 等具体型号)",
            "列出 Qwen 2 各模型的参数规模 (如 Qwen2-0.5B/1.5B/7B/72B 等具体型号)",
            "明确 Llama 3 的开源协议名称 (Llama Community License 等) 及商用条款",
            "明确 Qwen 2 的开源协议名称 (Apache 2.0、Tongyi Qianwen License 等) 及商用条款",
            "给出 Llama 3 系列的上下文窗口长度",
            "给出 Qwen 2 系列的上下文窗口长度",
            "至少给出 2 项可对比的具体数字差异 (如最大模型参数比、上下文长度比等)",
        ],
    },

    # --- 2. 5 家 LLM API 价格与限速 ---
    {
        "research_brief": (
            "我是独立开发者, 想在 2024-2025 年面向消费级应用集成一个 LLM API。"
            "请帮我对比 OpenAI、Anthropic、Google、DeepSeek、Moonshot 5 家主流厂商的入门级 / 主力模型"
            "在每百万 token 的输入 / 输出价格以及免费用户 / 付费用户的速率限制。"
        ),
        "criteria": [
            "列出 5 家厂商各自的入门级 / 主力模型名称",
            "每家给出输入 token 的价格 (USD per 1M tokens)",
            "每家给出输出 token 的价格 (USD per 1M tokens)",
            "至少给出 3 家厂商的速率限制信息 (RPM 或 TPM)",
            "标注价格信息的更新时间或参考日期",
            "至少一项跨厂商的价格对比结论 (如最便宜 / 最贵)",
            "至少一项跨厂商的限速对比结论",
        ],
    },

    # --- 3. 家用 NAS 选型 ---
    {
        "research_brief": (
            "我家里有 4 个人, 希望买一台 2024 年新发售的 4 盘位以下家用 NAS, "
            "主要用于备份家庭照片视频和 Plex 媒体服务。"
            "请帮我对比适合家庭用户的主流型号, 关注 CPU、内存、硬件转码能力、价格和噪音。"
        ),
        "criteria": [
            "列出至少 3 款 2024 年发售的家用 NAS 型号",
            "每款给出 CPU 信息 (型号或架构)",
            "每款给出基础内存配置",
            "至少 2 款讨论是否支持硬件转码 (与 Plex 兼容性)",
            "至少 2 款给出官方建议零售价或市场价格",
            "至少 1 款讨论运行噪音或散热",
            "给出针对 4 口之家的具体推荐意见 (不仅是规格罗列)",
        ],
    },

    # --- 4. LangGraph 核心抽象 ---
    {
        "research_brief": (
            "我准备学习 LangGraph 框架, 请帮我整理它的三个核心抽象 StateGraph、Send、interrupt "
            "各自的用途、典型使用场景, 以及它们之间如何协作。"
        ),
        "criteria": [
            "解释 StateGraph 的用途和核心 API (add_node / add_edge / compile 等)",
            "解释 Send 的用途 (典型用于 fan-out / map)",
            "解释 interrupt 的用途 (典型用于 human-in-the-loop)",
            "StateGraph 的至少一个代码片段或具体使用例",
            "Send 的至少一个具体使用场景",
            "interrupt 的至少一个具体使用场景",
            "给出三者如何在同一个 graph 中协作的说明或示例",
        ],
    },

    # --- 5. Mira Murati 离职后 ---
    {
        "research_brief": (
            "OpenAI 前 CTO Mira Murati 在 2024 年 9 月离职后创办了新公司, "
            "请告诉我她的新公司名字、研究方向、已公开的融资金额或估值、关键合伙人或团队成员。"
        ),
        "criteria": [
            "给出 Mira Murati 新公司的正式名称",
            "描述新公司的研究方向或核心定位",
            "给出至少一轮公开融资的金额或估值",
            "列出至少 2 位关键合伙人或团队成员",
            "给出公司成立或宣布的大致时间 (年 / 月)",
            "至少一处信息标注来源 (媒体报道或公司官网)",
        ],
    },

    # --- 6. 2024 RAG 评估基准论文 ---
    {
        "research_brief": (
            "请帮我整理 2024 年发表的关于检索增强生成 (RAG) 评估基准的代表性论文 3-5 篇, "
            "给出每篇论文的标题、作者机构、提出的评估方法或数据集名称, "
            "以及在 arXiv 或会议的出处。"
        ),
        "criteria": [
            "列出 3-5 篇 2024 年发表的 RAG 评估相关论文",
            "每篇给出标题",
            "每篇给出至少一位作者或作者机构",
            "每篇给出提出的评估方法 / 基准 / 数据集名称",
            "每篇给出 arXiv ID 或会议 (NeurIPS / ACL / EMNLP 等) 出处",
            "至少一篇给出论文摘要或主要贡献的简短描述",
        ],
    },

    # --- 7. M4 vs M4 Pro Mac mini ---
    {
        "research_brief": (
            "苹果在 2024 年 10 月发布了 M4 和 M4 Pro 两个版本的 Mac mini, "
            "请帮我详细对比它们在 CPU 核心、GPU 核心、内存配置 / 带宽、雷电接口规格、"
            "起售价 5 个维度的差异。"
        ),
        "criteria": [
            "列出 M4 版 Mac mini 的 CPU 核心数 (性能核 + 能效核拆开)",
            "列出 M4 Pro 版 Mac mini 的 CPU 核心数",
            "列出 M4 / M4 Pro 各自的 GPU 核心数",
            "给出 M4 / M4 Pro 各自的内存带宽数字 (GB/s)",
            "给出 M4 / M4 Pro 各自的雷电接口规格 (Thunderbolt 4 / 5) 和数量",
            "给出 M4 / M4 Pro 美国起售价 (美元)",
            "至少一项明确的对比结论 (如带宽倍数 / 价格差)",
        ],
    },

    # --- 8. 京都赏樱 ---
    {
        "research_brief": (
            "我和家人计划 2025 年 4 月去京都看樱花, 行程 5 天 4 晚。"
            "请推荐 3 个必去的赏樱景点 (含最佳赏花时间), 以及推荐住宿的 1-2 个区域 (含理由)。"
        ),
        "criteria": [
            "推荐 3 个京都赏樱景点",
            "每个景点给出大致最佳观赏时间 (4 月上 / 中 / 下旬)",
            "至少 1 个景点说明特色 (夜樱 / 哲学之道 / 寺院 / 河岸等具体亮点)",
            "推荐 1-2 个住宿区域",
            "每个住宿区域给出推荐理由 (交通 / 步行可达景点)",
            "提供至少 1 处 2025 年开花预测或时间提示来源",
        ],
    },

    # --- 9. 老年人骨质疏松一线用药 ---
    {
        "research_brief": (
            "请整理目前老年人骨质疏松症的一线药物治疗方案, "
            "包括代表性药物名称、给药方式 (口服 / 注射) 、常见副作用以及通常需要联合补充的营养素。"
        ),
        "criteria": [
            "列出至少 3 类一线骨质疏松治疗药物 (如双膦酸盐、地舒单抗、雷洛昔芬等)",
            "每类给出至少一个代表性药物名称 (通用名)",
            "标注每类药物的给药方式 (口服 / 注射 / 静脉滴注)",
            "列出每类药物的常见副作用 (至少 2-3 个)",
            "提到联合补充的营养素 (如钙、维生素 D)",
            "至少一处说明治疗方案的医学指南来源 (NIH / WHO / 国家骨质疏松基金会等)",
        ],
    },

    # --- 10. TIPS vs 普通国债 ---
    {
        "research_brief": (
            "我想了解美国国债 TIPS (Treasury Inflation-Protected Securities) "
            "与普通国债 (如 10 年期 Treasury Note) 在通胀对冲机制上的区别, "
            "包括 TIPS 的本金调整方式、利息计算方式、税收处理特点, "
            "以及它们各自适合的投资场景。"
        ),
        "criteria": [
            "解释 TIPS 的本金如何随 CPI 调整",
            "解释 TIPS 利息如何在调整后的本金上计算",
            "解释普通国债 (Treasury Note) 的固定票息机制",
            "给出 TIPS 在通胀升高 / 降低环境下相对普通国债的表现",
            "说明 TIPS 的税收特殊性 (phantom income 即本金增长部分需当期纳税)",
            "至少一处给出 TIPS / 普通国债的当前收益率参考或最近的市场情况",
            "至少一句结论性建议 (TIPS / 普通国债各自适合的投资人)",
        ],
    },
]


DATASET_DESCRIPTION = (
    "用于评估 research_agent 端到端研究质量的数据集。每个样本含一段中文研究简报作为 inputs, "
    "以及一份 criteria 列表 — 研究输出的 compressed_research 应针对每条 criterion 提供具体支撑."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="如果数据集已存在, 先删除再重建",
    )
    parser.add_argument(
        "--dataset-name",
        default=os.getenv("LANGSMITH_DATASET", "deep_research_agent_quality"),
        help="LangSmith 数据集名称 (默认 deep_research_agent_quality)",
    )
    return parser.parse_args()


def build_examples(test_cases: list[TestCase]) -> list[dict]:
    return [
        {
            "inputs": {
                "researcher_messages": [HumanMessage(content=tc["research_brief"])],
            },
            "outputs": {"criteria": tc["criteria"]},
        }
        for tc in test_cases
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

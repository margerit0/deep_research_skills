"""创建并上传 deep_research_scoping 数据集到 LangSmith。

准备 10 个测试用例: 每个用例由 ``conversation`` (Human -> AI澄清 -> Human详细回答)
和 ``criteria`` (用户实际给出的、研究简报应当涵盖的事实清单) 两部分组成。

用法::

    cd deep_research_skills
    python -m scripts.upload_scoping_dataset            # 数据集已存在则提示
    python -m scripts.upload_scoping_dataset --recreate # 先删除再重建

环境变量::

    LANGSMITH_API_KEY   必填
    LANGSMITH_DATASET   可选, 默认 "deep_research_scoping"
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import TypedDict

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langsmith import Client


class TestCase(TypedDict):
    """单个评估用例的输入与标准答案。"""

    conversation: list[BaseMessage]
    criteria: list[str]


# ============================================================
# 10 个评估用例 (全部中文)
# ------------------------------------------------------------
# 每个 conversation 遵循三段式:
#   1) HumanMessage  - 初始模糊请求
#   2) AIMessage     - 澄清 agent 提出的澄清问题
#   3) HumanMessage  - 用户给出的具体条件
# criteria 列表完整记录第 3 步中用户提到的每一项约束;
# 后续 evaluate_success_criteria 会逐条判断 brief 是否覆盖.
# ============================================================

TEST_CASES: list[TestCase] = [
    # --- 1. 退休投资 ---
    {
        "conversation": [
            HumanMessage(content="怎么把 5 万美元用于退休投资比较好？"),
            AIMessage(content=(
                "为了为您 5 万美元的退休投资方案提供更贴合您情况的建议,请补充以下信息:\n"
                "- 您当前的年龄或希望的退休年龄\n"
                "- 您的风险承受能力(低、中、高)\n"
                "- 对投资类型的偏好(如股票、债券、共同基金、房地产)\n"
                "- 是通过税收优惠账户(如 IRA、401(k))还是普通券商账户进行投资\n"
                "这些信息能帮助我提供更个性化的建议。"
            )),
            HumanMessage(content=(
                "我今年 25 岁,希望 45 岁退休。目前的风险承受能力较高,但我预计会随时间下降。"
                "听说股票和 ETF 是不错的选择,不过其他类型我也愿意了解。我已经有 401k,"
                "这次只通过普通券商账户进行投资。"
            )),
        ],
        "criteria": [
            "当前年龄为 25 岁",
            "希望的退休年龄为 45 岁",
            "当前风险承受能力较高",
            "风险承受能力预计会随时间下降",
            "对股票和 ETF 感兴趣",
            "也愿意了解股票和 ETF 之外的投资类型",
            "投资账户为普通券商账户",
        ],
    },

    # --- 2. 纽约公寓 ---
    {
        "conversation": [
            HumanMessage(content="我想在纽约找一套公寓,能帮我吗?"),
            AIMessage(content=(
                "可以的,请告诉我您的具体偏好,例如:\n"
                "- 倾向的街区或行政区\n"
                "- 卧室和卫生间的数量\n"
                "- 月租预算范围\n"
                "- 必须具备的配套设施\n"
                "- 希望的入住日期\n"
                "这些信息能帮助我推荐最合适的房源。"
            )),
            HumanMessage(content=(
                "我倾向于住在 Chelsea、Flatiron 或 West Village。需要 2 室 2 卫,"
                "月租不超过 7000 美元。希望是带门卫的公寓楼,最好有户内洗衣机和烘干机,"
                "但没有也可以。楼里有健身房是加分项。希望 2025 年 9 月入住。"
            )),
        ],
        "criteria": [
            "在 Chelsea、Flatiron 或 West Village 寻找 2 室 2 卫的公寓",
            "月租不超过 7000 美元",
            "希望是带门卫的公寓楼",
            "最好有户内洗衣机和烘干机,但不是硬性要求",
            "楼里有健身房是加分项,但不是硬性要求",
            "入住日期为 2025 年 9 月",
        ],
    },

    # --- 3. 笔记本电脑 ---
    {
        "conversation": [
            HumanMessage(content="我想买一台新笔记本电脑,能帮我看看吗?"),
            AIMessage(content=(
                "当然可以。请告诉我以下信息:\n"
                "- 主要用途(办公、游戏、设计等)\n"
                "- 预算范围\n"
                "- 操作系统偏好(Windows、macOS、Linux)\n"
                "- 便携性要求(屏幕尺寸、重量)\n"
                "- 必须运行的特定软件"
            )),
            HumanMessage(content=(
                "我是一名软件开发者,需要运行 Docker、JetBrains 系列 IDE,"
                "偶尔做一些 1080p 视频剪辑。预算大约 2000 美元。倾向 macOS,"
                "但也接受 Windows。经常出差,重量要在 2 公斤以下。屏幕 14-16 英寸。"
            )),
        ],
        "criteria": [
            "主要用途为软件开发,需要运行 Docker 和 JetBrains 系列 IDE",
            "偶尔有 1080p 视频剪辑需求",
            "预算大约 2000 美元",
            "倾向 macOS,但也接受 Windows",
            "因出差需要,重量须在 2 公斤以下",
            "屏幕尺寸介于 14-16 英寸之间",
        ],
    },

    # --- 4. 日本旅行 ---
    {
        "conversation": [
            HumanMessage(content="我打算去日本旅行,能帮我规划一下吗?"),
            AIMessage(content=(
                "可以的。为了帮您定制行程,请提供以下信息:\n"
                "- 出行日期和总天数\n"
                "- 不含机票的总预算\n"
                "- 想去的城市或地区\n"
                "- 兴趣点(美食、历史、自然、动漫等)\n"
                "- 同行人数\n"
                "- 住宿偏好"
            )),
            HumanMessage(content=(
                "计划 2026 年 4 月下旬出发,共 10 天,两位成人,预算约 3000 美元(不含机票)。"
                "想去东京和京都,希望体验樱花、传统文化和美食。住宿偏好是中档酒店和温泉旅馆。"
            )),
        ],
        "criteria": [
            "出行日期为 2026 年 4 月下旬",
            "行程总长 10 天",
            "同行人数为两位成人",
            "预算约 3000 美元(不含机票)",
            "想去的城市为东京和京都",
            "兴趣点为樱花、传统文化和美食",
            "住宿偏好为中档酒店和温泉旅馆",
        ],
    },

    # --- 5. 婚礼场地 ---
    {
        "conversation": [
            HumanMessage(content="我在找婚礼场地,能帮我吗?"),
            AIMessage(content=(
                "当然可以。请告诉我:\n"
                "- 婚礼日期或大致时间段\n"
                "- 城市或区域\n"
                "- 预计宾客人数\n"
                "- 室内、室外或两者兼备\n"
                "- 仅场地的预算\n"
                "- 必须具备的特性"
            )),
            HumanMessage(content=(
                "婚礼计划在 2026 年 9 月,地点在德州奥斯汀。预计约 120 位宾客。"
                "希望是户外仪式 + 室内备用宴会厅以防下雨。场地预算 15000 美元。"
                "必须允许外部餐饮供应商,并且至少能停 80 辆车。"
            )),
        ],
        "criteria": [
            "婚礼日期为 2026 年 9 月",
            "地点在德州奥斯汀",
            "预计宾客约 120 人",
            "户外仪式 + 室内备用宴会厅以防下雨",
            "仅场地预算为 15000 美元",
            "必须允许外部餐饮供应商",
            "停车位至少 80 个",
        ],
    },

    # --- 6. 转行机器学习 ---
    {
        "conversation": [
            HumanMessage(content="我想转行做机器学习,应该怎么入手?"),
            AIMessage(content=(
                "为了给您制定个性化的路线图,请告诉我:\n"
                "- 您当前的岗位和技术背景\n"
                "- 每周可投入的学习时间\n"
                "- 目标机器学习岗位(研究员、应用型 ML 工程师、MLOps 等)\n"
                "- 课程或认证的预算\n"
                "- 偏好的学习形式(自学、训练营、正规学位)"
            )),
            HumanMessage(content=(
                "我目前是后端工程师,有 6 年 Python 和 SQL 经验,但没有机器学习背景。"
                "每周可以投入 10 小时。希望在 12-18 个月内进入中型公司担任应用型 ML 工程师。"
                "付费课程预算 2000 美元。偏好通过结构化在线课程自学,不打算重新攻读学位。"
            )),
        ],
        "criteria": [
            "当前岗位是后端工程师,有 6 年 Python 和 SQL 经验",
            "没有机器学习背景",
            "每周可投入学习时间为 10 小时",
            "目标岗位为中型公司的应用型 ML 工程师",
            "转行时间线为 12-18 个月",
            "付费课程预算为 2000 美元",
            "偏好通过结构化在线课程自学",
            "不打算重新攻读正规学位",
        ],
    },

    # --- 7. 周年纪念晚餐 ---
    {
        "conversation": [
            HumanMessage(content="我需要为一次重要晚餐推荐一家餐厅。"),
            AIMessage(content=(
                "好的。请告诉我:\n"
                "- 城市和倾向的街区\n"
                "- 用餐日期和时间\n"
                "- 菜系偏好\n"
                "- 人均预算\n"
                "- 氛围偏好(浪漫、热闹、休闲、高端)\n"
                "- 是否有饮食禁忌"
            )),
            HumanMessage(content=(
                "为我们的 10 周年纪念晚餐找一家餐厅,地点在旧金山,最好在 Mission 或 Hayes Valley。"
                "周六晚上 7 点左右。我们喜欢意大利菜和日料。人均预算不超过 200 美元(含酒水)。"
                "希望氛围浪漫、安静,不要太吵。我伴侣是素食者。"
            )),
        ],
        "criteria": [
            "用餐场合为 10 周年纪念晚餐",
            "地点在旧金山,最好在 Mission 或 Hayes Valley",
            "用餐时间为周六晚上 7 点左右",
            "菜系偏好为意大利菜或日料",
            "人均预算不超过 200 美元(含酒水)",
            "氛围需浪漫、安静",
            "需要为一位素食者提供菜品选择",
        ],
    },

    # --- 8. AWS 认证 ---
    {
        "conversation": [
            HumanMessage(content="我想考一个 AWS 认证,该选哪个?"),
            AIMessage(content=(
                "为了推荐合适的认证,请告诉我:\n"
                "- 当前的云和 AWS 使用经验\n"
                "- 当前岗位和目标岗位\n"
                "- 每周可用于备考的时间\n"
                "- 目标考试日期或时间线\n"
                "- 由雇主报销还是自费"
            )),
            HumanMessage(content=(
                "我做了 2 年 DevOps 工程师,使用 AWS 主要是 EC2、S3 和 IAM。"
                "希望转向云架构师岗位。每周可以备考 8 小时。目标是 3 个月内通过考试。"
                "公司可以报销考试费,但培训资料需要我自费。"
            )),
        ],
        "criteria": [
            "当前经验为 2 年 DevOps 工程师并使用 AWS",
            "当前用过的 AWS 服务为 EC2、S3 和 IAM",
            "目标岗位为云架构师",
            "每周备考时间为 8 小时",
            "目标在 3 个月内通过考试",
            "考试费由公司报销,培训资料需自费",
        ],
    },

    # --- 9. 二手车 ---
    {
        "conversation": [
            HumanMessage(content="我想买一辆二手车,帮我看看应该关注哪些方面。"),
            AIMessage(content=(
                "好的。请提供以下信息:\n"
                "- 总预算(含税费和上牌费)\n"
                "- 车型偏好(轿车、SUV、两厢、皮卡等)\n"
                "- 可接受的最大里程和车龄\n"
                "- 燃料类型偏好(燃油、混动、纯电)\n"
                "- 主要用途(通勤、家用、长途自驾)\n"
                "- 必备配置"
            )),
            HumanMessage(content=(
                "总预算 20000 美元(含税费和上牌费)。想要紧凑型 SUV 或跨界车。"
                "里程不超过 6 万英里,车龄不早于 2020 款。希望是混动以提高油耗经济性,"
                "因为我每天通勤 50 英里。必须配备 Apple CarPlay、倒车影像和四驱。"
            )),
        ],
        "criteria": [
            "总预算 20000 美元(含税费和上牌费)",
            "车型为紧凑型 SUV 或跨界车",
            "最大里程 6 万英里",
            "车龄不早于 2020 款",
            "燃料类型偏好为混动",
            "主要用途为每天 50 英里的通勤",
            "必须配备 Apple CarPlay、倒车影像和四驱",
        ],
    },

    # --- 10. 新项目编程语言选型 ---
    {
        "conversation": [
            HumanMessage(content="我新项目应该用什么编程语言?"),
            AIMessage(content=(
                "为了推荐合适的语言,请告诉我:\n"
                "- 项目类型(Web 应用、CLI 工具、数据流水线等)\n"
                "- 性能和扩展性要求\n"
                "- 团队当前的语言经验\n"
                "- 部署目标(云、移动端、嵌入式等)\n"
                "- 时间线和团队规模\n"
                "- 必需的库或框架"
            )),
            HumanMessage(content=(
                "要构建一个高吞吐量的数据摄取流水线,每秒处理约 10 万条事件。"
                "将部署在 AWS 的 Kubernetes 集群上。团队 3 名后端工程师,Go 和 Python 经验扎实,"
                "但没有 Rust 经验。需要在 2 个月内交付 MVP。必须能集成 Kafka 和 PostgreSQL。"
            )),
        ],
        "criteria": [
            "项目类型为高吞吐量数据摄取流水线",
            "吞吐量要求为每秒约 10 万条事件",
            "部署目标为 AWS 上的 Kubernetes 集群",
            "团队为 3 名后端工程师,具备扎实的 Go 和 Python 经验",
            "团队没有 Rust 经验",
            "时间线为 2 个月内交付 MVP",
            "必须能集成 Kafka 和 PostgreSQL",
        ],
    },
]


DATASET_DESCRIPTION = (
    "用于评估研究简报 (research brief) 生成质量的数据集。每个样本包含一段"
    "三轮的用户/助手澄清对话作为 inputs, 以及一份标准答案 criteria 列表 ——"
    "下游生成的研究简报应当完整保留这些事实。"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="如果数据集已存在,先删除再重建",
    )
    parser.add_argument(
        "--dataset-name",
        default=os.getenv("LANGSMITH_DATASET", "deep_research_scoping"),
        help="LangSmith 数据集名称 (默认 deep_research_scoping)",
    )
    return parser.parse_args()


def build_examples(test_cases: list[TestCase]) -> list[dict]:
    return [
        {
            "inputs": {"messages": tc["conversation"]},
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
                f"  - 如需追加新示例,请到 LangSmith UI 手动操作\n"
                f"  - 如需重建,请加上 --recreate 重新运行本脚本",
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

"""One source-grounded review per draft; at most one semantic revision."""
import hashlib
import json
import re
import time

from langchain_core.messages import HumanMessage, SystemMessage
from openai import APIError, LengthFinishReasonError
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from deep_research.model_transport import ainvoke_with_stream_retry, streaming_options
from deep_research.review_diagnostics import safe_provider_error, safe_validation_errors
from deep_research.prompts import evidence_fidelity_instructions
from deep_research.research_requirements import requirements_context, approximate_report_length, report_length_guidance
from deep_research.source_evidence import writer_evidence_payload
from deep_research.structured_output_fallback import build_json_fallback_prompt
from deep_research.workflow_contract import message_text


decision_claim_checks = (
    "重点逐项核对数字、括号内结论和处置建议：数字所在句须写清比较基线、测试范围和例外，"
    "不能只借标题暗示基线；不同时间范围的预期与目标不得拼接成同一版本承诺。"
    "回退或配置改变只说明来源证明的对应影响，不能扩写为全部收益消失或其他风险均已消除，"
    "括号中的简写也必须保留范围。可选的防护或适配须保留触发条件，不改成无条件要求。"
    "对于用户所问操作，分别核对参数取值、生效时机和是否允许在进行中的过程里任意切换；"
    "限定来源缺少哪一项就明确说明哪一项，不能用笼统的‘其他行为未说明’代替。"
    "保留的函数、宏或接口必须交代来源给出的可用构建、版本及其他适用前提。"
    "用户未要求的实现细节或发布展望若不能完整保留其条件，应整条删除，不要为它们扩写短报告。"
    "风险句即使使用‘可能’，仍须保留来源限定的对象、使用规模、工作负载或其他触发条件；"
    "‘可能发生’不能代替‘在何种条件下可能发生’，也不能反推其他情况一定安全。"
    "把一种适配途径写成取得某类收益的必要条件，也需要来源支持；"
    "即使没有写‘全部’或‘所有’，也不能把某项配置变化推论为该类收益不存在。"
)


class ReviewDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    passed: bool
    issues: list[str] = Field(max_length=12)


class SourcePassage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source_id: int = Field(ge=1)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)


class ClaimSupport(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    claim_id: int = Field(ge=1)
    evidence: list[SourcePassage] = Field(min_length=1, max_length=4)


class SourceCondition(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    condition: str = Field(min_length=1, max_length=800)
    source: SourcePassage


class ConditionSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    prerequisites: list[SourceCondition] = Field(max_length=3, description=(
        "先独立检查来源中的实质适用、安全或适配前提。支持声明、标签、成功构建和性能测试"
        "不属于这类前提，也不能替代它们。忠实保留来源的触发条件和可能性。"))
    prerequisites_absent_reason: str = Field(default="", max_length=500, description=(
        "仅当限定来源没有与任务相关的实质前提时，简短说明证据边界；不能因篇幅短而省略检查。"))
    conditions: list[SourceCondition] = Field(max_length=5, description=(
        "其余决策条件：操作边界、兼容性及关键指标的适用范围；不重复实质前提，不枚举实现教程。"))


class ConditionCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    condition_id: int = Field(ge=1)
    claim_ids: list[int] = Field(default_factory=list, max_length=80)
    not_applicable_reason: str = Field(default="", max_length=500)


class GroundedReviewDecision(ReviewDecision):
    # Rejections need issues, not a complete proof of support. A passing result
    # must cover every supplied claim; that is checked against this candidate.
    support: list[ClaimSupport] = Field(default_factory=list, max_length=80)
    condition_coverage: list[ConditionCoverage] = Field(default_factory=list, max_length=8)


class ReportReviewBudgetError(ValueError):
    """The shared source-selection/review transport-read allowance is exhausted."""


class ReportReviewContext:
    """Per writing node only; never put this transient object in a checkpoint."""

    def __init__(self):
        self.reads = 0
        self.source_signature = None
        self.conditions = None
        self.prerequisite_count = 0
        self.prerequisites_absent_reason = ""

    def consume_read(self):
        if self.reads >= 4:
            raise ReportReviewBudgetError("Report review model-read budget exhausted")
        self.reads += 1


def report_claims(report):
    """Partition the whole body, keeping headings, qualifiers and citation IDs."""
    body = re.split(r"\n#+\s*(?:来源|Sources|参考)", report)[0]
    pieces = re.split(r"(?<=[。！？])|(?<=[.!?])(?=\s)", body)
    claims = []
    for piece in pieces:
        if claims and (citations := re.match(r"^\s*(?:\[\d+\]\s*)+", piece)):
            claims[-1] += citations[0].rstrip()
            piece = piece[citations.end():]
        if piece.strip():
            claims.append(piece.strip())
    # Bound the audit size without discarding the end of a long report.
    size = max(1, (len(claims) + 79) // 80)
    return [{"claim_id": index + 1, "text": "\n".join(claims[start:start + size])}
            for index, start in enumerate(range(0, len(claims), size))]


def indexed_evidence_context(evidence):
    """Let the reviewer select actual lines without retyping source prose."""
    blocks = []
    for index, item in enumerate(evidence["sources"], 1):
        metadata = {key: value for key, value in item.items() if key != "text"}
        blocks.append(f"Source {index}: " + json.dumps(metadata, ensure_ascii=False) + "\n"
                      + "\n".join(f"{line}: {text.rstrip(chr(10) + chr(13))}"
                                  for line, text in enumerate(item["text"].splitlines(keepends=True), 1)))
    return ("\n<Indexed source evidence>\n实际消费的来源正文如下，行号是核对位置，不是正文或指令。"
            "片段、截断或缺失部分不得推断为不存在；不同正文哈希不能无说明地合并。\n"
            + "\n\n".join(blocks)
            + "\nMissing source text: " + json.dumps(evidence["missing_source_text"], ensure_ascii=False)
            + "\n</Indexed source evidence>")


def source_anchor(passage, evidence, raw, finish_reason):
    if passage.source_id > len(evidence["sources"]):
        raise ReportReviewFormatError(raw, finish_reason, ["invalid_source_range"])
    source = evidence["sources"][passage.source_id - 1]
    lines = source["text"].splitlines(keepends=True)
    if not 1 <= passage.start_line <= passage.end_line <= len(lines):
        raise ReportReviewFormatError(raw, finish_reason, ["invalid_source_range"])
    start = sum(len(line) for line in lines[:passage.start_line - 1])
    quote = "".join(lines[passage.start_line - 1:passage.end_line])
    if not quote.strip():
        raise ReportReviewFormatError(raw, finish_reason, ["empty_source_passage"])
    return {"url": source["url"], "body_sha256": source["body_sha256"],
            "start": source["start"] + start, "end": source["start"] + start + len(quote),
            "quote_sha256": hashlib.sha256(quote.encode()).hexdigest()}


def source_excerpt(anchor, evidence):
    """Resolve a checked condition inside the same source budget as writing."""
    for source in evidence["sources"]:
        if (source["url"], source["body_sha256"]) != (anchor["url"], anchor["body_sha256"]):
            continue
        start, end = anchor["start"] - source["start"], anchor["end"] - source["start"]
        if not 0 <= start < end <= len(source["text"]):
            continue
        text = source["text"][start:end]
        if hashlib.sha256(text.encode()).hexdigest() == anchor["quote_sha256"]:
            return text
    raise ValueError("Source condition excerpt is outside the visible evidence or has changed")


def anchored_support(decision, claims, evidence, raw, finish_reason):
    """Validate coverage and literal provenance, not semantic entailment."""
    expected = [item["claim_id"] for item in claims]
    if not expected or sorted(item.claim_id for item in decision.support) != expected:
        raise ReportReviewFormatError(raw, finish_reason, ["incomplete_claim_support"])
    records = []
    for item in sorted(decision.support, key=lambda item: item.claim_id):
        anchors = [source_anchor(passage, evidence, raw, finish_reason) for passage in item.evidence]
        records.append({"claim_id": item.claim_id,
                        "claim_sha256": hashlib.sha256(claims[item.claim_id - 1]["text"].encode()).hexdigest(),
                        "evidence": anchors})
    return records


class ReportReviewFormatError(ValueError):
    """Persist only safe response diagnostics, never provider text or reasoning."""

    def __init__(self, raw, finish_reason, errors, *, validation=None):
        self.diagnostics = {
            "response_sha256": hashlib.sha256(raw.encode()).hexdigest(),
            "response_characters": len(raw),
            "finish_reason": finish_reason if finish_reason in {
                "stop", "length", "content_filter", "tool_calls", "function_call"
            } else "unknown",
            "validation_error_types": errors,
        }
        if validation is not None:
            self.diagnostics.update(validation)
        super().__init__("Report review did not produce a complete, valid decision")


class ReportReviewRequestError(ValueError):
    """A failed SDK read is unavailable, not a semantic rejection."""

    def __init__(self, error, elapsed):
        status = getattr(error, "status_code", None)
        self.diagnostics = {
            "phase": "model_read", "elapsed_seconds": elapsed,
            "exception_type": type(error).__name__ if type(error).__module__.startswith("openai") else "APIError",
            "http_status": status if type(status) is int and 100 <= status <= 599 else None,
            "provider_error": safe_provider_error({"type": getattr(error, "type", None),
                                                  "code": getattr(error, "code", None)}),
            "decision_available": False,
        }
        super().__init__("Report review SDK read failed; no decision is available")


async def read_review_json(model, schema, prompt, content, context):
    prompt = build_json_fallback_prompt(schema, prompt, disable_thinking=False)
    reviewer = model.bind(response_format={"type": "json_object"}) if streaming_options(model) else model
    started = time.monotonic()
    try:
        response = await ainvoke_with_stream_retry(reviewer, [
            SystemMessage(content=prompt), HumanMessage(content=content),
        ], before_attempt=context.consume_read)
    except LengthFinishReasonError as exc:
        visible = "".join(message_text(choice.message.content) for choice in exc.completion.choices)
        raise ReportReviewFormatError(visible, "length", ["incomplete_response"]) from None
    except APIError as exc:
        raise ReportReviewRequestError(exc, time.monotonic() - started) from None
    raw = message_text(response.content)
    finish_reason = response.response_metadata.get("finish_reason")
    if finish_reason and finish_reason != "stop":
        raise ReportReviewFormatError(raw, finish_reason, ["incomplete_response"])
    payload = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    try:
        decision = schema.model_validate_json(payload)
    except ValidationError as exc:
        errors = exc.errors(include_url=False, include_context=False, include_input=False)
        raise ReportReviewFormatError(raw, finish_reason, sorted({
            error["type"] for error in errors
        }), validation=safe_validation_errors(schema, errors)) from None
    return decision, raw, finish_reason


async def select_source_conditions(model, state, evidence, context):
    """Choose decision prerequisites from the sources without seeing a draft."""
    signature = hashlib.sha256((json.dumps(evidence, sort_keys=True, ensure_ascii=False)
                                + requirements_context(state)).encode()).hexdigest()
    if context.source_signature not in {None, signature}:
        raise ValueError("Report review context does not belong to these sources and requirements")
    context.source_signature = signature
    if context.conditions is None:
        selection, raw, finish = await read_review_json(model, ConditionSelection, (
            "只依据原始研究要求与实际来源，独立选择会改变比较结论或试用建议的必要条件。"
            "当前没有候选稿，不要猜测报告会写什么，也不要写报告答案。"
            "先单独填写 prerequisites：通读来源，选择能力真正成立或安全使用所需的实质适用与适配前提。"
            "不能将支持声明、标签、构建方式或性能表现放入此组；这些不是实际安全或适配工作的替代品。"
            "来源描述的内部机制、状态或资源的安全约束若影响试用建议，应概括为实质审查或适配前提，"
            "保留可能性和触发条件，不扩大为所有场景一律实施某项防护。"
            "只有原文确实没有与任务相关的此类前提，才留空并填写 prerequisites_absent_reason。"
            "再填写 conditions 中的其余决策条件，不因容易复述而优先选择标签或数值。"
            "短比较报告两组合计约四至六项，最多八项；不按来源目录顺序枚举。"
            "同义的声明、标记与回退行为合并；一项条件只表达一个清晰前提，不塞入整章摘要。"
            "不罗列全部 API 或实现步骤；用户未问未来计划时不把历史展望列为必需内容。"
            "用户只问是否试用时，不要从兼容性维度推导必须覆盖源码适配手册；"
            "编程接口调用、底层内存管理、编译平台与分发工具的具体操作不作为独立必需项。"
            "每项 condition 用一句话忠实概括所选前提，source 给出可直接核对的完整来源行范围。"
            "概括必须保留对象、触发条件和例外，不得新增来源未说的义务。"
            "输出 schema 要求的 JSON，不输出思考过程。"
            + evidence_fidelity_instructions + requirements_context(state)
        ), indexed_evidence_context(evidence), context)
        if bool(selection.prerequisites) == bool(selection.prerequisites_absent_reason.strip()):
            raise ReportReviewFormatError(raw, finish, ["inconsistent_prerequisite_selection"])
        conditions = [*selection.prerequisites, *selection.conditions]
        if not conditions:
            raise ReportReviewFormatError(raw, finish, ["empty_source_conditions"])
        for condition in conditions:
            source_anchor(condition.source, evidence, raw, finish)
        context.conditions = conditions
        context.prerequisite_count = len(selection.prerequisites)
        context.prerequisites_absent_reason = selection.prerequisites_absent_reason
    return context.conditions


def checked_condition_coverage(decision, conditions, claims, raw, finish):
    expected = list(range(1, len(conditions) + 1))
    if sorted(item.condition_id for item in decision.condition_coverage) != expected:
        raise ReportReviewFormatError(raw, finish, ["incomplete_condition_coverage"])
    valid_claims = {item["claim_id"] for item in claims}
    for item in decision.condition_coverage:
        if item.claim_ids:
            if item.not_applicable_reason or len(set(item.claim_ids)) != len(item.claim_ids) or not set(item.claim_ids) <= valid_claims:
                raise ReportReviewFormatError(raw, finish, ["invalid_condition_coverage"])
        elif not item.not_applicable_reason.strip():
            raise ReportReviewFormatError(raw, finish, ["missing_condition_coverage"])
    if not any(item.claim_ids for item in decision.condition_coverage):
        raise ReportReviewFormatError(raw, finish, ["no_relevant_source_conditions"])
    return [item.model_dump() for item in sorted(decision.condition_coverage, key=lambda item: item.condition_id)]


async def review_report(model, state, report):
    """Use the existing final writer role; malformed/unavailable review fails closed."""
    evidence = writer_evidence_payload(state.get("source_evidence", []), state.get("sources", []))
    grounded = bool(state.get("source_evidence"))
    claims = report_claims(report) if grounded else []
    schema = GroundedReviewDecision if grounded else ReviewDecision
    context = state.get("_report_review_context") or ReportReviewContext()
    conditions = await select_source_conditions(model, state, evidence, context) if grounded else []
    condition_locations = [{"condition_id": index,
                            "kind": "substantive_prerequisite" if index <= context.prerequisite_count else "decision_condition",
                            "source_excerpt": source_excerpt(source_anchor(item.source, evidence, "", None), evidence),
                            **item.model_dump()}
                           for index, item in enumerate(conditions, 1)]
    prompt = (
        "逐句核对候选报告与实际来源，尤其检查建议、总结和重复出现的数字是否丢掉了限定。"
        "每条断言都必须由限定来源支持，不能用自身知识填补。固定版本中的未来预期"
        "必须明确是该版本文档当时的预期，不得写成今天的预告；风险条件和适用范围不得强化。"
        "同时检查用户要求的重要限定是否遗漏、编号引用及证据不足说明。不要估算字数，程序另行计数。"
        "只指出改变事实含义、决策条件或用户要求的实质问题，不因措辞风格而拒绝。"
        "核验对象是报告已有断言和用户明确要求，不是要求短报告覆盖整篇资料。"
        "未写入报告且用户未要求的 API 示例、平台细节和构建步骤，不得单独列为遗漏。"
        "但影响报告结论的条件、例外，以及用户所问操作在限定来源中的证据缺口必须检查。"
        "每条问题引用候选稿短语并说明与来源的实质差异；不要只要求增加细节。"
        "逐项区分接口或指标的检测对象，不得把能力、配置和当前运行状态混为同一判断。"
        "检查建议中的实质适配和安全审查前提；仅声明支持、成功构建或性能测试不能代替来源要求的审查。"
        "支持关系允许忠实释义和谨慎的逻辑推论，不要求逐字照抄；已明确标注的条件性建议"
        "可以不是来源原话。不得误报候选稿中已经明确保留的限定或已解决的问题。"
        "按整篇上下文判断建议是否已标注、限定是否清楚，不要求每句话重复标签；"
        "但独立重述的数量、保证或适用条件不能与前文限定矛盾。"
        + decision_claim_checks
        + "只返回符合下方 schema 的 JSON，包含 passed 和 issues。"
        "有任何实质问题必须 passed=false；通过时 issues 必须为空。不要重写报告，不输出推理。"
        + evidence_fidelity_instructions + requirements_context(state)
    )
    if grounded:
        prompt += (
            "\n必须逐项核对 Claims to check 中全部编号断言，再检查结论是否遗漏来源中的重要前提。"
            "通过时 support 必须逐一列出每个 claim_id 及其 evidence：source_id、start_line、end_line；"
            "source_id 对应 Source 编号，行号包含起止行，只能选择实际提供的行。程序据此提取原文。"
            "选取足以核对条件、例外和时间属性的最小完整原文范围，不要只指向相同名词。"
            "建议和证据缺口也要列出据以判断的相关原文；格式标题与其后的断言一起核对。"
            "若原文不能支持报告的完整含义，或建议漏掉实质前提，应 passed=false 并在 issues 中指出；"
            "拒绝时 support 可以为空。只输出来源位置与实质问题，不输出思考过程。"
            "来源列举多个对象时，报告可以只选其中与任务相关的对象，不必复述整个集合。"
            "未写入报告、也未被用户要求的未来计划不得反向要求添加。issues 不得包含你已判为可接受的条目。"
            "\n另逐一核对 Source decision conditions，这些是未看候选稿时从原文独立选出的条件。"
            "每项相邻的 source_excerpt 是程序从实际原文提取的内容；概括若漏了触发条件或例外，以原文为准。"
            "不能只核对报告已经写出的断言而遗漏整条决策前提。通过时 condition_coverage 须覆盖所有 condition_id，"
            "用 claim_ids 指向报告实际保留该前提的断言。仅有声明、标记或性能验证不得算作实质安全审查。"
            "标为 substantive_prerequisite 的条件单独核对；报告只提到支持声明或形式性步骤时，这项仍未覆盖。"
            "按整个段落判断覆盖，允许忠实合并与条件性推断，不要求照抄术语或每句话重复前提。"
            "短比较报告对实质适配和安全审查的准确概括，可以覆盖相应底层实现约束，"
            "不必展开接口调用、内存管理或构建教程；只有报告保留了对应细节断言时才逐项检查那些细节。"
            "选择结果也是待核对的数据；若某条件与来源不符或确实不适用于原始要求和报告，"
            "可留下空 claim_ids 并用 not_applicable_reason 简短说明；缺失的重要前提不能用不适用来代替。"
            "有适用而未覆盖的条件必须拒绝，并指出缺少什么及依据的来源位置。"
        )
    # Reuse the shared JSON instructions without adding fallback model calls or
    # forced tools, which conflict with some providers' thinking modes.
    decision, raw, finish_reason = await read_review_json(model, schema, prompt,
        indexed_evidence_context(evidence)
        + "\n<Candidate report>\n" + report + "\n</Candidate report>"
        + ("\n<Claims to check>\n" + json.dumps(claims, ensure_ascii=False)
           + "\n</Claims to check>\n<Source decision conditions>\n"
           + json.dumps(condition_locations, ensure_ascii=False)
           + "\n</Source decision conditions>" if grounded else ""), context)
    if decision.passed != (not decision.issues):
        raise ReportReviewFormatError(raw, finish_reason, ["inconsistent_decision"])
    result = decision.model_dump(exclude={"support", "condition_coverage"})
    if grounded:
        result["source_conditions"] = [{"condition_id": index, "condition": item.condition,
                                        "kind": "substantive_prerequisite" if index <= context.prerequisite_count else "decision_condition",
                                        "source": source_anchor(item.source, evidence, raw, finish_reason)}
                                       for index, item in enumerate(conditions, 1)]
        result["source_prerequisites_absent_reason"] = context.prerequisites_absent_reason
        result["review_model_reads"] = context.reads
    if grounded and decision.passed:
        result["source_support"] = anchored_support(decision, claims, evidence, raw, finish_reason)
        result["condition_coverage"] = checked_condition_coverage(decision, conditions, claims, raw, finish_reason)
    body = re.split(r"\n#+\s*(?:来源|Sources|参考)", report)[0]
    count = len(re.findall(r"[\u4e00-\u9fff]", body))
    result["body_han_count"] = count
    if (target := approximate_report_length(state)) is not None:
        lower, upper = round(target * 0.8), round(target * 1.3)
        result["body_han_bounds"] = [lower, upper]
        if not lower <= count <= upper:
            result["passed"] = False
            result["issues"].insert(0, f"程序实测正文 {count} 个汉字，用户约 {target} 字的范围为 {lower}–{upper}；请重新规划全文至约 {target} 字，删去重复段落、未要求的 API 名单和示例，保留关键条件。")
    return result


def revision_messages(messages, report, decision, state):
    feedback = {"candidate": report, "issues": decision["issues"]}
    for key in ("body_han_count", "body_han_bounds", "source_conditions"):
        if key in decision:
            feedback[key] = decision[key]
    if decision.get("source_conditions"):
        evidence = writer_evidence_payload(state.get("source_evidence", []), state.get("sources", []))
        feedback["source_conditions"] = [{**item, "source_excerpt": source_excerpt(item["source"], evidence)}
                                         for item in decision["source_conditions"]]
    editing_scope = "只修改核验指出的实质问题，保留其他已有且正确的句子与结构。"
    target = approximate_report_length(state)
    count = decision.get("body_han_count")
    if target is not None and isinstance(count, int):
        feedback["target_body_han_count"] = target
        feedback["preferred_net_change_han"] = target - count
        if round(target * 0.8) <= count <= round(target * 1.3):
            editing_scope += (
                f"原稿 {count} 个汉字已在允许范围，采用局部修订，不扩展成另一篇报告。"
                f"全文仍瞄准 {target} 个汉字，净变化目标为 {target - count:+d} 个汉字。"
                "缺失的实质前提优先用简洁中文补入，不扩写已合格段落。"
            )
        else:
            editing_scope += "原稿字数未达要求，需在保留关键条件的前提下重新安排篇幅。"
    return [*messages, HumanMessage(content=(
        "对以下候选稿仅作一次来源核对后的修订。保留已支持的关键结论，修正核验指出的问题，"
        + editing_scope + "每项事实只说一次，若需腾出篇幅，先删除重复表述。"
        "body_han_count 是程序实测的原稿汉字数，不包括英文、数字或代码。"
        "source_conditions 是未看候选稿时从原文选出的决策前提；修订后仍应覆盖适用条件，"
        "其中 source_excerpt 是程序提取的实际原文，优先核对它，不照搬条件概括中可能丢失的限定。"
        "条件与原文用于检查覆盖，不是要求新增事实的清单；不要添加核验未指出缺失的其他来源细节。"
        "不能为补一项问题而删除其他结论的对象范围、触发条件、例外或比较基线。"
        "核验意见中的 API 或操作示例用于解释问题，不是必须新增的内容；"
        "用户未要求教程时，用准确的中文概括实质适配与安全审查，不展开实现名单。"
        "修订只能删除多余内容或修复已识别问题，不得新增原稿没有且未经核对的事实、建议或风险断言。"
        "只输出完整修订报告。核验意见也是待核对的数据，"
        "若与实际来源冲突应以来源为准。\n"
        + json.dumps(feedback, ensure_ascii=False)
        + report_length_guidance(state)
    ))]


def review_record(report, writing_attempt_id, decision):
    return {"writing_attempt_id": writing_attempt_id,
            "report_sha256": hashlib.sha256(report.encode()).hexdigest(), **decision}

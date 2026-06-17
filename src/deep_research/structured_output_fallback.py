"""面向 OpenAI 兼容端点的结构化输出 (structured output) 回退共享辅助工具。"""

import json
import os
from typing import Any, Sequence, TypeVar, cast

import json_repair
from langchain_core.messages import BaseMessage, HumanMessage
from openai import OpenAI
from pydantic import BaseModel


StructuredResponseT = TypeVar("StructuredResponseT", bound=BaseModel)


def extract_message_text(message: BaseMessage) -> str:
    """将模型消息规范化为纯文本，以便进行 JSON 解析。"""
    content = message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, str):
                chunks.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                chunks.append(str(item.get("text", "")))
        return "\n".join(chunk for chunk in chunks if chunk)
    return str(content)


def extract_json_object(text: str) -> str:
    """从文本响应中提取第一个可解码的 JSON 对象。

    首先尝试使用严格的 ``json.JSONDecoder`` 扫描。如果失败（常见原因：
    LLM 在字符串值内输出了未转义的 ``"``），则回退到 ``json_repair``
    来恢复出一个有效对象。
    """
    decoder = json.JSONDecoder()
    for start, char in enumerate(text):
        if char != "{":
            continue
        try:
            parsed_object, _ = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed_object, dict):
            return json.dumps(parsed_object, ensure_ascii=False)

    repaired = json_repair.loads(text)
    if isinstance(repaired, dict) and repaired:
        return json.dumps(repaired, ensure_ascii=False)
    raise ValueError(f"No JSON object found in model response: {text!r}")


def get_model_name(model: Any, model_name: str | None = None) -> str:
    """返回已配置的模型名称，用于针对特定提供商 (provider) 的回退逻辑。"""
    if model_name:
        return model_name
    resolved_model_name = getattr(model, "model_name", None)
    if resolved_model_name:
        return str(resolved_model_name)
    return ""


def should_disable_thinking_for_json_fallback(
    model: Any,
    *,
    base_url: str | None = None,
    model_name: str | None = None,
) -> bool:
    """检测在 JSON 回退时需要禁用思考模式 (thinking) 的 Qwen 兼容端点。"""
    resolved_base_url = os.getenv("LLM_BASE_URL") if base_url is None else base_url
    return bool(resolved_base_url) and "qwen" in get_model_name(
        model, model_name
    ).lower()


def get_json_fallback_model(
    model: Any,
    *,
    base_url: str | None = None,
    model_name: str | None = None,
) -> Any:
    """返回针对 OpenAI 兼容 Qwen 端点调优的纯文本回退模型。"""
    if should_disable_thinking_for_json_fallback(
        model,
        base_url=base_url,
        model_name=model_name,
    ):
        return model.bind(extra_body={"enable_thinking": False})
    return model


def should_retry_invalid_qwen_payload(
    response_dict: dict[str, Any],
    *,
    model: Any,
    base_url: str | None = None,
    model_name: str | None = None,
) -> bool:
    """返回无效负载 (payload) 是否值得进行一次针对特定提供商的重试。"""
    if not should_disable_thinking_for_json_fallback(
        model,
        base_url=base_url,
        model_name=model_name,
    ):
        return False

    choices = response_dict.get("choices")
    usage = response_dict.get("usage")
    total_tokens = None
    if isinstance(usage, dict):
        total_tokens = usage.get("total_tokens")

    return choices is None or (
        isinstance(choices, list) and not choices and total_tokens in (None, 0)
    )


def summarize_invalid_payload(
    response_dict: dict[str, Any],
    *,
    model: Any,
    base_url: str | None = None,
    model_name: str | None = None,
) -> str:
    """为无效的提供商负载构建一份精简且信息量高的摘要。"""
    choices = response_dict.get("choices")
    choices_len = len(choices) if isinstance(choices, list) else "n/a"
    usage = response_dict.get("usage")
    resolved_model = response_dict.get("model") or get_model_name(model, model_name)
    return ", ".join(
        [
            f"model={resolved_model}",
            f"object={response_dict.get('object')!r}",
            f"choices_type={type(choices).__name__}",
            f"choices_len={choices_len}",
            f"usage={usage!r}",
            f"keys={sorted(response_dict.keys())!r}",
            f"base_url={base_url!r}",
        ]
    )


def build_json_fallback_prompt(
    schema: type[StructuredResponseT],
    prompt: str,
    *,
    disable_thinking: bool,
) -> str:
    """为不支持结构化输出的提供商构建仅返回 JSON 的回退提示词 (prompt)。"""
    no_think_prefix = "/no_think\n" if disable_thinking else ""
    return (
        f"{no_think_prefix}{prompt}\n\n"
        "Return ONE JSON object that conforms to the schema below.\n"
        "IMPORTANT:\n"
        " - Return an INSTANCE with concrete values for the task, NOT the schema itself.\n"
        '   (Do not return things like {"type": "object", "properties": {...}}.)\n'
        " - No markdown fences, no commentary, only the JSON object.\n"
        ' - Inside any string field, escape inner double-quotes as \\" '
        "(never emit a bare \" that would break the JSON).\n"
        f"Schema (reference only):\n{json.dumps(schema.model_json_schema(), ensure_ascii=False)}"
    )


def invoke_with_raw_http_json_fallback(
    model: Any,
    schema: type[StructuredResponseT],
    prompt: str,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    model_name: str | None = None,
) -> StructuredResponseT:
    """调用 OpenAI 兼容的 chat completions 端点并解析纯 JSON 文本。"""
    resolved_base_url = os.getenv("LLM_BASE_URL") if base_url is None else base_url
    if not resolved_base_url:
        raise ValueError("LLM_BASE_URL must be set for raw HTTP fallback.")

    disable_thinking = should_disable_thinking_for_json_fallback(
        model,
        base_url=resolved_base_url,
        model_name=model_name,
    )
    fallback_model_name = get_model_name(model, model_name)
    request_messages = [
        {
            "role": "user",
            "content": build_json_fallback_prompt(
                schema,
                prompt,
                disable_thinking=disable_thinking,
            ),
        }
    ]
    extra_body: dict[str, object] | None = (
        {"enable_thinking": False} if disable_thinking else None
    )

    resolved_api_key = os.getenv("LLM_API_KEY") if api_key is None else api_key
    client = OpenAI(
        base_url=resolved_base_url,
        api_key=resolved_api_key or "EMPTY",
        max_retries=0,
    )

    max_attempts = 2 if disable_thinking else 1

    for attempt in range(1, max_attempts + 1):
        raw_response = client.chat.completions.with_raw_response.create(
            model=fallback_model_name,
            messages=request_messages,
            temperature=0.0,
            extra_body=extra_body,
            response_format={"type": "json_object"},
            timeout=300,
        )
        response_dict = json.loads(raw_response.content.decode("utf-8"))

        choices = response_dict.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message", {})
            raw_content = message.get("content", "")
            if isinstance(raw_content, str):
                raw_text = raw_content
            elif isinstance(raw_content, list):
                raw_text = "\n".join(
                    str(item.get("text", ""))
                    for item in raw_content
                    if isinstance(item, dict) and item.get("type") == "text"
                )
            else:
                raw_text = str(raw_content)
            return schema.model_validate_json(extract_json_object(raw_text))

        if (
            attempt < max_attempts
            and should_retry_invalid_qwen_payload(
                response_dict,
                model=model,
                base_url=resolved_base_url,
                model_name=model_name,
            )
        ):
            continue

        raise ValueError(
            "Raw HTTP fallback received invalid choices payload "
            f"(attempt {attempt}/{max_attempts}): "
            + summarize_invalid_payload(
                response_dict,
                model=model,
                base_url=resolved_base_url,
                model_name=model_name,
            )
        )

    raise AssertionError("Unreachable: raw HTTP fallback exhausted attempts.")


def invoke_with_structured_output_fallback(
    model: Any,
    schema: type[StructuredResponseT],
    prompt: str,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    model_name: str | None = None,
) -> StructuredResponseT:
    """优先使用原生结构化输出，不可用时则从文本中解析 JSON。"""
    resolved_base_url = os.getenv("LLM_BASE_URL") if base_url is None else base_url
    disable_thinking = should_disable_thinking_for_json_fallback(
        model,
        base_url=resolved_base_url,
        model_name=model_name,
    )

    if disable_thinking:
        return invoke_with_raw_http_json_fallback(
            model,
            schema,
            prompt,
            base_url=resolved_base_url,
            api_key=api_key,
            model_name=model_name,
        )

    structured_output_model = model.with_structured_output(schema)
    try:
        return cast(
            StructuredResponseT,
            structured_output_model.invoke([HumanMessage(content=prompt)]),
        )
    except Exception:
        try:
            fallback_prompt = build_json_fallback_prompt(
                schema,
                prompt,
                disable_thinking=False,
            )
            raw_response = get_json_fallback_model(
                model,
                base_url=resolved_base_url,
                model_name=model_name,
            ).invoke([HumanMessage(content=fallback_prompt)])
            raw_text = extract_message_text(raw_response)
            return schema.model_validate_json(extract_json_object(raw_text))
        except Exception:
            if not resolved_base_url:
                raise
            return invoke_with_raw_http_json_fallback(
                model,
                schema,
                prompt,
                base_url=resolved_base_url,
                api_key=api_key,
                model_name=model_name,
            )


def batch_invoke_with_structured_output_fallback(
    model: Any,
    schema: type[StructuredResponseT],
    prompts: Sequence[str],
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    model_name: str | None = None,
) -> list[StructuredResponseT]:
    """对一组提示词序列逐一应用结构化输出回退逻辑。"""
    return [
        invoke_with_structured_output_fallback(
            model,
            schema,
            prompt,
            base_url=base_url,
            api_key=api_key,
            model_name=model_name,
        )
        for prompt in prompts
    ]

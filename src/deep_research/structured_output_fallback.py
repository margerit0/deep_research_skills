"""面向 OpenAI 兼容端点的结构化输出 (structured output) 回退共享辅助工具。"""

import json
import os
from typing import Any, Sequence, TypeVar, cast

import json_repair
from httpx import URL
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.runnables.base import RunnableBindingBase
from langchain_openai import ChatOpenAI
from openai import OpenAI
from pydantic import BaseModel, ValidationError

from deep_research.review_diagnostics import safe_provider_error


StructuredResponseT = TypeVar("StructuredResponseT", bound=BaseModel)


def _bound_model_options(model):
    options = {}
    while isinstance(model, RunnableBindingBase):
        options = {**model.kwargs, **options}
        model = model.bound
    return model, options


def structured_output_strategy(model: Any, strategy: str | None = None) -> str:
    """Opt in per model; existing models keep the native-first path.

    An isolated GLM client can set metadata={"structured_output_strategy":
    "json_object"}. Explicit arguments take precedence over model metadata.
    """
    base, _ = _bound_model_options(model)
    metadata = getattr(base, "metadata", None)
    if strategy is None:
        strategy = metadata.get("structured_output_strategy", "native") if isinstance(metadata, dict) else "native"
    if strategy not in {"native", "json_object"}:
        raise ValueError("Unknown structured output strategy")
    return strategy


class StructuredOutputStreamError(ValueError):
    """Incomplete JSON streams never become schema-valid results."""

    def __init__(self, reason, *, finish_reason=None, done=False, provider_error=None):
        self.diagnostics = {
            "reason": reason,
            "finish_reason": finish_reason if isinstance(finish_reason, str) and finish_reason in {"stop", "length", "content_filter", "tool_calls"} else "unknown",
            "done_marker": done,
            "schema_valid": False,
        }
        if provider_error is not None:
            self.diagnostics["provider_error"] = safe_provider_error(provider_error)
        super().__init__("Structured JSON stream was incomplete or invalid")


def _read_json_stream(response):
    """Buffer SSE content only, require the terminal event, and reject errors.

    Read raw SDK lines because its parsed Stream API hides [DONE]. This also
    handles choices=null without taking a separate LangChain invoke path.
    """
    parts, data = [], []
    finish, done, choices_seen, event = None, False, False, ""
    last, usage = {}, None

    def consume():
        nonlocal finish, done, choices_seen, last, usage
        text = "\n".join(data)
        if event == "error":
            try:
                payload = json.loads(text)
            except ValueError:
                payload = {}
            raise StructuredOutputStreamError("provider_error", finish_reason=finish,
                provider_error=payload.get("error", payload) if isinstance(payload, dict) else {})
        if text.strip() == "[DONE]":
            done = True
            return
        if not text:
            return
        try:
            payload = json.loads(text)
        except ValueError:
            raise StructuredOutputStreamError("invalid_event", finish_reason=finish) from None
        if not isinstance(payload, dict):
            raise StructuredOutputStreamError("invalid_event", finish_reason=finish)
        if "error" in payload:
            raise StructuredOutputStreamError("provider_error", finish_reason=finish, provider_error=payload["error"])
        last = payload
        if payload.get("usage") is not None:
            usage = payload["usage"]
        choices = payload.get("choices")
        if choices is not None and not isinstance(choices, list):
            raise StructuredOutputStreamError("invalid_choices", finish_reason=finish)
        for choice in choices or []:
            if not isinstance(choice, dict) or choice.get("index", 0) != 0:
                raise StructuredOutputStreamError("invalid_choices", finish_reason=finish)
            choices_seen = True
            delta = choice.get("delta") or {}
            if not isinstance(delta, dict) or delta.get("tool_calls"):
                raise StructuredOutputStreamError("invalid_delta", finish_reason=finish)
            content = delta.get("content")
            if content is not None:
                if not isinstance(content, str) or finish is not None:
                    raise StructuredOutputStreamError("invalid_delta", finish_reason=finish)
                parts.append(content)
            if choice.get("finish_reason") is not None:
                finish = choice["finish_reason"]

    for line in response.iter_lines():
        if not line:
            consume()
            data, event = [], ""
            if done:
                break
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].removeprefix(" "))
    if data and not done:
        consume()
    if not done or (choices_seen and finish != "stop"):
        raise StructuredOutputStreamError("incomplete_response", finish_reason=finish, done=done)
    return {
        "model": last.get("model"), "object": "chat.completion", "usage": usage,
        "choices": [{"message": {"content": "".join(parts)}, "finish_reason": finish}]
        if choices_seen else last.get("choices"),
    }


def model_connection(model, base_url=None, api_key=None):
    """Respect the selected model's transport, including role-specific gateways."""
    model, _ = _bound_model_options(model)
    if base_url is None:
        value = getattr(model, "openai_api_base", None)
        if not value:
            client_url = getattr(getattr(model, "root_client", None), "base_url", None)
            if isinstance(client_url, (str, URL)):
                value = str(client_url)
        base_url = value if isinstance(value, str) and value else os.getenv("LLM_BASE_URL")
    if api_key is None:
        value = getattr(model, "openai_api_key", None)
        if hasattr(value, "get_secret_value"):
            value = value.get_secret_value()
        api_key = value if isinstance(value, str) and value else os.getenv("LLM_API_KEY")
    return base_url, api_key


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
    model, _ = _bound_model_options(model)
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
    stream: bool | None = None,
) -> StructuredResponseT:
    """调用 OpenAI 兼容的 chat completions 端点并解析纯 JSON 文本。"""
    resolved_base_url, api_key = model_connection(model, base_url, api_key)
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
    base, bound_options = _bound_model_options(model)
    streaming = stream if stream is not None else getattr(base, "streaming", False) is True
    # A configured ChatOpenAI already owns transport, SDK retry limits, timeout,
    # and headers. Reuse it for streaming rather than dropping those settings.
    client = base.root_client if streaming and isinstance(base, ChatOpenAI) else OpenAI(
        base_url=resolved_base_url, api_key=resolved_api_key or "EMPTY", max_retries=0,
    )
    if streaming and isinstance(base, ChatOpenAI) and (
        str(client.base_url).rstrip("/") != resolved_base_url.rstrip("/")
        or client.api_key != (resolved_api_key or "EMPTY")
    ):
        client = client.with_options(base_url=resolved_base_url, api_key=resolved_api_key or "EMPTY")

    max_attempts = 2 if disable_thinking else 1

    for attempt in range(1, max_attempts + 1):
        request_options = dict(
            model=fallback_model_name,
            messages=request_messages,
            temperature=0.0,
            extra_body=extra_body,
            response_format={"type": "json_object"},
            timeout=300,
        )
        if streaming:
            if isinstance(base, ChatOpenAI):
                params = {**base._default_params, **bound_options}
                if params.get("tools") or params.get("n", 1) != 1:
                    raise ValueError("JSON object reading requires one response without tools")
                request_options = {**params, **request_options}
                request_options["temperature"] = params.get("temperature", 0.0)
                request_options["extra_body"] = {**(params.get("extra_body") or {}), **(extra_body or {})} or None
                request_options["timeout"] = base.request_timeout if base.request_timeout is not None else client.timeout
                if base.rate_limiter is not None:
                    base.rate_limiter.acquire(blocking=True)
            with client.chat.completions.with_streaming_response.create(
                **{**request_options, "stream": True, "stream_options": {"include_usage": True}},
            ) as response:
                response_dict = _read_json_stream(response)
        else:
            raw_response = client.chat.completions.with_raw_response.create(**request_options)
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
            if streaming:
                # Never repair truncated or malformed streamed JSON into success.
                try:
                    return schema.model_validate_json(raw_text)
                except ValidationError:
                    raise StructuredOutputStreamError("schema_validation", finish_reason="stop", done=True) from None
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
    strategy: str | None = None,
) -> StructuredResponseT:
    """优先使用原生结构化输出，不可用时则从文本中解析 JSON。"""
    resolved_base_url, api_key = model_connection(model, base_url, api_key)
    disable_thinking = should_disable_thinking_for_json_fallback(
        model,
        base_url=resolved_base_url,
        model_name=model_name,
    )

    if structured_output_strategy(model, strategy) == "json_object":
        return invoke_with_raw_http_json_fallback(
            model, schema, prompt, base_url=resolved_base_url,
            api_key=api_key, model_name=model_name, stream=True,
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
    strategy: str | None = None,
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
            strategy=strategy,
        )
        for prompt in prompts
    ]

"""Use streamed transport for buffered OpenAI-compatible graph node results.

LangChain still returns one complete message, including parsed tool calls.
Passing the option through invoke keeps RunnableRetry around the whole call;
streaming a RunnableRetry directly would bypass that retry boundary.
"""

import asyncio
import logging

import httpx
from langchain_core.runnables.base import RunnableBindingBase
from langchain_openai import ChatOpenAI


def streaming_options(model) -> dict:
    """Leave other providers and standalone non-chat callables unchanged."""
    while isinstance(model, RunnableBindingBase):
        model = model.bound
    return {"stream": True} if isinstance(model, ChatOpenAI) else {}


async def ainvoke_with_stream_retry(model, messages, *, before_attempt=None):
    """Retry one interrupted buffered response, before any tools are dispatched.

    SDK retries cover connection establishment but not a response body that
    disconnects after headers. Do not retry HTTP rejection or semantic errors.
    """
    for attempt in range(2):
        if before_attempt is not None:
            before_attempt()
        try:
            return await model.ainvoke(messages, **streaming_options(model))
        except (httpx.RemoteProtocolError, httpx.ReadError, httpx.ReadTimeout):
            if attempt:
                raise
            logging.getLogger(__name__).warning("Buffered model stream interrupted; retrying once")
            await asyncio.sleep(1)

"""Use streamed transport for buffered OpenAI-compatible graph node results.

LangChain still returns one complete message, including parsed tool calls.
Passing the option through invoke keeps RunnableRetry around the whole call;
streaming a RunnableRetry directly would bypass that retry boundary.
"""

from langchain_core.runnables.base import RunnableBindingBase
from langchain_openai import ChatOpenAI


def streaming_options(model) -> dict:
    """Leave other providers and standalone non-chat callables unchanged."""
    while isinstance(model, RunnableBindingBase):
        model = model.bound
    return {"stream": True} if isinstance(model, ChatOpenAI) else {}

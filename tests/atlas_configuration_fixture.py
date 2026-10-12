"""Exercise actual configuration selection at every model and Skills call site."""

import os
from types import SimpleNamespace
from langchain_core.messages import AIMessage, ToolMessage
from deep_research import model_config, utils


def install(fixture, count, structured, plan, research, search, compress, write):
    class Model:
        def __init__(self, model, role=None, **kwargs):
            self.model_name = model
            self.role = role

        def bind_tools(self, tools):
            names = [
                getattr(tool, "name", getattr(tool, "__name__", "")) for tool in tools
            ]
            self.role = "SUPERVISOR" if "ConductResearch" in names else "RESEARCHER"
            return self

        def with_retry(self, **kwargs):
            return self

        def with_structured_output(self, schema, **kwargs):
            return SimpleNamespace(invoke=lambda messages: self.summary(schema))

        def summary(self, schema):
            count(f"config:SUMMARIZATION:{self.model_name}")
            return schema(summary="Fixture summary", key_excerpts="Fixture excerpt")

        def invoke(self, messages):
            role = self.role or "COMPRESSION"
            count(f"config:{role}:{self.model_name}")
            if role == "RESEARCHER":
                if not any(
                    isinstance(message, ToolMessage) and message.name == "load_skill"
                    for message in messages
                ):
                    return AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "id": name,
                                "name": "load_skill",
                                "args": {"skill_name": name},
                            }
                            for name in ("academic-research", "product-comparison")
                        ],
                    )
                return research(messages)
            return compress(messages)

        async def ainvoke(self, messages):
            role = self.role or "FINAL_REPORT"
            count(f"config:{role}:{self.model_name}")
            return await (plan(messages) if role == "SUPERVISOR" else write(messages))

    def scoped(model, schema, prompt):
        count(f"config:SCOPING:{model.model_name}")
        return structured(model, schema, prompt)

    def summarized_search(args):
        utils.process_search_results(
            {
                "https://example.com/fixture": {
                    "title": "fixture",
                    "raw_content": "Fixture source",
                }
            }
        )
        return search(args)

    model_config.init_chat_model = Model
    fixture.scope.invoke_with_structured_output_fallback = scoped
    fixture.scope.model = Model(os.environ["SCOPING_MODEL"], "SCOPING")
    fixture.supervisor.supervisor_model_with_tools = Model(
        os.environ["SUPERVISOR_MODEL"], "SUPERVISOR"
    )
    fixture.researcher.model_with_tools = Model(
        os.environ["RESEARCHER_MODEL"], "RESEARCHER"
    )
    fixture.researcher.compress_model = Model(
        os.environ["COMPRESSION_MODEL"], "COMPRESSION"
    )
    fixture.full.writer_model = Model(os.environ["FINAL_REPORT_MODEL"], "FINAL_REPORT")
    utils.summarization_model = Model(
        os.environ["SUMMARIZATION_MODEL"], "SUMMARIZATION"
    )
    fixture.researcher.tools_by_name["tavily_search"].invoke = summarized_search

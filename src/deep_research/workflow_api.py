"""Expose bounded workflow management requests without importing research graphs."""

from __future__ import annotations

import json
from functools import wraps

from pydantic import TypeAdapter, ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse
from starlette.routing import Route

from deep_research.workflow_definition import (
    MAX_DOCUMENT_BYTES,
    ArchiveWorkflowRequest,
    CreateWorkflowRequest,
    Identifier,
    PublishWorkflowRequest,
    SaveDraftRequest,
    ValidateWorkflowRequest,
)
from deep_research.workflow_registry import node_catalog
from deep_research.workflow_store import WorkflowStoreError, get_workflow_store

# Document bytes are also checked after parsing. Envelope overhead is bounded
# separately, including publication notes and escaped JSON supplied by clients.
MAX_REQUEST_BYTES = MAX_DOCUMENT_BYTES + 16_384
_IDENTIFIER = TypeAdapter(Identifier)


def _reject_constant(value):
    raise ValueError("Non-finite JSON")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


async def _body(request, model):
    try:
        length = request.headers.get("content-length")
        if length is not None and (int(length) < 0 or int(length) > MAX_REQUEST_BYTES):
            raise ValueError("Oversized request")
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > MAX_REQUEST_BYTES:
                raise ValueError("Oversized request")
            data.extend(chunk)
        value = json.loads(
            data.decode("utf-8"),
            parse_constant=_reject_constant,
            object_pairs_hook=_unique_object,
        )
        return model.model_validate(value)
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise WorkflowStoreError("workflow_request_invalid", 400) from exc


def _store(request):
    store = getattr(request.app.state, "workflow_store", None) or get_workflow_store()
    if store is None:
        raise WorkflowStoreError("workflow_editor_unavailable", 503)
    return store


def _endpoint(function):
    @wraps(function)
    async def wrapped(request):
        try:
            try:
                for value in request.path_params.values():
                    _IDENTIFIER.validate_python(value)
            except ValidationError as exc:
                raise WorkflowStoreError("workflow_request_invalid", 400) from exc
            result = await function(request)
            return JSONResponse(
                result.model_dump(mode="json"), headers={"Cache-Control": "no-store"}
            )
        except WorkflowStoreError as exc:
            return JSONResponse(
                exc.payload(),
                status_code=exc.status,
                headers={"Cache-Control": "no-store"},
            )
        except Exception:
            # Never serialize private database errors, paths, or provider text.
            return JSONResponse(
                {"reason": "workflow_storage_unavailable"},
                status_code=503,
                headers={"Cache-Control": "no-store"},
            )

    return wrapped


def _page(request) -> dict:
    try:
        return {
            "after": int(request.query_params.get("after", "0")),
            "limit": int(request.query_params.get("limit", "30")),
        }
    except ValueError as exc:
        raise WorkflowStoreError("workflow_page_invalid", 400) from exc


@_endpoint
async def catalog(request):
    """Return public node metadata, never handler names or credentials."""
    await run_in_threadpool(_store(request).check_ready)
    return node_catalog()


@_endpoint
async def workflows(request):
    """Create a workflow or read a stable page of workflow summaries."""
    store = _store(request)
    if request.method == "POST":
        body = await _body(request, CreateWorkflowRequest)
        return await run_in_threadpool(store.create, body)
    return await run_in_threadpool(
        store.list,
        archived=request.query_params.get("archived", "active"),
        **_page(request),
    )


@_endpoint
async def draft(request):
    """Read the current draft; a read has no publication or execution effect."""
    return await run_in_threadpool(
        _store(request).get, request.path_params["workflow_id"]
    )


@_endpoint
async def summary(request):
    """Read archive state for a directly opened workflow or revision."""
    return await run_in_threadpool(
        _store(request).summary, request.path_params["workflow_id"]
    )


@_endpoint
async def save(request):
    """Save a full document using its expected edit version."""
    body = await _body(request, SaveDraftRequest)
    return await run_in_threadpool(
        _store(request).save, request.path_params["workflow_id"], body
    )


@_endpoint
async def validate(request):
    """Check a saved snapshot against actual server publication capabilities."""
    body = await _body(request, ValidateWorkflowRequest)
    return await run_in_threadpool(
        _store(request).validate,
        request.path_params["workflow_id"],
        body.expected_edit_version,
    )


@_endpoint
async def publish(request):
    """Publish the saved version or return the original idempotent receipt."""
    body = await _body(request, PublishWorkflowRequest)
    return await run_in_threadpool(
        _store(request).publish, request.path_params["workflow_id"], body
    )


@_endpoint
async def revisions(request):
    """Read a bounded page of immutable publication summaries."""
    return await run_in_threadpool(
        _store(request).revisions, request.path_params["workflow_id"], **_page(request)
    )


@_endpoint
async def revision(request):
    """Read an intact publication even if its implementation is unavailable."""
    return await run_in_threadpool(
        _store(request).revision,
        request.path_params["workflow_id"],
        request.path_params["revision_id"],
    )


@_endpoint
async def archive(request):
    """Archive without deleting historical revisions, drafts or run references."""
    body = await _body(request, ArchiveWorkflowRequest)
    return await run_in_threadpool(
        _store(request).archive, request.path_params["workflow_id"], body
    )


routes = [
    Route("/atlas/workflow-node-types", catalog, methods=["GET"]),
    Route("/atlas/workflows", workflows, methods=["GET", "POST"]),
    Route("/atlas/workflows/{workflow_id}/summary", summary, methods=["GET"]),
    Route("/atlas/workflows/{workflow_id}", draft, methods=["GET"]),
    Route("/atlas/workflows/{workflow_id}/draft", save, methods=["PUT"]),
    Route("/atlas/workflows/{workflow_id}/validate", validate, methods=["POST"]),
    Route("/atlas/workflows/{workflow_id}/publish", publish, methods=["POST"]),
    Route("/atlas/workflows/{workflow_id}/revisions", revisions, methods=["GET"]),
    Route(
        "/atlas/workflows/{workflow_id}/revisions/{revision_id}",
        revision,
        methods=["GET"],
    ),
    Route("/atlas/workflows/{workflow_id}/archive", archive, methods=["POST"]),
]

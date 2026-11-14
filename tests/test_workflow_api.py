"""M2 management API contract, bounded input and fail-closed capability checks."""

import json

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from deep_research import workflow_api
from deep_research.workflow_store import WorkflowStore
from tests.test_workflow_store import publication_context


@pytest.fixture
def client(tmp_path):
    app = Starlette(routes=workflow_api.routes)
    app.state.workflow_store = WorkflowStore(
        tmp_path / "api.sqlite3", publication_context=publication_context
    )
    with TestClient(app) as client:
        yield client


def new_draft(client):
    response = client.post(
        "/atlas/workflows",
        json={
            "request_id": "new",
            "name": "API 研究",
            "source": {"kind": "template", "template_id": "standard_research"},
        },
    )
    assert response.status_code == 200
    return response.json()


def test_complete_management_roundtrip_and_cache_control(client):
    catalog = client.get("/atlas/workflow-node-types")
    assert len(catalog.json()["node_types"]) == 9
    assert catalog.headers["cache-control"] == "no-store"
    draft = new_draft(client)
    path = f"/atlas/workflows/{draft['workflow_id']}"
    assert client.get(path).json() == draft
    assert client.get(path + "/summary").json()["archived"] is False
    assert len(client.get("/atlas/workflows").json()["items"]) == 1
    validation = client.post(path + "/validate", json={"expected_edit_version": 1})
    assert validation.json()["scope"] == "publication" and validation.json()["valid"]
    request = {"expected_edit_version": 1, "request_id": "publish"}
    revision = client.post(path + "/publish", json=request).json()
    assert client.post(path + "/publish", json=request).json() == revision
    assert client.get(path + "/revisions/" + revision["revision_id"]).json() == revision
    assert client.get(path + "/revisions").json()["items"][0]["revision_number"] == 1
    assert client.get(path).json()["edit_version"] == 2
    assert client.post(path + "/archive", json={"expected_edit_version": 2}).json()[
        "archived"
    ]
    assert client.get(path).status_code == 200
    assert client.get("/atlas/workflows").json()["items"] == []
    assert len(client.get("/atlas/workflows?archived=all").json()["items"]) == 1


def test_save_conflict_and_validation_error_are_structured(client):
    draft = new_draft(client)
    path = f"/atlas/workflows/{draft['workflow_id']}"
    draft["document"]["definition"]["edges"] = []
    body = {"expected_edit_version": 1, "document": draft["document"]}
    assert client.put(path + "/draft", json=body).json()["edit_version"] == 2
    conflict = client.put(path + "/draft", json=body)
    assert conflict.status_code == 409
    assert conflict.json() == {
        "reason": "workflow_edit_conflict",
        "current_edit_version": 2,
    }
    failed = client.post(
        path + "/publish", json={"request_id": "bad", "expected_edit_version": 2}
    )
    assert failed.status_code == 422
    assert failed.json()["validation"]["checked_edit_version"] == 2
    assert failed.json()["validation"]["issues"][0]["field"].startswith("/definition/")


@pytest.mark.parametrize(
    "fault",
    [
        "credential",
        "binding",
        "version",
        "nan",
        "duplicate",
        "invalid_utf8",
        "size",
        "chunked_size",
    ],
)
def test_invalid_requests_are_bounded_and_never_echo_payload(client, fault):
    draft = new_draft(client)
    path = f"/atlas/workflows/{draft['workflow_id']}/draft"
    body = {"expected_edit_version": 1, "document": draft["document"]}
    if fault == "credential":
        body["document"]["definition"]["nodes"][0]["parameters"]["api_key"] = (
            "synthetic-private-value"
        )
    if fault == "binding":
        body["document"]["workflow_binding"] = {"thread_id": "synthetic-private-value"}
    if fault == "version":
        body["expected_edit_version"] = True
    data = json.dumps(body).encode()
    if fault == "nan":
        data = data.replace(b'"x": 0.0', b'"x": NaN')
    if fault == "duplicate":
        data = b'{"expected_edit_version":1,"expected_edit_version":2}'
    if fault == "invalid_utf8":
        data = b"\xff"
    if fault in {"size", "chunked_size"}:
        data = b" " * (workflow_api.MAX_REQUEST_BYTES + 1)
    content = (
        (chunk for chunk in (data[:100], data[100:]))
        if fault == "chunked_size"
        else data
    )
    response = client.put(
        path, content=content, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 400
    assert response.json() == {"reason": "workflow_request_invalid"}
    assert "synthetic-private-value" not in response.text
    assert client.get(path.removesuffix("/draft")).json()["edit_version"] == 1


@pytest.mark.parametrize(
    "query",
    [
        "limit=0",
        "limit=101",
        "after=-1",
        "after=1.5",
        "after=9007199254740992",
        "archived=unexpected",
    ],
)
def test_invalid_pagination(client, query):
    assert client.get("/atlas/workflows?" + query).status_code == 400


def test_unknown_ids_and_disabled_publication_are_explicit(client):
    assert client.get("/atlas/workflows/missing").status_code == 404
    assert client.get("/atlas/workflows/bad%20id").status_code == 400
    draft = new_draft(client)
    client.app.state.workflow_store.publication_context = None
    response = client.post(
        f"/atlas/workflows/{draft['workflow_id']}/publish",
        json={"request_id": "publish", "expected_edit_version": 1},
    )
    assert (
        response.status_code == 503
        and response.json()["reason"] == "workflow_runtime_unavailable"
    )


def test_storage_errors_hide_paths_and_leave_old_config_available(client, monkeypatch):
    def fail():
        raise OSError("synthetic-private-value")

    monkeypatch.setattr(client.app.state.workflow_store, "check_ready", fail)
    response = client.get("/atlas/workflow-node-types")
    assert response.status_code == 503
    assert response.json() == {"reason": "workflow_storage_unavailable"}


def test_editor_capability_only_after_storage_check_and_never_execution(
    client, monkeypatch
):
    from deep_research import atlas_api

    monkeypatch.setattr(atlas_api, "public_model_config", lambda: {"models": [{}] * 6})
    monkeypatch.setattr(
        atlas_api, "get_workflow_store", lambda: client.app.state.workflow_store
    )
    with TestClient(atlas_api.app) as config_client:
        result = config_client.get("/atlas/config").json()
        assert result["workflow_editor_version"] == 1
        assert (
            "workflow_execution_version" not in result
            and "workflow_events_version" not in result
        )

        def fail():
            raise OSError("private storage failure")

        monkeypatch.setattr(client.app.state.workflow_store, "check_ready", fail)
        response = config_client.get("/atlas/config")
        assert response.status_code == 200
        assert "workflow_editor_version" not in response.json()

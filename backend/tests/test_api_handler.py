import json

import pytest
from botocore.exceptions import ClientError

from app import api_handler


class FakeTable:
    def __init__(self):
        self.items = {}

    def get_item(self, Key):
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": item} if item else {}

    def put_item(self, Item):
        self.items[(Item["pk"], Item["sk"])] = Item


@pytest.fixture(autouse=True)
def env(monkeypatch):
    for k, v in {
        "KNOWLEDGE_BASE_ID": "KB1",
        "DATA_SOURCE_ID": "DS1",
        "MODEL_ARN": "arn:model",
        "TABLE_NAME": "tbl",
        "DOCS_BUCKET": "docs",
    }.items():
        monkeypatch.setenv(k, v)
    api_handler.get_settings.cache_clear()
    table = FakeTable()
    monkeypatch.setattr(api_handler.store, "table", lambda name, region: table)
    yield table


def event(route, body=None, groups="[hr]", sub="user-1"):
    return {
        "routeKey": route,
        "body": json.dumps(body) if body is not None else None,
        "requestContext": {"authorizer": {"jwt": {"claims": {"sub": sub, "email": "a@x.com", "cognito:groups": groups}}}},
    }


class Ctx:
    aws_request_id = "req-1"


def call(evt):
    resp = api_handler.handler(evt, Ctx())
    return resp["statusCode"], json.loads(resp["body"])


def test_health_is_public():
    assert call({"routeKey": "GET /health"}) == (200, {"status": "ok"})


def test_unknown_route():
    assert call(event("GET /nope"))[0] == 404


def test_empty_question_rejected():
    status, body = call(event("POST /ask", {"question": "   "}))
    assert status == 400 and "question" in body["error"].lower()


def test_ask_uses_filter_from_token_not_body(monkeypatch):
    seen = {}

    def fake_ask(question, retrieval_filter, settings, session_id):
        seen["filter"] = retrieval_filter
        return {"answer": "ok", "sources": [], "session_id": "s-1", "grounded": False, "guardrail_action": None}

    monkeypatch.setattr(api_handler.rag, "ask", fake_ask)
    body = {"question": "leave?", "department": "finance", "filter": None}  # attempted escalation is ignored
    status, out = call(event("POST /ask", body, groups="[hr]"))
    assert status == 200
    assert seen["filter"]["andAll"][0] == {"in": {"key": "department", "value": ["hr"]}}
    assert out["message_id"].startswith("MSG#")


def test_foreign_session_is_not_reused(monkeypatch, env):
    seen = {}

    def fake_ask(question, retrieval_filter, settings, session_id):
        seen["session"] = session_id
        return {"answer": "ok", "sources": [], "session_id": "new", "grounded": False, "guardrail_action": None}

    monkeypatch.setattr(api_handler.rag, "ask", fake_ask)
    env.put_item({"pk": "USER#someone-else", "sk": "SESSION#their-session"})
    call(event("POST /ask", {"question": "hi", "session_id": "their-session"}))
    assert seen["session"] is None


def test_own_session_is_reused(monkeypatch, env):
    seen = {}

    def fake_ask(question, retrieval_filter, settings, session_id):
        seen["session"] = session_id
        return {"answer": "ok", "sources": [], "session_id": "mine", "grounded": False, "guardrail_action": None}

    monkeypatch.setattr(api_handler.rag, "ask", fake_ask)
    env.put_item({"pk": "USER#user-1", "sk": "SESSION#mine"})
    call(event("POST /ask", {"question": "and for managers?", "session_id": "mine"}))
    assert seen["session"] == "mine"


def test_user_without_department_gets_403():
    status, body = call(event("POST /ask", {"question": "hi"}, groups="[]"))
    assert status == 403


def test_non_admin_cannot_sync():
    assert call(event("POST /admin/sync", {}, groups="[hr]"))[0] == 403


def test_throttling_maps_to_429(monkeypatch):
    def throttled(*a, **k):
        raise ClientError({"Error": {"Code": "ThrottlingException", "Message": "slow down"}}, "RetrieveAndGenerate")

    monkeypatch.setattr(api_handler.rag, "ask", throttled)
    assert call(event("POST /ask", {"question": "hi"}))[0] == 429


def test_bad_feedback_rejected():
    assert call(event("POST /feedback", {"message_id": "x", "rating": "up"}))[0] == 400

import json

import pytest
from botocore.exceptions import ClientError

from app import ingest_handler


class FakeAgent:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def start_ingestion_job(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise ClientError({"Error": {"Code": self.error, "Message": "x"}}, "StartIngestionJob")
        return {"ingestionJob": {"ingestionJobId": "job-1", "status": "STARTING"}}


def sqs_event(*keys):
    return {
        "Records": [
            {"body": json.dumps({"detail-type": "Object Created", "detail": {"object": {"key": k}}})} for k in keys
        ]
    }


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("KNOWLEDGE_BASE_ID", "KB1")
    monkeypatch.setenv("DATA_SOURCE_ID", "DS1")


def test_one_job_for_a_whole_batch(monkeypatch):
    agent = FakeAgent()
    monkeypatch.setattr(ingest_handler, "_client", lambda: agent)
    out = ingest_handler.handler(sqs_event("documents/hr/a.pdf", "documents/hr/b.pdf"), None)
    assert out == {"job_id": "job-1", "changes": 2}
    assert len(agent.calls) == 1
    assert agent.calls[0]["knowledgeBaseId"] == "KB1"


def test_running_job_triggers_retry(monkeypatch):
    monkeypatch.setattr(ingest_handler, "_client", lambda: FakeAgent("ConflictException"))
    with pytest.raises(ingest_handler.RetryLater):
        ingest_handler.handler(sqs_event("documents/it/vpn.pdf"), None)


def test_real_errors_are_raised(monkeypatch):
    monkeypatch.setattr(ingest_handler, "_client", lambda: FakeAgent("AccessDeniedException"))
    with pytest.raises(ClientError):
        ingest_handler.handler(sqs_event("documents/it/vpn.pdf"), None)

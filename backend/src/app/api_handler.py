"""API Lambda behind an API Gateway HTTP API (payload format 2.0).

Routes
  GET  /health                    public
  POST /ask                       {"question": "...", "session_id": "optional"}
  GET  /history                   last 20 exchanges for the caller
  POST /feedback                  {"message_id": "...", "rating": "up"|"down", "comment": ""}
  POST /admin/sync                admin group only: start an ingestion job now
  GET  /admin/ingestion-jobs      admin group only: recent ingestion jobs
"""

import json
import logging
import re
import time

import boto3
from botocore.exceptions import ClientError

from . import rag, store
from .access import AccessDenied, build_retrieval_filter, user_from_claims
from .config import get_settings
from .logutil import get_logger, log

logger = get_logger("api")
SESSION_ID_RE = re.compile(r"^[0-9a-zA-Z._:-]{2,100}$")
MESSAGE_ID_RE = re.compile(r"^MSG#[0-9T:.+\-]+#[0-9a-f]{8}$")
_agent = None


class BadRequest(Exception):
    pass


class Forbidden(Exception):
    pass


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", "Cache-Control": "no-store"},
        "body": json.dumps(body, default=str),
    }


def _body(event: dict) -> dict:
    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        import base64

        raw = base64.b64decode(raw).decode("utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as err:
        raise BadRequest("Request body must be valid JSON.") from err
    if not isinstance(data, dict):
        raise BadRequest("Request body must be a JSON object.")
    return data


def _claims(event: dict) -> dict:
    return ((event.get("requestContext") or {}).get("authorizer") or {}).get("jwt", {}).get("claims", {})


def _agent_client(region: str):
    global _agent
    if _agent is None:
        _agent = boto3.client("bedrock-agent", region_name=region)
    return _agent


# ---------------------------------------------------------------- routes

def ask(event, user, settings):
    data = _body(event)
    question = str(data.get("question", "")).strip()
    if not question:
        raise BadRequest("Enter a question.")
    if len(question) > settings.max_question_chars:
        raise BadRequest(f"Questions can be up to {settings.max_question_chars} characters.")

    tbl = store.table(settings.table_name, settings.region)
    session_id = data.get("session_id") or None
    if session_id and (not SESSION_ID_RE.match(session_id) or not store.session_owned(tbl, user.user_id, session_id)):
        session_id = None  # never continue a session the caller doesn't own

    retrieval_filter = build_retrieval_filter(user)
    started = time.time()
    try:
        result = rag.ask(question, retrieval_filter, settings, session_id)
    except ClientError as err:
        # An expired Bedrock session (>24h) fails validation: start a fresh one.
        if session_id and err.response["Error"]["Code"] == "ValidationException":
            result = rag.ask(question, retrieval_filter, settings, None)
        else:
            raise
    latency_ms = int((time.time() - started) * 1000)

    if result.get("session_id"):
        store.save_session(tbl, user.user_id, result["session_id"])
    message_id = store.save_message(tbl, user.user_id, question, result, settings.history_ttl_days)

    log(
        logger,
        logging.INFO,
        "answered",
        user=user.user_id,
        groups=sorted(user.groups),
        latency_ms=latency_ms,
        sources=len(result["sources"]),
        grounded=result["grounded"],
        guardrail=result.get("guardrail_action"),
    )
    return _response(200, {**result, "message_id": message_id, "latency_ms": latency_ms})


def history(event, user, settings):
    tbl = store.table(settings.table_name, settings.region)
    return _response(200, {"items": store.list_history(tbl, user.user_id)})


def feedback(event, user, settings):
    data = _body(event)
    message_id = str(data.get("message_id", ""))
    rating = str(data.get("rating", ""))
    if not MESSAGE_ID_RE.match(message_id):
        raise BadRequest("Unknown message.")
    if rating not in {"up", "down"}:
        raise BadRequest("Rating must be 'up' or 'down'.")
    tbl = store.table(settings.table_name, settings.region)
    if not store.set_feedback(tbl, user.user_id, message_id, rating, str(data.get("comment", ""))):
        raise BadRequest("Unknown message.")
    return _response(200, {"saved": True})


def admin_sync(event, user, settings):
    if not user.is_admin:
        raise Forbidden("Only administrators can start a sync.")
    agent = _agent_client(settings.region)
    try:
        job = agent.start_ingestion_job(
            knowledgeBaseId=settings.knowledge_base_id,
            dataSourceId=settings.data_source_id,
            description=f"Manual sync by {user.email or user.user_id}",
        )["ingestionJob"]
    except ClientError as err:
        if err.response["Error"]["Code"] in {"ConflictException", "ServiceQuotaExceededException"}:
            return _response(409, {"error": "A sync is already running. Try again when it finishes."})
        raise
    return _response(202, {"job_id": job["ingestionJobId"], "status": job["status"]})


def admin_jobs(event, user, settings):
    if not user.is_admin:
        raise Forbidden("Only administrators can view sync jobs.")
    agent = _agent_client(settings.region)
    resp = agent.list_ingestion_jobs(
        knowledgeBaseId=settings.knowledge_base_id,
        dataSourceId=settings.data_source_id,
        sortBy={"attribute": "STARTED_AT", "order": "DESCENDING"},
        maxResults=10,
    )
    jobs = [
        {
            "job_id": j["ingestionJobId"],
            "status": j["status"],
            "started_at": j.get("startedAt"),
            "updated_at": j.get("updatedAt"),
            "statistics": j.get("statistics", {}),
        }
        for j in resp.get("ingestionJobSummaries", [])
    ]
    return _response(200, {"jobs": jobs})


ROUTES = {
    "POST /ask": ask,
    "GET /history": history,
    "POST /feedback": feedback,
    "POST /admin/sync": admin_sync,
    "GET /admin/ingestion-jobs": admin_jobs,
}


def handler(event, context):
    route = event.get("routeKey", "")
    request_id = getattr(context, "aws_request_id", "local")

    if route == "GET /health":
        return _response(200, {"status": "ok"})

    fn = ROUTES.get(route)
    if fn is None:
        return _response(404, {"error": "Not found"})

    settings = get_settings()
    try:
        user = user_from_claims(_claims(event))
        return fn(event, user, settings)
    except BadRequest as err:
        return _response(400, {"error": str(err)})
    except (AccessDenied, Forbidden) as err:
        log(logger, logging.WARNING, "access_denied", route=route, request_id=request_id, reason=str(err))
        return _response(403, {"error": str(err)})
    except ClientError as err:
        code = err.response["Error"]["Code"]
        log(logger, logging.ERROR, "aws_error", route=route, request_id=request_id, code=code, detail=str(err))
        if code in {"ThrottlingException", "ServiceQuotaExceededException", "TooManyRequestsException"}:
            return _response(429, {"error": "The assistant is busy. Try again in a few seconds."})
        return _response(502, {"error": "The knowledge service returned an error. Try again, or contact support with this ID.", "request_id": request_id})
    except Exception:
        logger.exception("unhandled", extra={"fields": {"route": route, "request_id": request_id}})
        return _response(500, {"error": "Something went wrong on our side. Contact support with this ID.", "request_id": request_id})

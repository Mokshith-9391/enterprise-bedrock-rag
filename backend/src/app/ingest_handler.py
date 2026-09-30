"""Ingestion worker: S3 -> EventBridge -> SQS -> this Lambda -> StartIngestionJob.

Why SQS in the middle?
  * Uploading 200 files produces 200 events. SQS batches them (up to 60 s),
    so one ingestion job picks up all of them. Syncs are incremental, so one
    job processes every added, changed or deleted file since the last sync.
  * A data source runs one ingestion job at a time. If a job is already
    running we raise, SQS makes the batch visible again after the visibility
    timeout, and we retry. After repeated failures messages go to a DLQ that
    raises a CloudWatch alarm.
"""

import json
import logging
import os

import boto3
from botocore.exceptions import ClientError

from .logutil import get_logger, log

logger = get_logger("ingest")
RETRYABLE = {"ConflictException", "ServiceQuotaExceededException", "ThrottlingException"}
_agent = None


class RetryLater(Exception):
    """Raised so SQS re-delivers the batch later."""


def _client():
    global _agent
    if _agent is None:
        _agent = boto3.client("bedrock-agent", region_name=os.environ.get("AWS_REGION"))
    return _agent


def _changed_keys(event: dict) -> list:
    keys = []
    for record in event.get("Records", []):
        try:
            body = json.loads(record.get("body", "{}"))
            detail = body.get("detail", {})
            keys.append(f'{body.get("detail-type", "?")}: {detail.get("object", {}).get("key", "?")}')
        except (json.JSONDecodeError, AttributeError):
            keys.append("unparseable message")
    return keys


def handler(event, context):
    kb_id = os.environ["KNOWLEDGE_BASE_ID"]
    ds_id = os.environ["DATA_SOURCE_ID"]
    changes = _changed_keys(event)

    try:
        job = _client().start_ingestion_job(
            knowledgeBaseId=kb_id,
            dataSourceId=ds_id,
            description=f"Auto sync for {len(changes)} S3 change(s)",
        )["ingestionJob"]
    except ClientError as err:
        code = err.response["Error"]["Code"]
        if code in RETRYABLE:
            log(logger, logging.INFO, "sync_busy_retry_later", code=code, changes=len(changes))
            raise RetryLater(code) from err
        log(logger, logging.ERROR, "sync_failed", code=code, detail=str(err))
        raise

    log(
        logger,
        logging.INFO,
        "sync_started",
        job_id=job["ingestionJobId"],
        status=job["status"],
        changes=changes[:50],
        change_count=len(changes),
    )
    return {"job_id": job["ingestionJobId"], "changes": len(changes)}

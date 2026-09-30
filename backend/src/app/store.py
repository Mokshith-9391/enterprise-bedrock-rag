"""Chat history, session ownership and feedback in a single DynamoDB table.

Key design (single-table):
  pk = USER#<cognito sub>
  sk = SESSION#<bedrock session id>     -> proves a session belongs to this user
  sk = MSG#<iso timestamp>#<short id>   -> one question/answer exchange

Every key starts with the caller's own user id, taken from the verified token,
so one user can never read or modify another user's items.
"""

import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

_table = None


def table(name: str, region: str):
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb", region_name=region).Table(name)
    return _table


def _pk(user_id: str) -> str:
    return f"USER#{user_id}"


def _ttl(days: int) -> int:
    return int(time.time()) + days * 86400


def session_owned(tbl, user_id: str, session_id: str) -> bool:
    item = tbl.get_item(Key={"pk": _pk(user_id), "sk": f"SESSION#{session_id}"}).get("Item")
    return item is not None


def save_session(tbl, user_id: str, session_id: str) -> None:
    # Bedrock keeps a RetrieveAndGenerate session for 24 hours, so ownership records match that.
    tbl.put_item(Item={"pk": _pk(user_id), "sk": f"SESSION#{session_id}", "expires_at": _ttl(1)})


def save_message(tbl, user_id: str, question: str, result: dict, ttl_days: int) -> str:
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    message_id = f"MSG#{now}#{uuid.uuid4().hex[:8]}"
    sources = [
        {"n": s["n"], "title": s["title"], "uri": s["uri"], "page": s.get("page") or 0}
        for s in result.get("sources", [])
    ]
    tbl.put_item(
        Item={
            "pk": _pk(user_id),
            "sk": message_id,
            "question": question,
            "answer": result.get("answer", ""),
            "sources": sources,
            "session_id": result.get("session_id") or "",
            "grounded": bool(result.get("grounded")),
            "created_at": now,
            "expires_at": _ttl(ttl_days),
        }
    )
    return message_id


def _plain(value):
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, Decimal):
        return int(value) if value == int(value) else float(value)
    return value


def list_history(tbl, user_id: str, limit: int = 20) -> list:
    resp = tbl.query(
        KeyConditionExpression=Key("pk").eq(_pk(user_id)) & Key("sk").begins_with("MSG#"),
        ScanIndexForward=False,
        Limit=limit,
    )
    items = []
    for item in resp.get("Items", []):
        items.append(
            {
                "message_id": item["sk"],
                "question": item.get("question", ""),
                "answer": item.get("answer", ""),
                "sources": _plain(item.get("sources", [])),
                "created_at": item.get("created_at"),
                "feedback": item.get("feedback"),
            }
        )
    return items


def set_feedback(tbl, user_id: str, message_id: str, rating: str, comment: str = "") -> bool:
    try:
        tbl.update_item(
            Key={"pk": _pk(user_id), "sk": message_id},
            UpdateExpression="SET feedback = :r, feedback_comment = :c, feedback_at = :t",
            ConditionExpression="attribute_exists(pk)",
            ExpressionAttributeValues={
                ":r": rating,
                ":c": comment[:1000],
                ":t": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            },
        )
        return True
    except ClientError as err:
        if err.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise

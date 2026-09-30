"""Runtime settings, read once from Lambda environment variables."""

import os
from dataclasses import dataclass
from functools import lru_cache


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    region: str
    knowledge_base_id: str
    data_source_id: str
    model_arn: str
    rerank_model_arn: str
    guardrail_id: str
    guardrail_version: str
    table_name: str
    docs_bucket: str
    num_results: int
    num_reranked: int
    enable_query_decomposition: bool
    max_question_chars: int
    presign_seconds: int
    history_ttl_days: int


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        region=os.getenv("AWS_REGION", "ap-south-1"),
        knowledge_base_id=os.getenv("KNOWLEDGE_BASE_ID", ""),
        data_source_id=os.getenv("DATA_SOURCE_ID", ""),
        model_arn=os.getenv("MODEL_ARN", ""),
        rerank_model_arn=os.getenv("RERANK_MODEL_ARN", ""),
        guardrail_id=os.getenv("GUARDRAIL_ID", ""),
        guardrail_version=os.getenv("GUARDRAIL_VERSION", ""),
        table_name=os.getenv("TABLE_NAME", ""),
        docs_bucket=os.getenv("DOCS_BUCKET", ""),
        num_results=_int("NUM_RESULTS", 10),
        num_reranked=_int("NUM_RERANKED", 5),
        enable_query_decomposition=_bool("ENABLE_QUERY_DECOMPOSITION", False),
        max_question_chars=_int("MAX_QUESTION_CHARS", 1000),
        presign_seconds=_int("PRESIGN_SECONDS", 300),
        history_ttl_days=_int("HISTORY_TTL_DAYS", 90),
    )

"""Everything that talks to the Bedrock Knowledge Base at query time."""

from urllib.parse import unquote, urlparse

import boto3
from botocore.config import Config

from .config import Settings

# $search_results$ is required. $output_format_instructions$ is what makes
# Bedrock return citations when you supply your own template.
PROMPT_TEMPLATE = """You are the company knowledge assistant. Employees ask you about internal
policies, procedures and project documents.

Answer the user's question using ONLY the search results below.

Rules:
1. Do not invent facts, numbers, names or dates that are not in the search results.
2. If the search results do not contain the answer, reply exactly:
   "I couldn't find this in the documents you have access to."
3. When results come from different documents, say which document each fact comes from
   and do not blend conflicting rules together.
4. Prefer the most specific and most recent document when two documents disagree, and point out the conflict.
5. Keep answers short and practical. Use a short list when there are steps.
6. Never reveal document metadata such as classification labels.

Search results:
$search_results$

$output_format_instructions$"""

_CLIENT_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"}, read_timeout=28, connect_timeout=5)
_runtime = None
_s3 = None


def runtime_client(region: str):
    global _runtime
    if _runtime is None:
        _runtime = boto3.client("bedrock-agent-runtime", region_name=region, config=_CLIENT_CONFIG)
    return _runtime


def s3_client(region: str):
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3", region_name=region, config=Config(signature_version="s3v4"))
    return _s3


def build_request(question: str, retrieval_filter, settings: Settings, session_id: str = None) -> dict:
    """Build kwargs for bedrock-agent-runtime.retrieve_and_generate."""
    vector_config = {"numberOfResults": settings.num_results}
    if retrieval_filter:
        vector_config["filter"] = retrieval_filter
    if settings.rerank_model_arn:
        vector_config["rerankingConfiguration"] = {
            "type": "BEDROCK_RERANKING_MODEL",
            "bedrockRerankingConfiguration": {
                "modelConfiguration": {"modelArn": settings.rerank_model_arn},
                "numberOfRerankedResults": min(settings.num_reranked, settings.num_results),
            },
        }

    generation = {
        "promptTemplate": {"textPromptTemplate": PROMPT_TEMPLATE},
        "inferenceConfig": {"textInferenceConfig": {"temperature": 0.0, "topP": 0.9, "maxTokens": 1024}},
    }
    if settings.guardrail_id and settings.guardrail_version:
        generation["guardrailConfiguration"] = {
            "guardrailId": settings.guardrail_id,
            "guardrailVersion": settings.guardrail_version,
        }

    kb_config = {
        "knowledgeBaseId": settings.knowledge_base_id,
        "modelArn": settings.model_arn,
        "retrievalConfiguration": {"vectorSearchConfiguration": vector_config},
        "generationConfiguration": generation,
    }
    if settings.enable_query_decomposition:
        # Splits comparison questions ("compare A and B") into sub-queries.
        kb_config["orchestrationConfiguration"] = {
            "queryTransformationConfiguration": {"type": "QUERY_DECOMPOSITION"}
        }

    request = {
        "input": {"text": question},
        "retrieveAndGenerateConfiguration": {"type": "KNOWLEDGE_BASE", "knowledgeBaseConfiguration": kb_config},
    }
    if session_id:
        request["sessionId"] = session_id
    return request


def _split_s3_uri(uri: str):
    parsed = urlparse(uri)
    if parsed.scheme != "s3":
        return None, None
    return parsed.netloc, unquote(parsed.path.lstrip("/"))


def _page(metadata: dict):
    page = metadata.get("x-amz-bedrock-kb-document-page-number")
    try:
        return int(float(page)) if page is not None else None
    except (TypeError, ValueError):
        return None


def parse_response(response: dict, presign=None) -> dict:
    """Turn the raw Bedrock response into the shape the web app renders.

    - Deduplicates sources and numbers them [1], [2], ...
    - Inserts those markers into the answer after each cited sentence.
    - presign(bucket, key) -> url is optional and returns a short-lived link.
    """
    answer = (response.get("output") or {}).get("text", "")
    sources, index_by_key = [], {}
    markers = []  # (cited_text, [source numbers])

    for citation in response.get("citations", []) or []:
        numbers = []
        for ref in citation.get("retrievedReferences", []) or []:
            location = ref.get("location") or {}
            uri = (location.get("s3Location") or {}).get("uri", "")
            metadata = ref.get("metadata") or {}
            page = _page(metadata)
            key = (uri, page)
            if key not in index_by_key:
                bucket, obj_key = _split_s3_uri(uri)
                title = obj_key.rsplit("/", 1)[-1] if obj_key else (uri or "Source")
                snippet = ((ref.get("content") or {}).get("text") or "").strip()
                source = {
                    "n": len(sources) + 1,
                    "title": title,
                    "uri": uri,
                    "department": metadata.get("department"),
                    "page": page,
                    "snippet": snippet[:320] + ("..." if len(snippet) > 320 else ""),
                    "url": None,
                }
                if presign and bucket and obj_key:
                    try:
                        source["url"] = presign(bucket, obj_key)
                    except Exception:  # a missing link must never break an answer
                        source["url"] = None
                index_by_key[key] = source["n"]
                sources.append(source)
            if index_by_key[key] not in numbers:
                numbers.append(index_by_key[key])
        part = ((citation.get("generatedResponsePart") or {}).get("textResponsePart") or {}).get("text", "")
        if numbers and part:
            markers.append((part, numbers))

    answer_with_marks = _insert_markers(answer, markers)
    return {
        "answer": answer_with_marks,
        "sources": sources,
        "session_id": response.get("sessionId"),
        "grounded": bool(sources),
        "guardrail_action": response.get("guardrailAction"),
    }


def _insert_markers(answer: str, markers) -> str:
    out, cursor = [], 0
    for part, numbers in markers:
        pos = answer.find(part, cursor)
        if pos < 0:
            continue
        end = pos + len(part)
        out.append(answer[cursor:end])
        out.append("".join(f"[{n}]" for n in numbers))
        cursor = end
    out.append(answer[cursor:])
    return "".join(out)


def ask(question: str, retrieval_filter, settings: Settings, session_id: str = None) -> dict:
    client = runtime_client(settings.region)
    request = build_request(question, retrieval_filter, settings, session_id)
    raw = client.retrieve_and_generate(**request)

    s3 = s3_client(settings.region)

    def presign(bucket, key):
        if bucket != settings.docs_bucket:
            return None
        return s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key, "ResponseContentDisposition": "inline"},
            ExpiresIn=settings.presign_seconds,
        )

    return parse_response(raw, presign=presign)

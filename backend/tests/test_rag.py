from app.config import Settings
from app.rag import PROMPT_TEMPLATE, build_request, parse_response


def settings(**overrides):
    base = dict(
        region="ap-south-1",
        knowledge_base_id="KB123",
        data_source_id="DS123",
        model_arn="arn:aws:bedrock:ap-south-1:111122223333:inference-profile/apac.amazon.nova-pro-v1:0",
        rerank_model_arn="",
        guardrail_id="",
        guardrail_version="",
        table_name="t",
        docs_bucket="docs-bucket",
        num_results=10,
        num_reranked=5,
        enable_query_decomposition=False,
        max_question_chars=1000,
        presign_seconds=300,
        history_ttl_days=90,
    )
    base.update(overrides)
    return Settings(**base)


def test_prompt_has_required_placeholders():
    assert "$search_results$" in PROMPT_TEMPLATE
    assert "$output_format_instructions$" in PROMPT_TEMPLATE


def test_basic_request_shape():
    req = build_request("What is the leave policy?", {"equals": {"key": "department", "value": "hr"}}, settings())
    kb = req["retrieveAndGenerateConfiguration"]["knowledgeBaseConfiguration"]
    assert req["input"] == {"text": "What is the leave policy?"}
    assert kb["knowledgeBaseId"] == "KB123"
    assert kb["retrievalConfiguration"]["vectorSearchConfiguration"]["filter"]["equals"]["value"] == "hr"
    assert "sessionId" not in req
    assert "rerankingConfiguration" not in kb["retrievalConfiguration"]["vectorSearchConfiguration"]
    assert "guardrailConfiguration" not in kb["generationConfiguration"]


def test_optional_features_are_wired():
    s = settings(
        rerank_model_arn="arn:aws:bedrock:us-west-2::foundation-model/amazon.rerank-v1:0",
        guardrail_id="gr1",
        guardrail_version="1",
        enable_query_decomposition=True,
    )
    req = build_request("Compare A and B", None, s, session_id="sess-1")
    kb = req["retrieveAndGenerateConfiguration"]["knowledgeBaseConfiguration"]
    vec = kb["retrievalConfiguration"]["vectorSearchConfiguration"]
    assert "filter" not in vec
    assert vec["rerankingConfiguration"]["bedrockRerankingConfiguration"]["numberOfRerankedResults"] == 5
    assert kb["generationConfiguration"]["guardrailConfiguration"] == {"guardrailId": "gr1", "guardrailVersion": "1"}
    assert kb["orchestrationConfiguration"]["queryTransformationConfiguration"]["type"] == "QUERY_DECOMPOSITION"
    assert req["sessionId"] == "sess-1"


def _ref(uri, text, page=None, dept="hr"):
    md = {"department": dept, "x-amz-bedrock-kb-source-uri": uri}
    if page is not None:
        md["x-amz-bedrock-kb-document-page-number"] = float(page)
    return {"content": {"text": text}, "location": {"type": "S3", "s3Location": {"uri": uri}}, "metadata": md}


def test_parse_response_numbers_and_marks_sources():
    raw = {
        "output": {"text": "You get 24 days of annual leave. Unused days carry forward up to 10."},
        "sessionId": "sess-9",
        "citations": [
            {
                "generatedResponsePart": {"textResponsePart": {"text": "You get 24 days of annual leave."}},
                "retrievedReferences": [_ref("s3://docs-bucket/documents/hr/leave-policy.md", "24 days", page=2)],
            },
            {
                "generatedResponsePart": {"textResponsePart": {"text": "Unused days carry forward up to 10."}},
                "retrievedReferences": [
                    _ref("s3://docs-bucket/documents/hr/leave-policy.md", "carry forward", page=2),
                    _ref("s3://docs-bucket/documents/hr/handbook.md", "carry"),
                ],
            },
        ],
    }
    out = parse_response(raw, presign=lambda b, k: f"https://signed/{k}")
    assert out["answer"] == "You get 24 days of annual leave.[1] Unused days carry forward up to 10.[1][2]"
    assert [s["title"] for s in out["sources"]] == ["leave-policy.md", "handbook.md"]
    assert out["sources"][0]["page"] == 2
    assert out["sources"][0]["url"] == "https://signed/documents/hr/leave-policy.md"
    assert out["session_id"] == "sess-9"
    assert out["grounded"] is True


def test_parse_response_without_citations_is_not_grounded():
    out = parse_response({"output": {"text": "I couldn't find this in the documents you have access to."}})
    assert out["grounded"] is False
    assert out["sources"] == []


def test_presign_failure_does_not_break_answer():
    def boom(bucket, key):
        raise RuntimeError("no")

    raw = {
        "output": {"text": "Use the VPN client."},
        "citations": [
            {
                "generatedResponsePart": {"textResponsePart": {"text": "Use the VPN client."}},
                "retrievedReferences": [_ref("s3://docs-bucket/documents/it/vpn-guide.md", "vpn", dept="it")],
            }
        ],
    }
    out = parse_response(raw, presign=boom)
    assert out["sources"][0]["url"] is None
    assert out["answer"].endswith("[1]")

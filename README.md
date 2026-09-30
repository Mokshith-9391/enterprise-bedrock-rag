# Enterprise RAG on Amazon Bedrock Knowledge Bases

A complete, deployable "company knowledge assistant". Employees sign in, ask questions in plain language, and get answers drawn only from the company documents their team is allowed to read, with numbered citations that link to the source file.

Everything is defined in Terraform and deploys with one command.

```
                           Employees (browser)
                                  |
                          CloudFront (+ optional WAF)
                                  |
                   Static web app  (S3, private, OAC)
                                  |   sign in: Cognito Hosted UI (code + PKCE)
                                  v
              API Gateway HTTP API  ── JWT authorizer (Cognito)
                                  |
                          Lambda: RAG API ───────────── DynamoDB
                    (ask / history / feedback / admin)   chat history,
                                  |                       session ownership
                  RetrieveAndGenerate + metadata filter
                                  |
                     Bedrock Knowledge Base ── Guardrail
                        /                \
      OpenSearch Serverless            Foundation model
       (vector index, faiss)           (Nova / Claude via
                ^                       inference profile)
                | parse, chunk, embed (Titan Text Embeddings V2)
                |
   S3 documents/ + .metadata.json ── EventBridge ── SQS ── Lambda: ingest
                                    (object created/deleted)   StartIngestionJob
```

## What's included

| Area | What you get |
| --- | --- |
| Retrieval | Bedrock Knowledge Base, Titan Text Embeddings V2 (1,024 dims), OpenSearch Serverless vector index with faiss HNSW, fixed-size chunking (300 tokens, 20% overlap) |
| Generation | `RetrieveAndGenerate` with a custom grounding prompt, citations, multi-turn sessions, optional reranking and query decomposition |
| Access control | Cognito groups mapped to document metadata (`department`, `classification`); the filter is built only from the verified token |
| Safety | Bedrock Guardrail (harmful content, prompt attacks, PII handling) |
| Ingestion | Upload to S3 and the knowledge base syncs itself: EventBridge, batched through SQS, with retries and a dead-letter queue |
| API | HTTP API with JWT authorizer, throttling, JSON access logs; routes for ask, history, feedback and admin sync |
| Web app | Vanilla JS, no build step. Answers render with clickable citation markers and source cards with short-lived links |
| Security | KMS customer-managed key (documents, chat table, logs), TLS-only bucket policy, least-privilege IAM, private S3 origins |
| Operations | CloudWatch alarms (errors, 5xx, latency, ingestion DLQ) to SNS email, X-Ray tracing |
| Quality | 32 unit tests, metadata validator, evaluation script that also checks for access-control leaks, GitHub Actions CI |

## Repository layout

```
enterprise-bedrock-rag/
├── Makefile                        make help lists every task
├── backend/
│   ├── src/app/
│   │   ├── api_handler.py          API Lambda: routing, validation, error mapping
│   │   ├── ingest_handler.py       Ingestion Lambda: SQS batch -> StartIngestionJob
│   │   ├── access.py               Cognito groups -> Bedrock retrieval filter
│   │   ├── rag.py                  RetrieveAndGenerate request + citation parsing
│   │   ├── store.py                DynamoDB history, session ownership, feedback
│   │   ├── config.py               Environment settings
│   │   └── logutil.py              JSON logging
│   ├── tests/                      pytest suites (no AWS needed)
│   └── requirements*.txt
├── infrastructure/terraform/
│   ├── versions.tf                 providers (aws, opensearch, time, archive)
│   ├── variables.tf, locals.tf, outputs.tf
│   ├── storage.tf                  KMS key, documents bucket, DynamoDB table
│   ├── opensearch.tf               collection, 3 policies, vector index
│   ├── bedrock.tf                  KB service role, knowledge base, data source, guardrail
│   ├── lambda.tf                   both functions, roles, log groups
│   ├── ingestion.tf                EventBridge rule, SQS + DLQ, event source mapping
│   ├── api.tf                      HTTP API, JWT authorizer, routes, stage
│   ├── cognito.tf                  user pool, groups, hosted domain, app client
│   ├── frontend.tf                 private bucket, CloudFront, config.js, optional WAF
│   ├── monitoring.tf               SNS + alarms
│   └── terraform.tfvars.example
├── frontend/                       index.html, styles.css, auth.js, app.js
├── sample-docs/documents/          9 sample documents across 5 departments + metadata
├── eval/questions.jsonl            13 evaluation questions, including negative and access tests
├── scripts/                        build, upload, sync, users, evaluation, local config
└── docs/architecture.md            request flows and design decisions
```

## Prerequisites

1. An AWS account and credentials with administrator access for the deployment (`aws sts get-caller-identity` works).
2. Terraform 1.6 or newer, AWS CLI v2, Python 3.12, `make`, `zip`.
3. **Model access in Amazon Bedrock** for the region you deploy to (default `ap-south-1`, Mumbai):
   - Amazon Titan Text Embeddings V2 (used for embeddings).
   - The generation model you choose. For Anthropic models, the first use in an account requires submitting the use-case form in the Bedrock console.
4. Find the generation model's inference-profile ARN:

   ```bash
   aws bedrock list-inference-profiles --region ap-south-1 \
     --query "inferenceProfileSummaries[].inferenceProfileArn" --output table
   ```

## Deploy

```bash
cd infrastructure/terraform
cp terraform.tfvars.example terraform.tfvars
# edit terraform.tfvars: set generation_model_arn (required) and alarm_email (optional)
cd ../..

make install      # pytest and boto3 for local tests
make deploy       # tests -> package Lambda -> terraform apply (two phases)
```

The first deploy takes about 10-15 minutes, mostly for OpenSearch Serverless and CloudFront.

**Why two phases?** The OpenSearch provider has to connect to the collection endpoint to create the vector index, and that endpoint doesn't exist until the collection does. `make deploy` creates the collection first, then everything else. Run it again any time; later runs are a normal single apply.

## Load documents and create users

```bash
make upload         # validates metadata, then syncs sample-docs/documents to S3
make sync-status    # a sync job appears within about a minute and completes in 1-3 minutes
make users          # creates five demo users (change the passwords in the Makefile first)
```

Open the `web_url` output, sign in, and ask something.

| Demo user | Groups | Can read |
| --- | --- | --- |
| admin@example.com | admin | everything, and can trigger syncs |
| hr.user@example.com | hr | HR documents (public and internal) |
| fin.user@example.com | finance | Finance documents |
| it.user@example.com | it | IT documents, but **not** the confidential incident runbook |
| secops@example.com | it, confidential | IT documents including the runbook |

Good demonstrations:

- Sign in as `it.user` and ask "Within how many hours must CERT-In be notified?" The assistant says it can't find it. Sign in as `secops` and ask again: it answers from the runbook, with a citation.
- Sign in as `admin` and ask "Compare the work from home rules with the VPN requirements." The answer cites both the HR and the IT document.
- Ask "What is our Mars office relocation policy?" The assistant refuses instead of inventing an answer.

## Adding your own documents

Put each file under `documents/<department>/` and add a sidecar file next to it with the same name plus `.metadata.json`:

```
documents/finance/travel-policy.pdf
documents/finance/travel-policy.pdf.metadata.json
```

```json
{
  "metadataAttributes": {
    "department": "finance",
    "document_type": "policy",
    "classification": "internal",
    "year": 2026
  }
}
```

- `department` must match a Cognito group (see `departments` in `terraform.tfvars`).
- `classification` is `public`, `internal` or `confidential`. Only the `admin` and `confidential` groups see confidential documents.
- A document with no metadata is visible to admins only, because the filter requires both fields. `scripts/validate_metadata.py` catches this before upload.

Supported formats include PDF, Markdown, text, HTML, Word, CSV and Excel. Upload with `./scripts/upload_docs.sh path/to/your/documents` or any S3 tool; the sync starts automatically.

## How access control works

1. Cognito issues an ID token containing `cognito:groups`.
2. API Gateway's JWT authorizer verifies the signature, issuer, audience and expiry before Lambda runs.
3. `access.py` turns the verified groups into a Bedrock retrieval filter, for example for an HR user:

   ```json
   {"andAll": [
     {"in": {"key": "department", "value": ["hr"]}},
     {"in": {"key": "classification", "value": ["public", "internal"]}}
   ]}
   ```

4. The vector search only considers chunks that match, so documents outside the user's access never reach the model.

Nothing in the request body affects the filter; `test_ask_uses_filter_from_token_not_body` proves it. Sessions are also bound to their owner: a user can't continue someone else's conversation by guessing a session ID.

For hard isolation of highly sensitive material (legal, board, M&A), use a separate knowledge base rather than metadata filtering.

## API reference

All routes except `/health` need `Authorization: Bearer <Cognito ID token>`.

| Method and path | Body | Returns |
| --- | --- | --- |
| `GET /health` | | `{"status": "ok"}` |
| `POST /ask` | `{"question": "...", "session_id": "optional"}` | `answer` (with `[n]` markers), `sources[]`, `session_id`, `message_id`, `grounded`, `latency_ms` |
| `GET /history` | | last 20 exchanges |
| `POST /feedback` | `{"message_id": "...", "rating": "up" or "down", "comment": ""}` | `{"saved": true}` |
| `POST /admin/sync` | `{}` | `202` with the job ID, or `409` if a sync is already running |
| `GET /admin/ingestion-jobs` | | 10 most recent sync jobs with statistics |

Errors return `{"error": "..."}` with 400, 403, 429 (throttled), 502 (AWS service error) or 500, plus a `request_id` for support.

## Configuration

Main `terraform.tfvars` settings:

| Variable | Default | Notes |
| --- | --- | --- |
| `generation_model_arn` | (required) | Inference profile or model ARN |
| `region` | `ap-south-1` | Titan V2 and Knowledge Bases must be available there |
| `rerank_model_arn` | `""` | Reranking is available only in some regions; empty disables it |
| `chunk_max_tokens`, `chunk_overlap_percentage` | 300, 20 | Affects newly ingested files. To re-chunk existing documents, re-upload them or recreate the data source |
| `num_results` / `num_reranked` | 10 / 5 | Chunks retrieved, and kept after reranking |
| `enable_query_decomposition` | true | Better answers for "compare A and B" questions, slightly slower |
| `enable_guardrail` | true | Content filters, prompt-attack detection, PII handling |
| `enable_waf` | false | AWS WAF on CloudFront with managed rules and per-IP rate limiting |
| `force_destroy` | true | Lets `make destroy` delete non-empty buckets. Set false for production |

## Evaluation

```bash
make evaluate        # retrieval hit@5 and access-control leak count (cheap)
make evaluate-full   # also generates answers and checks keywords / refusals
```

The script uses the same filter code as the API, simulating each question's user groups. The leak count must be 0; the script exits non-zero otherwise, so it can gate a CI deployment. Add your own cases to `eval/questions.jsonl` whenever users report a bad answer.

## Local development

```bash
make test        # unit tests, no AWS needed
make web-local   # serves the UI at http://localhost:8080 against the deployed API
```

`http://localhost:8080` is already an allowed CORS origin and Cognito callback URL.

## Cost

Everything is pay-per-use except **OpenSearch Serverless**, which bills a minimum number of OCU-hours even when idle. For a lab or demo environment, that's the dominant cost, typically a few hundred US dollars per month if left running. Other costs (Bedrock tokens, Lambda, API Gateway, DynamoDB, S3, CloudFront) are small at training-class volumes.

Run `make destroy` when you finish a session. For a cheaper long-running environment, swap the vector store for Amazon S3 Vectors (supported by Bedrock Knowledge Bases); only `opensearch.tf` and the `storage_configuration` block in `bedrock.tf` change.

## Troubleshooting

| Symptom | Likely cause and fix |
| --- | --- |
| Phase 2 fails creating `opensearch_index` with 403 | The data access policy hasn't propagated. Re-run `make deploy`. If you deploy with an assumed role, the role (not the session) must be in the policy; Terraform uses `aws_iam_session_context` for this. |
| Knowledge base creation fails: "no such index" | The index wasn't created. Check phase 1 finished, then re-run. |
| `AccessDeniedException` on `InvokeModel` | Model access isn't enabled for the embedding or generation model, or `generation_model_arn` is a model that needs an inference profile. |
| `ValidationException` mentioning the model | Use an inference-profile ARN from `aws bedrock list-inference-profiles`. |
| Sync completes but documents fail | `make sync-status` shows `failed`. Common causes: metadata file over 10 KB, unsupported format, or a scanned PDF with no text layer. |
| Uploaded file isn't searchable | Wait about a minute for the batched sync, then `make sync-status`. If the DLQ alarm fired, check the `-ingest` Lambda logs. |
| Every answer says "couldn't find this" | The user's groups don't match any document's `department`, or documents lack metadata. Check the tags shown in the web app header. |
| Browser shows a CORS error | Only the CloudFront URL and `local_dev_origin` are allowed. Custom domains need adding to `api.tf` and `cognito.tf`. |
| 503/504 on long questions | The HTTP API limit is 30 s. Lower `num_results`, disable query decomposition, or move to Lambda response streaming (see `docs/architecture.md`). |

## Tear down

```bash
make destroy
```

This deletes every resource, including stored documents and chat history when `force_destroy = true`. The KMS key enters its 7-day deletion window.
# enterprise-bedrock-rag

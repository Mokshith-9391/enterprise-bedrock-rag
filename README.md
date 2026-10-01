# Enterprise RAG on Amazon Bedrock Knowledge Bases

A complete, deployable **company knowledge assistant**. Employees sign in, ask questions in plain language, and get answers drawn only from the company documents their team is allowed to read — with numbered citations that link to the source file.

Everything is defined in Terraform and deploys from a single EC2 control machine.

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

---

## What's Included

| Area | What you get |
| --- | --- |
| **Retrieval** | Bedrock Knowledge Base, Titan Text Embeddings V2 (1,024 dims), OpenSearch Serverless vector index with faiss HNSW, fixed-size chunking (300 tokens, 20% overlap) |
| **Generation** | `RetrieveAndGenerate` with a custom grounding prompt, citations, multi-turn sessions, optional reranking and query decomposition |
| **Access control** | Cognito groups mapped to document metadata (`department`, `classification`); the filter is built only from the verified token |
| **Safety** | Bedrock Guardrail (harmful content, prompt attacks, PII handling) |
| **Ingestion** | Upload to S3 and the knowledge base syncs itself: EventBridge, batched through SQS, with retries and a dead-letter queue |
| **API** | HTTP API with JWT authorizer, throttling, JSON access logs; routes for ask, history, feedback and admin sync |
| **Web app** | Vanilla JS, no build step. Answers render with clickable citation markers and source cards with short-lived links |
| **Security** | KMS customer-managed key (documents, chat table, logs), TLS-only bucket policy, least-privilege IAM, private S3 origins |
| **Operations** | CloudWatch alarms (errors, 5xx, latency, ingestion DLQ) to SNS email, X-Ray tracing |
| **Quality** | 32 unit tests, metadata validator, evaluation script that also checks for access-control leaks, GitHub Actions CI |

---

## Repository Layout

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

---

## End-to-End Deployment Guide

> **This guide takes you from zero to a running RAG on AWS Bedrock.**
> Estimated total time: **40–60 minutes** (most is waiting for AWS resources to provision).

### Prerequisites

| Requirement | Details |
| --- | --- |
| AWS account | With valid payment method and administrator access |
| Region | `ap-south-1` (Mumbai) — Bedrock Knowledge Bases and Titan V2 must be available |
| Bedrock model access | Amazon Titan Text Embeddings V2 + a generation model (Nova Pro recommended) |

---

### Step 1 — Launch an EC2 Deployment Machine

Use an EC2 instance as your deployment control plane. This avoids Windows compatibility issues with bash scripts, `make`, and `zip`.

**Open AWS Console → EC2 → Launch instance** with these settings:

| Setting | Value |
| --- | --- |
| **Name** | `enterprise-rag-deployer` |
| **Region** | `ap-south-1` (Mumbai) |
| **AMI** | Ubuntu Server 24.04 LTS, 64-bit (x86) |
| **Instance type** | `t3.small` |
| **Key pair** | Create new → `enterprise-rag-key` (RSA, `.pem`) → save securely |
| **Network** | Enable **Auto-assign public IP** |
| **Security group** | Create new → allow only **SSH (TCP 22) from My IP** |
| **Storage** | 20 GiB gp3 (encrypted) |
| **IAM instance profile** | Attach a role with `AdministratorAccess` (for lab; restrict for production) |

> **⚠️ Security:** Never open SSH to `0.0.0.0/0`. Restrict to your IP only. For production, use Session Manager instead of SSH and a least-privilege IAM role.

Click **Launch instance** and wait for both status checks to pass.

---

### Step 2 — Connect to the EC2 Instance

**From your local machine (PowerShell / Terminal):**

```bash
# Replace with your .pem path and EC2 public IP
ssh -i "enterprise-rag-key.pem" ubuntu@<EC2_PUBLIC_IP>
```

**Or use PuTTY on Windows:**
1. Convert `.pem` to `.ppk` using PuTTYgen
2. Connect with Host = EC2 public IP, User = `ubuntu`, Auth = `.ppk` file

**After connecting, verify:**

```bash
whoami            # Expected: ubuntu
uname -m          # Expected: x86_64
cat /etc/os-release | head -3
```

---

### Step 3 — Install System Dependencies

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git curl unzip zip jq make python3 python3-pip python3-venv
```

**Verify:**

```bash
git --version       # git version 2.x
python3 --version   # Python 3.12+
pip3 --version      # pip 24.x
make --version      # GNU Make 4.x
jq --version        # jq-1.7+
```

---

### Step 4 — Install AWS CLI v2

```bash
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o awscliv2.zip
unzip -q awscliv2.zip
sudo ./aws/install
rm -rf aws awscliv2.zip
```

**Set the deployment region:**

```bash
aws configure set region ap-south-1
```

**Verify your IAM role works (no access keys needed — the EC2 instance profile provides credentials):**

```bash
aws sts get-caller-identity
```

Expected output:

```json
{
    "UserId": "AROAEXAMPLE:i-0abc123def456",
    "Account": "111122223333",
    "Arn": "arn:aws:sts::111122223333:assumed-role/YourEC2Role/i-0abc123def456"
}
```

> **Note your 12-digit Account ID** — you'll need it in Step 8.

> **⚠️ Important:** Do NOT run `aws configure` with long-lived access keys on EC2. The IAM instance profile is the secure way.

---

### Step 5 — Install Terraform

```bash
# Add HashiCorp GPG key and repository
wget -O- https://apt.releases.hashicorp.com/gpg | sudo gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/hashicorp.list
sudo apt update && sudo apt install terraform -y
```

**Verify (must be ≥ 1.6.0):**

```bash
terraform version
```

---

### Step 6 — Clone the Repository

```bash
cd ~
git clone https://github.com/Mokshith-9391/enterprise-bedrock-rag.git
cd ~/enterprise-bedrock-rag
```

**Verify:**

```bash
git branch --show-current   # Expected: main
ls -la                      # Should show Makefile, backend/, infrastructure/, etc.
```

**Fix script permissions (Git on Windows can strip execute bits):**

```bash
chmod +x scripts/*.sh
ls -l scripts/*.sh          # All should show -rwxr-xr-x
```

---

### Step 7 — Set Up Python and Run Tests

```bash
cd ~/enterprise-bedrock-rag

# Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r backend/requirements-dev.txt

# Run the 32 unit tests
make test
```

Expected:

```
32 passed
```

**Validate Terraform formatting:**

```bash
terraform -chdir=infrastructure/terraform fmt -check -recursive
```

> **⚠️ Do NOT proceed if tests fail.** They validate critical RBAC security logic.

---

### Step 8 — Enable Bedrock Model Access

You need to explicitly enable model access in your AWS account before using any Bedrock models.

**8a. Open the Bedrock Console:**

1. Go to **AWS Console** → **Amazon Bedrock** → ensure region is **ap-south-1**
2. Click **Model access** in the left sidebar
3. Click **Modify model access**

**8b. Enable these models:**

| Model | Purpose | Approval time |
| --- | --- | --- |
| **Amazon Titan Text Embeddings V2** | Document embedding (vectors) | Instant |
| **Amazon Nova Pro** | Answer generation | Instant |
| (Optional) **Anthropic Claude** | Higher-quality generation | Minutes–hours |

Click **Save changes** and wait for **Access granted** ✅.

**8c. Get your generation model's inference profile ARN:**

```bash
aws bedrock list-inference-profiles \
  --region ap-south-1 \
  --query "inferenceProfileSummaries[?status=='ACTIVE'].{Name:inferenceProfileName,ARN:inferenceProfileArn}" \
  --output table
```

**Copy the full ARN** for your chosen model, e.g.:

```
arn:aws:bedrock:ap-south-1:111122223333:inference-profile/apac.amazon.nova-pro-v1:0
```

**8d. Verify embedding model availability:**

```bash
aws bedrock get-foundation-model-availability \
  --region ap-south-1 \
  --model-id amazon.titan-embed-text-v2:0 \
  --output json
```

**8e. Check embedding quotas (important — prevents ingestion failures):**

```bash
aws service-quotas list-service-quotas \
  --service-code bedrock \
  --region ap-south-1 \
  --query "Quotas[?contains(QuotaName, 'Titan Text Embeddings V2')].[QuotaName,Value,Adjustable]" \
  --output table
```

> **⚠️ A model can show AUTHORIZED but have a zero on-demand quota**, causing `429 ThrottlingException` during ingestion. If you see a zero or very low quota, request an increase via Service Quotas before proceeding.

---

### Step 9 — Configure Terraform Variables

```bash
cd ~/enterprise-bedrock-rag

cp infrastructure/terraform/terraform.tfvars.example \
   infrastructure/terraform/terraform.tfvars

nano infrastructure/terraform/terraform.tfvars
```

**Set these values (replace the ARN with yours from Step 8c):**

```hcl
project_name = "enterprise-rag"
environment  = "dev"
region       = "ap-south-1"

# REQUIRED — paste your inference profile ARN from Step 8c
generation_model_arn = "arn:aws:bedrock:ap-south-1:111122223333:inference-profile/apac.amazon.nova-pro-v1:0"

# Leave empty — reranking isn't available in ap-south-1
rerank_model_arn = ""

departments = ["hr", "finance", "it", "projects", "training"]

enable_guardrail           = true
enable_query_decomposition = true
enable_waf                 = false

alarm_email = ""  # Optional: your-email@example.com for alarm notifications
```

Save and exit (`Ctrl+O`, `Enter`, `Ctrl+X` in nano).

> **⚠️ Never commit `terraform.tfvars`** — it's already in `.gitignore`.

---

### Step 10 — Initialize and Validate Terraform

```bash
terraform -chdir=infrastructure/terraform init
```

Expected:

```
Terraform has been successfully initialized!
```

```bash
terraform -chdir=infrastructure/terraform validate
```

Expected:

```
Success! The configuration is valid.
```

---

### Step 11 — Build the Lambda Package

```bash
make build
```

This packages your Python backend code for AWS Lambda (ARM64 architecture):

```bash
# Verify the package was created
ls -lah build/lambda/
find build/lambda -maxdepth 2 -type f | head -20
```

---

### Step 12 — Review the Terraform Plan

```bash
terraform -chdir=infrastructure/terraform plan
```

A clean first plan creates approximately **78 resources**:

```
Plan: 78 to add, 0 to change, 0 to destroy.
```

Review the plan carefully — do not approve unexpected destroy or replace operations.

---

### Step 13 — Deploy Phase 1: OpenSearch Serverless Foundation

The deployment requires **two phases** because the OpenSearch Terraform provider needs the collection endpoint to create the vector index, and that endpoint doesn't exist until the collection is created.

```bash
terraform -chdir=infrastructure/terraform apply \
  -target=aws_opensearchserverless_collection.kb \
  -target=aws_opensearchserverless_access_policy.data \
  -target=time_sleep.aoss_policy_propagation
```

**Type `yes` when prompted.** This takes ~3–4 minutes.

**What Phase 1 creates:**

- KMS customer-managed encryption key
- S3 document bucket (versioned, encrypted, TLS-only)
- DynamoDB chat history table
- OpenSearch Serverless encryption, network and data-access policies
- OpenSearch Serverless VECTORSEARCH collection
- 60-second wait for IAM policy propagation

**Verify the collection is active:**

```bash
aws opensearchserverless batch-get-collection \
  --region ap-south-1 \
  --names enterprise-rag-dev-kb \
  --output json | jq '.collectionDetails[0].status'
```

Expected: `"ACTIVE"`

```bash
terraform -chdir=infrastructure/terraform output vector_collection_endpoint
```

---

### Step 14 — Deploy Phase 2: Full Infrastructure

```bash
terraform -chdir=infrastructure/terraform plan    # Review first
terraform -chdir=infrastructure/terraform apply   # Type: yes
```

**This takes ~8–12 minutes.** Phase 2 creates everything else:

| Category | Resources created |
| --- | --- |
| **Vector index** | k-NN index in OpenSearch Serverless (faiss, HNSW, 1024 dims) |
| **Bedrock** | Knowledge Base, S3 Data Source (300-token chunks, 20% overlap), Guardrail |
| **Compute** | API Lambda (512 MB, arm64, 29s timeout), Ingest Lambda (256 MB, arm64, 30s) |
| **API** | HTTP API Gateway, JWT authorizer, 6 routes, throttling (10 rps) |
| **Auth** | Cognito User Pool, 7 groups, hosted domain, web client (PKCE) |
| **Frontend** | S3 web bucket, CloudFront distribution, config.js, optional WAF |
| **Ingestion** | EventBridge rule, SQS queue (batch 100, 60s window), DLQ |
| **Monitoring** | SNS topic, 4 CloudWatch alarms (errors, 5xx, p90 latency, DLQ) |

**Troubleshooting common errors:**

| Error | Cause | Fix |
| --- | --- | --- |
| `opensearch_index` 403 | Data access policy hasn't propagated | Re-run `terraform apply` |
| "no such index" | Phase 1 didn't complete | Re-run from Step 13 |
| `AccessDeniedException` on `InvokeModel` | Model access not enabled | Complete Step 8b in Bedrock Console |
| `ValidationException` mentioning model | Used model ARN instead of inference profile | Fix `generation_model_arn` in `terraform.tfvars` |

---

### Step 15 — Verify Terraform Outputs

```bash
terraform -chdir=infrastructure/terraform output
```

**Important outputs:**

```
web_url                   = "https://d1a2b3c4d5e6f7.cloudfront.net"
api_url                   = "https://abc123.execute-api.ap-south-1.amazonaws.com"
docs_bucket               = "enterprise-rag-dev-docs-111122223333"
knowledge_base_id         = "ABCDEF1234"
data_source_id            = "GHIJKL5678"
user_pool_id              = "ap-south-1_AbCdEfGh"
user_pool_client_id       = "1234567890abcdef"
cognito_login_domain      = "https://enterprise-rag-dev-111122223333.auth.ap-south-1.amazoncognito.com"
vector_collection_endpoint = "https://abcdef.ap-south-1.aoss.amazonaws.com"
generation_model_arn      = "arn:aws:bedrock:ap-south-1:111122223333:inference-profile/..."
guardrail_id              = "abc123def456"
region                    = "ap-south-1"
```

Save these for troubleshooting.

---

### Step 16 — Verify the Knowledge Base

```bash
KB_ID=$(terraform -chdir=infrastructure/terraform output -raw knowledge_base_id)
DS_ID=$(terraform -chdir=infrastructure/terraform output -raw data_source_id)

# Check Knowledge Base status
aws bedrock-agent get-knowledge-base \
  --region ap-south-1 \
  --knowledge-base-id "$KB_ID" \
  --query 'knowledgeBase.status' \
  --output text
```

Expected: `ACTIVE`

```bash
# Check Data Source
aws bedrock-agent get-data-source \
  --region ap-south-1 \
  --knowledge-base-id "$KB_ID" \
  --data-source-id "$DS_ID" \
  --query 'dataSource.status' \
  --output text
```

Expected: `AVAILABLE`

---

### Step 17 — Upload Documents to the Knowledge Base

```bash
make upload
```

This runs `scripts/validate_metadata.py` to check all sidecar metadata, then syncs `sample-docs/documents/` into `s3://<docs-bucket>/documents/`.

**Verify the upload:**

```bash
DOCS_BUCKET=$(terraform -chdir=infrastructure/terraform output -raw docs_bucket)
aws s3 ls "s3://$DOCS_BUCKET/documents/" --recursive --human-readable
```

You should see 9 documents + 9 metadata files across 5 department folders:

```
hr/leave-policy.md
hr/leave-policy.md.metadata.json
hr/work-from-home-policy.md
finance/travel-policy.md
finance/reimbursement-policy.md
it/vpn-guide.md
it/security-policy.md
it/incident-response-runbook.md     ← confidential!
projects/project-alpha-architecture.md
training/aws-training-plan.md
```

Each document has a matching `.metadata.json` sidecar:

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

---

### Step 18 — Wait for Document Ingestion

Uploading to S3 automatically triggers the ingestion pipeline:

```
S3 upload → EventBridge (Object Created) → SQS (batched, 60s) → Ingest Lambda → StartIngestionJob
```

**Monitor the ingestion job:**

```bash
make sync-status
```

Or use the raw AWS CLI:

```bash
aws bedrock-agent list-ingestion-jobs \
  --region ap-south-1 \
  --knowledge-base-id "$KB_ID" \
  --data-source-id "$DS_ID" \
  --sort-by attribute=STARTED_AT,order=DESCENDING \
  --max-results 5 \
  --output table
```

**Wait until status is `COMPLETE`** (typically 1–3 minutes for 9 sample documents):

```
┌──────┬─────────┬──────────┬────────┬────────┐
│failed│ indexed │ scanned  │ status │  ...   │
├──────┼─────────┼──────────┼────────┼────────┤
│  0   │    9    │    9     │COMPLETE│  ...   │
└──────┴─────────┴──────────┴────────┴────────┘
```

**If no job appears after 2 minutes**, trigger a manual sync:

```bash
make sync
```

> **⚠️ Do not run `make sync` repeatedly** if a sync is already `IN_PROGRESS`. Bedrock returns `ConflictException` when another job is running.

**If ingestion fails with `ThrottlingException` (429):**

Test the embedding model directly:

```bash
printf '%s' '{"inputText":"health check","dimensions":256,"normalize":true}' > /tmp/titan-test.json

aws bedrock-runtime invoke-model \
  --region ap-south-1 \
  --model-id amazon.titan-embed-text-v2:0 \
  --content-type application/json \
  --accept application/json \
  --body fileb:///tmp/titan-test.json \
  /tmp/titan-test.out

cat /tmp/titan-test.out | jq '.embedding | length'
```

If this also returns 429, the issue is your account's on-demand quota — request an increase via Service Quotas (see Step 8e).

---

### Step 19 — Create Demo Users

```bash
./scripts/create_user.sh admin@example.com   'Change-Me-Admin#2026' admin
./scripts/create_user.sh hr.user@example.com 'Change-Me-Hr#2026'    hr
./scripts/create_user.sh fin.user@example.com 'Change-Me-Fin#2026'  finance
./scripts/create_user.sh it.user@example.com 'Change-Me-It#2026'    it
./scripts/create_user.sh secops@example.com  'Change-Me-Sec#2026'   it confidential
```

> **⚠️ Replace passwords** with your own strong passwords (min 12 characters, upper + lower + number + symbol).

**User access model:**

| User | Groups | Can read |
| --- | --- | --- |
| `admin@example.com` | `admin` | Everything; can trigger syncs |
| `hr.user@example.com` | `hr` | HR documents (public + internal) |
| `fin.user@example.com` | `finance` | Finance documents |
| `it.user@example.com` | `it` | IT documents, **not** the confidential incident runbook |
| `secops@example.com` | `it`, `confidential` | IT documents including the confidential runbook |

The access filter is built from **verified Cognito group claims** — nothing in the request body can widen access.

---

### Step 20 — Open the Web Application

```bash
terraform -chdir=infrastructure/terraform output -raw web_url
```

1. Copy the URL and open it in your browser
2. Click **Sign in** — redirects to Cognito Hosted UI
3. Enter a demo user's email and password
4. After sign-in, you'll see the chat interface with your email and group badges

**Try these demonstrations:**

| Test | Sign in as | Ask | Expected |
| --- | --- | --- | --- |
| Basic retrieval | `hr.user` | "How many days of annual leave do employees get?" | "24 days" with citation from leave-policy.md |
| Access blocked | `it.user` | "Within how many hours must CERT-In be notified?" | "I couldn't find this in the documents you have access to." |
| Access granted | `secops` | Same question as above | "6 hours" with citation from the confidential runbook |
| Cross-document | `admin` | "Compare the work from home rules with the VPN requirements." | Cites both HR and IT documents |
| Hallucination prevention | Any user | "What is our Mars office relocation policy?" | Refuses to answer |

---

### Step 21 — Direct API/RAG Validation (Optional)

For low-level Bedrock validation without the browser:

```bash
KB_ID=$(terraform -chdir=infrastructure/terraform output -raw knowledge_base_id)
GEN_MODEL=$(terraform -chdir=infrastructure/terraform output -raw generation_model_arn)

aws bedrock-agent-runtime retrieve-and-generate \
  --region ap-south-1 \
  --input '{"text":"What is the employee leave policy?"}' \
  --retrieve-and-generate-configuration "{
    \"type\":\"KNOWLEDGE_BASE\",
    \"knowledgeBaseConfiguration\":{
      \"knowledgeBaseId\":\"$KB_ID\",
      \"modelArn\":\"$GEN_MODEL\"
    }
  }" \
  --output json | jq '.output.text'
```

The response should contain generated text with citation information.

---

### Step 22 — Run the Evaluation Suite

```bash
# Quick: retrieval hit@5 + access-control leak check (cheap, no generation)
make evaluate

# Full: also generates answers and checks keywords/refusals
make evaluate-full
```

Expected output:

```
id                    hit@5   leaks  answer  top files
leave-days            yes     0      -       leave-policy.md, ...
runbook-blocked       -       0      -       (no results)
runbook-allowed       yes     0      -       incident-response-runbook.md, ...
not-in-docs           -       0      -       ...

Retrieval hit@5: 10/10 (100%)
Access-control leaks: 0 (must be 0)
```

> **⚠️ "Access-control leaks: 0" is critical.** The script exits non-zero if any leak is detected — this can gate CI deployments.

---

### Step 23 — Local Frontend Testing (Optional)

From the EC2 instance:

```bash
make web-local
```

This generates `frontend/config.js` from Terraform outputs and serves the UI at `http://localhost:8080`. The repository already configures `http://localhost:8080` as a CORS origin and Cognito callback URL.

---

### Step 24 — Check Monitoring

```bash
# List project log groups
aws logs describe-log-groups --region ap-south-1 \
  --query "logGroups[?contains(logGroupName, 'enterprise-rag')].logGroupName" \
  --output table

# List alarms
aws cloudwatch describe-alarms --region ap-south-1 \
  --alarm-name-prefix enterprise-rag-dev \
  --query "MetricAlarms[].{Name:AlarmName,State:StateValue}" \
  --output table
```

Terraform provisions these CloudWatch alarms:

| Alarm | Triggers when |
| --- | --- |
| `*-api-lambda-errors` | Any unhandled Lambda error in 5 minutes |
| `*-api-5xx` | More than 5 API Gateway 5xx errors in 5 minutes |
| `*-api-p90-latency` | p90 Lambda duration > 20 seconds for 3 consecutive periods |
| `*-ingest-dlq` | Any message in the ingestion dead-letter queue |

---

## Adding Your Own Documents

### File Structure

Place files under `documents/<department>/` with a sidecar `.metadata.json`:

```
documents/finance/travel-policy.pdf
documents/finance/travel-policy.pdf.metadata.json
```

### Metadata Format

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

**Rules:**

- `department` must match a Cognito group (see `departments` in `terraform.tfvars`)
- `classification` must be `public`, `internal`, or `confidential`
  - Only `admin` and `confidential` groups see `confidential` documents
- A document with no metadata is visible to admins only
- Supported formats: PDF, Markdown, Text, HTML, Word (.doc/.docx), CSV, Excel (.xls/.xlsx)

**Upload:**

```bash
./scripts/upload_docs.sh path/to/your/documents
# Or: make upload  (uses sample-docs/documents/)
```

The sync starts automatically within ~60 seconds.

---

## How Access Control Works

1. Cognito issues an ID token containing `cognito:groups`
2. API Gateway's JWT authorizer verifies signature, issuer, audience and expiry
3. `access.py` turns the verified groups into a Bedrock retrieval filter:

   ```json
   {"andAll": [
     {"in": {"key": "department", "value": ["hr"]}},
     {"in": {"key": "classification", "value": ["public", "internal"]}}
   ]}
   ```

4. The vector search only considers chunks that match — documents outside the user's access never reach the model

Nothing in the request body affects the filter. Sessions are also bound to their owner: a user can't continue someone else's conversation.

For hard isolation of highly sensitive material (legal, board, M&A), use a separate knowledge base rather than metadata filtering.

---

## API Reference

All routes except `/health` need `Authorization: Bearer <Cognito ID token>`.

| Method & path | Body | Returns |
| --- | --- | --- |
| `GET /health` | — | `{"status": "ok"}` |
| `POST /ask` | `{"question": "...", "session_id": "optional"}` | `answer` (with `[n]` markers), `sources[]`, `session_id`, `message_id`, `grounded`, `latency_ms` |
| `GET /history` | — | Last 20 exchanges |
| `POST /feedback` | `{"message_id": "...", "rating": "up" or "down", "comment": ""}` | `{"saved": true}` |
| `POST /admin/sync` | `{}` | `202` with job ID, or `409` if already running |
| `GET /admin/ingestion-jobs` | — | 10 most recent sync jobs with statistics |

Errors return `{"error": "..."}` with 400, 403, 429, 502 or 500, plus a `request_id`.

---

## Configuration

| Variable | Default | Notes |
| --- | --- | --- |
| `generation_model_arn` | (required) | Inference profile or model ARN |
| `region` | `ap-south-1` | Titan V2 and Knowledge Bases must be available |
| `rerank_model_arn` | `""` | Empty disables reranking |
| `chunk_max_tokens` / `chunk_overlap_percentage` | 300 / 20 | Affects newly ingested files |
| `num_results` / `num_reranked` | 10 / 5 | Chunks retrieved / kept after reranking |
| `enable_query_decomposition` | `true` | Better for "compare A and B" questions |
| `enable_guardrail` | `true` | Content filters, prompt attacks, PII handling |
| `enable_waf` | `false` | AWS WAF on CloudFront |
| `force_destroy` | `true` | Lets `make destroy` delete non-empty buckets |

---

## Security Notes Before Production

- Replace the **public OpenSearch network policy** with a VPC endpoint and run Lambda in private subnets
- **Narrow `bedrock:InvokeModel`** from `foundation-model/*` to specific model IDs
- Add a **custom domain** with ACM certificates for CloudFront and API Gateway
- **Federate Cognito** with your corporate IdP (SAML/OIDC) and map IdP groups to Cognito groups
- Enable **Bedrock model invocation logging** to S3 for audit
- Set `enable_waf = true` and `force_destroy = false`
- Store **Terraform state** in S3 with DynamoDB locking (see `versions.tf`)
- Run `make evaluate-full` in **CI** after each document batch
- Use separate AWS **accounts/environments** for production and development

---

## Cost

| Service | Billing | Typical cost |
| --- | --- | --- |
| **OpenSearch Serverless** | Minimum OCU-hours even when idle | **~\$200–400/month** (dominant cost) |
| Bedrock tokens | Pay per input/output token | Small at demo volumes |
| Lambda, API Gateway, DynamoDB, S3, CloudFront | Pay per use | Negligible |
| KMS | \$1/key/month + API calls | ~\$1/month |

> **Run `make destroy` when you finish a session.** For a cheaper long-running environment, swap the vector store for Amazon S3 Vectors — only `opensearch.tf` and `storage_configuration` in `bedrock.tf` change.

---

## Clean Shutdown / Destroy Procedure

> **⚠️ Critical for temporary labs.** OpenSearch Serverless continues generating charges when idle.

### 1. Stop activity

Don't start new sync jobs or tests while destroying.

### 2. Destroy Terraform resources

```bash
cd ~/enterprise-bedrock-rag
source .venv/bin/activate
make destroy
```

Review the plan and type `yes`. The KMS key enters its 7-day deletion window.

### 3. Verify state is empty

```bash
terraform -chdir=infrastructure/terraform state list
# Should return nothing
```

### 4. Terminate the EC2 instance

```bash
# From your local machine (not from the EC2 itself):
aws ec2 terminate-instances --instance-ids <EC2_INSTANCE_ID> --region ap-south-1
```

Or terminate from the EC2 Console. The root volume is deleted on termination by default.

### 5. Remove temporary IAM permissions

If you attached `AdministratorAccess` to the EC2 role, detach it now.

### 6. Verify no project resources remain

```bash
# Check for leftover resources
aws s3api list-buckets --query "Buckets[?contains(Name, 'enterprise-rag-dev')].Name" --output table
aws lambda list-functions --region ap-south-1 --query "Functions[?contains(FunctionName, 'enterprise-rag-dev')].FunctionName" --output table
aws dynamodb list-tables --region ap-south-1 --query "TableNames[?contains(@, 'enterprise-rag-dev')]" --output table
aws opensearchserverless list-collections --region ap-south-1 --output table
```

Also check the Console for: CloudFront, API Gateway, Cognito, KMS keys, CloudWatch log groups, SNS topics, SQS queues, EventBridge rules.

---

## Troubleshooting

| Symptom | Likely cause and fix |
| --- | --- |
| Phase 2 fails creating `opensearch_index` with 403 | Data access policy hasn't propagated. Re-run `terraform apply`. |
| Knowledge base creation fails: "no such index" | The index wasn't created. Re-run from Phase 1. |
| `AccessDeniedException` on `InvokeModel` | Model access isn't enabled, or wrong ARN. Check Bedrock Console. |
| `ValidationException` mentioning the model | Use an inference-profile ARN from `list-inference-profiles`. |
| `ThrottlingException` / 429 on embedding | Account quota is zero or too low. Check Service Quotas. |
| Sync completes but documents fail | Check `make sync-status` for `failed` count. Common: metadata >10 KB, unsupported format, scanned PDF with no text. |
| Uploaded file isn't searchable | Wait ~1 minute for batched sync. Check ingestion job status. |
| Every answer says "couldn't find this" | User's groups don't match document `department`, or documents lack metadata. |
| Browser shows a CORS error | Only CloudFront URL and `local_dev_origin` are allowed. |
| 503/504 on long questions | HTTP API 30s limit. Disable query decomposition or lower `num_results`. |

---

## Deployment Checklist

- [ ] EC2 launched in `ap-south-1`
- [ ] SSH restricted to My IP
- [ ] EC2 IAM role attached
- [ ] AWS CLI works through IAM role (`aws sts get-caller-identity`)
- [ ] Terraform ≥ 1.6.0 installed
- [ ] Repository cloned
- [ ] `scripts/*.sh` executable
- [ ] `make test` passes (32 tests)
- [ ] `make build` succeeds
- [ ] Bedrock model access granted (Titan V2 + generation model)
- [ ] Bedrock embedding quota verified
- [ ] `terraform.tfvars` configured with inference profile ARN
- [ ] `terraform init` succeeds
- [ ] `terraform validate` succeeds
- [ ] `terraform plan` reviewed
- [ ] Phase 1 (AOSS) succeeds — collection `ACTIVE`
- [ ] Phase 2 (full) succeeds
- [ ] Knowledge Base is `ACTIVE`
- [ ] Documents uploaded to S3
- [ ] Ingestion reaches `COMPLETE`
- [ ] Demo users created
- [ ] Cognito login works in browser
- [ ] RAG returns grounded answers with citations
- [ ] Access-control tests pass (`make evaluate`)
- [ ] Monitoring checked
- [ ] **After done:** `make destroy` completed
- [ ] **After done:** EC2 terminated
- [ ] **After done:** No leftover project resources
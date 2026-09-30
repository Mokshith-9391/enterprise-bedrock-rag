Enterprise RAG on Amazon Bedrock Knowledge Bases

An end-to-end company knowledge assistant built with Amazon Bedrock Knowledge Bases, OpenSearch Serverless, S3, Lambda, API Gateway, Cognito, CloudFront, DynamoDB, EventBridge, SQS, KMS and CloudWatch.

The application is designed around this flow:

Employees / Browser
        |
        v
CloudFront
        |
Private S3 frontend + OAC
        |
Cognito Hosted UI (OAuth code + PKCE)
        |
        v
API Gateway HTTP API
        |
JWT Authorizer
        |
        v
Lambda - RAG API -------------------- DynamoDB
        |                               |
        |                               +-- chat history / feedback
        |
        +--> Bedrock Knowledge Base
                    |
             OpenSearch Serverless
                    |
          vector retrieval / metadata filter
                    |
               Bedrock model
                    |
            answer + citations

Document ingestion:

S3 documents/
     |
     v
EventBridge
     |
     v
SQS + DLQ
     |
     v
Ingestion Lambda
     |
     v
Bedrock StartIngestionJob
     |
     +--> parsing
     +--> chunking
     +--> Titan Text Embeddings V2
     +--> OpenSearch Serverless vector index

Repository components

backend/src/app/api_handler.py - API Lambda entry point

backend/src/app/ingest_handler.py - SQS-driven ingestion Lambda

backend/src/app/access.py - Cognito group to Bedrock metadata-filter logic

backend/src/app/rag.py - retrieval/generation and citation parsing

backend/src/app/store.py - DynamoDB history/session/feedback

backend/src/app/config.py - runtime configuration

backend/src/app/logutil.py - structured logging

infrastructure/terraform/ - all AWS infrastructure

frontend/ - static browser application

sample-docs/documents/ - sample knowledge base content

eval/ - evaluation questions

scripts/ - deployment, upload, sync, user and evaluation helpers

docs/architecture.md - architecture/design details

Architecture implemented by this repository

Query path

Browser
  -> CloudFront
  -> Cognito login
  -> JWT
  -> API Gateway HTTP API
  -> JWT authorizer
  -> Lambda RAG API
  -> access.py builds a filter from verified Cognito groups
  -> Bedrock Knowledge Base
  -> OpenSearch Serverless
  -> retrieval / optional reranking / query decomposition
  -> foundation model or inference profile
  -> citations
  -> Lambda
  -> API response
  -> browser

Ingestion path

Document
  -> S3 bucket under documents/
  -> EventBridge Object Created/Deleted event
  -> SQS
  -> ingestion Lambda
  -> Bedrock StartIngestionJob
  -> Knowledge Base parsing
  -> fixed-size chunking
  -> Titan Text Embeddings V2
  -> OpenSearch Serverless

The current Terraform configuration uses Titan Text Embeddings V2 at 1,024 dimensions, 300-token chunks and 20% overlap. Generation uses an ARN supplied by generation_model_arn; newer Bedrock models may require an inference-profile ARN.

Prerequisites

AWS account

You need an AWS account with a valid payment method and sufficient service access. The deployment creates billable resources, especially OpenSearch Serverless and CloudFront.

Recommended deployment machine

Use an EC2 deployment/control machine rather than running the infrastructure directly from your laptop.

Recommended EC2 setup for this repo:

Region:         ap-south-1 (Mumbai)
AMI:            Ubuntu Server 24.04 LTS 64-bit x86
Instance:       t3.small
Root disk:      20 GiB gp3
Public IPv4:    enabled for initial SSH
Security:       SSH/22 from My IP only

The repository README specifies Python 3.12, Terraform 1.6+, AWS CLI v2, make, zip and an AWS identity that can deploy the required resources.

AWS authentication on EC2

Prefer an EC2 IAM instance profile rather than long-lived access keys.

For a temporary lab, the deployment instance can use a role with enough permissions to create the resources in this repository. A fast lab shortcut is temporary AdministratorAccess; remove it as soon as deployment/validation is finished. Production should use a dedicated least-privilege Terraform deployment role.

Do not put AWS access keys in .env, the Git repository, shell scripts or Terraform variables.

1. Create the EC2 deployment machine

Open AWS Console -> EC2 -> Launch instance.

Select ap-south-1.

Select Ubuntu Server 24.04 LTS, 64-bit x86.

Select t3.small.

Create an RSA key pair such as enterprise-rag-key and save the .pem file securely.

Enable a public IPv4 address.

Create a security group allowing only:

SSH TCP 22 -> My IP

Do not open 0.0.0.0/0 on SSH.

Attach an IAM instance profile to the EC2 instance. Include AmazonSSMManagedInstanceCore if you want Session Manager access.

Use a 20 GiB gp3 encrypted root volume.

Launch the instance.

Verify the instance is Running and the status checks pass.

2. Connect from PuTTY/SSH

Use the EC2 public IPv4 address, user ubuntu, and the private key created during launch.

After connecting:

whoami
hostname
uname -m
cat /etc/os-release

Expected architecture is x86_64 and the OS should be Ubuntu.

3. Prepare Ubuntu

sudo apt update
sudo apt upgrade -y
sudo apt install -y git curl unzip zip jq make python3 python3-pip python3-venv

Verify:

git --version
python3 --version
pip3 --version
make --version
jq --version

4. Install AWS CLI v2

Use the official AWS CLI v2 Linux installer. Example:

curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o awscliv2.zip
unzip -q awscliv2.zip
sudo ./aws/install
aws --version
rm -rf aws awscliv2.zip

Set the deployment region:

aws configure set region ap-south-1
aws configure get region

Expected:

ap-south-1

Verify EC2 role authentication:

aws sts get-caller-identity

The ARN should represent your EC2-assumed role. Do not run aws configure with long-lived access keys.

5. Install Terraform

Use HashiCorp's official APT repository and install a Terraform version satisfying the repository requirement (>= 1.6.0).

Verify:

terraform version

6. Clone the exact repository

cd ~
git clone https://github.com/Mokshith-9391/enterprise-bedrock-rag.git
cd ~/enterprise-bedrock-rag

git branch --show-current
git status

Expected branch:

main

7. Fix Linux shell-script executable permissions

Some Git environments can lose executable bits. Before running the Makefile:

chmod +x scripts/*.sh

Check:

ls -l scripts/*.sh

Shell scripts such as build_lambda.sh, upload_docs.sh and sync_now.sh should have an x permission.

If Git reports a mode change such as:

mode change 100644 => 100755

keep that change and commit it later so future Linux/CI environments do not reproduce the permission failure.

8. Terraform formatting and Python tests

Create a Python virtual environment:

cd ~/enterprise-bedrock-rag
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r backend/requirements-dev.txt

Run tests:

make test

Format Terraform:

terraform -chdir=infrastructure/terraform fmt -recursive
terraform -chdir=infrastructure/terraform fmt -check -recursive

Validate Git changes:

git status --short
git diff --check
git diff -- infrastructure/terraform/ scripts/

9. Build the Lambda package

make build

The repository build script creates:

build/lambda/

and installs Lambda dependencies for the target Python/ARM64 runtime.

Verify:

ls -lah build/lambda
find build/lambda -maxdepth 2 -type f | head -30

10. Check Amazon Bedrock model access

Generation model

List available inference profiles:

aws bedrock list-inference-profiles \
  --region ap-south-1 \
  --query "inferenceProfileSummaries[?status=='ACTIVE'].{Name:inferenceProfileName,ARN:inferenceProfileArn,Type:type}" \
  --output table

Choose an active profile supported in your account/region and put its ARN in generation_model_arn.

For the lab run documented during this project, the selected generation profile was:

APAC Amazon Nova Pro

with the account-specific inference-profile ARN returned by the command above.

Embedding model

The repository uses:

amazon.titan-embed-text-v2:0

Check availability:

aws bedrock get-foundation-model-availability \
  --region ap-south-1 \
  --model-id amazon.titan-embed-text-v2:0 \
  --output json

The important fields should report that authorization, entitlement and regional availability are available.

Check the account's assigned quotas:

aws service-quotas list-service-quotas \
  --service-code bedrock \
  --region ap-south-1 \
  --query "Quotas[?contains(QuotaName, 'Titan Text Embeddings V2')].[QuotaName,Value,Adjustable,QuotaCode]" \
  --output table

Do this before starting ingestion. A model can show AUTHORIZED and still have an account-specific on-demand quota that is too low or zero, resulting in 429 ThrottlingException during direct InvokeModel calls or Knowledge Base ingestion.

11. Create Terraform variables

From the repository root:

cp infrastructure/terraform/terraform.tfvars.example \
   infrastructure/terraform/terraform.tfvars
nano infrastructure/terraform/terraform.tfvars

Minimum working example:

project_name = "enterprise-rag"
environment  = "dev"
region       = "ap-south-1"

generation_model_arn = "<ACTIVE_INFERENCE_PROFILE_ARN>"

rerank_model_arn = ""

departments = ["hr", "finance", "it", "projects", "training"]

enable_guardrail          = true
enable_query_decomposition = true
enable_waf                  = false
alarm_email                = ""

Do not commit a real terraform.tfvars containing environment/account-specific values.

12. Initialize and validate Terraform

terraform -chdir=infrastructure/terraform init
terraform -chdir=infrastructure/terraform validate

Expected:

Success! The configuration is valid.

Optional provider inspection:

terraform -chdir=infrastructure/terraform providers

13. Create the Terraform plan

terraform -chdir=infrastructure/terraform plan

Review the final summary.

A clean first plan for this lab was:

Plan: 78 to add, 0 to change, 0 to destroy.

After the OpenSearch Serverless foundation was created separately, the normal plan became smaller. Your exact count depends on state and prior partial operations.

Do not approve an unexpected destroy or replacement of the OpenSearch collection.

For a reproducible apply, save the plan:

terraform -chdir=infrastructure/terraform plan -out=tfplan

14. Deploy in two phases

This repository uses two deployment phases because the OpenSearch provider needs the collection endpoint before it can create the OpenSearch vector index.

Phase 1 - OpenSearch Serverless foundation

terraform -chdir=infrastructure/terraform apply \
  -target=aws_opensearchserverless_collection.kb \
  -target=aws_opensearchserverless_access_policy.data \
  -target=time_sleep.aoss_policy_propagation

Review the targeted plan and type yes only when the plan is the expected OpenSearch/bootstrap operation.

The first OpenSearch Serverless collection in an account may also cause AWS to create the service-linked role:

AWSServiceRoleForAmazonOpenSearchServerless

The first collection requires iam:CreateServiceLinkedRole.

Verify:

aws opensearchserverless batch-get-collection \
  --region ap-south-1 \
  --names enterprise-rag-dev-kb \
  --output json

Expected status:

ACTIVE

Get the Terraform output:

terraform -chdir=infrastructure/terraform output vector_collection_endpoint

Phase 2 - full infrastructure

First run a normal plan:

terraform -chdir=infrastructure/terraform plan

Make sure it shows no unwanted destroy/replacement.

Then:

terraform -chdir=infrastructure/terraform apply

Alternatively, when you have created a saved plan and verified it:

terraform -chdir=infrastructure/terraform apply tfplan

The full infrastructure creates the application resources defined in infrastructure/terraform/.

15. Verify Terraform outputs

terraform -chdir=infrastructure/terraform output

Important outputs:

web_url
api_url
docs_bucket
knowledge_base_id
data_source_id
user_pool_id
user_pool_client_id
cognito_login_domain
vector_collection_endpoint
generation_model_arn
guardrail_id
region

Capture them for troubleshooting.

16. Verify the Knowledge Base

KB_ID=$(terraform -chdir=infrastructure/terraform output -raw knowledge_base_id)
DS_ID=$(terraform -chdir=infrastructure/terraform output -raw data_source_id)

aws bedrock-agent get-knowledge-base \
  --region ap-south-1 \
  --knowledge-base-id "$KB_ID" \
  --output json

The Knowledge Base should reach:

ACTIVE

Check the data source:

aws bedrock-agent get-data-source \
  --region ap-south-1 \
  --knowledge-base-id "$KB_ID" \
  --data-source-id "$DS_ID" \
  --output json

17. Upload documents

The repository's sample documents live under:

sample-docs/documents/

Upload them with:

make upload

The script validates metadata and runs an S3 sync into:

s3://<docs-bucket>/documents/

Verify:

DOCS_BUCKET=$(terraform -chdir=infrastructure/terraform output -raw docs_bucket)
aws s3 ls "s3://$DOCS_BUCKET/documents/" --recursive

Each document can have a sidecar metadata file with the same base name plus .metadata.json.

Example:

documents/finance/travel-policy.md
documents/finance/travel-policy.md.metadata.json

Example metadata:

{
  "metadataAttributes": {
    "department": "finance",
    "document_type": "policy",
    "classification": "internal",
    "year": 2026
  }
}

department values should match your configured Cognito groups. classification is used for document access control.

18. Ingestion: automatic first, manual fallback

S3 changes are designed to flow automatically:

S3 -> EventBridge -> SQS -> ingestion Lambda -> StartIngestionJob

Check recent jobs first:

make sync-status

Do not call make sync repeatedly if a sync is already in progress. Bedrock can return ConflictException when another operation is already using the Knowledge Base.

If no job is running and you need a manual sync:

make sync

The repository's manual sync script starts a job and waits for COMPLETE, FAILED or STOPPED.

Direct AWS check:

aws bedrock-agent list-ingestion-jobs \
  --region ap-south-1 \
  --knowledge-base-id "$KB_ID" \
  --data-source-id "$DS_ID" \
  --sort-by attribute=STARTED_AT,order=DESCENDING \
  --max-results 5 \
  --output table

If needed, poll the latest job:

JOB_ID=$(aws bedrock-agent list-ingestion-jobs \
  --region ap-south-1 \
  --knowledge-base-id "$KB_ID" \
  --data-source-id "$DS_ID" \
  --sort-by attribute=STARTED_AT,order=DESCENDING \
  --max-results 1 \
  --query 'ingestionJobSummaries[0].ingestionJobId' \
  --output text)

while true; do
  STATUS=$(aws bedrock-agent get-ingestion-job \
    --region ap-south-1 \
    --knowledge-base-id "$KB_ID" \
    --data-source-id "$DS_ID" \
    --ingestion-job-id "$JOB_ID" \
    --query 'ingestionJob.status' \
    --output text)

  echo "$(date '+%H:%M:%S') status=$STATUS"

  case "$STATUS" in
    COMPLETE|FAILED|STOPPED) break ;;
  esac

  sleep 10
done

Final statistics:

aws bedrock-agent get-ingestion-job \
  --region ap-south-1 \
  --knowledge-base-id "$KB_ID" \
  --data-source-id "$DS_ID" \
  --ingestion-job-id "$JOB_ID" \
  --output json

19. Important Bedrock throttling troubleshooting

A particularly important account-level failure mode is:

ValidationException / ThrottlingException
Too many requests, please wait before trying again.

If a direct test also returns 429, do not keep hammering the ingestion API.

Check:

aws bedrock get-foundation-model-availability \
  --region ap-south-1 \
  --model-id amazon.titan-embed-text-v2:0 \
  --output json

aws service-quotas list-service-quotas \
  --service-code bedrock \
  --region ap-south-1 \
  --query "Quotas[?contains(QuotaName, 'Titan Text Embeddings V2')].[QuotaName,Value,Adjustable,QuotaCode]" \
  --output table

Then make a single small direct test:

printf '%s' '{"inputText":"Enterprise RAG health check","dimensions":256,"normalize":true}' > /tmp/titan-test.json

aws bedrock-runtime invoke-model \
  --region ap-south-1 \
  --model-id amazon.titan-embed-text-v2:0 \
  --content-type application/json \
  --accept application/json \
  --body fileb:///tmp/titan-test.json \
  /tmp/titan-test.out

If that direct invocation also gets 429, the application code is not the immediate cause. Check account quotas, billing/payment status and AWS Support before rebuilding the Knowledge Base.

Do not casually change the embedding model after the Knowledge Base exists. Changing embeddings generally means rebuilding the vector/Knowledge Base configuration rather than editing a single runtime variable.

20. Create demo users

The repository provides scripts/create_user.sh.

Create users with your own strong passwords:

./scripts/create_user.sh admin@example.com 'YOUR-STRONG-PASSWORD' admin
./scripts/create_user.sh hr.user@example.com 'YOUR-STRONG-PASSWORD' hr
./scripts/create_user.sh fin.user@example.com 'YOUR-STRONG-PASSWORD' finance
./scripts/create_user.sh it.user@example.com 'YOUR-STRONG-PASSWORD' it
./scripts/create_user.sh secops@example.com 'YOUR-STRONG-PASSWORD' it confidential

Do not publish these passwords.

The group-to-document model is:

admin                   -> full access
hr                      -> HR public/internal
finance                 -> Finance documents
it                      -> IT public/internal
it + confidential       -> IT confidential material

The access filter is built from verified Cognito group claims rather than trusting a group supplied in the request body.

21. Open the application

Get the CloudFront URL:

terraform -chdir=infrastructure/terraform output -raw web_url

Open it in a browser.

The browser authenticates through Cognito, receives tokens, calls API Gateway, and the API invokes the RAG Lambda.

22. Local frontend testing

The repository also supports:

make web-local

This writes a local frontend/config.js using Terraform outputs and serves the frontend at:

http://localhost:8080

The repository already configures http://localhost:8080 as a CORS origin and Cognito callback URL.

23. Direct API/RAG validation

Use the deployed API or the browser first. For low-level Bedrock validation, retrieve-and-generate can query a Knowledge Base and generate a response using a foundation model or inference profile.

Example variables:

KB_ID=$(terraform -chdir=infrastructure/terraform output -raw knowledge_base_id)
GEN_MODEL=$(terraform -chdir=infrastructure/terraform output -raw generation_model_arn)

Example direct request:

aws bedrock-agent-runtime retrieve-and-generate \
  --region ap-south-1 \
  --input '{"text":"What is the employee leave policy?"}' \
  --retrieve-and-generate-configuration "{\
    \"type\":\"KNOWLEDGE_BASE\",\
    \"knowledgeBaseConfiguration\":{\
      \"knowledgeBaseId\":\"$KB_ID\",\
      \"modelArn\":\"$GEN_MODEL\"\
    }\
  }" \
  --output json

The response should contain generated text and citation information when retrieval succeeds.

24. Evaluation

Run the cheap retrieval/access-control evaluation:

make evaluate

Run answer generation checks as well:

make evaluate-full

The evaluation suite includes access-control cases and should report zero access-control leaks.

25. Monitoring

Terraform provisions CloudWatch/SNS monitoring for:

Lambda errors

API Gateway 5xx

Lambda p90 latency

SQS ingestion DLQ messages

Useful commands:

aws logs describe-log-groups --region ap-south-1 | grep enterprise-rag
aws sns list-topics --region ap-south-1 | grep enterprise-rag

26. Security notes before production

This repository is a strong learning/demo architecture, but review these settings before treating it as production-ready:

The current OpenSearch Serverless network policy allows public network access. Data access is still governed by IAM/data policies, but a production design should consider an AOSS VPC endpoint and private networking.

CloudFront is using the default certificate in the repository. Production should use an ACM certificate and a custom domain.

The repository currently sets CloudFront's default certificate configuration directly rather than a custom domain certificate; review TLS settings before production.

enable_waf defaults to false; enable and tune WAF for an internet-facing production application.

The repository has not provisioned CloudTrail in Terraform; add it if CloudTrail is a hard production requirement.

Replace temporary broad Terraform deployment permissions with a dedicated least-privilege deployment role.

Use separate AWS accounts/environments for production and development.

For highly sensitive material such as legal, board or M&A documents, prefer physically separate Knowledge Bases instead of relying only on metadata filtering.

27. Clean shutdown / destroy procedure

This is critical for a temporary lab because OpenSearch Serverless and other resources can continue generating charges.

First: stop ingestion and application activity

Don't start new sync jobs or tests while destroying.

Second: destroy Terraform-managed resources

From the repository root:

cd ~/enterprise-bedrock-rag
source .venv/bin/activate
make destroy

Review the destruction plan and confirm the intended project resources are being removed.

The repository has:

force_destroy = true

for the lab buckets, so Terraform can delete non-empty S3 buckets. The KMS key is scheduled for deletion with a 7-day waiting period by the Terraform configuration.

Third: verify Terraform state is empty

terraform -chdir=infrastructure/terraform state list

It should return no managed resources after a successful destroy.

Fourth: terminate the EC2 deployment machine

EC2 was your control plane and is not created by this Terraform project, so Terraform will not delete it.

Terminate the instance from the EC2 console or:

aws ec2 terminate-instances --instance-ids <EC2_INSTANCE_ID> --region ap-south-1

Also check for unattached EBS volumes. The root volume launched with the normal console setting is normally deleted on termination; preserved volumes continue to incur storage charges.

Fifth: remove temporary IAM deployment permissions

If you temporarily attached AdministratorAccess to the EC2 role, detach it.

If you created an inline deployment policy only for this lab (for example TerraformDeploymentBootstrap), remove that policy after the deployment machine is terminated, unless you intentionally want to reuse it.

Do not delete an IAM role that existed before this project unless you have confirmed it is used only by this project.

Sixth: check the OpenSearch Serverless service-linked role

OpenSearch Serverless can create:

AWSServiceRoleForAmazonOpenSearchServerless

AWS requires all OpenSearch Serverless collections to be deleted before this service-linked role can be manually deleted. If this role is no longer used anywhere in the account, delete it after confirming there are no remaining AOSS collections.

Seventh: verify no project resources remain

Search by the project prefix:

aws s3api list-buckets \
  --query "Buckets[?contains(Name, 'enterprise-rag-dev')].Name" \
  --output table

aws lambda list-functions \
  --region ap-south-1 \
  --query "Functions[?contains(FunctionName, 'enterprise-rag-dev')].FunctionName" \
  --output table

aws dynamodb list-tables \
  --region ap-south-1 \
  --query "TableNames[?contains(@, 'enterprise-rag-dev')]" \
  --output table

aws opensearchserverless list-collections \
  --region ap-south-1 \
  --output table

Also check manually in the AWS Console for:

CloudFront
API Gateway
Cognito
KMS Customer managed keys
CloudWatch log groups
SNS topics
SQS queues
EventBridge rules
IAM roles created specifically for enterprise-rag-dev

Important billing expectation

Destroying the stack prevents future resource runtime charges once resources are actually gone, but AWS can still bill usage that occurred before destruction. KMS customer-managed keys scheduled for deletion are not charged for key storage while pending deletion, and the key is permanently deleted after the waiting period. CloudFront distribution deletion can take time because the distribution must be disabled and propagated before it can be deleted.

28. Final deployment checklist

[ ] EC2 launched in ap-south-1
[ ] SSH restricted to My IP
[ ] EC2 IAM role attached
[ ] AWS CLI works through IAM role
[ ] Terraform installed
[ ] Repository cloned
[ ] scripts/*.sh executable
[ ] make test passes
[ ] make build succeeds
[ ] Bedrock model access verified
[ ] Bedrock quota verified
[ ] terraform.tfvars configured
[ ] terraform init succeeds
[ ] terraform validate succeeds
[ ] terraform plan reviewed
[ ] AOSS Phase 1 succeeds
[ ] AOSS collection ACTIVE
[ ] Full Terraform deployment succeeds
[ ] Knowledge Base ACTIVE
[ ] Documents uploaded to S3
[ ] Ingestion reaches COMPLETE
[ ] Demo users created
[ ] Cognito login works
[ ] API Gateway JWT works
[ ] RAG returns grounded answers + citations
[ ] Access-control tests pass
[ ] Monitoring checked
[ ] AdministratorAccess removed
[ ] Terraform destroy completed when finished
[ ] EC2 terminated
[ ] No leftover project resources

AWS documentation references

For current implementation details, check the AWS documentation for:

EC2 launch and security groups

Systems Manager Session Manager

AWS CLI installation

Terraform installation

Amazon Bedrock Knowledge Bases supported models and Regions

Bedrock StartIngestionJob, GetIngestionJob and RetrieveAndGenerate

OpenSearch Serverless IAM permissions and service-linked roles

CloudFront deletion

EC2 termination and EBS delete-on-termination

AWS KMS key deletion

License

Add your preferred license here.
# One zip, two handlers. `make build` creates ../../build/lambda first.
data "archive_file" "lambda" {
  type        = "zip"
  source_dir  = local.lambda_src_dir
  output_path = "${path.module}/../../build/lambda.zip"
}

data "aws_iam_policy_document" "lambda_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

# ================================================================ API function

resource "aws_iam_role" "api" {
  name               = "${local.prefix}-api-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

resource "aws_iam_role_policy_attachment" "api_basic" {
  role       = aws_iam_role.api.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "api_xray" {
  role       = aws_iam_role.api.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/AWSXRayDaemonWriteAccess"
}

data "aws_iam_policy_document" "api" {
  statement {
    sid       = "RetrieveAndGenerate"
    actions   = ["bedrock:RetrieveAndGenerate"]
    resources = ["*"] # this action does not support resource-level permissions
  }
  statement {
    sid       = "QueryKnowledgeBase"
    actions   = ["bedrock:Retrieve"]
    resources = [aws_bedrockagent_knowledge_base.main.arn]
  }
  statement {
    sid       = "AdminSync"
    actions   = ["bedrock:StartIngestionJob", "bedrock:ListIngestionJobs", "bedrock:GetIngestionJob"]
    resources = [aws_bedrockagent_knowledge_base.main.arn]
  }
  statement {
    sid     = "GenerationModel"
    actions = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream", "bedrock:GetInferenceProfile"]
    # An inference profile routes to the same model in several regions, so the
    # underlying foundation-model ARNs are needed too. Narrow the wildcard to
    # your model id (for example foundation-model/amazon.nova-pro-v1:0) in production.
    resources = compact([
      var.generation_model_arn,
      "arn:${local.partition}:bedrock:*::foundation-model/*",
      var.rerank_model_arn,
    ])
  }
  dynamic "statement" {
    for_each = var.rerank_model_arn == "" ? [] : [1]
    content {
      sid       = "Rerank"
      actions   = ["bedrock:Rerank"]
      resources = ["*"]
    }
  }
  dynamic "statement" {
    for_each = var.enable_guardrail ? [1] : []
    content {
      sid       = "Guardrail"
      actions   = ["bedrock:ApplyGuardrail"]
      resources = [aws_bedrock_guardrail.main[0].guardrail_arn]
    }
  }
  statement {
    sid       = "ChatHistory"
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Query"]
    resources = [aws_dynamodb_table.chat.arn]
  }
  statement {
    sid       = "SourceLinks" # presigned links to cited documents
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.docs.arn}/documents/*"]
  }
  statement {
    sid       = "Kms"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [aws_kms_key.main.arn]
  }
}

resource "aws_iam_role_policy" "api" {
  name   = "api-access"
  role   = aws_iam_role.api.id
  policy = data.aws_iam_policy_document.api.json
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/lambda/${local.prefix}-api"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.main.arn
}

resource "aws_lambda_function" "api" {
  function_name    = "${local.prefix}-api"
  description      = "RAG API: ask, history, feedback, admin sync"
  role             = aws_iam_role.api.arn
  filename         = data.archive_file.lambda.output_path
  source_code_hash = data.archive_file.lambda.output_base64sha256
  handler          = "app.api_handler.handler"
  runtime          = "python3.12"
  architectures    = ["arm64"]
  memory_size      = 512
  timeout          = 29 # HTTP API integrations time out at 30 s

  tracing_config {
    mode = "Active"
  }

  environment {
    variables = {
      KNOWLEDGE_BASE_ID          = aws_bedrockagent_knowledge_base.main.id
      DATA_SOURCE_ID             = aws_bedrockagent_data_source.docs.data_source_id
      MODEL_ARN                  = var.generation_model_arn
      RERANK_MODEL_ARN           = var.rerank_model_arn
      GUARDRAIL_ID               = var.enable_guardrail ? aws_bedrock_guardrail.main[0].guardrail_id : ""
      GUARDRAIL_VERSION          = var.enable_guardrail ? aws_bedrock_guardrail_version.main[0].version : ""
      TABLE_NAME                 = aws_dynamodb_table.chat.name
      DOCS_BUCKET                = aws_s3_bucket.docs.id
      NUM_RESULTS                = tostring(var.num_results)
      NUM_RERANKED               = tostring(var.num_reranked)
      ENABLE_QUERY_DECOMPOSITION = tostring(var.enable_query_decomposition)
      LOG_LEVEL                  = "INFO"
    }
  }

  depends_on = [aws_cloudwatch_log_group.api, aws_iam_role_policy.api]
}

# ================================================================ ingestion function

resource "aws_iam_role" "ingest" {
  name               = "${local.prefix}-ingest-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

resource "aws_iam_role_policy_attachment" "ingest_basic" {
  role       = aws_iam_role.ingest.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "ingest" {
  statement {
    sid       = "StartSync"
    actions   = ["bedrock:StartIngestionJob", "bedrock:GetIngestionJob", "bedrock:ListIngestionJobs"]
    resources = [aws_bedrockagent_knowledge_base.main.arn]
  }
  statement {
    sid       = "ReadQueue"
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes", "sqs:ChangeMessageVisibility"]
    resources = [aws_sqs_queue.ingest.arn]
  }
}

resource "aws_iam_role_policy" "ingest" {
  name   = "ingest-access"
  role   = aws_iam_role.ingest.id
  policy = data.aws_iam_policy_document.ingest.json
}

resource "aws_cloudwatch_log_group" "ingest" {
  name              = "/aws/lambda/${local.prefix}-ingest"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.main.arn
}

resource "aws_lambda_function" "ingest" {
  function_name    = "${local.prefix}-ingest"
  description      = "Starts a Knowledge Base sync when documents change"
  role             = aws_iam_role.ingest.arn
  filename         = data.archive_file.lambda.output_path
  source_code_hash = data.archive_file.lambda.output_base64sha256
  handler          = "app.ingest_handler.handler"
  runtime          = "python3.12"
  architectures    = ["arm64"]
  memory_size      = 256
  timeout          = 30

  environment {
    variables = {
      KNOWLEDGE_BASE_ID = aws_bedrockagent_knowledge_base.main.id
      DATA_SOURCE_ID    = aws_bedrockagent_data_source.docs.data_source_id
      LOG_LEVEL         = "INFO"
    }
  }

  depends_on = [aws_cloudwatch_log_group.ingest, aws_iam_role_policy.ingest]
}

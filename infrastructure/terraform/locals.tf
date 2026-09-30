data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

# Converts an assumed-role session ARN into the underlying role ARN,
# which is the form OpenSearch Serverless access policies accept.
data "aws_iam_session_context" "current" {
  arn = data.aws_caller_identity.current.arn
}

locals {
  prefix     = "${var.project_name}-${var.environment}"
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition

  collection_name    = substr("${local.prefix}-kb", 0, 32)
  aoss_policy_prefix = substr(local.collection_name, 0, 26) # policy names are limited to 32 characters
  index_name      = "bedrock-kb-index"
  vector_field    = "bedrock-knowledge-base-default-vector"
  text_field      = "AMAZON_BEDROCK_TEXT_CHUNK"
  metadata_field  = "AMAZON_BEDROCK_METADATA"

  embedding_model_arn = "arn:${local.partition}:bedrock:${var.region}::foundation-model/amazon.titan-embed-text-v2:0"

  cognito_groups = concat(var.departments, ["confidential", "admin"])
  lambda_src_dir = "${path.module}/../../build/lambda"
  web_origin     = "https://${aws_cloudfront_distribution.web.domain_name}"

  tags = merge(
    {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "terraform"
    },
    var.tags
  )
}

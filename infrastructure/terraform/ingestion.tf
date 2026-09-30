# S3 object change -> EventBridge -> SQS (batched) -> ingest Lambda -> StartIngestionJob

resource "aws_sqs_queue" "ingest_dlq" {
  name                      = "${local.prefix}-ingest-dlq"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "ingest" {
  name                       = "${local.prefix}-ingest"
  visibility_timeout_seconds = 300 # retry a busy sync after 5 minutes
  message_retention_seconds  = 86400
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.ingest_dlq.arn
    maxReceiveCount     = 20
  })
}

resource "aws_cloudwatch_event_rule" "doc_changes" {
  name        = "${local.prefix}-doc-changes"
  description = "Document added, replaced or deleted under documents/"
  event_pattern = jsonencode({
    source        = ["aws.s3"]
    "detail-type" = ["Object Created", "Object Deleted"]
    detail = {
      bucket = { name = [aws_s3_bucket.docs.id] }
      object = { key = [{ prefix = "documents/" }] }
    }
  })
}

resource "aws_cloudwatch_event_target" "doc_changes" {
  rule = aws_cloudwatch_event_rule.doc_changes.name
  arn  = aws_sqs_queue.ingest.arn
}

data "aws_iam_policy_document" "ingest_queue" {
  statement {
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.ingest.arn]
    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }
    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_cloudwatch_event_rule.doc_changes.arn]
    }
  }
}

resource "aws_sqs_queue_policy" "ingest" {
  queue_url = aws_sqs_queue.ingest.id
  policy    = data.aws_iam_policy_document.ingest_queue.json
}

resource "aws_lambda_event_source_mapping" "ingest" {
  event_source_arn                   = aws_sqs_queue.ingest.arn
  function_name                      = aws_lambda_function.ingest.arn
  batch_size                         = 100
  maximum_batching_window_in_seconds = 60 # collect a burst of uploads into one sync

  scaling_config {
    maximum_concurrency = 2 # the lowest value SQS allows; syncs run one at a time anyway
  }
}

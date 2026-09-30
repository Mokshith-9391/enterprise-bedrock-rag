output "web_url" {
  description = "Open this in a browser."
  value       = local.web_origin
}

output "api_url" {
  value = aws_apigatewayv2_api.http.api_endpoint
}

output "docs_bucket" {
  description = "Upload documents under s3://<bucket>/documents/<department>/"
  value       = aws_s3_bucket.docs.id
}

output "knowledge_base_id" {
  value = aws_bedrockagent_knowledge_base.main.id
}

output "data_source_id" {
  value = aws_bedrockagent_data_source.docs.data_source_id
}

output "user_pool_id" {
  value = aws_cognito_user_pool.main.id
}

output "user_pool_client_id" {
  value = aws_cognito_user_pool_client.web.id
}

output "cognito_login_domain" {
  value = "https://${aws_cognito_user_pool_domain.main.domain}.auth.${var.region}.amazoncognito.com"
}

output "vector_collection_endpoint" {
  value = aws_opensearchserverless_collection.kb.collection_endpoint
}

output "generation_model_arn" {
  value = var.generation_model_arn
}

output "guardrail_id" {
  value = var.enable_guardrail ? aws_bedrock_guardrail.main[0].guardrail_id : null
}

output "region" {
  value = var.region
}

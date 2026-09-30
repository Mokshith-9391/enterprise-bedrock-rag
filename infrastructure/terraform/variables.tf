variable "project_name" {
  description = "Short lowercase name used as a prefix for every resource."
  type        = string
  default     = "enterprise-rag"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,19}$", var.project_name))
    error_message = "Use 3-20 lowercase letters, digits or hyphens, starting with a letter."
  }
}

variable "environment" {
  description = "Deployment stage, for example dev, test or prod."
  type        = string
  default     = "dev"

  validation {
    condition     = can(regex("^[a-z0-9]{2,6}$", var.environment))
    error_message = "Use 2-6 lowercase letters or digits."
  }
}

variable "region" {
  description = "AWS region for everything except the CloudFront WAF."
  type        = string
  default     = "ap-south-1"
}

variable "generation_model_arn" {
  description = <<-EOT
    Model or inference-profile ARN that writes the answers. Many newer models are only
    callable through a cross-region inference profile, for example
    arn:aws:bedrock:ap-south-1:<ACCOUNT_ID>:inference-profile/apac.amazon.nova-pro-v1:0
    List what your account can use with:
      aws bedrock list-inference-profiles --region ap-south-1
  EOT
  type        = string
}

variable "rerank_model_arn" {
  description = "Optional reranker model ARN. Leave empty if reranking isn't offered in your region."
  type        = string
  default     = ""
}

variable "departments" {
  description = "Department groups. Each value must match the 'department' metadata on documents."
  type        = list(string)
  default     = ["hr", "finance", "it", "projects", "training"]
}

variable "chunk_max_tokens" {
  description = "Maximum tokens per chunk (fixed-size chunking)."
  type        = number
  default     = 300
}

variable "chunk_overlap_percentage" {
  description = "Overlap between neighbouring chunks, in percent."
  type        = number
  default     = 20
}

variable "num_results" {
  description = "Chunks retrieved per question (before reranking)."
  type        = number
  default     = 10
}

variable "num_reranked" {
  description = "Chunks kept after reranking (only used when a reranker is set)."
  type        = number
  default     = 5
}

variable "enable_query_decomposition" {
  description = "Split comparison questions into sub-queries before retrieval."
  type        = bool
  default     = true
}

variable "enable_guardrail" {
  description = "Create a Bedrock guardrail (harmful content, prompt attacks, PII masking)."
  type        = bool
  default     = true
}

variable "enable_waf" {
  description = "Put AWS WAF in front of CloudFront (adds a small monthly cost)."
  type        = bool
  default     = false
}

variable "alarm_email" {
  description = "Email for CloudWatch alarm notifications. Leave empty to skip."
  type        = string
  default     = ""
}

variable "local_dev_origin" {
  description = "Extra origin allowed by CORS and Cognito callbacks for local frontend testing."
  type        = string
  default     = "http://localhost:8080"
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention."
  type        = number
  default     = 30
}

variable "force_destroy" {
  description = "Allow terraform destroy to delete non-empty buckets. Set false in production."
  type        = bool
  default     = true
}

variable "tags" {
  description = "Extra tags for every resource."
  type        = map(string)
  default     = {}
}

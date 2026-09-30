terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.80.0, < 7.0.0"
    }
    opensearch = {
      source  = "opensearch-project/opensearch"
      version = "~> 2.3"
    }
    time = {
      source  = "hashicorp/time"
      version = "~> 0.12"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.6"
    }
  }

  # For team use, keep state remotely. Create the bucket and table once, then uncomment.
  # backend "s3" {
  #   bucket         = "my-terraform-state-bucket"
  #   key            = "enterprise-rag/dev/terraform.tfstate"
  #   region         = "ap-south-1"
  #   dynamodb_table = "terraform-locks"
  #   encrypt        = true
  # }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = local.tags
  }
}

# WAF for CloudFront must be created in us-east-1.
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"
  default_tags {
    tags = local.tags
  }
}

# Used only to create the vector index inside the OpenSearch Serverless collection.
provider "opensearch" {
  url                   = aws_opensearchserverless_collection.kb.collection_endpoint
  aws_region            = var.region
  aws_signature_service = "aoss"
  healthcheck           = false
}

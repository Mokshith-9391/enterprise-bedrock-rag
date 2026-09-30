# OpenSearch Serverless holds the vectors. Three policies are required before
# the collection works: encryption, network and data access.
#
# COST NOTE: a vector collection bills a minimum number of OCUs per hour even
# when idle. Run `make destroy` when a lab is finished.

resource "aws_opensearchserverless_security_policy" "encryption" {
  name = "${local.aoss_policy_prefix}-enc"
  type = "encryption"
  policy = jsonencode({
    Rules = [{
      ResourceType = "collection"
      Resource     = ["collection/${local.collection_name}"]
    }]
    AWSOwnedKey = true
  })
}

# Public endpoint, still protected by IAM (SigV4) and the data access policy.
# For production, replace with a VPC endpoint (aws_opensearchserverless_vpc_endpoint).
resource "aws_opensearchserverless_security_policy" "network" {
  name = "${local.aoss_policy_prefix}-net"
  type = "network"
  policy = jsonencode([{
    Rules = [
      { ResourceType = "collection", Resource = ["collection/${local.collection_name}"] },
      { ResourceType = "dashboard", Resource = ["collection/${local.collection_name}"] }
    ]
    AllowFromPublic = true
  }])
}

resource "aws_opensearchserverless_access_policy" "data" {
  name = "${local.aoss_policy_prefix}-data"
  type = "data"
  policy = jsonencode([{
    Rules = [
      {
        ResourceType = "index"
        Resource     = ["index/${local.collection_name}/*"]
        Permission = [
          "aoss:CreateIndex", "aoss:DeleteIndex", "aoss:DescribeIndex",
          "aoss:ReadDocument", "aoss:WriteDocument", "aoss:UpdateIndex"
        ]
      },
      {
        ResourceType = "collection"
        Resource     = ["collection/${local.collection_name}"]
        Permission   = ["aoss:CreateCollectionItems", "aoss:DescribeCollectionItems", "aoss:UpdateCollectionItems"]
      }
    ]
    Principal = [
      aws_iam_role.kb.arn,
      data.aws_iam_session_context.current.issuer_arn, # whoever runs Terraform creates the index
    ]
  }])
}

resource "aws_opensearchserverless_collection" "kb" {
  name = local.collection_name
  type = "VECTORSEARCH"

  depends_on = [
    aws_opensearchserverless_security_policy.encryption,
    aws_opensearchserverless_security_policy.network,
  ]
}

# Data access policies take a short while to apply.
resource "time_sleep" "aoss_policy_propagation" {
  create_duration = "60s"
  depends_on = [
    aws_opensearchserverless_access_policy.data,
    aws_opensearchserverless_collection.kb,
  ]
}

# The index layout Bedrock Knowledge Bases expects. faiss is required for metadata filtering.
resource "opensearch_index" "kb" {
  name                           = local.index_name
  number_of_shards               = "2"
  number_of_replicas             = "0"
  index_knn                      = true
  index_knn_algo_param_ef_search = "512"
  force_destroy                  = true

  mappings = jsonencode({
    properties = {
      (local.vector_field) = {
        type      = "knn_vector"
        dimension = 1024
        method = {
          name       = "hnsw"
          engine     = "faiss"
          space_type = "l2"
          parameters = { m = 16, ef_construction = 512 }
        }
      }
      (local.text_field)     = { type = "text", index = true }
      (local.metadata_field) = { type = "text", index = false }
    }
  })

  # Bedrock adds a field per metadata key during ingestion. Without this,
  # the next apply would try to replace (and empty) the index.
  lifecycle {
    ignore_changes = [mappings]
  }

  depends_on = [time_sleep.aoss_policy_propagation]
}

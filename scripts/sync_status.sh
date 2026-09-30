#!/usr/bin/env bash
# Shows the five most recent ingestion jobs.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
aws bedrock-agent list-ingestion-jobs \
  --region "$("$ROOT/scripts/tf_output.sh" region)" \
  --knowledge-base-id "$("$ROOT/scripts/tf_output.sh" knowledge_base_id)" \
  --data-source-id "$("$ROOT/scripts/tf_output.sh" data_source_id)" \
  --sort-by attribute=STARTED_AT,order=DESCENDING --max-results 5 \
  --query "ingestionJobSummaries[].{job:ingestionJobId,status:status,started:startedAt,scanned:statistics.numberOfDocumentsScanned,indexed:statistics.numberOfNewDocumentsIndexed,modified:statistics.numberOfModifiedDocumentsIndexed,deleted:statistics.numberOfDocumentsDeleted,failed:statistics.numberOfDocumentsFailed}" \
  --output table

#!/usr/bin/env bash
# Starts an ingestion job manually and waits for it to finish.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
KB="$("$ROOT/scripts/tf_output.sh" knowledge_base_id)"
DS="$("$ROOT/scripts/tf_output.sh" data_source_id)"
REGION="$("$ROOT/scripts/tf_output.sh" region)"

JOB=$(aws bedrock-agent start-ingestion-job --region "$REGION" \
  --knowledge-base-id "$KB" --data-source-id "$DS" \
  --query ingestionJob.ingestionJobId --output text)
echo "Started ingestion job $JOB"
while true; do
  STATUS=$(aws bedrock-agent get-ingestion-job --region "$REGION" \
    --knowledge-base-id "$KB" --data-source-id "$DS" --ingestion-job-id "$JOB" \
    --query ingestionJob.status --output text)
  echo "  status: $STATUS"
  case "$STATUS" in COMPLETE|FAILED|STOPPED) break ;; esac
  sleep 10
done
aws bedrock-agent get-ingestion-job --region "$REGION" \
  --knowledge-base-id "$KB" --data-source-id "$DS" --ingestion-job-id "$JOB" \
  --query "ingestionJob.{status:status,statistics:statistics,failures:failureReasons}"

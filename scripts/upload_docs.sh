#!/usr/bin/env bash
# Uploads sample-docs/documents/ to s3://<docs bucket>/documents/.
# EventBridge sees the new objects and the ingest Lambda starts a sync by itself.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${1:-$ROOT/sample-docs/documents}"
BUCKET="$("$ROOT/scripts/tf_output.sh" docs_bucket)"

python3 "$ROOT/scripts/validate_metadata.py" "$SRC"
aws s3 sync "$SRC" "s3://$BUCKET/documents/" --delete --exclude ".DS_Store"
echo "Uploaded. A sync starts automatically within about a minute."
echo "Watch it with: make sync-status"

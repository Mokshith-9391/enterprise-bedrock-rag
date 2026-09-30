#!/usr/bin/env bash
# Packages backend/src/app plus pinned dependencies into build/lambda/.
# Terraform zips that folder (see infrastructure/terraform/lambda.tf).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/build/lambda"

rm -rf "$OUT" && mkdir -p "$OUT"
python3 -m pip install --quiet --upgrade \
  --target "$OUT" \
  --platform manylinux2014_aarch64 --implementation cp --python-version 3.12 --only-binary=:all: \
  -r "$ROOT/backend/requirements.txt"
cp -R "$ROOT/backend/src/app" "$OUT/app"
find "$OUT" -name "__pycache__" -type d -prune -exec rm -rf {} +
echo "Lambda package ready: $OUT ($(du -sh "$OUT" | cut -f1))"

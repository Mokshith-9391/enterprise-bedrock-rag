#!/usr/bin/env bash
# Usage: scripts/tf_output.sh <output_name>
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
terraform -chdir="$ROOT/infrastructure/terraform" output -raw "$1"

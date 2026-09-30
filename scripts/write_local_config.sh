#!/usr/bin/env bash
# Writes frontend/config.js from Terraform outputs so you can run the UI on localhost:8080.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
out() { "$ROOT/scripts/tf_output.sh" "$1"; }
cat > "$ROOT/frontend/config.js" <<JS
window.APP_CONFIG = {
  apiUrl: "$(out api_url)",
  region: "$(out region)",
  cognitoDomain: "$(out cognito_login_domain)",
  clientId: "$(out user_pool_client_id)",
  appName: "Company knowledge assistant",
};
JS
echo "Wrote frontend/config.js. Serve with: python3 -m http.server 8080 -d frontend"

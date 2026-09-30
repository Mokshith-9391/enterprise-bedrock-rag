#!/usr/bin/env bash
# Usage: scripts/create_user.sh <email> <password> <group> [group ...]
# Example: scripts/create_user.sh asha@example.com 'Str0ng!Passw0rd' hr confidential
# Groups: hr finance it projects training confidential admin
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ "$#" -lt 3 ]; then
  echo "Usage: $0 <email> <password> <group> [group ...]" >&2
  exit 1
fi
EMAIL="$1"; PASSWORD="$2"; shift 2
POOL="$("$ROOT/scripts/tf_output.sh" user_pool_id)"
REGION="$("$ROOT/scripts/tf_output.sh" region)"

aws cognito-idp admin-create-user --region "$REGION" --user-pool-id "$POOL" \
  --username "$EMAIL" --message-action SUPPRESS \
  --user-attributes Name=email,Value="$EMAIL" Name=email_verified,Value=true >/dev/null
aws cognito-idp admin-set-user-password --region "$REGION" --user-pool-id "$POOL" \
  --username "$EMAIL" --password "$PASSWORD" --permanent
for GROUP in "$@"; do
  aws cognito-idp admin-add-user-to-group --region "$REGION" --user-pool-id "$POOL" \
    --username "$EMAIL" --group-name "$GROUP"
done
echo "Created $EMAIL in groups: $*"

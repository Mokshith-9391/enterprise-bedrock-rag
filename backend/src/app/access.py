"""Turns a verified Cognito identity into a Bedrock retrieval filter.

Security rule: the filter is built ONLY from claims that API Gateway's JWT
authorizer has already verified. Nothing in the request body can widen access.

Group model (Cognito groups):
  hr, finance, it, projects, training  -> may read documents whose metadata
                                           "department" equals that group
  confidential                         -> may also read classification=confidential
  admin                                -> may read everything, and trigger syncs
"""

import json
import re
from dataclasses import dataclass, field

DEPARTMENTS = frozenset({"hr", "finance", "it", "projects", "training"})
ADMIN_GROUP = "admin"
CONFIDENTIAL_GROUP = "confidential"
NON_CONFIDENTIAL = ["public", "internal"]


class AccessDenied(Exception):
    """Raised when a signed-in user has no group that grants document access."""


def parse_groups(raw) -> set:
    """Normalise the cognito:groups claim.

    Depending on the API Gateway flavour the claim arrives as a list, a JSON
    string ('["hr","it"]'), a bracketed space-separated string ('[hr it]',
    HTTP API JWT authorizer), or a comma-separated string ('hr,it').
    """
    if raw is None:
        return set()
    if isinstance(raw, (list, tuple, set)):
        items = raw
    else:
        text = str(raw).strip()
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = json.loads(text)
                items = parsed if isinstance(parsed, list) else [parsed]
            except json.JSONDecodeError:
                items = re.split(r"[\s,]+", text[1:-1])
        else:
            items = re.split(r"[\s,]+", text)
    return {str(i).strip().lower() for i in items if str(i).strip()}


@dataclass(frozen=True)
class UserContext:
    user_id: str
    email: str = ""
    groups: frozenset = field(default_factory=frozenset)

    @property
    def is_admin(self) -> bool:
        return ADMIN_GROUP in self.groups

    @property
    def departments(self) -> list:
        return sorted(self.groups & DEPARTMENTS)

    @property
    def can_read_confidential(self) -> bool:
        return self.is_admin or CONFIDENTIAL_GROUP in self.groups


def user_from_claims(claims: dict) -> UserContext:
    user_id = (claims or {}).get("sub")
    if not user_id:
        raise AccessDenied("Token has no subject claim")
    return UserContext(
        user_id=user_id,
        email=claims.get("email", ""),
        groups=frozenset(parse_groups(claims.get("cognito:groups"))),
    )


def build_retrieval_filter(user: UserContext):
    """Return a Bedrock RetrievalFilter dict, or None for unrestricted access."""
    filters = []
    if not user.is_admin:
        if not user.departments:
            raise AccessDenied("Your account isn't in any department group yet. Ask an administrator to add you.")
        filters.append({"in": {"key": "department", "value": user.departments}})
    if not user.can_read_confidential:
        filters.append({"in": {"key": "classification", "value": NON_CONFIDENTIAL}})

    if not filters:
        return None
    if len(filters) == 1:
        return filters[0]
    return {"andAll": filters}

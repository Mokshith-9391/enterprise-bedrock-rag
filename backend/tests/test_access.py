import pytest

from app.access import AccessDenied, UserContext, build_retrieval_filter, parse_groups, user_from_claims


@pytest.mark.parametrize(
    "raw, expected",
    [
        (None, set()),
        (["HR", "it"], {"hr", "it"}),
        ('["hr","finance"]', {"hr", "finance"}),
        ("[hr finance]", {"hr", "finance"}),  # HTTP API JWT authorizer format
        ("hr,finance", {"hr", "finance"}),     # REST API Cognito authorizer format
        ("admin", {"admin"}),
        ("[]", set()),
    ],
)
def test_parse_groups(raw, expected):
    assert parse_groups(raw) == expected


def test_user_from_claims_requires_sub():
    with pytest.raises(AccessDenied):
        user_from_claims({"email": "a@b.com"})


def test_department_user_gets_department_and_classification_filter():
    user = UserContext("u1", groups=frozenset({"hr"}))
    assert build_retrieval_filter(user) == {
        "andAll": [
            {"in": {"key": "department", "value": ["hr"]}},
            {"in": {"key": "classification", "value": ["public", "internal"]}},
        ]
    }


def test_confidential_group_drops_classification_filter():
    user = UserContext("u1", groups=frozenset({"it", "finance", "confidential"}))
    assert build_retrieval_filter(user) == {"in": {"key": "department", "value": ["finance", "it"]}}


def test_admin_is_unrestricted():
    assert build_retrieval_filter(UserContext("u1", groups=frozenset({"admin"}))) is None


def test_user_without_department_is_denied():
    with pytest.raises(AccessDenied):
        build_retrieval_filter(UserContext("u1", groups=frozenset({"confidential"})))


def test_unknown_groups_grant_nothing():
    with pytest.raises(AccessDenied):
        build_retrieval_filter(UserContext("u1", groups=frozenset({"marketing", "everyone"})))

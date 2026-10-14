"""Public plan rights must describe runtime behavior, not unused stored keys."""

import pytest

from api.subscription import QuotaResponse, SubscriptionCatalogEntitlementsResponse
from tests.test_api.test_entitlement_consistency import _headers, _plan, _subscribe, _user

RETIRED = {
    "context_window_tokens": 16384, "custom_prompts": True,
    "material_uploads": 5, "priority_support": True,
    "writing_credits_monthly": 100000, "agent_runs_monthly": 100,
    "active_projects_limit": 40, "context_tokens_limit": 16384,
    "material_uploads_monthly": 5, "material_decompositions_monthly": 9,
    "custom_skills_limit": 40, "skill_creates_monthly": 20, "priority_queue_level": "priority",
}


def test_neutral_compatibility_fields_are_explicitly_deprecated_in_the_public_schema():
    catalog = SubscriptionCatalogEntitlementsResponse.model_json_schema()['properties']
    for key in ('material_uploads_monthly', 'context_tokens_limit', 'priority_queue_level', 'writing_credits_monthly', 'agent_runs_monthly'):
        assert catalog[key]['deprecated'] is True
    assert QuotaResponse.model_json_schema()['properties']['material_uploads']['deprecated'] is True


@pytest.mark.parametrize("stored_copy_limit", [100, 0, 7, -1, None])
async def test_pro_copy_right_matches_existing_unlimited_execution(client, db_session, stored_copy_limit):
    user = _user(db_session, "copy_right")
    _plan(db_session, "free", 0, {})
    pro = _plan(db_session, "pro", 4900, {**RETIRED, "inspiration_copies_monthly": stored_copy_limit})
    _subscribe(db_session, user, pro, days=30)
    headers = await _headers(client, user.username)

    plans = (await client.get('/api/v1/subscription/plans')).json()
    me = (await client.get('/api/v1/subscription/me', headers=headers)).json()
    catalog = (await client.get('/api/v1/subscription/catalog')).json()
    quota = (await client.get('/api/v1/subscription/quota', headers=headers)).json()
    public_features = next(plan['features'] for plan in plans if plan['name'] == 'pro')
    entitlements = next(plan['entitlements'] for plan in catalog['tiers'] if plan['name'] == 'pro')
    assert public_features['inspiration_copies_monthly'] == me['features']['inspiration_copies_monthly'] == -1
    assert entitlements['inspiration_copies_monthly'] == quota['inspiration_copies']['limit'] == -1
    assert not set(RETIRED).intersection(public_features)
    assert not set(RETIRED).intersection(me['features'])
    assert entitlements['material_uploads_monthly'] == 0
    assert quota['material_uploads'] == {'used': 0, 'limit': 0, 'reset_at': None}


async def test_deprecated_admin_keys_are_accepted_but_not_persisted(client, db_session):
    admin = _user(db_session, 'legacy_plan_admin', admin=True)
    pro = _plan(db_session, 'pro', 4900, dict(RETIRED))
    headers = await _headers(client, admin.username)
    response = await client.put(f'/api/admin/plans/{pro.id}', headers=headers, json={
        'features': {**RETIRED, 'max_projects': -1, 'inspiration_copies_monthly': -1},
    })
    assert response.status_code == 200
    assert response.json()['features'] == {'max_projects': -1, 'inspiration_copies_monthly': -1}


async def test_pro_copy_policy_cannot_be_lowered_by_admin(client, db_session):
    admin = _user(db_session, 'pro_policy_admin', admin=True)
    pro = _plan(db_session, 'pro', 4900, {'inspiration_copies_monthly': 100})
    headers = await _headers(client, admin.username)
    response = await client.put(f'/api/admin/plans/{pro.id}', headers=headers, json={
        'features': {'inspiration_copies_monthly': 100},
    })
    assert response.status_code == 422
    assert 'inspiration_copies_monthly' in response.json()['error_detail']

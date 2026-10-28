import pytest
from pydantic import ValidationError
from backend.settings import Settings

DB = 'postgresql+asyncpg://mori:local@postgres/mori_workflow_test'
ORIGIN = 'http://127.0.0.1:8000'

def config(**kwargs):
    return Settings(database_url=DB, app_env='local', **kwargs)

def test_unconfigured_oauth_disabled():
    assert config().auth_providers == []

@pytest.mark.parametrize('provider', ['google', 'kakao'])
def test_configured_provider_secret_and_callback(provider):
    settings = config(**{f'{provider}_client_id':'test-client',
                         f'{provider}_client_secret':'synthetic-secret',
                         f'{provider}_redirect_uri':f'{ORIGIN}/api/v1/auth/{provider}/callback'})
    assert settings.auth_providers == [provider]
    assert 'synthetic-secret' not in repr(settings)
    assert settings.model_dump()[f'{provider}_client_secret'].get_secret_value() == 'synthetic-secret'

@pytest.mark.parametrize('provider', ['google', 'kakao'])
@pytest.mark.parametrize('uri', ['https://foreign.invalid/api/v1/auth/google/callback',
    f'{ORIGIN}/callback', f'{ORIGIN}/api/v1/auth/google/callback?next=1'])
def test_callback_mismatch_rejected(provider, uri):
    with pytest.raises(ValidationError):
        config(**{f'{provider}_client_id':'client', f'{provider}_client_secret':'secret',
                  f'{provider}_redirect_uri':uri})

def test_google_missing_secret_is_incomplete_configuration():
    with pytest.raises(ValidationError):
        config(google_client_id='client', google_redirect_uri=f'{ORIGIN}/api/v1/auth/google/callback')

def test_kakao_secret_is_optional_for_apps_without_client_secret():
    settings = config(kakao_client_id='client', kakao_redirect_uri=f'{ORIGIN}/api/v1/auth/kakao/callback')
    assert settings.auth_providers == ['kakao']

def test_all_empty_template_values_are_disabled():
    settings = config(google_client_id='', google_client_secret='',google_redirect_uri=f'{ORIGIN}/api/v1/auth/google/callback',
                      kakao_client_id='',kakao_client_secret='',kakao_redirect_uri=f'{ORIGIN}/api/v1/auth/kakao/callback')
    assert settings.auth_providers == []

def test_login_request_persists_only_hashed_tokens():
    from backend.models import OAuthLoginRequest
    columns = OAuthLoginRequest.__table__.columns
    assert {'provider','state_hash','binding_hash','return_to','expires_at','consumed_at'} <= set(columns.keys())
    assert not ({'state','binding','code','access_token','client_secret'} & set(columns.keys()))
    assert columns.state_hash.unique is True

@pytest.mark.asyncio
async def test_public_config_lists_enabled_providers_without_credentials(tmp_path):
    import httpx
    from backend.main import create_app
    settings = config(storage_root=tmp_path,google_client_id='synthetic-client',
                      google_client_secret='synthetic-secret',
                      google_redirect_uri=f'{ORIGIN}/api/v1/auth/google/callback')
    app = create_app(settings=settings, session_factory=lambda: None)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=ORIGIN) as client:
            response = await client.get('/api/v1/client-config')
    assert response.status_code == 200
    assert response.json()['data']['auth_providers'] == ['google']
    assert 'synthetic-secret' not in response.text
    assert 'synthetic-client' not in response.text
    assert response.headers['cache-control'] == 'no-store'

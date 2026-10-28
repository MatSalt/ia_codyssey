from decimal import Decimal
import pytest
from pydantic import ValidationError
from backend.settings import Settings

DB='postgresql+asyncpg://mori:local@postgres/mori_workflow_test'

def test_real_ai_defaults_off_and_budget_decimal():
    value=Settings(database_url=DB)
    assert not value.ai_real_calls_enabled
    assert not value.generation_enabled
    assert value.ai_validation_budget_usd == Decimal('100')
    assert value.ai_validation_initial_budget_usd == Decimal('5')

@pytest.mark.parametrize('extra', [
    {'ai_validation_budget_usd':'101'},
    {'ai_validation_initial_budget_usd':'101'},
    {'ai_validation_initial_budget_usd':'NaN'},
    {'ai_validation_budget_usd':'0'},
    {'ai_validation_budget_usd':'1','ai_validation_initial_budget_usd':'2'},
    {'ai_real_calls_enabled':True},
    {'ai_real_calls_enabled':True,'openai_api_key':'test','dev_ai_enabled':True,'app_env':'local'},
    {'ai_real_calls_enabled':True,'openai_api_key':'test','openai_caption_model':'unpriced-model'},
])
def test_real_ai_fails_closed(extra):
    with pytest.raises(ValidationError): Settings(database_url=DB,**extra)

def test_real_ai_capability_and_secret_safe_repr():
    value=Settings(database_url=DB,ai_real_calls_enabled=True,openai_api_key='test-secret')
    assert value.generation_enabled
    assert 'test-secret' not in repr(value)
    assert Settings(database_url=DB,app_env='local',dev_ai_enabled=True).generation_enabled

@pytest.mark.asyncio
async def test_real_capability_does_not_claim_fake_output(tmp_path):
    import httpx
    from backend.main import create_app
    settings=Settings(database_url=DB,ai_real_calls_enabled=True,openai_api_key='test-secret',storage_root=tmp_path)
    app=create_app(settings=settings)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            data=(await client.get('/api/dev/config')).json()['data']
            assert data['generation_enabled'] is True
            assert data['generation_mode']=='openai'
            assert data['dev_ai_enabled'] is False
            assert 'test-secret' not in str(data)

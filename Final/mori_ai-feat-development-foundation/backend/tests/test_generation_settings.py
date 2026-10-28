import pytest
from pydantic import ValidationError
from backend.settings import Settings

DB = 'postgresql+asyncpg://mori:local@postgres/mori_workflow_test'


def test_fake_ai_default_disabled_and_local_only():
    assert Settings(database_url=DB).dev_ai_enabled is False
    assert Settings(database_url=DB, app_env='local', dev_ai_enabled=True).dev_ai_enabled is True
    for env in ['test','production']:
        with pytest.raises(ValidationError):
            Settings(database_url=DB,app_env=env,dev_ai_enabled=True)

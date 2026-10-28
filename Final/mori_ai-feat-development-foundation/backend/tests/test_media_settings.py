import pytest
from pydantic import ValidationError
from backend.settings import Settings


def test_media_environment_is_validated_and_loaded(monkeypatch):
    monkeypatch.setenv('NORMALIZED_MAX_EDGE', '2048')
    monkeypatch.setenv('NORMALIZED_MAX_BYTES', '1048576')
    monkeypatch.setenv('THUMBNAIL_WEBP_QUALITY', '75')
    settings = Settings(database_url='postgresql+asyncpg://localhost/test')
    assert settings.normalized_max_edge == 2048
    assert settings.normalized_max_bytes == 1048576
    assert settings.thumbnail_webp_quality == 75


@pytest.mark.parametrize('name,value', [
    ('NORMALIZED_MAX_EDGE', '3'), ('NORMALIZED_MAX_EDGE', '16384'),
    ('NORMALIZED_MAX_BYTES', '0'), ('NORMALIZED_WEBP_QUALITY', '0'),
    ('NORMALIZED_WEBP_QUALITY', '101'),
    ('THUMBNAIL_WEBP_QUALITY', '101'), ('RESULT_WEBP_QUALITY', '0'),
    ('THUMBNAIL_MAX_EDGE', '481'),
])
def test_invalid_media_environment_fails_startup(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError):
        Settings(database_url='postgresql+asyncpg://localhost/test')


def test_normalization_defaults_and_legacy_override():
    settings = Settings(database_url='postgresql+asyncpg://localhost/test')
    assert settings.normalized_webp_lossless is False
    assert settings.normalized_webp_quality == 90
    assert Settings(database_url='postgresql+asyncpg://localhost/test', normalized_webp_lossless=True).normalized_webp_lossless is True

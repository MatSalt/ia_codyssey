from app import config


def test_custom_gateway_configuration(monkeypatch):
    monkeypatch.setattr(config, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "story-analytics-assistant")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://copa.codyssey.kr/v1")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5-mini")
    monkeypatch.setenv("OPENAI_API_KEY", "test-virtual-key")
    settings = config.get_settings()
    assert settings.openai_base_url == "https://copa.codyssey.kr/v1"
    assert settings.openai_model == "gpt-5-mini"
    assert settings.firebase_project_id == "story-analytics-assistant"
    assert settings.openai_api_key == "test-virtual-key"
    assert "test-virtual-key" not in repr(settings)


def test_missing_gateway_url_is_optional(monkeypatch):
    monkeypatch.setattr(config, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    assert config.get_settings().openai_base_url is None

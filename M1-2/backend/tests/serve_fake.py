"""Loopback-only test server with in-memory data and synthetic GPT answers.

Used by frontend npm run test:integration; never loads local .env credentials
or initializes Firestore/OpenAI clients. Not a production entry point.
"""
from pathlib import Path
from unittest.mock import patch

from fastapi.staticfiles import StaticFiles
from app import config
from flow_fakes import MemoryData, MemoryConversations, SummaryGateway


def create_fake_app():
    # Patch before importing the module-level app as well as creating our app.
    with patch.object(config, 'get_settings', return_value=config.Settings(allowed_origins=())):
        from app.main import create_app
        app = create_app()
    from app.dependencies import get_data_repository, get_conversation_repository, get_chat_gateway
    data, conversations, gateway = MemoryData(), MemoryConversations(), SummaryGateway()
    app.dependency_overrides.update({
        get_data_repository: lambda: data,
        get_conversation_repository: lambda: conversations,
        get_chat_gateway: lambda: gateway,
    })
    dist = Path(__file__).resolve().parents[2] / 'frontend' / 'dist'
    app.mount('/', StaticFiles(directory=dist, html=True), name='test-frontend')
    return app

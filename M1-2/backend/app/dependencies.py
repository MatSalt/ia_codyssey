"""Lazy external boundaries; tests override providers without loading credentials."""
from functools import lru_cache
from uuid import uuid4

from .config import get_settings
from .ports import ChatGateway, ConversationRepository, DataRepository, GenerationUnavailable, StorageUnavailable


@lru_cache(maxsize=4)
def _build_firestore_client(project_id: str, credential_path: str):
    from firebase_admin import credentials, firestore, initialize_app
    certificate = credentials.Certificate(credential_path)
    firebase_app = initialize_app(certificate, {"projectId": project_id}, name=f"story-analytics-{uuid4().hex}")
    return firestore.client(app=firebase_app)


def get_data_repository() -> DataRepository:
    settings = get_settings()
    if not settings.firebase_project_id or not settings.google_application_credentials:
        raise StorageUnavailable("Data storage is not configured")
    try:
        from .data.repository import FirestoreDataRepository
        client = _build_firestore_client(settings.firebase_project_id, settings.google_application_credentials)
        return FirestoreDataRepository(client)
    except Exception:
        raise StorageUnavailable("Storage is temporarily unavailable.") from None


def get_conversation_repository() -> ConversationRepository:
    settings = get_settings()
    if not settings.firebase_project_id or not settings.google_application_credentials:
        raise StorageUnavailable("Conversation storage is not configured")
    try:
        from .conversations.repository import FirestoreConversationRepository
        client = _build_firestore_client(settings.firebase_project_id, settings.google_application_credentials)
        return FirestoreConversationRepository(client)
    except Exception:
        raise StorageUnavailable("Storage is temporarily unavailable.") from None


class _LazyChatGateway:
    def complete(self, system, messages):
        client = None
        try:
            settings = get_settings()
            if not settings.openai_api_key or not settings.openai_model:
                raise GenerationUnavailable("Answer generation is not configured")
            from openai import OpenAI
            from .chat.gateway import OpenAIChatGateway
            client = OpenAI(api_key=settings.openai_api_key,
                            base_url=settings.openai_base_url,
                            timeout=settings.openai_timeout_seconds,
                            max_retries=settings.openai_max_retries)
            return OpenAIChatGateway(client, settings.openai_model,
                                     settings.openai_max_output_tokens).complete(system, messages)
        except Exception:
            raise GenerationUnavailable("Answer generation is temporarily unavailable.") from None
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass


def get_chat_gateway() -> ChatGateway:
    return _LazyChatGateway()

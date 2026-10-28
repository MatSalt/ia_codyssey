"""Synchronous boundaries shared by services and external adapters."""
from typing import Protocol
from .models import Conversation, ConversationCreate, ConversationListItem, MessageInput, Record, RecordCreate, RecordUpdate


class DuplicateRecord(Exception):
    pass


class NotFound(Exception):
    pass


class StorageUnavailable(Exception):
    pass


class GenerationUnavailable(Exception):
    pass


class DataRepository(Protocol):
    def list_records(self) -> list[Record]: ...
    def create(self, record: RecordCreate) -> Record: ...
    def update(self, record_id: str, patch: RecordUpdate) -> Record: ...
    def delete(self, record_id: str) -> None: ...


class ConversationRepository(Protocol):
    def create(self, payload: ConversationCreate) -> Conversation: ...
    def list_conversations(self) -> list[ConversationListItem]: ...
    def get(self, conversation_id: str) -> Conversation: ...
    def append_turn(self, conversation_id: str, question: str, answer: str) -> Conversation: ...
    def delete(self, conversation_id: str) -> None: ...


class ChatGateway(Protocol):
    def complete(self, system: str, messages: list[MessageInput]) -> str: ...

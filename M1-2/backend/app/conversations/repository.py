"""Conversation persistence with atomic, retryable turn appends."""
from datetime import datetime, timezone
from google.api_core.exceptions import FailedPrecondition, NotFound as SDKNotFound
from google.cloud.firestore_v1 import transactional
from ..models import Conversation, ConversationListItem, Message
from ..ports import NotFound, StorageUnavailable


def valid_id(key):
    if not key or '/' in key or key in ('.', '..') or len(key.encode('utf-8')) > 1500:
        raise NotFound()


class FirestoreConversationRepository:
    def __init__(self, client):
        self.client = client
        self.collection = client.collection('conversations')

    def create(self, payload):
        try:
            now = datetime.now(timezone.utc)
            ref = self.collection.document()
            item = Conversation(id=ref.id, title=payload.title, created_at=now, updated_at=now,
                                messages=[Message(**m.model_dump(), created_at=now) for m in payload.messages])
            ref.create(item.model_dump(exclude={'id'}), retry=None, timeout=10)
            return item
        except Exception:
            raise StorageUnavailable('Storage is temporarily unavailable.') from None

    def list_conversations(self):
        try:
            items = [Conversation(id=s.id, **s.to_dict()) for s in self.collection.stream(retry=None, timeout=10)]
            return [ConversationListItem(**c.model_dump(exclude={'messages'}))
                    for c in sorted(items, key=lambda c: c.updated_at, reverse=True)]
        except Exception:
            raise StorageUnavailable('Storage is temporarily unavailable.') from None

    def get(self, conversation_id):
        valid_id(conversation_id)
        try:
            snapshot = self.collection.document(conversation_id).get(retry=None, timeout=10)
            if not snapshot.exists:
                raise NotFound()
            return Conversation(id=snapshot.id, **snapshot.to_dict())
        except NotFound:
            raise
        except Exception:
            raise StorageUnavailable('Storage is temporarily unavailable.') from None

    def append_turn(self, conversation_id, question, answer):
        valid_id(conversation_id)
        try:
            ref = self.collection.document(conversation_id)
            transaction = self.client.transaction(max_attempts=3)
            @transactional
            def append(tx):
                snapshot = ref.get(transaction=tx, retry=None, timeout=10)
                if not snapshot.exists:
                    raise NotFound()
                item = Conversation(id=snapshot.id, **snapshot.to_dict())
                now = datetime.now(timezone.utc)
                item.messages.extend([Message(role='user', content=question, created_at=now),
                                      Message(role='assistant', content=answer, created_at=now)])
                item.updated_at = now
                tx.update(ref, {'messages': [m.model_dump() for m in item.messages], 'updated_at': now})
                return item
            return append(transaction)
        except (NotFound, SDKNotFound, FailedPrecondition):
            raise NotFound() from None
        except Exception:
            raise StorageUnavailable('Storage is temporarily unavailable.') from None

    def delete(self, conversation_id):
        valid_id(conversation_id)
        try:
            self.collection.document(conversation_id).delete(
                option=self.client.write_option(exists=True), retry=None, timeout=10)
        except (SDKNotFound, FailedPrecondition):
            raise NotFound() from None
        except Exception:
            raise StorageUnavailable('Storage is temporarily unavailable.') from None

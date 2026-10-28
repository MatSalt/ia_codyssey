"""In-memory external boundaries for integrated API/browser verification only."""
from datetime import datetime, timezone
from uuid import uuid4
import json
from app.models import Conversation, ConversationListItem, Message, Record
from app.ports import DuplicateRecord, NotFound

class MemoryData:
    def __init__(self): self.rows = {}
    def list_records(self): return sorted(self.rows.values(), key=lambda r: r.date)
    def create(self, record):
        key = record.date.isoformat()
        if key in self.rows: raise DuplicateRecord()
        self.rows[key] = Record(id=key, **record.model_dump())
        return self.rows[key]
    def update(self, key, patch):
        if key not in self.rows: raise NotFound()
        self.rows[key] = Record(id=key, date=key, **patch.model_dump())
        return self.rows[key]
    def delete(self, key):
        if key not in self.rows: raise NotFound()
        del self.rows[key]

class MemoryConversations:
    def __init__(self): self.rows = {}
    def create(self, payload):
        now = datetime.now(timezone.utc)
        result = Conversation(id=uuid4().hex, title=payload.title, created_at=now, updated_at=now,
            messages=[Message(**m.model_dump(), created_at=now) for m in payload.messages])
        self.rows[result.id] = result
        return result
    def get(self, key):
        if key not in self.rows: raise NotFound()
        return self.rows[key]
    def list_conversations(self):
        return [ConversationListItem(**r.model_dump(exclude={'messages'})) for r in
            sorted(self.rows.values(), key=lambda r: r.updated_at, reverse=True)]
    def append_turn(self, key, question, answer):
        record = self.get(key)
        now = datetime.now(timezone.utc)
        record.messages.extend([Message(role='user',content=question,created_at=now), Message(role='assistant',content=answer,created_at=now)])
        record.updated_at = now
        return record
    def delete(self, key):
        self.get(key)
        del self.rows[key]

class SummaryGateway:
    def __init__(self): self.calls = []
    def complete(self, system, messages):
        summary = json.loads(system.split('\nSUMMARY_JSON\n')[1])
        self.calls.append((summary, messages))
        return f"합성 검증 답변: 총 {summary['metrics']['total']}회입니다."

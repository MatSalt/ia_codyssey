"""External-boundary test doubles; never imported by production code."""
from dataclasses import dataclass, field
from app.models import MessageInput, Record


@dataclass
class FakeDataRepository:
    records: list[Record] = field(default_factory=list)

    def list_records(self) -> list[Record]:
        return sorted(self.records, key=lambda record: record.date)


@dataclass
class FakeChatGateway:
    answer: str = 'Synthetic test answer'
    calls: list[tuple[str, list[MessageInput]]] = field(default_factory=list)

    def complete(self, system: str, messages: list[MessageInput]) -> str:
        self.calls.append((system, list(messages)))
        return self.answer

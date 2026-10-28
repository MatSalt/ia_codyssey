from ..models import Record, RecordCreate, RecordUpdate
from ..ports import DataRepository


class DataService:
    def __init__(self, repo: DataRepository):
        self.repo = repo

    def list_records(self) -> list[Record]:
        return sorted(self.repo.list_records(), key=lambda record: record.date)

    def create(self, record: RecordCreate) -> Record:
        return self.repo.create(record)

    def update(self, record_id: str, patch: RecordUpdate) -> Record:
        return self.repo.update(record_id, patch)

    def delete(self, record_id: str) -> None:
        self.repo.delete(record_id)

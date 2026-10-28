"""Firestore adapter with bounded RPCs and atomic existence checks."""
from google.api_core.exceptions import AlreadyExists, FailedPrecondition, NotFound as SDKNotFound
from ..models import Record, RecordCreate, RecordUpdate
from ..ports import DuplicateRecord, NotFound, StorageUnavailable


class FirestoreDataRepository:
    def __init__(self, client):
        self.client = client
        self.collection = client.collection('data')

    def list_records(self) -> list[Record]:
        try:
            records = [Record(id=s.id, **s.to_dict()) for s in self.collection.stream(retry=None, timeout=10)]
            if any(record.id != record.date.isoformat() for record in records):
                raise ValueError('Stored record date does not match document ID')
            return sorted(records, key=lambda r: r.date)
        except Exception:
            raise StorageUnavailable('Storage is temporarily unavailable.') from None

    def create(self, record: RecordCreate) -> Record:
        key = record.date.isoformat()
        try:
            self.collection.document(key).create(record.model_dump(mode='json'), retry=None, timeout=10)
        except AlreadyExists:
            raise DuplicateRecord() from None
        except Exception:
            raise StorageUnavailable('Storage is temporarily unavailable.') from None
        return Record(id=key, **record.model_dump())

    def update(self, record_id: str, patch: RecordUpdate) -> Record:
        try:
            self.collection.document(record_id).update(patch.model_dump(), retry=None, timeout=10)
        except SDKNotFound:
            raise NotFound() from None
        except Exception:
            raise StorageUnavailable('Storage is temporarily unavailable.') from None
        return Record(id=record_id, date=record_id, **patch.model_dump())

    def delete(self, record_id: str) -> None:
        try:
            # Enforce existence in the write itself, including concurrent deletes.
            self.collection.document(record_id).delete(option=self.client.write_option(exists=True), retry=None, timeout=10)
        except (SDKNotFound, FailedPrecondition):
            raise NotFound() from None
        except Exception:
            raise StorageUnavailable('Storage is temporarily unavailable.') from None

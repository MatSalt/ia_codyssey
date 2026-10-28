"""SDK doubles isolate all Firestore RPCs; no credentials are loaded."""
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from google.api_core.exceptions import AlreadyExists, NotFound as SDKNotFound, ServiceUnavailable
from app.models import RecordCreate, RecordUpdate
from app.ports import DuplicateRecord, NotFound, StorageUnavailable
from app.data.repository import FirestoreDataRepository


@pytest.fixture
def sdk():
    client = Mock()
    document = client.collection.return_value.document.return_value
    return client, document, FirestoreDataRepository(client)


def test_atomic_duplicate(sdk):
    client, document, repo = sdk
    payload = RecordCreate(date='2026-01-02', value=5)
    assert repo.create(payload).model_dump(mode='json') == {'id': '2026-01-02', 'date': '2026-01-02', 'value': 5, 'memo': ''}
    client.collection.assert_called_with('data')
    document.create.assert_called_once_with({'date': '2026-01-02', 'value': 5, 'memo': ''}, retry=None, timeout=10)
    document.get.assert_not_called()
    document.create.side_effect = AlreadyExists('secret')
    with pytest.raises(DuplicateRecord):
        repo.create(payload)


def test_sorted_records(sdk):
    client, _, repo = sdk
    client.collection.return_value.stream.return_value = [SimpleNamespace(id=d, to_dict=lambda d=d: {'date':d, 'value':2, 'memo':''}) for d in ['2026-01-03', '2026-01-01']]
    assert [r.id for r in repo.list_records()] == ['2026-01-01', '2026-01-03']


def test_update_no_upsert_and_missing_mapping(sdk):
    _, document, repo = sdk
    patch = RecordUpdate(value=9, memo='new')
    assert repo.update('2026-01-02', patch).value == 9
    document.update.assert_called_once_with({'value':9, 'memo':'new'}, retry=None, timeout=10)
    document.set.assert_not_called()
    document.update.side_effect = SDKNotFound('secret')
    with pytest.raises(NotFound):
        repo.update('2026-01-02', patch)


def test_delete_has_atomic_existence_precondition(sdk):
    client, document, repo = sdk
    repo.delete('2026-01-02')
    client.write_option.assert_called_once_with(exists=True)
    document.delete.assert_called_once_with(option=client.write_option.return_value, retry=None, timeout=10)
    document.get.assert_not_called()
    document.delete.side_effect = SDKNotFound('secret')
    with pytest.raises(NotFound):
        repo.delete('2026-01-02')


@pytest.mark.parametrize('operation', ['list', 'create', 'update', 'delete'])
def test_storage_failures_are_safe(sdk, operation):
    client, document, repo = sdk
    target = client.collection.return_value.stream if operation == 'list' else getattr(document, operation)
    target.side_effect = ServiceUnavailable('private-key-secret')
    with pytest.raises(StorageUnavailable) as error:
        if operation == 'list': repo.list_records()
        elif operation == 'create': repo.create(RecordCreate(date='2026-01-02', value=1))
        elif operation == 'update': repo.update('2026-01-02', RecordUpdate(value=1, memo=''))
        else: repo.delete('2026-01-02')
    assert 'private-key-secret' not in str(error.value)


def test_delete_serializes_existence_precondition_without_network():
    # Real SDK serialization verifies that the fake's accepted option matches
    # the wire contract; only the commit transport is replaced.
    from google.auth.credentials import AnonymousCredentials
    from google.cloud.firestore_v1 import Client
    client = Client(project='synthetic-test-project', credentials=AnonymousCredentials())
    transport = Mock()
    client._firestore_api_internal = transport
    FirestoreDataRepository(client).delete('2026-01-02')
    request = transport.commit.call_args.kwargs['request']
    write = request['writes'][0]
    assert write.current_document.exists is True
    assert write.delete.endswith('/data/2026-01-02')


def test_delete_failed_existence_precondition_maps_to_not_found(sdk):
    from google.api_core.exceptions import FailedPrecondition
    _, document, repo = sdk
    document.delete.side_effect = FailedPrecondition('missing private document')
    with pytest.raises(NotFound):
        repo.delete('2026-01-02')


def test_inconsistent_stored_document_is_unavailable(sdk):
    client, _, repo = sdk
    client.collection.return_value.stream.return_value = [SimpleNamespace(id='2026-01-01', to_dict=lambda: {'date':'2026-01-02','value':2,'memo':''})]
    with pytest.raises(StorageUnavailable):
        repo.list_records()

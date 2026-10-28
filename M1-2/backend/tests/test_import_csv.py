"""Synthetic fixtures protect validation-before-write and restart behavior."""
from pathlib import Path
from unittest.mock import Mock
import pytest
from app.models import Record, RecordCreate
from app.ports import DuplicateRecord, StorageUnavailable


def importer():
    from scripts import import_csv
    return import_csv


def csv_file(tmp_path, body):
    path = tmp_path / 'synthetic.csv'
    path.write_text(body, encoding='utf-8-sig')
    return path


def test_bom_and_integer_count_parse(tmp_path):
    records = importer().parse_csv(csv_file(tmp_path, 'date,value,memo\n2026-01-01,12,hello\n'))
    assert records == [RecordCreate(date='2026-01-01', value=12, memo='hello')]


@pytest.mark.parametrize('body', [
    'date,value,memo\n2026-01-01,2,ok\n2026-02-30,3,bad\n',
    'date,value,memo\n2026-01-01,2,ok\n2026-01-01,3,duplicate\n',
    'date,value,memo\n2026-01-01,1.0,bad\n',
    'date,value,memo\n2026-01-01,-1,bad\n',
    'date,value,memo\n2026-01-01,true,bad\n',
    'date,value,memo\n2026-01-01,1,ok,extra\n',
    'date,value,value\n2026-01-01,1,2\n',
    'date,value\n2026-01-01,1\n',
    'date,value,memo\n2026-01-01,1\n',
])
def test_invalid_csv_never_writes(tmp_path, body):
    repo = Mock()
    with pytest.raises(ValueError):
        importer().import_records(importer().parse_csv(csv_file(tmp_path, body)), repo)
    assert repo.create.call_count == 0


def test_import_validates_entire_input_before_writing():
    repo = Mock()
    with pytest.raises(ValueError):
        importer().import_records([RecordCreate(date='2026-01-01', value=2), {'date': 'bad', 'value': 3}], repo)
    assert repo.create.call_count == 0


def test_restart_skips_existing_and_preserves_values():
    class Repository:
        def __init__(self):
            self.rows = {'2026-01-01': Record(id='2026-01-01', date='2026-01-01', value=99)}
        def create(self, record):
            key = record.date.isoformat()
            if key in self.rows:
                raise DuplicateRecord()
            self.rows[key] = Record(id=key, **record.model_dump())
            return self.rows[key]
    repo = Repository()
    records = [RecordCreate(date='2026-01-01', value=1), RecordCreate(date='2026-01-02', value=2)]
    first = importer().import_records(records, repo)
    second = importer().import_records(records, repo)
    assert (first.created, first.skipped) == (1, 1)
    assert (second.created, second.skipped) == (0, 2)
    assert repo.rows['2026-01-01'].value == 99


def test_storage_failure_reports_only_completed_counts_without_sensitive_error():
    repo = Mock()
    repo.create.side_effect = [None, DuplicateRecord(), StorageUnavailable('secret credential')]
    records = [RecordCreate(date=f'2026-01-0{i}', value=i) for i in range(1, 5)]
    with pytest.raises(importer().ImportFailed) as error:
        importer().import_records(records, repo)
    assert (error.value.result.created, error.value.result.skipped) == (1, 1)
    assert 'secret' not in str(error.value)
    assert repo.create.call_count == 3


def test_cli_dry_run_does_not_initialize_storage(tmp_path, monkeypatch, capsys):
    module = importer()
    monkeypatch.setattr(module, 'get_data_repository', Mock(side_effect=AssertionError('storage initialized')))
    assert module.main(['--file', str(csv_file(tmp_path, 'date,value,memo\n2026-01-01,4,\n')), '--dry-run']) == 0
    assert '1' in capsys.readouterr().out


def test_cli_storage_failure_exits_nonzero_and_reports_progress(tmp_path, monkeypatch, capsys):
    module = importer()
    repo = Mock()
    repo.create.side_effect = [None, RuntimeError('secret endpoint')]
    monkeypatch.setattr(module, 'get_data_repository', lambda: repo)
    assert module.main(['--file', str(csv_file(tmp_path, 'date,value,memo\n2026-01-01,4,\n2026-01-02,5,\n'))]) == 1
    error = capsys.readouterr().err
    assert 'created=1' in error and 'skipped=0' in error
    assert 'secret' not in error

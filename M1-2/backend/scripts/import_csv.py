"""Validate CSV fully before writes; existing dates are preserved."""
import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
import re
import sys
from app.dependencies import get_data_repository
from app.models import RecordCreate
from app.ports import DataRepository, DuplicateRecord


@dataclass(frozen=True)
class ImportResult:
    created: int = 0
    skipped: int = 0


class ImportFailed(RuntimeError):
    def __init__(self, result: ImportResult):
        self.result = result
        super().__init__(f'Import interrupted: created={result.created}, skipped={result.skipped}. Rerun to resume; existing dates are preserved.')


def _validated_records(records) -> list[RecordCreate]:
    validated = []
    dates = set()
    for index, record in enumerate(records, start=1):
        try:
            item = RecordCreate.model_validate(record.model_dump() if isinstance(record, RecordCreate) else record)
        except (ValueError, TypeError):
            raise ValueError(f'Invalid record at position {index}.') from None
        if item.date in dates:
            raise ValueError(f'Duplicate date at position {index}.')
        dates.add(item.date)
        validated.append(item)
    return validated


def parse_csv(path: Path) -> list[RecordCreate]:
    records = []
    try:
        with path.open(encoding='utf-8-sig', newline='') as stream:
            reader = csv.reader(stream, strict=True)
            if next(reader, None) != ['date', 'value', 'memo']:
                raise ValueError('CSV header must be date,value,memo.')
            for row in reader:
                if len(row) != 3 or re.fullmatch(r'[0-9]+', row[1]) is None:
                    raise ValueError(f'Invalid CSV row at line {reader.line_num}.')
                try:
                    records.append(RecordCreate(date=row[0], value=int(row[1]), memo=row[2]))
                except (ValueError, TypeError):
                    raise ValueError(f'Invalid CSV row at line {reader.line_num}.') from None
    except (csv.Error, UnicodeError):
        raise ValueError('Invalid CSV encoding or syntax.') from None
    return _validated_records(records)


def import_records(records: list[RecordCreate], repo: DataRepository) -> ImportResult:
    validated = _validated_records(records)
    created = skipped = 0
    for record in validated:
        try:
            repo.create(record)
        except DuplicateRecord:
            skipped += 1
        except Exception:
            raise ImportFailed(ImportResult(created, skipped)) from None
        else:
            created += 1
    return ImportResult(created, skipped)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--file', required=True, type=Path)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    try:
        records = parse_csv(args.file)
    except (ValueError, OSError):
        print('CSV validation failed; no records were written.', file=sys.stderr)
        return 1
    if args.dry_run:
        print(f'CSV valid: records={len(records)}; dry-run completed.')
        return 0
    try:
        repo = get_data_repository()
    except Exception:
        print(str(ImportFailed(ImportResult())), file=sys.stderr)
        return 1
    try:
        result = import_records(records, repo)
    except ImportFailed as error:
        print(str(error), file=sys.stderr)
        return 1
    print(f'Import complete: created={result.created}, skipped={result.skipped}.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

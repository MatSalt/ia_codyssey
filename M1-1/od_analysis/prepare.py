"""Stream immutable ZIPs; audit numeric cells/keys and aggregate to derived files."""
import argparse
import fcntl
import json
import time
import zipfile
import polars as pl
from .common import WORK, CACHE, ROOT, OUT, AUDIT, META, HOURS, COLS, VERSION, sha, write_json
from .references import prepare_regions


def collapse_keys(frame, keys):
    """Drop identical duplicates; exclude every conflicting row of a key."""
    unique = frame.unique(subset=keys + HOURS, maintain_order=True)
    identical = frame.height - unique.height
    conflicts = unique.select(keys).is_duplicated()
    return unique.filter(~conflicts), identical, int(conflicts.sum())


def aggregate(frame, key, scope, date):
    exprs = []
    for h in HOURS:
        exprs.extend([pl.when(pl.col(h).count() > 0).then(pl.col(h).sum()).otherwise(None).alias(h), pl.col(h).count().alias('n' + h[1:])])
    return frame.group_by(key).agg(exprs).rename({key: 'region'}).with_columns(pl.lit(date).alias('date'), pl.lit(scope).alias('scope'))


def process_day(content, expected, mapping):
    # Korean header was checked in acquisition; numeric body remains ASCII.
    body = content.split(b'\n', 1)[1]
    if not body.strip(): return None, {'rows': 0}
    frame = pl.read_csv(body, has_header=False, schema={c: pl.String if i < 3 else pl.Int64 for i, c in enumerate(COLS)}, null_values='')
    dates = frame['date'].unique().to_list()
    if sorted(dates) != sorted(expected) or len(dates) != 1: raise ValueError(f'Unexpected record dates {dates}')
    date = dates[0]
    stats = {'date': date, 'rows': frame.height, 'blank_hour_cells': int(frame.select(pl.col(HOURS).null_count()).to_numpy().sum()), 'numeric_hour_cells': int(frame.select(pl.col(HOURS).count()).to_numpy().sum()), 'raw_passenger_sum': int(frame.select(pl.col(HOURS).sum()).to_numpy().sum())}
    invalid = frame.select(pl.any_horizontal(pl.col(HOURS) < 0)).to_series().fill_null(False)
    stats['negative_rows'] = int(invalid.sum())
    valid_ids = frame['origin'].is_not_null() & frame['destination'].is_not_null()
    stats['null_id_rows'] = frame.height - int(valid_ids.sum())
    frame = frame.filter(valid_ids & ~invalid)
    frame, stats['identical_raw_duplicates_removed'], stats['conflicting_raw_rows_excluded'] = collapse_keys(frame, COLS[:3])
    frame = frame.join(mapping.rename({'raw_id': 'origin', 'region': 'o', 'stable_seoul_name': 'os'}), on='origin', how='left')
    frame = frame.join(mapping.rename({'raw_id': 'destination', 'region': 'd', 'stable_seoul_name': 'ds'}), on='destination', how='left')
    unmapped = frame['o'].is_null() | frame['d'].is_null()
    stats['unmapped_endpoint_rows'] = int(unmapped.sum())
    stats['unmapped_endpoint_passenger_sum'] = int(frame.filter(unmapped).select(pl.col(HOURS).sum()).to_numpy().sum())
    stats['unmapped_ids'] = sorted(set(frame.filter(pl.col('o').is_null())['origin'].to_list() + frame.filter(pl.col('d').is_null())['destination'].to_list()))
    frame = frame.with_columns(pl.coalesce('o', pl.concat_str(pl.lit('unmapped:'), 'origin')).alias('ok'), pl.coalesce('d', pl.concat_str(pl.lit('unmapped:'), 'destination')).alias('dk'))
    frame, stats['identical_alias_duplicates_removed'], stats['conflicting_alias_rows_excluded'] = collapse_keys(frame, ['date', 'ok', 'dk'])
    stable = frame.filter(pl.col('os').fill_null(False) & pl.col('ds').fill_null(False))
    internal = stable.filter(pl.col('o') != pl.col('d'))
    within = stable.filter(pl.col('o') == pl.col('d'))
    stats['internal_rows'] = internal.height
    stats['internal_passenger_sum'] = int(internal.select(pl.col(HOURS).sum()).to_numpy().sum())
    stats['within_passenger_sum'] = int(within.select(pl.col(HOURS).sum()).to_numpy().sum())
    stats['stable_regions_seen'] = sorted(set(stable['o'].to_list() + stable['d'].to_list()))
    inbound = aggregate(internal, 'd', 'internal_in', date)
    outbound = aggregate(internal, 'o', 'internal_out', date)
    a = inbound.select(pl.col(HOURS).sum()).to_numpy(); b = outbound.select(pl.col(HOURS).sum()).to_numpy()
    if (a != b).any() or int(a.sum()) != stats['internal_passenger_sum']: raise AssertionError('Inbound/outbound conservation failed')
    stats['conservation_passed'] = True
    exploratory = aggregate(frame.filter(pl.col('ds').fill_null(False)), 'd', 'all_origins_including_within', date)
    return pl.concat([inbound, outbound, exploratory]), stats


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--stamp'); args = parser.parse_args()
    AUDIT.mkdir(parents=True, exist_ok=True); (CACHE).mkdir(parents=True, exist_ok=True)
    lock = (AUDIT / 'prepare.lock').open('w'); fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    master = prepare_regions(); mapping = pl.DataFrame(master[['raw_id', 'region', 'stable_seoul_name']].to_dict(orient='list')); mapping_hash = sha(OUT / 'region_crosswalk.csv')
    records = json.loads((META / 'acquisition.json').read_text())['files']
    for index, spec in enumerate(records, 1):
        if args.stamp and spec['stamp'] != args.stamp: continue
        stamp = spec['stamp']; path = WORK / spec['path']; record = json.loads((WORK / spec['record']).read_text())
        audit_path = AUDIT / f'{stamp}.json'; product = CACHE / f'{stamp}.parquet'; start = time.monotonic()
        if sha(path) != spec['sha256']: raise ValueError(f'Raw hash changed: {stamp}')
        if audit_path.exists() and product.exists():
            old = json.loads(audit_path.read_text())
            if old.get('version') == VERSION and old.get('mapping_sha256') == mapping_hash and old.get('source_sha256') == spec['sha256'] and old.get('product_sha256') == sha(product):
                print('REUSED', stamp, flush=True); continue
        frames = []; days = []
        with zipfile.ZipFile(path) as z:
            for member in record['members']:
                data, stats = process_day(z.read(member['name']), member['dates'], mapping)
                if stats['rows'] != member['rows']: raise ValueError('Record count changed')
                stats['member'] = member['name']; days.append(stats)
                if data is not None: frames.append(data)
        pl.concat(frames).sort(['date', 'scope', 'region']).write_parquet(product, compression='zstd')
        write_json(audit_path, {'version': VERSION, 'stamp': stamp, 'source_sha256': spec['sha256'], 'mapping_sha256': mapping_hash, 'product_sha256': sha(product), 'missing_dates': record['missing_dates'], 'days': days, 'seconds': round(time.monotonic()-start, 2), 'status': 'complete'})
        print('DONE', index, '/', len(records), stamp, 'days', len(frames), 'seconds', round(time.monotonic()-start, 1), flush=True)

if __name__ == '__main__': main()

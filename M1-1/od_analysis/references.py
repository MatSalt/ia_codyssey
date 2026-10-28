"""Exact source-ID mapping and conservative historical name screening."""
import io
import json
import zipfile
import pandas as pd
from .common import WORK, CACHE, RAW, OUT, AUDIT, META, ROOT, sha, write_json


def prepare_regions():
    OUT.mkdir(parents=True, exist_ok=True)
    catalog = json.loads((ROOT/'data/sources/catalog.json').read_text())
    for source in catalog['files']:
        if source['path'].startswith('data/raw/locations/admin/'):
            assert sha(WORK/source['path']) == source['sha256'], 'Reference original hash changed'
    master = pd.read_csv(RAW / 'locations/admin/transit_admin_master_20261027.csv', encoding='cp949', dtype=str)
    master.columns = ['raw_id', 'dong', 'district', 'province']
    # Only explicitly listed raw IDs are aliases. Never append/remove a digit.
    master['region'] = master['province'] + '|' + master['district'] + '|' + master['dong']
    ambiguous = master.groupby('raw_id').region.nunique()
    ambiguous = ambiguous[ambiguous > 1].index.tolist()
    master = master[~master.raw_id.isin(ambiguous)].drop_duplicates('raw_id').copy()
    histories = []
    with zipfile.ZipFile(RAW / 'locations/admin/admin_codes.zip') as z:
        for name in z.namelist():
            if not name.endswith('.csv'):
                continue
            d = pd.read_csv(io.BytesIO(z.read(name)), dtype=str)
            d = d[d.SIDO_NM == '서울특별시'].copy()
            d['region'] = '서울|' + d.SGG_NM + '|' + d.ADMI_NM
            histories.append(d[['region', 'ADMI_CD', 'BASE_YM']])
    history = pd.concat(histories).drop_duplicates()
    periods = sorted(history.BASE_YM.unique())
    checks = history.groupby('region').agg(months=('BASE_YM', 'nunique'), historical_codes=('ADMI_CD', 'nunique'))
    stable = set(checks[(checks.months == len(periods)) & (checks.historical_codes == 1)].index)
    master['history_name_stable'] = master.region.isin(stable)
    exclusions_path = AUDIT / 'alias_panel_exclusions.json'
    exclusions = json.loads(exclusions_path.read_text())['excluded_regions'] if exclusions_path.exists() else []
    presence_path = AUDIT / 'presence_panel_exclusions.json'
    presence_exclusions = json.loads(presence_path.read_text())['excluded_regions'] if presence_path.exists() else []
    exclusions = sorted(set(exclusions) | set(presence_exclusions))
    master['stable_seoul_name'] = master.region.isin(stable) & ~master.region.isin(exclusions)
    master.to_csv(OUT / 'region_crosswalk.csv', index=False)
    history.to_csv(OUT / 'seoul_monthly_codes.csv', index=False)
    checks.to_csv(OUT / 'region_history_check.csv')
    write_json(AUDIT / 'region_reference.json', {
        'master_rows': 2270, 'mapped_unique_ids': len(master), 'ambiguous_ids_excluded': ambiguous,
        'history_months': periods, 'stable_seoul_regions': int(master[master.history_name_stable].region.nunique()),
        'analysis_panel_regions': int(master[master.stable_seoul_name].region.nunique()), 'panel_excluded_regions': exclusions,
        'aliases_rule': 'Only IDs explicitly attached to identical province/district/dong in official master',
        'different_code_systems': 'Transit IDs and monthly administrative codes joined by exact Seoul district + dong names, never by numeric conversion',
        'limit': 'Stable name/code is not a proof of identical historical boundaries. Reference ends 2026-08; Sep/Oct exploratory only.'
    })
    return master

if __name__ == '__main__':
    prepare_regions()

"""Identify regions whose officially mapped aliases coexist within an OD key.

Different alias keys might partition traffic or duplicate it. Without provenance,
exclude the affected region from the primary fixed panel for ALL periods.
"""
import json
import zipfile
import polars as pl
from .common import WORK, CACHE, ROOT, OUT, AUDIT, META, COLS, write_json

def main():
    mapping=pl.read_csv(OUT/'region_crosswalk.csv',schema_overrides={'raw_id':pl.String}).select('raw_id','region')
    all_regions=set(); evidence=[]
    for path in sorted(AUDIT.glob('20*.json')):
        a=json.loads(path.read_text()); candidates=[d for d in a['days'] if d.get('conflicting_alias_rows_excluded',0)+d.get('identical_alias_duplicates_removed',0)>0]
        if not candidates:continue
        source=json.loads((META/f"{a['stamp']}.json").read_text())
        with zipfile.ZipFile(WORK/source['path']) as z:
            for d in candidates:
                body=z.read(d['member']).split(b'\n',1)[1]
                f=pl.read_csv(body,has_header=False,columns=[0,1,2],schema={c:pl.String for c in COLS},null_values='')
                f=f.join(mapping.rename({'raw_id':'origin','region':'o'}),on='origin',how='left').join(mapping.rename({'raw_id':'destination','region':'d'}),on='destination',how='left')
                f=f.filter(pl.col('o').is_not_null() & pl.col('d').is_not_null())
                duplicates=f.filter(f.select(['o','d']).is_duplicated())
                grouped=duplicates.group_by(['o','d']).agg(pl.col('origin').n_unique().alias('origins'),pl.col('destination').n_unique().alias('destinations'))
                affected=set(grouped.filter(pl.col('origins')>1)['o'].to_list()+grouped.filter(pl.col('destinations')>1)['d'].to_list())
                all_regions.update(affected);evidence.append({'date':d['date'],'regions':sorted(affected)})
    write_json(AUDIT/'alias_panel_exclusions.json',{'excluded_regions':sorted(all_regions),'evidence':evidence,'rule':'Coexisting official aliases in the same daily canonical OD key; fixed exclusion across every year. This does not assert underlying records were duplicate passengers.'})
    print('EXCLUDE',sorted(all_regions),'days',len(evidence),flush=True)
if __name__=='__main__':main()

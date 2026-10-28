"""Independent stdlib CSV calculation, file provenance and artifact checks."""
import csv
import io
import json
import re
import zipfile
from datetime import datetime, timezone
import pandas as pd
import polars as pl
from .common import WORK, CACHE, ROOT, OUT, AUDIT, META, HOURS, sha, write_json


def independent_day(stamp, member, crosswalk):
    source=json.loads((META/f'{stamp}.json').read_text())
    sums=[0]*24; n=0; keys={}; conflicting=set()
    with zipfile.ZipFile(WORK/source['path']) as z:
        with io.TextIOWrapper(z.open(member['name']),encoding=member['encoding']) as f:
            reader=csv.reader(f);next(reader)
            for row in reader:
                n+=1
                if len(row)!=27:raise AssertionError('Wrong raw row width')
                o=crosswalk.get(row[1]);d=crosswalk.get(row[2])
                if not o or not d or not o[1] or not d[1] or o[0]==d[0]:continue
                values=tuple(int(v) if v else None for v in row[3:])
                if any(v is not None and v<0 for v in values):continue
                key=(row[0],o[0],d[0])
                if key in keys and keys[key]!=values:conflicting.add(key)
                else:keys[key]=values
    for key,values in keys.items():
        if key in conflicting:continue
        for h,v in enumerate(values):
            if v is not None:sums[h]+=v
    date=member['dates'][0]
    actual=pl.read_parquet(CACHE/f'{stamp}.parquet').filter((pl.col('date')==date)&(pl.col('scope')=='internal_in')).select(pl.col(HOURS).sum()).row(0)
    assert list(actual)==sums,(date,sums,actual)
    assert n==member['rows']
    return {'date':date,'rows':n,'sum':sum(sums),'hour_totals_equal':True,'source_sha256':source['sha256']}


def main():
    mapping=pd.read_csv(OUT/'region_crosswalk.csv',dtype={'raw_id':str})
    crosswalk={r.raw_id:(r.region,r.stable_seoul_name) for r in mapping.itertuples()}
    checked=[]
    for stamp in ['202301','202404','202501','202601']:
        r=json.loads((META/f'{stamp}.json').read_text())
        member=next(m for m in r['members'] if m['rows']>0)
        checked.append(independent_day(stamp,member,crosswalk))
    state=json.loads((META/'acquisition.json').read_text()); sources=[]
    for spec in state['files']:
        a=json.loads((AUDIT/f"{spec['stamp']}.json").read_text())
        assert a['source_sha256']==sha(WORK/spec['path'])
        assert a['product_sha256']==sha(CACHE/f"{spec['stamp']}.parquet")
        assert a['mapping_sha256']==sha(OUT/'region_crosswalk.csv')
        sources.append(spec['stamp'])
    catalog=json.loads((ROOT/'data/sources/catalog.json').read_text())
    reference_checks=0
    for source in catalog['files']:
        if source['path'].startswith('data/raw/') and 'transit_hourly_od/' not in source['path']:
            assert sha(WORK/source['path'])==source['sha256']
            reference_checks+=1
    day=pd.read_csv(OUT/'daily_city.csv');assert day.observed.sum()>=100 and (~day.observed).sum()==24
    assert day.loc[~day.observed,'internal_passenger_sum'].isna().all()
    assert day.loc[~day.observed,'rolling_28d'].isna().all()
    assert not day.date.duplicated().any()
    report=(ROOT/'REPORT.md').read_text();images=re.findall(r'!\[[^]]*\]\(([^)]+)\)',report)
    assert len(images)>=3 and all((ROOT/p).is_file() for p in images)
    broken=[]
    for target in re.findall(r'\]\(([^)]+)\)',report):
        if not target.startswith(('https://','http://','#')) and not (ROOT/target.split('#')[0]).exists():broken.append(target)
    assert not broken,broken
    import PIL.Image
    dimensions={}
    for p in images:
        with PIL.Image.open(ROOT/p) as im:im.verify()
        with PIL.Image.open(ROOT/p) as im:dimensions[p]=list(im.size)
    documents = ['README.md', 'REPORT.md']
    for name in documents:
        document = ROOT/name
        for target in re.findall(r'\]\(([^)]+)\)', document.read_text()):
            if target.startswith(('https://', 'http://', '#')):
                continue
            assert (document.parent/target.split('#')[0]).exists(), (name, target)
    write_json(AUDIT/'final_verification.json',{'passed':True,'independent_csv_checks':checked,'unchanged_raw_zip_hashes':len(sources),
        'unchanged_reference_hashes':reference_checks,'derived_hashes_verified':len(sources),'missing_dates_preserved_as_null':24,'report_images':dimensions,'broken_report_links':broken,
        'verified_at_utc':datetime.now(timezone.utc).isoformat(),
        'report_sha256':sha(ROOT/'REPORT.md'),
        'figure_sha256':{p:sha(ROOT/p) for p in images},
        'current_document_links_checked':documents,
        'scope':'Verifies implementation and artifact consistency, not official collection completeness or causal conclusions.'})
    print('PASS: 4 independent daily/hourly checks, 66 raw + derived hashes, missing dates, report images/links',flush=True)

if __name__=='__main__':main()

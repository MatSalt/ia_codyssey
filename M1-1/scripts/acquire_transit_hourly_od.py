"""Acquire OA-21226 originals, inspect ZIP contents without extracting to disk.

Checks every record's date; preserves blanks and does not aggregate passenger
values. Numeric-cell and duplicate OD-key audits belong to the analysis stage.
"""
import os
import calendar
import csv
import fcntl
import hashlib
import io
import json
import re
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import pandas as pd

PROJECT=Path(__file__).resolve().parents[1]
ROOT=Path(os.environ.get('B3_OD_WORKDIR', PROJECT.parent/'tmp/B3-1-work')).expanduser().resolve()
META=ROOT/'data/metadata/transit_hourly_od'
RAW=ROOT/'data/raw/transit_hourly_od'
URL='https://datafile.seoul.go.kr/bigfile/iot/inf/nio_download.do?&useCache=false'
PAGE='https://data.seoul.go.kr/dataList/OA-21226/F/1/datasetView.do'
COLUMNS=['기준_날짜','시작_행정동_ID','종료_행정동_ID']+[f'승객_수_{h:02d}' for h in range(24)]

def save(path,obj):
    part=path.with_suffix('.json.tmp');part.write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n');part.replace(path)

def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def acquire(spec):
    stamp=spec['stamp'];dest=RAW/stamp[:4]/spec['filename'];dest.parent.mkdir(parents=True,exist_ok=True)
    record=META/(stamp+'.json');params={'infId':'OA-21226','infSeq':'1','seq':spec['seq']}
    if record.exists() and dest.exists():
        old=json.loads(record.read_text())
        if old.get('validation_status')=='passed' and sha(dest)==old['sha256']:return old
    if not dest.exists():
        part=dest.with_suffix('.zip.part')
        for attempt in range(3):
            try:
                with urlopen(Request(URL,data=urlencode(params).encode()),timeout=120) as resp, part.open('wb') as f:
                    length=resp.headers.get('Content-Length');size=0
                    while block:=resp.read(4*1024*1024):
                        if size==0 and block[:2]!=b'PK':raise ValueError('Response is not ZIP')
                        f.write(block);size+=len(block)
                if length and size!=int(length):raise ValueError('Incomplete download')
                if not zipfile.is_zipfile(part):raise ValueError('Invalid ZIP')
                part.replace(dest);break
            except Exception:
                part.unlink(missing_ok=True)
                if attempt==2:raise
                time.sleep(2)
    print('DOWNLOADED',stamp,dest.stat().st_size,flush=True)
    dates=set();rows=0;members=[];headers=[];ids=set()
    with zipfile.ZipFile(dest) as z:
        for info in z.infolist():
            if info.is_dir():continue
            if not info.filename.lower().endswith('.csv'):raise ValueError('Unexpected non-CSV member')
            with z.open(info) as f:first=f.readline()
            try:first.decode('utf-8-sig');enc='utf-8-sig'
            except UnicodeDecodeError:enc='cp949'
            header=next(csv.reader(io.StringIO(first.decode(enc))))
            raw_header=header.copy()
            if header[0]=='?\"기준_날짜\"':header[0]='기준_날짜'
            if header!=COLUMNS:raise ValueError(f'Schema change: {info.filename}: {header}')
            count=0;actual=set();null_ids=0;null_dates=0
            # Reading until EOF also verifies each member CRC via ZipExtFile.
            with z.open(info) as f:
                for c in pd.read_csv(f,encoding=enc,dtype=str,header=0,names=COLUMNS,usecols=COLUMNS[:3],chunksize=250000):
                    count+=len(c);actual.update(c[COLUMNS[0]].dropna().unique().tolist())
                    null_ids+=int(c[COLUMNS[1:3]].isna().to_numpy().sum());null_dates+=int(c[COLUMNS[0]].isna().sum())
                    ids.update(c[COLUMNS[1]].dropna().unique().tolist());ids.update(c[COLUMNS[2]].dropna().unique().tolist())
            if null_dates:raise ValueError(f'Missing date: {info.filename}')
            for d in actual:
                datetime.strptime(d,'%Y%m%d')
                if not d.startswith(stamp):raise ValueError(f'Date {d} outside {stamp}')
            rows+=count;dates.update(actual)
            members.append({'name':info.filename,'bytes_uncompressed':info.file_size,'crc32':f'{info.CRC:08x}','encoding':enc,'rows':count,'dates':sorted(actual),'header_only':count==0,'null_od_identifier_cells':null_ids,'raw_header_anomaly':raw_header if raw_header!=COLUMNS else None})
    if len(stamp)==6:
        expected={stamp+f'{i:02d}' for i in range(1,calendar.monthrange(int(stamp[:4]),int(stamp[4:]))[1]+1)}
    else:expected={stamp}
    result={**spec,'path':str(dest.relative_to(ROOT)),'source_url':PAGE,'download_url':URL,'post_parameters':params,'bytes':dest.stat().st_size,'sha256':sha(dest),'columns':COLUMNS,'rows':rows,'observed_days':len(dates),'observed_dates':sorted(dates),'missing_dates':sorted(expected-dates),'members':members,'area_ids':sorted(ids),'zip_crc_full_read':True,'validation_status':'passed','validation_scope':'full ZIP CRC, SHA256, all CSV headers, every record date; null OD identifiers counted and preserved; passenger numeric cells and duplicate keys not yet audited','time_basis':'unconfirmed event; label as source-reported hour','mode_scope':'bus and subway combined; no per-mode columns','checked_at':datetime.now(timezone.utc).isoformat()}
    save(record,result);print('VERIFIED',stamp,count if len(members)==1 else rows,'days',len(dates),'missing',len(expected-dates),flush=True)
    return result

def main():
    META.mkdir(parents=True,exist_ok=True)
    lock=(META/'acquire.lock').open('w')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    specs=json.loads((PROJECT/'data/sources/inventory.json').read_text());results={};errors=[]
    # Inspect one month per year early, then the remaining files.
    specs.sort(key=lambda x:(x['stamp'] not in ['202301','202401','202501','202601'],x['stamp']))
    status=META/'acquisition.json'
    def progress():
        files=sorted(results.values(),key=lambda x:x['stamp'])
        expected=pd.date_range('2023-01-01','2026-10-21').strftime('%Y%m%d').tolist()
        present={d for r in files for d in r['observed_dates']}
        save(status,{'status':'complete' if len(files)==len(specs) and not errors else 'running' if len(files)+len(errors)<len(specs) else 'incomplete','expected_files':len(specs),'verified_files':len(files),'bytes':sum(r['bytes'] for r in files),'rows':sum(r['rows'] for r in files),'observed_days':len(present),'target_start':'2023-01-01','target_end':'2026-10-21','missing_dates_final_only':sorted(set(expected)-present) if len(files)==len(specs) else None,'files':[{'stamp':r['stamp'],'path':r['path'],'bytes':r['bytes'],'sha256':r['sha256'],'observed_days':r['observed_days'],'rows':r['rows'],'record':str((META/(r['stamp']+'.json')).relative_to(ROOT))} for r in files],'errors':errors,'checked_at':datetime.now(timezone.utc).isoformat()})
    progress()
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs={pool.submit(acquire,s):s for s in specs}
        for job in as_completed(jobs):
            spec=jobs[job]
            try:results[spec['stamp']]=job.result()
            except Exception as e:errors.append({'stamp':spec['stamp'],'error':str(e)});print('ERROR',spec['stamp'],str(e),flush=True)
            progress()
    print('FINISHED',len(results),'errors',errors,flush=True)

if __name__=='__main__':main()

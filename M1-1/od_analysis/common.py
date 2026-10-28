from pathlib import Path
import os
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
WORK = Path(os.environ.get('B3_OD_WORKDIR', ROOT.parent / 'tmp/B3-1-work')).expanduser().resolve()
RAW = WORK / 'data/raw'
OUT = ROOT / 'data/tables'
CACHE = WORK / 'data/processed/transit_od/months'
EVIDENCE = ROOT / 'data/evidence'
AUDIT = WORK / 'outputs/od_validation'
FIG = ROOT / 'figures'
META = WORK / 'data/metadata/transit_hourly_od'
HOURS = [f'h{h:02}' for h in range(24)]
COLS = ['date', 'origin', 'destination'] + HOURS
VERSION = 'od-v1'

def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(path.suffix + '.tmp')
    part.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    part.replace(path)
    # Only report evidence is delivered; per-file audit/cache stays outside submission.
    published = {'analysis_summary.json', 'region_reference.json', 'calendar_sources.json',
                 'presence_panel_exclusions.json', 'final_verification.json'}
    if path.parent == AUDIT and path.name in published:
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        (EVIDENCE/path.name).write_bytes(path.read_bytes())

def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

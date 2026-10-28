"""Freeze the geographic panel to regions actually observed on every source day."""
import json
import pandas as pd
from .common import OUT, AUDIT, META, write_json

def main():
    files=json.loads((META/'acquisition.json').read_text())['files']
    sets=[]; days=[]
    for f in files:
        a=json.loads((AUDIT/f"{f['stamp']}.json").read_text())
        for d in a['days']:
            if d['rows']:sets.append(set(d['stable_regions_seen']));days.append(d['date'])
    common=set.intersection(*sets)
    master=pd.read_csv(OUT/'region_crosswalk.csv')
    candidate=set(master.loc[master.history_name_stable,'region'])
    aliases=set(json.loads((AUDIT/'alias_panel_exclusions.json').read_text())['excluded_regions'])
    excluded=candidate-common-aliases
    write_json(AUDIT/'presence_panel_exclusions.json',{'excluded_regions':sorted(excluded),'common_regions':sorted(common-aliases),
        'observed_dates':len(days),'rule':'Fixed exclusion across all years if no eligible movement endpoint on any observed source date; absence not treated as zero.',
        'note':'A region being present does not prove that every OD pair or hour was completely collected.'})
    print('Presence exclusions',len(excluded),'common panel',len(common-aliases),flush=True)
if __name__=='__main__':main()

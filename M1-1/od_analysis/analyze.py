"""Derive comparison tables with explicit denominators and missing-day handling."""
import json
import numpy as np
import pandas as pd
import polars as pl
from .common import WORK, CACHE, ROOT, OUT, AUDIT, META, HOURS, write_json, sha
from .calendar import prepare_calendar

FOCUS = ['서울|중구|명동', '서울|마포구|서교동', '서울|성동구|성수2가3동', '서울|용산구|한남동']
WINDOWS = {'weekday_morning': (list(range(7,10)), list(range(5))), 'weekend_day': (list(range(10,22)), [5,6]), 'weekend_core': (list(range(12,20)), [5,6])}


def standardize(frame, period, months, year, excluded=None):
    """Equal month×weekday weighting; no comparison if a required stratum absent."""
    part = frame[(frame.year == year) & frame.month.isin(months) & frame.regular].copy()
    if excluded: part = part[~part.date.isin(excluded)]
    outputs = []
    for window, (hours, weekdays) in WINDOWS.items():
        d = part[part.weekday.isin(weekdays)]
        strata = d.groupby(['scope','region','month','weekday'])[window].agg(['mean','count']).reset_index()
        for (scope, region), g in strata.groupby(['scope','region']):
            expected = len(months) * len(weekdays)
            eligible = len(g) == expected and int(g['count'].min()) >= 2
            outputs.append({'period':period,'scope':scope,'region':region,'window':window,'strata':len(g),'expected_strata':expected,
                            'min_days_per_stratum':int(g['count'].min()),'observed_days':int(g['count'].sum()),
                            'value':float(g['mean'].mean()) if eligible else np.nan,'eligible':eligible})
    return pd.DataFrame(outputs)


def make_comparisons(table):
    frames=[]
    for a,b,label in [('2023','2025','2023_to_2025'),('2024','2025','2024_to_2025'),('2025_JanAug','2026_JanAug','2025_to_2026_JanAug')]:
        keys=['scope','region','window']
        left=table[table.period==a].rename(columns={'value':'base','eligible':'base_eligible'})
        right=table[table.period==b].rename(columns={'value':'current','eligible':'current_eligible'})
        merged=left[keys+['base','base_eligible']].merge(right[keys+['current','current_eligible']],on=keys,validate='one_to_one')
        merged['comparison']=label
        merged['pct_change']=np.where(merged.base_eligible & merged.current_eligible & (merged.base>0),100*(merged.current/merged.base-1),np.nan)
        frames.append(merged)
    return pd.concat(frames,ignore_index=True)


def main():
    calendar=prepare_calendar()
    state=json.loads((META/'acquisition.json').read_text()); audits=[]
    for spec in state['files']:
        record=json.loads((AUDIT/f"{spec['stamp']}.json").read_text())
        assert record['status']=='complete' and record['source_sha256']==spec['sha256']
        assert record['mapping_sha256']==sha(OUT/'region_crosswalk.csv'), 'Mixed panel versions: rerun prepare'
        audits += [dict(day,stamp=spec['stamp']) for day in record['days'] if day['rows']]
    day=pd.DataFrame(audits).drop(columns=['stable_regions_seen','unmapped_ids','member'])
    assert not day.date.duplicated().any()
    day=calendar.merge(day,on='date',how='left',validate='one_to_one')
    day['observed']=day.rows.notna()
    day['blank_fraction']=day.blank_hour_cells/(day.blank_hour_cells+day.numeric_hour_cells)
    # Flag unusual city-wide days; retain them in baseline, compare exclusion separately.
    ref=day[day.regular & day.observed].groupby(['year','month','weekday'])[['internal_passenger_sum','rows']].median().rename(columns={'internal_passenger_sum':'same_weekday_median','rows':'row_median'})
    day=day.merge(ref,on=['year','month','weekday'],how='left',validate='many_to_one')
    day['ratio_to_peer']=day.internal_passenger_sum/day.same_weekday_median
    day['review_flag']=day.regular & day.observed & ((day.ratio_to_peer<.35)|(day.ratio_to_peer>2.5)|(day.rows/day.row_median<.5))
    day['rolling_28d']=pd.Series(day.internal_passenger_sum.to_numpy(),index=pd.to_datetime(day.date,format='%Y%m%d')).rolling('28D',min_periods=28).mean().to_numpy()
    day.to_csv(OUT/'daily_city.csv',index=False)
    day[~day.observed].to_csv(OUT/'missing_dates.csv',index=False)
    day[day.review_flag].to_csv(OUT/'review_days.csv',index=False)
    paths=[CACHE/f"{s['stamp']}.parquet" for s in state['files']]
    data=pl.scan_parquet(paths)
    # Windows require every regional hour aggregate, rather than fill missing hours.
    expr=[pl.sum_horizontal([pl.col(f'h{h:02}') for h in hours],ignore_nulls=False).truediv(len(hours)).alias(name) for name,(hours,_) in WINDOWS.items()]
    values=data.filter(pl.col('scope')!='internal_out').select(['date','scope','region']+expr).collect()
    window=pd.DataFrame(values.to_dict(as_series=False)).merge(calendar,on='date',validate='many_to_one')
    window[window.region.isin(FOCUS)].to_csv(OUT/'focus_daily_windows.csv',index=False)
    periods=[('2023',list(range(1,13)),2023),('2024',list(range(1,13)),2024),('2025',list(range(1,13)),2025),('2025_JanAug',list(range(1,9)),2025),('2026_JanAug',list(range(1,9)),2026)]
    standardized=pd.concat([standardize(window,*p) for p in periods],ignore_index=True)
    standardized.to_csv(OUT/'standardized_windows.csv',index=False)
    comparisons=make_comparisons(standardized);comparisons.to_csv(OUT/'comparisons.csv',index=False)
    flagged=set(day.loc[day.review_flag,'date'])
    sensitivity=pd.concat([standardize(window,*p,excluded=flagged) for p in periods],ignore_index=True)
    make_comparisons(sensitivity).to_csv(OUT/'comparisons_excluding_review_days.csv',index=False)
    # Monthly equal-weekday means, observed whole-city internal totals.
    monthly=(day[day.regular & day.observed].groupby(['year','month','weekday']).internal_passenger_sum.mean().groupby(['year','month']).mean().reset_index(name='weekday_standardized_mean'))
    monthly.to_csv(OUT/'monthly_city.csv',index=False)
    focus=data.filter(pl.col('region').is_in(FOCUS)).select(['date','region','scope']+HOURS).collect()
    focus_pd=pd.DataFrame(focus.to_dict(as_series=False)).merge(calendar,on='date',validate='many_to_one')
    profile=focus_pd[(focus_pd.year==2025)&focus_pd.regular].groupby(['region','scope','weekday'])[HOURS].mean().reset_index()
    profile.to_csv(OUT/'focus_2025_hour_profile.csv',index=False)
    profile_counts=focus_pd[(focus_pd.year==2025)&focus_pd.regular].groupby(['region','scope','weekday'])[HOURS].count().reset_index()
    profile_counts.to_csv(OUT/'focus_2025_hour_profile_counts.csv',index=False)
    # Unweighted weekday profile is descriptive, not a tourist classification.
    annual=day.groupby('year').agg(observed_days=('observed','sum'),raw_rows=('rows','sum'),raw_passenger_sum=('raw_passenger_sum','sum'),
        primary_passenger_sum=('internal_passenger_sum','sum'),null_id_rows=('null_id_rows','sum'),unknown_endpoint_rows=('unmapped_endpoint_rows','sum'),
        unknown_endpoint_sum=('unmapped_endpoint_passenger_sum','sum'),blank_cells=('blank_hour_cells','sum'),numeric_cells=('numeric_hour_cells','sum'),review_days=('review_flag','sum'))
    annual['blank_cell_fraction']=annual.blank_cells/(annual.blank_cells+annual.numeric_cells)
    annual['unmapped_passenger_fraction']=annual.unknown_endpoint_sum/annual.raw_passenger_sum
    annual.to_csv(OUT/'annual_quality.csv')
    # Actual observed presence, supplementing name history (not a boundary proof).
    sets=[set(x['stable_regions_seen']) for x in audits]
    common=set.intersection(*sets); union=set.union(*sets)
    write_json(AUDIT/'analysis_summary.json',{
        'original_files':len(state['files']),'raw_rows':int(day.rows.sum()),'observed_days':int(day.observed.sum()),'missing_days':int((~day.observed).sum()),
        'common_regions_every_day':sorted(common),'regions_missing_some_days':sorted(union-common),
        'negative_rows':int(day.negative_rows.sum()),'identical_raw_duplicates_removed':int(day.identical_raw_duplicates_removed.sum()),
        'conflicting_raw_rows_excluded':int(day.conflicting_raw_rows_excluded.sum()),'identical_alias_duplicates_removed':int(day.identical_alias_duplicates_removed.sum()),
        'conflicting_alias_rows_excluded':int(day.conflicting_alias_rows_excluded.sum()),'review_dates':sorted(flagged),
        'all_conservation_checks_passed':bool(day.loc[day.observed,'conservation_passed'].all()),
        'numeric_parse':'Every nonblank hourly cell strictly parsed to Int64; invalid text would stop processing',
        'scope':'Primary: stable-name Seoul-to-Seoul inter-dong movements; exploratory: all origins including within-dong',
        'missing_cell_interpretation':'Known-value sums only. Blank cells not asserted to be zeros. Null hours remain null; incomplete windows excluded.'})
    print('Analyzed',int(day.observed.sum()),'days;',len(common),'regions seen every day;',len(flagged),'review dates',flush=True)

if __name__=='__main__':main()

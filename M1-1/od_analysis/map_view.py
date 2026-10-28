"""Build a standalone district map from the verified fixed-panel OD cache."""
import argparse
import json
import calendar
from datetime import datetime, timezone

import pandas as pd
import polars as pl

from .analyze import WINDOWS
from .common import ROOT, OUT, CACHE, AUDIT, EVIDENCE, HOURS, sha

TABLE = OUT / 'map_monthly.csv'
BOUNDARY = ROOT / 'data/sources/seoul_districts_20250630.geojson'


def prepare_table():
    """Sum fixed-panel dongs by district before weekday standardization.

    All panel dongs must have all hours in a window. A missing dong/hour
    invalidates that district-day, rather than reducing its denominator.
    Within-district inter-dong journeys remain included; not district-border OD.
    """
    panel = json.loads((EVIDENCE / 'analysis_summary.json').read_text())['common_regions_every_day']
    expected = pd.Series([r.split('|')[1] for r in panel]).value_counts().to_dict()
    inventory = json.loads((ROOT / 'data/sources/inventory.json').read_text())
    frames = []
    for item in inventory:
        stamp = item['stamp']
        p = CACHE / f'{stamp}.parquet'
        audit = json.loads((AUDIT / f'{stamp}.json').read_text())
        assert audit['product_sha256'] == sha(p), f'Changed cache: {stamp}'
        assert audit['mapping_sha256'] == sha(OUT / 'region_crosswalk.csv')
        frame = pl.read_parquet(p).filter(pl.col('scope').is_in(['internal_in', 'internal_out']))
        assert set(frame['region'].unique()) <= set(panel)
        frames.append(frame.select(['date', 'region', 'scope'] + HOURS))
    data = pl.concat(frames)
    assert not data.select(['date', 'scope', 'region']).is_duplicated().any()
    expressions = [pl.sum_horizontal([pl.col(f'h{h:02}') for h in hours], ignore_nulls=False)
                   .truediv(len(hours)).alias(name)
                   for name, (hours, _) in WINDOWS.items() if name != 'weekend_core']
    values = pd.DataFrame(data.select(['date', 'region', 'scope'] + expressions).to_dict(as_series=False))
    values['district'] = values.region.str.split('|', regex=False).str[1]
    cal = pd.read_csv(OUT / 'calendar.csv', dtype={'date': str})
    result = []
    for window in ['weekday_morning', 'weekend_day']:
        day = values.groupby(['date', 'scope', 'district'])[window].agg(['sum', 'count']).reset_index()
        day.loc[day['count'] != day.district.map(expected), 'sum'] = float('nan')
        day = day.merge(cal, on='date', validate='many_to_one')
        day = day[day.regular & day.weekday.isin(WINDOWS[window][1]) & (day.date <= '20260831')]
        strata = day.groupby(['year', 'month', 'scope', 'district', 'weekday'])['sum'].agg(['mean', 'count']).reset_index()
        for (year, month, scope, district), g in strata.groupby(['year', 'month', 'scope', 'district']):
            eligible = len(g) == len(WINDOWS[window][1]) and g['count'].min() >= 2
            result.append(dict(year=int(year), month=int(month), scope=scope, district=district,
                               window=window, value=float(g['mean'].mean()) if eligible else None,
                               eligible=bool(eligible), min_days=int(g['count'].min()),
                               days=int(g['count'].sum()), panel_dongs=int(expected[district])))
    table = pd.DataFrame(result).sort_values(['year', 'month', 'scope', 'district', 'window'])
    assert not table.duplicated(['year', 'month', 'scope', 'district', 'window']).any()
    assert len(expected) == 25 and sum(expected.values()) == 398
    table.to_csv(TABLE, index=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--from-tables', action='store_true')
    args = parser.parse_args()
    if not args.from_tables:
        prepare_table()
    table = pd.read_csv(TABLE)
    boundary = json.loads(BOUNDARY.read_text())
    source = json.loads((ROOT / 'data/sources/map_boundary_source.json').read_text())
    assert sha(BOUNDARY) == source['derived_sha256']
    assert set(table.district) == {f['properties']['name'] for f in boundary['features']}
    dates = pd.read_csv(OUT / 'daily_city.csv', dtype={'date': str})
    coverage = {}
    for (year, month), g in dates.groupby(['year', 'month']):
        coverage[f'{year}-{month:02}'] = dict(observed=int(g.observed.sum()),
            expected=calendar.monthrange(int(year), int(month))[1],
            missing=g.loc[~g.observed, 'date'].tolist())
    payload = dict(rows=json.loads(table.to_json(orient='records')), geometry=boundary,
                   coverage=coverage, boundary_source=source['source_url'])
    template = (ROOT / 'od_analysis/map_template.html').read_text()
    html = template.replace('__PAYLOAD__', json.dumps(payload, ensure_ascii=False, allow_nan=False).replace('</', '<\\/'))
    (ROOT / 'MAP.html').write_text(html)
    preview(table, boundary)
    evidence = dict(generated_at_utc=datetime.now(timezone.utc).isoformat(), monthly_rows=len(table),
        districts=25, panel_dongs=398, period='2023-01..2026-08',
        boundary_sha256=sha(BOUNDARY), table_sha256=sha(TABLE), html_sha256=sha(ROOT/'MAP.html'),
        preview_sha256=sha(ROOT/'figures/05_map_change.png'),
        method='District-day sums of complete fixed-panel dong windows; equal weekday/month weighting, at least 2 days per stratum.',
        missing_policy='Any missing panel dong/hour invalidates district-day window; unavailable periods grey, never zero-filled.',
        meaning='Destination/origin district of inter-dong journeys within the fixed Seoul panel; includes journeys inside the same district. Time attribution unconfirmed.')
    (EVIDENCE / 'map_verification.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2)+'\n')
    print('MAP.html:', len(table), 'monthly values; 25 districts, 398 panel dongs')


def preview(table, boundary):
    """Static scientific preview of the same monthly table, with fixed color scale."""
    import numpy as np
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon
    from matplotlib.colors import LinearSegmentedColormap, Normalize
    from matplotlib import font_manager
    names = {f.name for f in font_manager.fontManager.ttflist}
    font = next((f for f in ['AppleGothic', 'NanumGothic', 'Malgun Gothic'] if f in names), 'DejaVu Sans')
    plt.rcParams.update({'font.family':font, 'axes.unicode_minus':False})
    cmap = LinearSegmentedColormap.from_list('change', ['#416ea2','#f2f4f3','#09755b'])
    norm = Normalize(-50,50,clip=True)
    fig,axes = plt.subplots(1,2,figsize=(14,7),facecolor='#f2f5f2')
    specs = [(2023,2025,list(range(1,13)),'2023 → 2025 · 연간'),(2025,2026,[8],'2025 → 2026 · 8월')]
    base = table[(table.scope=='internal_in') & (table.window=='weekend_day')]
    for ax,(a,b,months,title) in zip(axes,specs):
        part = base[base.month.isin(months)]
        grouped = part.groupby(['district','year']).agg(value=('value','mean'),valid=('eligible','sum'),n=('value','count'))
        changes = {}
        for district in table.district.unique():
            pair=[grouped.loc[(district,y)] for y in [a,b]]
            changes[district] = (pair[1].value/pair[0].value-1)*100 if all(r.valid==len(months) and r.n==len(months) for r in pair) and pair[0].value>0 else None
        for f in boundary['features']:
            name=f['properties']['name'];v=changes[name]
            polygons=[f['geometry']['coordinates']] if f['geometry']['type']=='Polygon' else f['geometry']['coordinates']
            for polygon in polygons:
                xy=np.asarray(polygon[0]);xy[:,0]*=np.cos(np.deg2rad(37.55))
                ax.add_patch(Polygon(xy,facecolor=cmap(norm(v)) if v is not None else '#d2d8d8',edgecolor='white',linewidth=1))
            xy=np.asarray(max(polygons,key=lambda p:len(p[0]))[0]);xy[:,0]*=np.cos(np.deg2rad(37.55))
            cross=xy[:-1,0]*xy[1:,1]-xy[1:,0]*xy[:-1,1]
            center=((xy[:-1]+xy[1:])*cross[:,None]).sum(axis=0)/(3*cross.sum())
            ax.text(*center,name+'\n'+(f'{v:+.1f}%' if v is not None else '비교 불가'),ha='center',va='center',fontsize=7.5,color='#183942')
        ax.autoscale_view();ax.set_aspect('equal');ax.axis('off');ax.set_title(title,fontsize=18,pad=16,color='#183942')
    fig.suptitle('서울 자치구별 주말 10–22시 지역행 관측 이동량 변화',fontsize=22,y=.97,color='#183942')
    fig.subplots_adjust(top=.84,bottom=.21,left=.03,right=.97,wspace=.06)
    bar=fig.colorbar(plt.cm.ScalarMappable(norm=norm,cmap=cmap),cax=fig.add_axes([.33,.14,.34,.018]),orientation='horizontal',extend='both')
    bar.set_ticks([-50,-25,0,25,50],labels=['-50%','-25%','0','+25%','+50%'])
    fig.text(.5,.05,'398개 고정 패널 동 사이 이동 · 구 내부 동 간 이동 포함 · 관광객 수 아님\n월·요일 동일 가중치 / 공휴일 제외 / 회색: 비교 기준 미달 / 2025-06-30 경계 표시',ha='center',fontsize=10,color='#536970')
    fig.savefig(ROOT/'figures/05_map_change.png',dpi=150,facecolor=fig.get_facecolor())
    plt.close(fig)


if __name__ == '__main__':
    main()

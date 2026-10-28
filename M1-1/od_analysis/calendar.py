"""Calendar derived from preserved KASI tables plus identified official updates."""
from datetime import date, timedelta
import html
import re
import pandas as pd
from .common import RAW, OUT, AUDIT, write_json

SUPPLEMENTS = {
 '20230529': ('부처님오신날 대체공휴일', 'https://www.mpm.go.kr/mpm/comm/newsPress/newsPressRelease/?cntId=3625&mode=view'),
 '20231002': ('임시공휴일', 'https://www.korea.kr/news/policyNewsView.do?newsId=148919605'),
 '20241001': ('임시공휴일', 'https://www.korea.kr/news/policyNewsView.do?newsId=148933400'),
 '20250127': ('임시공휴일', 'https://www.korea.kr/news/policyNewsView.do?newsId=148938559'),
 '20250603': ('대통령선거일', 'https://www.mois.go.kr/frt/bbs/type010/commonSelectBoardArticle.do?bbsId=BBSMSTR_000000000008&nttId=116942'),
 '20260501': ('노동절', 'https://www.mpm.go.kr/mpm/comm/newsPress/newsPressRelease/?cntId=4250&mode=view'),
 '20260717': ('제헌절', 'https://www.mpm.go.kr/mpm/comm/newsPress/newsPressRelease/?cntId=4250&mode=view'),
}


def prepare_calendar():
    named = {}; tables = {}
    for year in range(2023, 2027):
        text = (RAW / 'calendar' / f'calendar_data_{year}.html').read_text(encoding='utf-8-sig')
        start = re.search(r'<h2[^>]*>국경일과 공휴일</h2>', text)
        if not start: raise ValueError(f'Calendar table missing {year}')
        table = text[start.end():text.find('</table>', start.end())]
        cells = [html.unescape(re.sub('<[^>]+>', ' ', v)).strip() for v in re.findall(r'<td[^>]*>(.*?)</td>', table, re.S)]
        dates = []
        for name, value in zip(cells[::2], cells[1::2]):
            if '제헌절' in name and value.startswith('*'): continue
            pairs = re.findall(r'(\d+)월\s*(\d+)일', value)
            if not pairs: continue
            first, last = date(year, *map(int, pairs[0])), date(year, *map(int, pairs[-1]))
            if not 0 <= (last-first).days <= 3: raise ValueError('Unexpected holiday range')
            for offset in range((last-first).days+1):
                key = (first+timedelta(days=offset)).strftime('%Y%m%d'); named[key] = name; dates.append(key)
        tables[str(year)] = dates
    named.update({d: x[0] for d, x in SUPPLEMENTS.items()})
    rows = []
    for d in pd.date_range('2023-01-01', '2026-10-21'):
        key = d.strftime('%Y%m%d')
        special = d.month == 5 and d.day == 1 and d.year < 2026
        rows.append({'date': key, 'year': d.year, 'month': d.month, 'weekday': d.day_of_week,
                     'holiday': key in named, 'special_day': special, 'holiday_name': named.get(key, ''),
                     'regular': key not in named and not special,
                     'day_type': 'holiday' if key in named else 'special' if special else 'weekend' if d.day_of_week >= 5 else 'weekday'})
    frame = pd.DataFrame(rows); OUT.mkdir(parents=True, exist_ok=True)
    frame.to_csv(OUT / 'calendar.csv', index=False)
    write_json(AUDIT / 'calendar_sources.json', {'kasi_tables': tables, 'supplements': SUPPLEMENTS,
        'method': 'KASI preserved official calendar pages + subsequent official notices. May 1 in 2023-2025 is an analytical special day, not a general public holiday.',
        'limit': 'Does not classify school vacation, weather, local events, or private workplace holidays.'})
    return frame

if __name__ == '__main__': prepare_calendar()

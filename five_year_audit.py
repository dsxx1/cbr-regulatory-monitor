"""Read-only source collection with explicit coverage boundaries and free LLM audit."""
import argparse
import json
from collections import Counter
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from html import escape
from pathlib import Path

import sources
from industry_history import collect_industry
from free_llm import FreeAnalyzer


def parse_date(value):
    for fmt in ('%d.%m.%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(value[:10], fmt).date()
        except ValueError:
            pass
    try:
        return parsedate_to_datetime(value).date()
    except (TypeError, ValueError):
        return None


def collect_history(start, end, max_pages=80):
    records, coverage = {}, []
    for tag, title in sources.NA_TOPICS:
        seen, reached, stop = set(), None, 'page_cap'
        for page in range(max_pages):
            try:
                raw = sources._fetch(f'{sources.NA_PAGE_URL}?TagId={tag}&Date.Time=Any&Page={page}', 30)
                chunk = sources._parse_acts_page(raw.decode('utf-8'), tag, title)
            except Exception as exc:
                stop = type(exc).__name__
                break
            fresh = [d for d in chunk if d.key not in seen]
            if not fresh:
                stop = 'empty_or_repeated_page_requires_review'
                break
            seen.update(d.key for d in fresh)
            dates = [parse_date(d.published) for d in fresh]
            valid = [d for d in dates if d]
            reached = str(min(valid)) if valid else reached
            for doc, published in zip(fresh, dates):
                if published and start <= published <= end:
                    records.setdefault(doc.key, doc.as_dict())
            if valid and len(valid) == len(fresh) and max(valid) < start:
                stop = 'crossed_start_date'
                break
            if len(chunk) < 10:
                stop = 'last_page'
                break
        coverage.append({'source': title, 'pages': page + 1, 'records_scanned': len(seen),
                         'oldest_page_date': reached, 'stop': stop})
        print(f'{title}: {len(seen)}, {stop}', flush=True)
    for cat in sources.EXPLAIN_CATEGORIES:
        try:
            docs = sources.fetch_explains(cat, 30)
            for doc in docs:
                modified = parse_date(doc.modification)
                if modified and start <= modified <= end:
                    records[doc.key] = doc.as_dict()
            coverage.append({'source': f'explain:{cat}', 'count': len(docs),
                             'stop': 'current_records_not_version_history'})
        except Exception as exc:
            coverage.append({'source': f'explain:{cat}', 'stop': type(exc).__name__})
    return list(records.values()), coverage


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', default='out/five-year-audit')
    parser.add_argument('--as-of', default=date.today().isoformat())
    parser.add_argument('--llm-calls', type=int, default=3)
    parser.add_argument('--reuse-records', action='store_true', help='Reuse collected public records; repeat LLM checks only')
    parser.add_argument('--reuse-analysis', action='store_true', help='Keep model evidence; refresh industry records only')
    args = parser.parse_args()
    end = date.fromisoformat(args.as_of)
    start = end.replace(year=end.year - 5, day=min(end.day, 28) if end.month == 2 else end.day)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.reuse_records:
        records = json.loads((out / 'records.json').read_text(encoding='utf-8'))
        coverage = json.loads((out / 'audit.json').read_text(encoding='utf-8'))['coverage']
    else:
        records, coverage = collect_history(start, end)
    records = [d for d in records if not d['source'].startswith('industry-')]
    coverage = [c for c in coverage if c['source'] not in ('СРО', 'Лига ломбардов')]
    industry, industry_coverage = collect_industry(start, end)
    records.extend(industry)
    records = list({d['key']:d for d in records}.values())
    coverage.extend(industry_coverage)
    # Save collected evidence before any optional model processing.
    (out / 'records.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
    model = FreeAnalyzer(max_calls=max(0, args.llm_calls))
    sample = sorted(records, key=lambda d: (d['source'] != 'cbr-explain', -len(d['body'])))
    analyses = []
    if args.reuse_analysis:
        old = json.loads((out/'audit.json').read_text(encoding='utf-8'))
        analyses = old['analyses']
        model.receipts, model.errors = old['llm_receipts'], old['llm_errors']
        model.rejected_claims = old['rejected_claims']
    else:
        for doc in sample[:model.max_calls]:
            result = model.analyze(doc['title'] + '\n' + doc['body'])
            analyses.append({'key': doc['key'], 'analysis': result})
    evidence = {'start': str(start), 'end': str(end), 'count': len(records),
                'source_counts': dict(Counter(d['source'] for d in records)),
                'coverage': coverage, 'analyses': analyses, 'llm_receipts': model.receipts,
                'llm_errors': model.errors, 'rejected_claims': model.rejected_claims,
                'limits': ['Legal acts: metadata collected; full PDF bodies not processed.',
                           'Explain API: current text and modification date, not all historical versions.',
                           'SRO: current window only. Liga: visible dates used; undated items excluded. Rosfinmonitoring/pravo archives not included.']}
    (out / 'audit.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
    rows = ''.join('<tr><td>' + escape(d['published'] or d['modification']) + '</td><td>' +
                   escape(d['source_title']) + '</td><td><a href="' + escape(d['url'], quote=True) + '">' +
                   escape(d['title']) + '</a></td></tr>' for d in records)
    page = '<!doctype html><meta charset="utf-8"><title>Ретроспектива регулирования</title><style>body{font:16px system-ui;max-width:1200px;margin:32px auto}td{padding:10px;border-bottom:1px solid #ddd}a{color:#164d9d}</style>'
    page += f'<h1>Регулирование: {start} — {end}</h1><p>Найдено {len(records)} уникальных записей. Сбор без отправки в Б24.</p>'
    page += '<p>Это реестр найденных материалов, а не полный архив законодательства. Для актов ЦБ собраны реквизиты, полные PDF не проанализированы. Дата правки разъяснения не равна дате вступления нормы в силу. СРО: только текущее окно новостей. Лига: открытая архивная страница; использованы видимые даты, материалы без распознанной даты исключены.</p>'
    page += '<h2>Проверка бесплатной модели</h2><p>Выборка: '+str(len(analyses))+' документов. Результаты — предложения модели; совпадение цитаты не доказывает юридическую правильность вывода.</p>'
    for item in analyses:
        doc = next(d for d in records if d['key'] == item['key'])
        page += '<h3>'+escape(doc['title'])+'</h3>'
        if not item['analysis']:
            page += '<p>Ответ не прошёл проверку.</p>'
            continue
        for requirement in item['analysis'].get('requirements', []):
            page += '<p>'+escape(requirement['text'])+'</p><blockquote>'+escape(requirement['citation'])+'</blockquote>'
    page += '<h2>Реестр источников</h2><table>'+rows+'</table>'
    (out / 'index.html').write_text(page, encoding='utf-8')
    print(json.dumps({'count': len(records), 'coverage': coverage, 'llm_calls': model.calls,
                      'llm_ok': sum(bool(x['analysis']) for x in analyses), 'errors': model.errors}, ensure_ascii=False))


if __name__ == '__main__':
    main()

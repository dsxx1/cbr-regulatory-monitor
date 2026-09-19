"""Public industry pages. Coverage is measured, never assumed complete."""
import re
import hashlib
from datetime import date
from sources import _fetch, normalize_text

MONTHS = dict(zip(('января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря'), range(1,13)))


def visible_date(text):
    match = re.search(r'\b(\d{1,2})\s+('+'|'.join(MONTHS)+r')\s+(20\d{2})\b', text[:120], re.I)
    if not match:
        return None
    try:
        return date(int(match[3]), MONTHS[match[2].lower()], int(match[1]))
    except ValueError:
        return None


def collect_industry(start, end):
    records, coverage = [], []
    url = 'https://www.ligalomb.ru/index-text.htm'
    try:
        raw = _fetch(url, 30).decode('cp1251')
        raw = re.sub(r'<!--.*?-->', '', raw, flags=re.S)
        anchors = list(re.finditer(r'<a\s+name="(\d{4}-\d{2}-\d{2}[^"<>]*)"[^>]*>', raw, re.I))
        dates = []
        unknown_dates = 0
        for i, match in enumerate(anchors):
            try:
                published = date.fromisoformat(match[1][:10])
            except ValueError:
                continue
            anchor_date = published
            block = raw[match.end():anchors[i+1].start() if i+1 < len(anchors) else len(raw)]
            block = re.sub(r'<(script|style)\b[^>]*>.*?</\1>', '', block, flags=re.S|re.I)
            text = normalize_text(block)
            published = visible_date(text)
            if published is None:
                unknown_dates += 1
                continue
            dates.append(published)
            if not start <= published <= end:
                continue
            fingerprint = hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]
            records.append({'key': 'liga:' + match[1] + ':' + fingerprint, 'source': 'industry-liga',
                'source_title': 'Лига ломбардов (отраслевой источник)', 'published': str(published),
                'modification': '', 'title': text[:230], 'body': text, 'url': url+'#'+match[1],
                'date_basis': 'visible date', 'anchor_date':str(anchor_date),
                'date_mismatch':anchor_date != published})
        coverage.append({'source':'Лига ломбардов', 'count':len(records),
            'oldest_page_date':str(min(dates)) if dates else None,
            'unknown_dates_excluded':unknown_dates,
            'stop':'single_public_archive_not_verified_complete'})
    except Exception as exc:
        coverage.append({'source':'Лига ломбардов','stop':type(exc).__name__})
    url = 'https://sro-lombard.ru/news.html'
    try:
        raw = _fetch(url,30).decode('utf-8')
        pattern = r'<div class="dttm">(\d{2}\.\d{2}\.\d{4})</div>\s*<a href="([^"]+)"[^>]*><h3>(.*?)</h3>'
        from datetime import datetime
        count, dates = 0, []
        for day, href, title in re.findall(pattern,raw,re.S):
            published = datetime.strptime(day,'%d.%m.%Y').date()
            dates.append(published)
            if start <= published <= end:
                records.append({'key':'sro:'+href,'source':'industry-sro',
                    'source_title':'СРО (отраслевой источник)', 'published':str(published),
                    'modification':'','title':normalize_text(title),'body':'',
                    'url':'https://sro-lombard.ru'+href,'date_basis':'visible publication date'})
                count += 1
        coverage.append({'source':'СРО','count':count,'oldest_page_date':str(min(dates)) if dates else None,
                         'stop':'current_news_window_only; older_archive_not_collected'})
    except Exception as exc:
        coverage.append({'source':'СРО','stop':type(exc).__name__})
    return records, coverage

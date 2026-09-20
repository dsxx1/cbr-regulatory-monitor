"""Public allow-listed dashboard projection; static assets survive scheduled runs."""
import hashlib
import json
import re
import shutil
from pathlib import Path
from urllib.parse import urlparse

MODELS = ['kilo-auto/free', 'inclusionai/ling-3.0-flash-vl:free']


def settings():
    config = json.loads(Path('monitor-settings.json').read_text(encoding='utf-8'))
    if config.get('generator') not in MODELS or config.get('reviewer') not in MODELS:
        raise ValueError('Only verified free-model routes are allowed')
    if type(config.get('max_calls')) is not int or not 1 <= config['max_calls'] <= 5:
        raise ValueError('max_calls must be 1..5')
    return config


def safe_url(url):
    return url if isinstance(url,str) and urlparse(url).scheme == 'https' and urlparse(url).hostname else ''


def document_type(doc):
    source = doc.get('source','')
    if source == 'cbr-na': return 'Правовой акт'
    if 'explain' in source or 'explain:' in doc.get('key',''): return 'Разъяснение'
    if 'project' in source: return 'Проект акта'
    return 'Новость'


def priority(doc, kind):
    title = doc.get('title','').lower().replace('ё','е')
    if any(w in title for w in ('семинар','вебинар','конференц','поздрав')): return 'news'
    if any(w in title for w in ('вступил в силу','вступили в силу','новый порядок','полной стоимости кредита','предельные значения пск')): return 'high'
    if kind == 'Правовой акт' or (doc.get('analysis') or {}).get('requirements'): return 'high'
    if any(w in title for w in ('изменени','отчетност','требован','пск','проект','новые правила','лимит','учетная политик','цифровой рубль')): return 'medium'
    if any(w in title for w in ('обзор','аналитик','статистик')): return 'low'
    return 'news'


def project(doc, stage, archive=False):
    key = doc.get('key','')
    kind = document_type(doc)
    analysis = doc.get('analysis') or {}
    requirements = [{'text':str(r.get('text','')), 'citation':str(r.get('citation',''))}
                    for r in analysis.get('requirements',[]) if isinstance(r,dict)]
    return {'id':hashlib.sha256(key.encode()).hexdigest()[:20], 'key':key,
        'title':doc.get('title','Без заголовка'), 'source':doc.get('source_title') or doc.get('source',''),
        'sourceCode':doc.get('source',''), 'url':safe_url(doc.get('url','')),
        'date':doc.get('published') or doc.get('modification') or doc.get('source_date',''),
        'dateKind':'Дата публикации' if doc.get('published') else 'Дата изменения источника',
        'checked':doc.get('checked',''), 'body':doc.get('body','')[:30000],
        'type':kind, 'priority':priority(doc,kind), 'stage':stage,
        'archive':archive or bool(doc.get('control')), 'control':bool(doc.get('control')),
        'requirements':requirements, 'model':analysis.get('model',''),
        'dateConflict':bool(doc.get('date_mismatch')),
        'summary':requirements[0]['text'] if requirements else ''}


def export():
    state = json.loads(Path('cloud-state.json').read_text(encoding='utf-8'))
    catalog_path = Path('news-catalog.json')
    catalog = json.loads(catalog_path.read_text(encoding='utf-8')) if catalog_path.exists() else []
    cards = {d['key']:project(d,'collected',True) for d in catalog}
    for stage, field in [('pending','queue'),('needs_text','needs_full_text')]:
        for key, doc in state.get(field,{}).items():
            cards[doc['key']] = project(doc,stage)
    for doc in state.get('cards',[]):
        # Archived control examples stay distinct from current news.
        key = doc['key']
        original_key = key.removeprefix('control:')
        if re.search(r':[0-9a-f]{64}$',original_key):
            original_key = original_key.rsplit(':',1)[0]
        original = next((item for item in catalog if item['key']==original_key),{})
        merged = {**original,**doc,'source_title':doc.get('source') or original.get('source_title','')}
        if original:
            merged['source'] = original.get('source','')
        cards[key] = project(merged,'verified')
    status = json.loads(json.dumps(state.get('status',{})))
    for source in status.get('sources',[]):
        source['detail'] = source.get('detail','').replace('single_public_archive_not_verified_complete','открытый архив; полнота не подтверждена').replace('current_news_window_only; older_archive_not_collected','текущее окно новостей; старый архив не собран')
    output = {'version':2, 'status':status, 'settings':settings(),
        'schedule':{'timezone':'Europe/Moscow','hours':['09:17','13:17'],'weekdays':[1,2,3,4,5]},
        'delivery':{'state':'blocked','text':'Б24: требуется право imbot','verifiedAt':'2026-09-20'},
        'news':list(cards.values()), 'models':MODELS}
    Path('public').mkdir(exist_ok=True)
    Path('public/news.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    for name in ('index.html','app.css','app.js'):
        shutil.copyfile(Path('web')/name,Path('public')/name)
    print(f'Dashboard: {len(cards)} cards exported')


if __name__ == '__main__':
    import sys
    if '--seed' in sys.argv:
        raw = json.loads(Path('out/five-year-audit/records.json').read_text(encoding='utf-8'))
        # Persist public source fields only. No B24 metadata or receipts.
        keys = ('key','source','source_title','title','body','url','published','modification','date_mismatch')
        Path('news-catalog.json').write_text(json.dumps([{k:d[k] for k in keys if k in d} for d in raw],ensure_ascii=False,indent=2),encoding='utf-8')
    export()

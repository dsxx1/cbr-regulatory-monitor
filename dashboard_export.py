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
    if source=='custom-page':return 'Изменение страницы'
    if source == 'cbr-na': return 'Правовой акт'
    if 'explain' in source or 'explain:' in doc.get('key',''): return 'Разъяснение'
    if 'project' in source: return 'Проект акта'
    return 'Новость'


def priority(doc, kind):
    brief=doc.get('brief') or {}
    value=brief.get('priority')
    if doc.get('brief_verified') and brief.get('priority_reason') and value in ('high','medium','low','news'):
        return value
    return 'unknown'


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
        'checked':doc.get('checked',''), 'body':doc.get('body','')[:30000], 'bodyExcerpt':len(doc.get('body',''))>30000,
        'type':kind, 'priority':priority(doc,kind), 'stage':stage,
        'archive':archive or bool(doc.get('control')), 'control':bool(doc.get('control')),
        'requirements':requirements, 'model':doc.get('model') or analysis.get('model',''),
        'brief':doc.get('brief') if doc.get('brief_verified') else None,
        'verification':doc.get('verification',{}),
        'dateConflict':bool(doc.get('date_mismatch')),
        'summary':(doc.get('brief') or {}).get('summary') if doc.get('brief_verified') else (requirements[0]['text'] if requirements else '')}


def material_markdown(card):
    brief=card['brief']
    if not brief:
        return '\n'.join(['# '+card['title'],'',f"Источник: {card['url']}",'',
            '## Статус','', 'Это исходный материал, а не подтверждённый аналитический разбор.',
            'Важность пока не определена. '+card.get('processingText','Ожидает обработки.'),'',
            '## Текст источника','',card.get('body') or 'Не удалось извлечь полный текст; используйте ссылку на оригинал.',
            '', 'Полный текст длинного документа может быть представлен отдельно в файле источника.' if card.get('bodyExcerpt') else ''])+'\n'
    lines=['# '+card['title'],'',f"Источник: {card['url']}",'',
        '## Что произошло','',brief['summary'],'','## Статус','',brief['event_status'],'',
        '## Почему такая важность','',brief['priority_reason'],'','## Влияние на работу','',brief['impact'],'',
        '## Сроки','',brief['timing'],'','## Рекомендуемые действия','',
        *['- '+x for x in brief['actions']],'','## Что ещё проверить','',
        *['- '+x for x in brief['uncertainties']],'','## Основания','']
    for evidence in brief['evidence']:
        lines.extend([evidence['claim'],'','> '+evidence['citation'],''])
    verification=card.get('verification',{})
    if verification.get('context_note'): lines.extend(['## Нормативный контекст','',verification['context_note'],''])
    for ref in verification.get('references',[]): lines.append(f"[{ref['title']}]({safe_url(ref['url'])})")
    lines.extend(['','---',verification.get('note','Цитаты проверены; выводы прошли отдельный запрос LLM.'),'Применимость подтверждает специалист.'])
    return '\n'.join(lines)+'\n'


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
        # The content fingerprint identifies a queue attempt, not a new publication.
        key = key if key.startswith('control:') else original_key
        merged = {**original,**doc,'key':key,'source_title':doc.get('source') or original.get('source_title','')}
        if original:
            merged['source'] = original.get('source','')
        cards[key] = project(merged,'verified')
    briefs_path=Path('material-briefs.json')
    if briefs_path.exists():
        for key,doc in json.loads(briefs_path.read_text(encoding='utf-8')).items():
            if doc.get('brief_verified'):
                cards[key]=project(doc,'verified')
    source_cache_path=Path('source-cache.json')
    source_cache=json.loads(source_cache_path.read_text(encoding='utf-8')) if source_cache_path.exists() else {}
    queue_path=Path('analysis-queue.json')
    queue=json.loads(queue_path.read_text(encoding='utf-8')) if queue_path.exists() else {'items':{}}
    for key,card in cards.items():
        cached=source_cache.get(key,{})
        if cached.get('body') and len(card.get('body',''))<120:
            card['body']=cached['body'][:30000];card['bodyExcerpt']=len(cached['body'])>30000
        job=queue['items'].get(key,{})
        card['processing']=job
        card['processingText']=({'retry':'Автоматическая повторная попытка запланирована.',
            'needs_operator':'Автоматические попытки исчерпаны; нужна проверка причины.'}).get(job.get('state'),'Ожидает обработки.')
        if card.get('brief'):card['processingText']='Разбор готов.'
    status = json.loads(json.dumps(state.get('status',{})))
    for source in status.get('sources',[]):
        source['detail'] = source.get('detail','').replace('single_public_archive_not_verified_complete','открытый архив; полнота не подтверждена').replace('current_news_window_only; older_archive_not_collected','текущее окно новостей; старый архив не собран')
    output = {'version':2, 'status':status, 'settings':settings(),
        'schedule':{'timezone':'Europe/Moscow','hours':['09:17','13:17'],'weekdays':[1,2,3,4,5]},
        'delivery':{'state':'blocked','text':'Б24: требуется право imbot','verifiedAt':'2026-09-20'},
        'news':list(cards.values()), 'models':MODELS,'backlog':{k:v for k,v in queue.items() if k!='items'}}
    from llm_health import report
    output['llmHealth'] = report()
    delivery=Path('public/delivery.json')
    if delivery.exists(): output['delivery']=json.loads(delivery.read_text(encoding='utf-8'))
    Path('public').mkdir(exist_ok=True)
    for card in output['news']:
        filename='materials/'+card['id']+'.md'
        Path('public/materials').mkdir(exist_ok=True)
        md_card=dict(card)
        if not card.get('brief') and source_cache.get(card['key'],{}).get('body'):
            md_card['body']=source_cache[card['key']]['body'];md_card['bodyExcerpt']=False
        Path('public',filename).write_text(material_markdown(md_card),encoding='utf-8')
        card['markdownUrl']=filename
        card['markdownKind']='analysis' if card.get('brief') else 'source'
    Path('public/news.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    for name in ('index.html','app.css','app.js','material.js','editorial.css','readable.css','minimal.css','operations.js'):
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

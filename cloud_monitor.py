"""Scheduled public-source ingestion, free LLM analysis, citation checks and dashboard."""
import hashlib
import html
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import sources
from free_llm import FreeAnalyzer

STATE = Path('cloud-state.json')


def quality(analysis, text):
    if not isinstance(analysis,dict) or not analysis.get('requirements'):
        return False
    # Literal, case-sensitive match is stricter than the legacy normalizer.
    return all(isinstance(r,dict) and isinstance(r.get('text'),str) and
        len(r.get('citation','')) >= 25 and r['citation'] in text for r in analysis['requirements'])


def main():
    state = json.loads(STATE.read_text(encoding='utf-8')) if STATE.exists() else {'seen':{},'cards':[],'queue':{}}
    state.setdefault('queue',{})
    if '--ack' in sys.argv:
        state['pending_message'] = ''
        STATE.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
        return
    now = datetime.now(timezone.utc).isoformat()
    documents, source_log, _ = sources.collect(categories=sources.EXPLAIN_CATEGORIES,root=sources.EXPLAIN_ROOT,timeout=20)
    control = os.environ.get('CONTROL_RUN') == 'yes'
    baseline = not state['seen']
    for doc in documents:
        fingerprint = hashlib.sha256(doc.payload().encode()).hexdigest()
        changed = state['seen'].get(doc.key) != fingerprint
        state['seen'][doc.key] = fingerprint
        if changed and doc.in_perimeter and not baseline:
            state['queue'][doc.key+':'+fingerprint] = doc.as_dict()
    if control:
        # Demonstrate quality using real full-text source, labelled as a control example.
        demos = sorted((d for d in documents if d.source=='cbr-explain'),key=lambda d:len(d.body),reverse=True)[:2]
        for doc in demos:
            state['queue']['control:'+doc.key] = doc.as_dict()
    analyzer = FreeAnalyzer(max_calls=3)
    accepted, rejected = [], []
    for key, doc in list(state['queue'].items())[:3]:
        text = doc['title']+'\n'+doc['body']
        analysis = analyzer.analyze(text)
        if quality(analysis,text):
            card = {'key':key,'title':doc['title'],'url':doc['url'],'source':doc['source_title'],
                    'analysis':analysis,'checked':now,'control':key.startswith('control:')}
            accepted.append(card)
            state['cards'].append(card)
            del state['queue'][key]
        else:
            rejected.append(key)
    state['cards'] = state['cards'][-100:]
    failed_sources = [s['name'] for s in source_log if s['status'] != 'ok']
    status = {'checked':now,'documents':len(documents),'sources':source_log,
              'llm_calls':analyzer.calls,'accepted':len(accepted),'rejected':len(rejected),
              'pending':len(state['queue']),'llm_errors':analyzer.errors,'receipts':analyzer.receipts}
    state['status'] = status
    lines = []
    if accepted or control:
        lines = ['Мониторинг регулирования — '+('контрольный запуск' if control else 'новые материалы'),
                 f'Проверено публикаций: {len(documents)}. LLM: {len(accepted)}/{analyzer.calls} ответов прошли проверку.',
                 'Модель бесплатная; цитаты сверены с источником. Применимость подтверждает специалист.']
        for card in accepted:
            lines.extend(['',('Контрольный пример из архива: ' if card['control'] else '')+card['title'][:220],card['url']])
            for req in card['analysis']['requirements'][:2]:
                lines.extend(['• '+req['text'][:600], 'Основание: «'+req['citation'][:800]+'»'])
        if rejected:
            lines.append(f'Не прошли проверку: {len(rejected)}. Сохранены для повторной обработки.')
        if failed_sources:
            lines.append('Не ответили источники: '+', '.join(failed_sources))
        lines.append('Dashboard: https://dsxx1.github.io/cbr-regulatory-monitor/')
    if lines:
        # Preserve pending delivery from a previous interrupted run.
        state['pending_message'] = (state.get('pending_message','')+'\n\n'+'\n'.join(lines)).strip()
    Path('runtime').mkdir(exist_ok=True)
    Path('runtime/message.txt').write_text(state.get('pending_message',''),encoding='utf-8')
    STATE.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
    public = Path('public'); public.mkdir(exist_ok=True)
    (public/'status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
    e = html.escape
    page = '<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Мониторинг регулирования</title><style>body{font:16px/1.6 system-ui;max-width:1000px;margin:32px auto;padding:0 20px;background:#f5f6f8}article,header{background:white;padding:24px;border-radius:12px;margin-bottom:20px}blockquote{border-left:3px solid #6378bf;padding-left:16px;color:#42506b}a{color:#3156a3}</style><header><h1>Мониторинг регулирования</h1>'
    page += f'<p>Последний запуск: {e(now)} UTC</p><p>Публикаций: {len(documents)} · Ответов LLM проверено: {len(accepted)}/{analyzer.calls} · В очереди: {len(state["queue"])}</p><p>GitHub Actions · бесплатная модель · проверка цитат. Это вспомогательный анализ, не юридическое заключение.</p></header>'
    for entry in source_log:
        page += '<p>'+e(entry['name'])+': '+e(entry['status'])+'</p>'
    for card in reversed(state['cards']):
        page += '<article><small>'+('Контрольный пример из архива' if card['control'] else 'Обнаруженное изменение')+'</small><h2>'+e(card['title'])+'</h2><a href="'+e(card['url'],quote=True)+'">Первоисточник</a>'
        for req in card['analysis']['requirements'][:5]:
            page += '<p>'+e(req['text'])+'</p><blockquote>'+e(req['citation'])+'</blockquote>'
        page += '</article>'
    page += '</html>'
    (public/'index.html').write_text(page,encoding='utf-8')
    print(json.dumps({k:v for k,v in status.items() if k not in ('sources','receipts')},ensure_ascii=False))


if __name__ == '__main__':
    main()

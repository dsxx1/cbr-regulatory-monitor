"""Bounded public transport evidence; never prompts, credentials or raw responses."""
import json
from pathlib import Path


def report(persist=True):
    path = Path('llm-health.json')
    old = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    events = {e['id']: e for e in old.get('events', [])}
    for file in Path('out/llm-events').glob('*.json'):
        try:
            value = json.loads(file.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            continue
        events[value['id']] = value
    rows = sorted(events.values(), key=lambda e: e['at'])[-300:]
    summary = {'window': 'Последние 300 попыток маршрутов после включения журнала', 'events': rows,
               'attempts': len(rows), 'responses': sum(e['status'] == 'response' for e in rows),
               'failures': sum(e['status'] == 'failed' for e in rows),
               'last': rows[-1]['at'] if rows else None}
    if persist:
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(path)
    return summary

#!/usr/bin/env python3
"""
Наблюдатель за регулированием Банка России.

Конвейер одного прогона:

    источники → сохранение версии → сравнение → машинный отбор →
    анализ моделью → карточка → исходящая очередь → отчёт

Что гарантируется:
  * прогон идемпотентен — повторный запуск на тех же данных не создаёт дублей;
  * отказ источника отличается от отсутствия изменений;
  * модель предлагает, человек подтверждает — это разные поля;
  * утверждение без дословной опоры в исходнике отбрасывается;
  * внешние действия выключены по умолчанию.

Зависимостей нет, только стандартная библиотека.
"""

from __future__ import annotations

import argparse
import hashlib
import html as html_mod
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import sources
from analyze import Analyzer
from b24 import Outbox

RETENTION_DAYS = 180   # запись, не встречавшаяся полгода, уходит из состояния


def sha16(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def excerpt(text: str, limit: int = 220) -> str:
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def esc(value) -> str:
    return html_mod.escape(str(value if value is not None else ""), quote=True)


# --------------------------------------------------------------- отчёт

CSS = """
  :root { --bg:#fbfbfa; --fg:#1a1a18; --mut:#6b6b66; --line:#e3e3df; --card:#fff;
          --new:#1f7a4d; --chg:#9a6700; --err:#b42318; --acc:#2d5db3 }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#16161a; --fg:#e8e8e4; --mut:#9a9a94; --line:#2c2c32; --card:#1e1e24;
            --new:#4ac585; --chg:#e0a72b; --err:#f2776a; --acc:#7aa2e3 }
  }
  * { box-sizing:border-box }
  body { margin:0; padding:2rem 1.25rem; background:var(--bg); color:var(--fg);
         font:15px/1.6 -apple-system,Segoe UI,Roboto,sans-serif }
  .wrap { max-width:960px; margin:0 auto }
  h1 { font-size:1.45rem; margin:0 0 .35rem }
  .sub { color:var(--mut); margin:0 0 1.5rem; font-size:.9rem }
  .stats { display:flex; flex-wrap:wrap; gap:.7rem; margin-bottom:1.5rem }
  .stat { flex:1 1 120px; background:var(--card); border:1px solid var(--line);
          border-radius:10px; padding:.8rem .95rem }
  .stat b { display:block; font-size:1.55rem; line-height:1.2 }
  .stat span { color:var(--mut); font-size:.78rem }
  .mode { background:var(--card); border:1px solid var(--line); border-left:3px solid var(--acc);
          border-radius:8px; padding:.8rem 1rem; margin-bottom:1.5rem; font-size:.85rem }
  .mode code { color:var(--acc) }
  h2 { font-size:1rem; text-transform:uppercase; letter-spacing:.06em;
       color:var(--mut); margin:2rem 0 .8rem; font-weight:600 }
  .card { background:var(--card); border:1px solid var(--line); border-left-width:3px;
          border-radius:8px; padding:1rem 1.1rem; margin-bottom:.7rem }
  .card.new { border-left-color:var(--new) }
  .card.changed { border-left-color:var(--chg) }
  .tag { font-size:.7rem; text-transform:uppercase; letter-spacing:.08em; font-weight:700 }
  .new .tag { color:var(--new) } .changed .tag { color:var(--chg) }
  .card h3 { font-size:.95rem; margin:.35rem 0 .45rem; font-weight:600 }
  .card p { margin:0 0 .5rem; opacity:.85; font-size:.88rem }
  .req { border-left:2px solid var(--line); padding-left:.75rem; margin:.5rem 0; font-size:.85rem }
  .req q { display:block; color:var(--mut); font-style:italic; margin-top:.2rem }
  .pend { color:var(--chg); font-weight:600; font-size:.8rem }
  .card footer { font-size:.74rem; color:var(--mut); font-family:ui-monospace,Consolas,monospace;
                 margin-top:.5rem }
  .empty { background:var(--card); border:1px dashed var(--line); border-radius:8px;
           padding:1rem 1.1rem; color:var(--mut) }
  .empty.warn { border-color:var(--chg); color:var(--chg) }
  table { width:100%; border-collapse:collapse; font-size:.84rem }
  th,td { text-align:left; padding:.5rem .55rem; border-bottom:1px solid var(--line) }
  th { color:var(--mut); font-weight:600; font-size:.73rem; text-transform:uppercase }
  td.ok { color:var(--new) } td.err { color:var(--err); font-weight:600 }
  .foot { margin-top:2.5rem; padding-top:1rem; border-top:1px solid var(--line);
          color:var(--mut); font-size:.79rem }
"""


def render_card(card: dict, kind: str) -> str:
    a = card.get("analysis") or {}
    body = [
        f'<article class="card {kind}">',
        f'  <div class="tag">{"Новое" if kind == "new" else "Изменилось"}'
        f'{" · в периметре" if card.get("in_perimeter") else ""}</div>',
        f'  <h3>{esc(excerpt(card["title"], 220))}</h3>',
    ]
    if card.get("body"):
        body.append(f'  <p>{esc(excerpt(card["body"], 300))}</p>')
    if card.get("comment_deadline"):
        body.append(f'  <p class="pend">Замечания по проекту принимаются до '
                    f'{esc(card["comment_deadline"])}</p>')
    if a:
        body.append(
            f'  <p>Предположение модели: <b>{esc(a.get("applicability_suggested"))}</b>'
            f' — {esc(a.get("applicability_reason"))}</p>')
        for req in (a.get("requirements") or [])[:4]:
            body.append(
                f'  <div class="req">{esc(req.get("text"))}'
                f'<q>«{esc(excerpt(req.get("citation", ""), 200))}»</q></div>')
        if a.get("claims_rejected"):
            body.append(f'  <p class="pend">Отброшено без дословной опоры: '
                        f'{a["claims_rejected"]}</p>')
        body.append('  <p class="pend">Подтверждение человеком не получено — шлюз 1</p>')
    body.append(f'  <footer>{esc(card["source_title"])} · {esc(card["key"])} · '
                f'хеш {esc(card["version"])}</footer>')
    body.append('</article>')
    return "\n".join(body)


def render_report(ctx: dict) -> str:
    failed = [s for s in ctx["sources"] if s["status"] != "ok"]
    cards = "".join(render_card(c, "new") for c in ctx["new"])
    cards += "".join(render_card(c, "changed") for c in ctx["changed"])
    if not cards:
        if failed:
            cards = ('<div class="empty warn">Изменений не обнаружено, но часть источников '
                     'не ответила. Это не то же самое, что «изменений нет».</div>')
        elif ctx["first_run"]:
            cards = ('<div class="empty">Первый прогон: база наполнена, всё записано как '
                     'исходное состояние. Сигналы начнутся со следующего запуска.</div>')
        else:
            cards = '<div class="empty">Изменений нет. Все источники ответили.</div>'

    rows = "".join(
        f'<tr><td>{esc(s["name"])}</td>'
        f'<td class="{"ok" if s["status"] == "ok" else "err"}">{esc(s["status"])}</td>'
        f'<td>{esc(s["detail"])}</td></tr>'
        for s in ctx["sources"])

    subs = ""
    if ctx["new_subs"]:
        subs = (f'<div class="empty warn">Появились новые подкатегории: '
                f'{", ".join(map(str, ctx["new_subs"]))}. Добавить в наблюдение.</div>')

    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Мониторинг регулирования Банка России</title>
<style>{CSS}</style></head><body><div class="wrap">

<h1>Мониторинг регулирования Банка России</h1>
<p class="sub">Периметр: ломбарды. Прогон №{ctx['run_count']} от
{ctx['run_at'].strftime('%d.%m.%Y %H:%M:%S')} UTC</p>

<div class="stats">
  <div class="stat"><b>{len(ctx['new'])}</b><span>новых</span></div>
  <div class="stat"><b>{len(ctx['changed'])}</b><span>изменилось</span></div>
  <div class="stat"><b>{ctx['perimeter_hits']}</b><span>в периметре</span></div>
  <div class="stat"><b>{ctx['watched']}</b><span>под наблюдением</span></div>
  <div class="stat"><b>{len(failed)}</b><span>отказов источников</span></div>
</div>

<div class="mode">
  <b>Режим:</b> {esc(ctx['mode'])}<br>
  Модель: {esc(ctx['analyzer_status'])}<br>
  Битрикс24: {esc(ctx['outbox_status'])}
</div>

{subs}

<h2>Сигналы этого прогона</h2>
{cards}

<h2>Состояние источников</h2>
<table><thead><tr><th>Источник</th><th>Статус</th><th>Подробности</th></tr></thead>
<tbody>{rows}</tbody></table>

<div class="foot">
  Отслеживается хеш нормализованного текста, а не вёрстка: переформатирование
  сигналом не считается. Поле <code>modification</code> — время правки записи,
  <b>не</b> дата вступления требования в силу. Предположения модели помечены как
  предположения и обязаны опираться на дословную выдержку из источника;
  применимость и сроки подтверждает человек.
</div>

</div></body></html>
"""


# --------------------------------------------------------------- прогон

def run(args) -> int:
    run_at = datetime.now(timezone.utc)
    state_path, report_path = Path(args.state), Path(args.report)

    first_run = not state_path.exists()
    state = ({"lastRun": None, "runCount": 0, "subCategories": [], "items": {}}
             if first_run else json.loads(state_path.read_text(encoding="utf-8")))
    known: dict = state.get("items", {})

    documents, source_log, subs_now = sources.collect(
        categories=args.categories, root=args.root, timeout=args.timeout)

    known_subs = [int(s) for s in state.get("subCategories", [])]
    new_subs = [] if first_run else [s for s in subs_now if s not in known_subs]

    analyzer = Analyzer()
    outbox = Outbox(args.outbox, send=args.send)

    new_cards: list[dict] = []
    changed_cards: list[dict] = []
    perimeter_hits = 0

    for doc in documents:
        digest = sha16(doc.payload())
        prev = known.get(doc.key)
        if doc.in_perimeter:
            perimeter_hits += 1

        card = {
            "key": doc.key, "version": digest, "title": doc.title, "body": doc.body,
            "url": doc.url, "source_title": doc.source_title,
            "in_perimeter": doc.in_perimeter, "detected": run_at.isoformat(),
            "comment_deadline": sources.extract_comment_deadline(doc.category),
            "level": "внимание" if doc.in_perimeter else "к сведению",
        }

        if prev is None:
            known[doc.key] = {"hash": digest, "source": doc.source,
                              "title": excerpt(doc.title, 300),
                              "in_perimeter": doc.in_perimeter,
                              "firstSeen": run_at.isoformat(),
                              "lastSeen": run_at.isoformat()}
            if not first_run:
                new_cards.append(card)
        elif prev.get("hash") != digest:
            prev.update({"hash": digest, "lastSeen": run_at.isoformat(),
                         "title": excerpt(doc.title, 300)})
            changed_cards.append(card)
        else:
            prev["lastSeen"] = run_at.isoformat()

    # Анализ — только для периметра и только в пределах бюджета вызовов.
    # Всё остальное сохранено и попадёт в лист отсева, но денег не стоит.
    for card in new_cards + changed_cards:
        if card["in_perimeter"]:
            card["analysis"] = analyzer.analyze(f"{card['title']}\n{card['body']}")
            if card.get("analysis"):
                outbox.enqueue(card)

    outbox.flush()
    outbox.save()

    # Чистка состояния: запись, не встречавшаяся RETENTION_DAYS, уходит.
    cutoff = (run_at - timedelta(days=RETENTION_DAYS)).isoformat()
    known = {k: v for k, v in known.items() if v.get("lastSeen", "") >= cutoff}

    state.update({"lastRun": run_at.isoformat(),
                  "runCount": int(state.get("runCount", 0)) + 1,
                  "subCategories": subs_now,
                  "items": dict(sorted(known.items()))})
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    mode = "тень — только обнаружение и отчёт"
    if analyzer.enabled and outbox.send_enabled:
        mode = "авто — анализ и отправка в Битрикс24"
    elif analyzer.enabled:
        mode = "полуавто — анализ включён, отправка выключена"

    ctx = {"run_at": run_at, "run_count": state["runCount"], "new": new_cards,
           "changed": changed_cards, "watched": len(known), "sources": source_log,
           "new_subs": new_subs, "first_run": first_run, "perimeter_hits": perimeter_hits,
           "mode": mode, "analyzer_status": analyzer.status_line(),
           "outbox_status": outbox.status_line()}

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(ctx), encoding="utf-8")

    failed = [s for s in source_log if s["status"] != "ok"]
    out = [f"Прогон №{state['runCount']} завершён {run_at.strftime('%H:%M:%S')} UTC",
           f"  режим:            {mode}",
           f"  новых:            {len(new_cards)}",
           f"  изменилось:       {len(changed_cards)}",
           f"  в периметре:      {perimeter_hits}",
           f"  под наблюдением:  {len(known)}",
           f"  модель:           {analyzer.status_line()}",
           f"  Битрикс24:        {outbox.status_line()}"]
    if failed:
        out.append(f"  ОТКАЗОВ ИСТОЧНИКОВ: {len(failed)}")
        out += [f"    - {f['name']}: {f['detail']}" for f in failed]
    if new_subs:
        out.append(f"  НОВЫЕ ПОДКАТЕГОРИИ: {new_subs}")
    out.append(f"  отчёт:            {report_path}")
    print("\n".join(out))

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(f"### Прогон №{state['runCount']} — {mode}\n\n")
            fh.write("| Показатель | Значение |\n|---|---|\n")
            fh.write(f"| Новых | {len(new_cards)} |\n| Изменилось | {len(changed_cards)} |\n")
            fh.write(f"| В периметре | {perimeter_hits} |\n")
            fh.write(f"| Под наблюдением | {len(known)} |\n")
            fh.write(f"| Отказов источников | {len(failed)} |\n\n")
            fh.write(f"Модель: {analyzer.status_line()}  \n")
            fh.write(f"Битрикс24: {outbox.status_line()}\n")
            for c in new_cards[:15]:
                fh.write(f"\n**Новое** — {excerpt(c['title'], 160)}\n")
            for c in changed_cards[:15]:
                fh.write(f"\n**Изменилось** — {excerpt(c['title'], 160)}\n")
            for f in failed:
                fh.write(f"\n> Отказ источника: {f['name']} — {f['detail']}\n")

    return 2 if (failed and args.fail_on_source_error) else 0


def main() -> int:
    p = argparse.ArgumentParser(description="Мониторинг регулирования Банка России")
    p.add_argument("--state", default="state.json")
    p.add_argument("--report", default="docs/index.html")
    p.add_argument("--outbox", default="outbox.json")
    p.add_argument("--categories", type=int, nargs="+", default=sources.EXPLAIN_CATEGORIES)
    p.add_argument("--root", type=int, default=sources.EXPLAIN_ROOT)
    p.add_argument("--timeout", type=int, default=30)
    p.add_argument("--fail-on-source-error", action="store_true")
    p.add_argument("--send", action="store_true",
                   help="разрешить реальную отправку в Битрикс24 (нужен B24_WEBHOOK)")
    return run(p.parse_args())


if __name__ == "__main__":
    sys.exit(main())

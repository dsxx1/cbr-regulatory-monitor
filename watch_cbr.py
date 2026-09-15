#!/usr/bin/env python3
"""
Наблюдатель за разъяснениями Банка России (периметр: ломбарды).

За один прогон:
  1. читает дерево категорий и замечает появление новых подкатегорий;
  2. забирает разъяснения по наблюдаемым категориям;
  3. считает хеш нормализованного текста и сравнивает с прошлым прогоном;
  4. различает «новое», «изменилось», «без изменений»;
  5. отличает отказ источника от отсутствия изменений;
  6. сохраняет состояние и рисует отчёт.

Прогон идемпотентен: повторный запуск на тех же данных даёт ноль новых.
Зависимостей нет — только стандартная библиотека.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API_BASE = "https://www.cbr.ru/ExplainApi/v1"
USER_AGENT = "regulatory-monitor/0.1 (+internal compliance monitoring)"

# Категории по умолчанию: «Оформление залогового билета» и «Отчётность → Ломбарды».
DEFAULT_CATEGORIES = [774, 378]
DEFAULT_ROOT = 426


# --------------------------------------------------------------- вспомогательное

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def normalize_text(raw: str | None) -> str:
    """Хеш должен меняться от смысла, а не от вёрстки."""
    if not raw:
        return ""
    text = TAG_RE.sub(" ", raw)
    text = html.unescape(text)
    text = text.replace(" ", " ")
    return WS_RE.sub(" ", text).strip()


def sha16(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def excerpt(text: str, limit: int = 220) -> str:
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def fetch_json(url: str, timeout: int = 30, attempts: int = 3):
    """GET с повторами. Последняя ошибка пробрасывается наверх — отказ источника
    обязан быть виден, а не проглочен."""
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
            })
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 — нужен любой отказ, включая сетевой
            last = exc
            if attempt < attempts:
                time.sleep(2 ** attempt)
    raise last  # type: ignore[misc]


def as_list(payload) -> list:
    """API может отдать как массив, так и одиночный объект."""
    if payload is None:
        return []
    if isinstance(payload, list):
        return payload
    return [payload]


# --------------------------------------------------------------- отчёт

REPORT_CSS = """
  :root { --bg:#fbfbfa; --fg:#1a1a18; --mut:#6b6b66; --line:#e3e3df; --card:#fff;
          --new:#1f7a4d; --chg:#9a6700; --err:#b42318; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#16161a; --fg:#e8e8e4; --mut:#9a9a94; --line:#2c2c32; --card:#1e1e24;
            --new:#4ac585; --chg:#e0a72b; --err:#f2776a; }
  }
  * { box-sizing:border-box }
  body { margin:0; padding:2rem 1.25rem; background:var(--bg); color:var(--fg);
         font:15px/1.6 -apple-system,Segoe UI,Roboto,sans-serif }
  .wrap { max-width:940px; margin:0 auto }
  h1 { font-size:1.45rem; margin:0 0 .35rem }
  .sub { color:var(--mut); margin:0 0 1.75rem; font-size:.9rem }
  .stats { display:flex; flex-wrap:wrap; gap:.75rem; margin-bottom:1.75rem }
  .stat { flex:1 1 130px; background:var(--card); border:1px solid var(--line);
          border-radius:10px; padding:.85rem 1rem }
  .stat b { display:block; font-size:1.6rem; line-height:1.2 }
  .stat span { color:var(--mut); font-size:.8rem }
  h2 { font-size:1rem; text-transform:uppercase; letter-spacing:.06em;
       color:var(--mut); margin:2rem 0 .85rem; font-weight:600 }
  .card { background:var(--card); border:1px solid var(--line); border-left-width:3px;
          border-radius:8px; padding:1rem 1.15rem; margin-bottom:.75rem }
  .card.new { border-left-color:var(--new) }
  .card.changed { border-left-color:var(--chg) }
  .tag { font-size:.7rem; text-transform:uppercase; letter-spacing:.08em; font-weight:700 }
  .new .tag { color:var(--new) } .changed .tag { color:var(--chg) }
  .card h3 { font-size:.98rem; margin:.4rem 0 .5rem; font-weight:600 }
  .card p { margin:0 0 .6rem; opacity:.85; font-size:.9rem }
  .card footer { font-size:.75rem; color:var(--mut); font-family:ui-monospace,Consolas,monospace }
  .empty { background:var(--card); border:1px dashed var(--line); border-radius:8px;
           padding:1.1rem 1.15rem; color:var(--mut) }
  .empty.warn { border-color:var(--chg); color:var(--chg) }
  table { width:100%; border-collapse:collapse; font-size:.85rem }
  th,td { text-align:left; padding:.55rem .6rem; border-bottom:1px solid var(--line) }
  th { color:var(--mut); font-weight:600; font-size:.75rem; text-transform:uppercase; letter-spacing:.05em }
  td.ok { color:var(--new) } td.err { color:var(--err); font-weight:600 }
  .foot { margin-top:2.5rem; padding-top:1rem; border-top:1px solid var(--line);
          color:var(--mut); font-size:.8rem }
"""


def esc(text) -> str:
    return html.escape(str(text if text is not None else ""), quote=True)


def render_card(rec: dict, kind: str) -> str:
    if kind == "new":
        tag, meta = "Новое", (f"категория {rec['categoryId']} · id {rec['id']} · "
                              f"изменено {rec['modification']} · хеш {rec['hash']}")
    else:
        tag, meta = "Изменилось", (f"категория {rec['categoryId']} · id {rec['id']} · "
                                   f"хеш {rec['oldHash']} &rarr; {rec['hash']} · "
                                   f"изменено {rec['oldModification']} &rarr; {rec['modification']}")
    return (
        f'      <article class="card {kind}">\n'
        f'        <div class="tag">{tag}</div>\n'
        f'        <h3>{esc(excerpt(rec["question"], 200))}</h3>\n'
        f'        <p>{esc(excerpt(rec["answer"], 320))}</p>\n'
        f'        <footer>{meta}</footer>\n'
        f'      </article>\n'
    )


def render_report(*, run_at, run_count, new, changed, unchanged, watched,
                  sources, new_subs, first_run, state_path) -> str:
    failed = [s for s in sources if s["status"] != "ok"]

    cards = "".join(render_card(r, "new") for r in new)
    cards += "".join(render_card(r, "changed") for r in changed)
    if not cards:
        if failed:
            cards = ('<div class="empty warn">Изменений не обнаружено, но часть источников '
                     'не ответила. Это не то же самое, что «изменений нет».</div>')
        elif first_run:
            cards = ('<div class="empty">Первый прогон: база наполнена, всё записано как '
                     'исходное состояние. Сигналы начнутся со следующего запуска.</div>')
        else:
            cards = '<div class="empty">Изменений нет. Все источники ответили.</div>'

    rows = "".join(
        f'<tr><td>{esc(s["name"])}</td>'
        f'<td class="{"ok" if s["status"] == "ok" else "err"}">{esc(s["status"])}</td>'
        f'<td>{esc(s["detail"])}</td></tr>\n'
        for s in sources
    )

    subs_note = ""
    if new_subs:
        subs_note = (f'<div class="empty warn">Появились новые подкатегории: '
                     f'{", ".join(str(s) for s in new_subs)}. Их нужно добавить в наблюдение.</div>')

    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Мониторинг разъяснений Банка России — ломбарды</title>
<style>{REPORT_CSS}</style></head><body><div class="wrap">

<h1>Мониторинг разъяснений Банка России</h1>
<p class="sub">Периметр: ломбарды. Прогон №{run_count} от {run_at.strftime('%d.%m.%Y %H:%M:%S')} UTC</p>

<div class="stats">
  <div class="stat"><b>{len(new)}</b><span>новых</span></div>
  <div class="stat"><b>{len(changed)}</b><span>изменилось</span></div>
  <div class="stat"><b>{unchanged}</b><span>без изменений</span></div>
  <div class="stat"><b>{watched}</b><span>под наблюдением</span></div>
  <div class="stat"><b>{len(failed)}</b><span>отказов источников</span></div>
</div>

{subs_note}

<h2>Сигналы этого прогона</h2>
{cards}

<h2>Состояние источников</h2>
<table><thead><tr><th>Источник</th><th>Статус</th><th>Подробности</th></tr></thead>
<tbody>
{rows}</tbody></table>

<div class="foot">
  Прототип решающего контура. Отслеживается хеш нормализованного текста, а не вёрстка,
  поэтому переформатирование страницы сигналом не считается.
  Поле <code>modification</code> — время правки разъяснения, а не дата вступления
  требования в силу; дату вступления подтверждает человек.
  Состояние: <code>{esc(state_path)}</code>
</div>

</div></body></html>
"""


# --------------------------------------------------------------- основной проход

def run(args) -> int:
    run_at = datetime.now(timezone.utc)
    state_path = Path(args.state)
    report_path = Path(args.report)

    first_run = not state_path.exists()
    if first_run:
        state = {"lastRun": None, "runCount": 0, "subCategories": [], "items": {}}
    else:
        state = json.loads(state_path.read_text(encoding="utf-8"))

    known: dict = state.get("items", {})
    sources: list[dict] = []
    new: list[dict] = []
    changed: list[dict] = []
    unchanged = 0

    # --- дерево категорий: новые подкатегории нельзя пропустить
    subs_now: list[int] = []
    try:
        tree = fetch_json(f"{API_BASE}/categories/{args.root}", args.timeout)
        subs_now = [int(c["id"]) for c in as_list(tree) if "id" in c]
        sources.append({"name": f"Дерево категорий {args.root}", "status": "ok",
                        "detail": f"подкатегорий: {len(subs_now)}"})
    except Exception as exc:  # noqa: BLE001
        sources.append({"name": f"Дерево категорий {args.root}", "status": "ошибка",
                        "detail": str(exc)})

    known_subs = [int(s) for s in state.get("subCategories", [])]
    new_subs = [] if first_run else [s for s in subs_now if s not in known_subs]

    # --- разъяснения
    for cat in args.categories:
        try:
            items = as_list(fetch_json(f"{API_BASE}/categories/{cat}/explains", args.timeout))
            sources.append({"name": f"Разъяснения, категория {cat}", "status": "ok",
                            "detail": f"записей: {len(items)}"})
        except Exception as exc:  # noqa: BLE001
            # Источник не ответил — это событие, а не тишина.
            sources.append({"name": f"Разъяснения, категория {cat}", "status": "ошибка",
                            "detail": str(exc)})
            continue

        for it in items:
            key = f"{cat}:{it.get('id')}"
            question = normalize_text(it.get("questionHtml"))
            answer = normalize_text(it.get("answerHtml"))
            digest = sha16(question + "\n" + answer)
            modification = it.get("modification")

            record = {"key": key, "id": it.get("id"), "categoryId": cat,
                      "question": question, "answer": answer,
                      "hash": digest, "modification": modification}

            prev = known.get(key)
            if prev is None:
                known[key] = {"hash": digest, "modification": modification,
                              "firstSeen": run_at.isoformat(), "lastSeen": run_at.isoformat(),
                              "question": excerpt(question, 300)}
                if first_run:
                    unchanged += 1
                else:
                    new.append(record)
            elif prev.get("hash") != digest:
                record["oldHash"] = prev.get("hash")
                record["oldModification"] = prev.get("modification")
                changed.append(record)
                prev.update({"hash": digest, "modification": modification,
                             "lastSeen": run_at.isoformat(),
                             "question": excerpt(question, 300)})
            else:
                unchanged += 1
                prev["lastSeen"] = run_at.isoformat()

    # --- сохранение
    state.update({
        "lastRun": run_at.isoformat(),
        "runCount": int(state.get("runCount", 0)) + 1,
        "subCategories": subs_now,
        "items": dict(sorted(known.items())),
    })
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(
        run_at=run_at, run_count=state["runCount"], new=new, changed=changed,
        unchanged=unchanged, watched=len(known), sources=sources,
        new_subs=new_subs, first_run=first_run, state_path=state_path.name,
    ), encoding="utf-8")

    # --- итог
    failed = [s for s in sources if s["status"] != "ok"]
    lines = [
        f"Прогон №{state['runCount']} завершён {run_at.strftime('%H:%M:%S')} UTC",
        f"  новых:            {len(new)}",
        f"  изменилось:       {len(changed)}",
        f"  без изменений:    {unchanged}",
        f"  под наблюдением:  {len(known)}",
    ]
    if failed:
        lines.append(f"  ОТКАЗОВ ИСТОЧНИКОВ: {len(failed)}")
        lines += [f"    - {f['name']}: {f['detail']}" for f in failed]
    if new_subs:
        lines.append(f"  НОВЫЕ ПОДКАТЕГОРИИ: {new_subs}")
    lines.append(f"  отчёт:            {report_path}")
    print("\n".join(lines))

    # Сводка в интерфейс GitHub Actions — прогон должен быть виден без чтения логов.
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(f"### Прогон №{state['runCount']}\n\n")
            fh.write("| Показатель | Значение |\n|---|---|\n")
            fh.write(f"| Новых | {len(new)} |\n| Изменилось | {len(changed)} |\n")
            fh.write(f"| Без изменений | {unchanged} |\n| Под наблюдением | {len(known)} |\n")
            fh.write(f"| Отказов источников | {len(failed)} |\n")
            for rec in new:
                fh.write(f"\n**Новое** — {excerpt(rec['question'], 160)}\n")
            for rec in changed:
                fh.write(f"\n**Изменилось** — {excerpt(rec['question'], 160)}\n")
            for f in failed:
                fh.write(f"\n> Отказ источника: {f['name']} — {f['detail']}\n")

    if failed and args.fail_on_source_error:
        return 2
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Мониторинг разъяснений Банка России")
    p.add_argument("--state", default="state.json", help="файл состояния")
    p.add_argument("--report", default="docs/index.html", help="файл отчёта")
    p.add_argument("--categories", type=int, nargs="+", default=DEFAULT_CATEGORIES,
                   help="id наблюдаемых категорий")
    p.add_argument("--root", type=int, default=DEFAULT_ROOT,
                   help="id корневой категории для отслеживания новых подкатегорий")
    p.add_argument("--timeout", type=int, default=30, help="таймаут запроса, сек")
    p.add_argument("--fail-on-source-error", action="store_true",
                   help="вернуть ненулевой код при отказе источника")
    return run(p.parse_args())


if __name__ == "__main__":
    sys.exit(main())

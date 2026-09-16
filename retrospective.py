#!/usr/bin/env python3
"""
Ретроспектива: что менялось по ломбардному периметру за последние N лет.

Зачем отдельно от наблюдателя: наблюдатель отвечает на вопрос «что нового с
прошлого прогона», а ретроспектива — на вопрос «что вообще происходило».
Это разные задачи и разная периодичность.

ЧЕСТНАЯ ГРАНИЦА ГЛУБИНЫ, проверено 16.09.2026:

  * API разъяснений отдаёт ВСЕ записи категории с датой правки. Глубина —
    вся история существования записи. По ломбардам это 2020-2024 годы.
  * RSS-ленты хранят ОКНО, а не архив: от нескольких дней до пары месяцев.
    Трёхлетнюю ретроспективу из них собрать нельзя, и притворяться,
    что можно, — худшее, что может сделать такая система.

Поэтому ретроспектива строится на разъяснениях, а текущее окно RSS
показывается отдельным блоком и честно помечено как окно.
"""

from __future__ import annotations

import argparse
import html as html_mod
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import sources
from analyze import Analyzer
from b24 import Outbox


def esc(value) -> str:
    return html_mod.escape(str(value if value is not None else ""), quote=True)


def excerpt(text: str, limit: int = 300) -> str:
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def collect_explains(categories: list[int], timeout: int) -> tuple[list, list[dict]]:
    docs, log = [], []
    for cat in categories:
        try:
            got = sources.fetch_explains(cat, timeout)
            docs.extend(got)
            log.append({"name": f"Разъяснения, категория {cat}", "status": "ok",
                        "detail": f"записей: {len(got)}"})
        except Exception as exc:  # noqa: BLE001
            log.append({"name": f"Разъяснения, категория {cat}", "status": "ошибка",
                        "detail": str(exc)})
    docs.sort(key=lambda d: d.modification or "", reverse=True)
    return docs, log


def collect_rss_window(timeout: int) -> tuple[list, list[dict]]:
    docs, log = [], []
    for code, title, url in sources.RSS_FEEDS:
        try:
            got = [d for d in sources.fetch_rss(code, title, url, timeout) if d.in_perimeter]
            docs.extend(got)
            log.append({"name": f"RSS: {title}", "status": "ok",
                        "detail": f"в периметре: {len(got)}"})
        except Exception as exc:  # noqa: BLE001
            log.append({"name": f"RSS: {title}", "status": "ошибка", "detail": str(exc)})
    docs.sort(key=lambda d: d.published or "", reverse=True)
    return docs, log


# --------------------------------------------------------------- текст для Б24

def build_digest_text(recent, by_year, rss_docs, years: int, analyses: dict) -> str:
    """Сводка для чата Битрикс24. Обычный текст: чат не рендерит HTML."""
    lines = [
        f"СВОДКА ПО РЕГУЛИРОВАНИЮ ЛОМБАРДОВ — ретроспектива за {years} года",
        f"Сформирована {datetime.now(timezone.utc).strftime('%d.%m.%Y')}",
        "",
        f"Разъяснений Банка России изменено за период: {len(recent)}",
    ]
    if recent:
        newest = (recent[0].modification or "")[:10]
        lines.append(f"Самое свежее изменение: {newest}")
    lines.append("")

    if not recent:
        lines.append("За период изменений не зафиксировано.")
    else:
        lines.append("ЧТО МЕНЯЛОСЬ:")
        for doc in recent:
            date = (doc.modification or "")[:10]
            lines.append(f"  [{date}] {excerpt(doc.title, 160)}")
            a = analyses.get(doc.key)
            if a and a.get("requirements"):
                for req in a["requirements"][:2]:
                    lines.append(f"      - {req.get('text', '')}")
                    lines.append(f"        основание: {excerpt(req.get('citation', ''), 140)}")
                lines.append("      применимость предположена моделью, "
                             "ПОДТВЕРЖДЕНИЕ ЧЕЛОВЕКОМ НЕ ПОЛУЧЕНО")
        lines.append("")

    lines.append("ПОЛНАЯ ХРОНОЛОГИЯ ПО ГОДАМ:")
    for year in sorted(by_year, reverse=True):
        lines.append(f"  {year}: {len(by_year[year])}")
    lines.append("")

    lines.append(f"ТЕКУЩЕЕ ОКНО ЛЕНТ ЦБ (не архив, только последние публикации): "
                 f"{len(rss_docs)} записей в периметре")
    for doc in rss_docs[:8]:
        lines.append(f"  {excerpt(doc.title, 150)}")
        if doc.url:
            lines.append(f"    {doc.url}")
    lines.append("")
    lines.append("ГРАНИЦА ДАННЫХ: ленты ЦБ архива не отдают, глубина ретроспективы "
                 "обеспечена только разъяснениями. Полнота не гарантируется: "
                 "общие требования к НФО могут касаться ломбарда без этого слова "
                 "в заголовке.")
    return "\n".join(lines)


# --------------------------------------------------------------- HTML

CSS = """
  :root { --bg:#fbfbfa; --fg:#1a1a18; --mut:#6b6b66; --line:#e3e3df; --card:#fff;
          --acc:#2d5db3; --warn:#9a6700 }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#16161a; --fg:#e8e8e4; --mut:#9a9a94; --line:#2c2c32; --card:#1e1e24;
            --acc:#7aa2e3; --warn:#e0a72b }
  }
  * { box-sizing:border-box }
  body { margin:0; padding:2rem 1.25rem; background:var(--bg); color:var(--fg);
         font:15px/1.65 -apple-system,Segoe UI,Roboto,sans-serif }
  .wrap { max-width:900px; margin:0 auto }
  h1 { font-size:1.5rem; margin:0 0 .3rem }
  .sub { color:var(--mut); margin:0 0 1.6rem; font-size:.9rem }
  .note { background:var(--card); border:1px solid var(--line); border-left:3px solid var(--warn);
          border-radius:8px; padding:.9rem 1.1rem; margin-bottom:1.6rem; font-size:.87rem }
  h2 { font-size:1rem; text-transform:uppercase; letter-spacing:.06em; color:var(--mut);
       margin:2.2rem 0 .9rem; font-weight:600 }
  .year { display:flex; align-items:baseline; gap:.8rem; padding:.45rem 0;
          border-bottom:1px solid var(--line) }
  .year b { font-size:1.05rem; min-width:3.5rem }
  .bar { height:9px; background:var(--acc); border-radius:5px; opacity:.75 }
  .item { background:var(--card); border:1px solid var(--line); border-left:3px solid var(--acc);
          border-radius:8px; padding:.9rem 1.05rem; margin-bottom:.65rem }
  .item .d { font-family:ui-monospace,Consolas,monospace; font-size:.78rem; color:var(--acc);
             font-weight:600 }
  .item h3 { font-size:.95rem; margin:.3rem 0 .4rem; font-weight:600 }
  .item p { margin:0; font-size:.87rem; opacity:.85 }
  .old { opacity:.62 }
  .foot { margin-top:2.5rem; padding-top:1rem; border-top:1px solid var(--line);
          color:var(--mut); font-size:.8rem }
"""


def render_html(recent, by_year, rss_docs, years: int, source_log, analyses) -> str:
    maxn = max((len(v) for v in by_year.values()), default=1)
    year_rows = "".join(
        f'<div class="year"><b>{y}</b>'
        f'<div class="bar" style="width:{int(len(by_year[y]) / maxn * 72) + 4}%"></div>'
        f'<span>{len(by_year[y])}</span></div>'
        for y in sorted(by_year, reverse=True))

    def item(doc, dim=False):
        a = analyses.get(doc.key) or {}
        reqs = "".join(
            f'<p style="margin-top:.4rem">• {esc(r.get("text"))}<br>'
            f'<span style="color:var(--mut);font-style:italic">'
            f'«{esc(excerpt(r.get("citation", ""), 180))}»</span></p>'
            for r in (a.get("requirements") or [])[:3])
        return (f'<div class="item{" old" if dim else ""}">'
                f'<div class="d">{esc((doc.modification or doc.published or "")[:10])}'
                f' · {esc(doc.source_title)}</div>'
                f'<h3>{esc(excerpt(doc.title, 240))}</h3>'
                f'<p>{esc(excerpt(doc.body, 320))}</p>{reqs}</div>')

    recent_html = "".join(item(d) for d in recent) or \
        '<div class="item"><p>За период изменений не зафиксировано.</p></div>'
    rss_html = "".join(item(d, dim=True) for d in rss_docs[:12]) or \
        '<div class="item old"><p>В текущем окне лент записей в периметре нет.</p></div>'

    rows = "".join(f'<tr><td>{esc(s["name"])}</td><td>{esc(s["status"])}</td>'
                   f'<td>{esc(s["detail"])}</td></tr>' for s in source_log)

    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ретроспектива регулирования — ломбарды</title>
<style>{CSS}</style></head><body><div class="wrap">

<h1>Регулирование ломбардов: ретроспектива</h1>
<p class="sub">Разъяснения Банка России. Сформировано
{datetime.now(timezone.utc).strftime('%d.%m.%Y %H:%M')} UTC</p>

<div class="note">
  <b>Граница данных.</b> Глубина ретроспективы обеспечена только API разъяснений —
  он отдаёт все записи категории с датой правки. RSS-ленты Банка России хранят
  <b>окно последних публикаций</b>, а не архив: от нескольких дней до пары месяцев.
  Собрать из них трёхлетнюю историю невозможно, поэтому текущее окно показано
  отдельным блоком и за ретроспективу не выдаётся.
</div>

<h2>Изменения за последние {years} года</h2>
{recent_html}

<h2>Вся хронология правок по годам</h2>
{year_rows}

<h2>Текущее окно лент ЦБ — не архив</h2>
{rss_html}

<h2>Источники</h2>
<table style="width:100%;border-collapse:collapse;font-size:.85rem">
<thead><tr><th style="text-align:left;padding:.5rem;border-bottom:1px solid var(--line)">Источник</th>
<th style="text-align:left;padding:.5rem;border-bottom:1px solid var(--line)">Статус</th>
<th style="text-align:left;padding:.5rem;border-bottom:1px solid var(--line)">Подробности</th></tr></thead>
<tbody>{rows}</tbody></table>

<div class="foot">
  Дата в карточке — время правки записи, <b>не</b> дата вступления требования в силу.
  Разъяснение не является нормой: это позиция регулятора по вопросу.
  Утверждения модели, если они есть, опираются на дословную выдержку из источника
  и остаются предположениями до подтверждения человеком.
  Полнота не гарантируется: общие требования к некредитным финансовым организациям
  могут касаться ломбарда, не содержа этого слова в заголовке.
</div>

</div></body></html>
"""


# --------------------------------------------------------------- прогон

def main() -> int:
    p = argparse.ArgumentParser(description="Ретроспектива регулирования ломбардов")
    p.add_argument("--years", type=int, default=3)
    p.add_argument("--report", default="docs/retrospective.html")
    p.add_argument("--digest", default="docs/digest.txt")
    p.add_argument("--outbox", default="outbox-digest.json")
    p.add_argument("--categories", type=int, nargs="+", default=sources.EXPLAIN_CATEGORIES)
    p.add_argument("--timeout", type=int, default=30)
    p.add_argument("--send", action="store_true",
                   help="разрешить отправку сводки в Битрикс24 (нужен B24_WEBHOOK)")
    args = p.parse_args()

    explains, log1 = collect_explains(args.categories, args.timeout)
    rss_docs, log2 = collect_rss_window(args.timeout)
    source_log = log1 + log2

    cutoff = str(datetime.now(timezone.utc).year - args.years)
    recent = [d for d in explains if (d.modification or "")[:4] >= cutoff]

    by_year: dict[str, list] = {}
    for doc in explains:
        by_year.setdefault((doc.modification or "????")[:4], []).append(doc)

    # Анализ только по изменениям за период — остальное денег не стоит.
    analyzer = Analyzer()
    analyses: dict[str, dict] = {}
    for doc in recent:
        result = analyzer.analyze(doc.payload())
        if result:
            analyses[doc.key] = result

    digest_text = build_digest_text(recent, by_year, rss_docs, args.years, analyses)

    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(
        render_html(recent, by_year, rss_docs, args.years, source_log, analyses),
        encoding="utf-8")
    Path(args.digest).write_text(digest_text, encoding="utf-8")

    outbox = Outbox(args.outbox, send=args.send)
    card = {"key": f"digest:{datetime.now(timezone.utc).strftime('%Y-%m')}",
            "version": str(len(recent)),
            "title": f"Сводка по регулированию ломбардов за {args.years} года",
            "source_title": "Ретроспектива", "detected": datetime.now(timezone.utc).isoformat(),
            "level": "к сведению"}
    entry = outbox.enqueue(card, action="digest")
    entry["text"] = digest_text          # сводка идёт как есть, без переупаковки
    outbox.flush()
    outbox.save()

    print(f"Ретроспектива за {args.years} года")
    print(f"  разъяснений всего:        {len(explains)}")
    print(f"  изменено за период:       {len(recent)}")
    if recent:
        print(f"  самое свежее изменение:   {(recent[0].modification or '')[:10]}")
    print(f"  по годам:                 "
          f"{', '.join(f'{y}: {len(v)}' for y in sorted(by_year, reverse=True) for v in [by_year[y]])}")
    print(f"  окно лент, в периметре:   {len(rss_docs)}")
    print(f"  модель:                   {analyzer.status_line()}")
    print(f"  Битрикс24:                {outbox.status_line()}")
    print(f"  отчёт:                    {args.report}")
    print(f"  текст сводки:             {args.digest}")

    failed = [s for s in source_log if s["status"] != "ok"]
    if failed:
        print(f"  ОТКАЗОВ ИСТОЧНИКОВ: {len(failed)}")
        for f in failed:
            print(f"    - {f['name']}: {f['detail']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

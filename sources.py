"""
Источники Банка России.

Два типа:
  * API разъяснений — структурированный JSON, поля id/modification/question/answer;
  * RSS-ленты — новости, пресс-релизы, события и проекты нормативных актов.

Каждый источник возвращает список Document — единый вид, чтобы дальше по конвейеру
не различать, откуда пришла запись.
"""

from __future__ import annotations

import html
import json
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, asdict

API_BASE = "https://www.cbr.ru/ExplainApi/v1"
USER_AGENT = "regulatory-monitor/0.2 (+internal compliance monitoring)"

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")

# Ленты RSS Банка России. Проверены 16.09.2026.
RSS_FEEDS = [
    ("cbr-project", "Проекты нормативных актов", "https://www.cbr.ru/rss/project"),
    ("cbr-press", "Пресс-релизы", "https://www.cbr.ru/rss/RssPress"),
    ("cbr-news", "Новое на сайте", "https://www.cbr.ru/rss/RssNews"),
    ("cbr-events", "События и комментарии", "https://www.cbr.ru/rss/eventrss"),
]

# Категории API разъяснений: «Оформление залогового билета» и «Отчётность → Ломбарды».
EXPLAIN_CATEGORIES = [774, 378]
EXPLAIN_ROOT = 426

# Периметр первой очереди. Это НЕ решение о применимости — только машинный отбор
# того, что имеет смысл показывать модели. Всё остальное сохраняется, но в анализ
# не идёт и попадает в лист отсева.
#
# Отбор двухуровневый. Одноуровневый список словами вроде «потребительск»
# затягивал макроэкономические доклады ЦБ про потребительскую активность —
# формально совпадение есть, к ломбардам отношения нет.

# Сильные термины: одного достаточно, периметр определяется однозначно.
PERIMETER_STRONG = [
    "ломбард", "залогов билет", "залоговый билет", "невостребованн вещ",
    "некредитн финансов", "нфо", "микрофинанс", "микрозайм",
    "ювелирн", "драгоценн металл", "драгоценн камн",
]

# Слабые термины: сами по себе ничего не значат, засчитываются только в паре
# с финансовым контекстом. «Заём» в докладе о ставках — не наш сигнал,
# «заём» рядом со словом «ломбард» или «отчётность» — наш.
PERIMETER_WEAK = ["потребительск", "заём", "заем", "залог", "оценк имуществ"]
PERIMETER_CONTEXT = [
    "указание банка россии", "положение банка россии", "требован",
    "отчетност", "отчётност", "форма 0420", "надзор", "реестр",
    "проект нормативн", "внесении изменений",
]

# Ложные друзья. «Ломбардный список» Банка России — это перечень ценных бумаг,
# принимаемых в обеспечение по кредитам ЦБ. К ломбардам как виду деятельности
# он не имеет никакого отношения, но совпадает по корню слова и без этого
# исключения регулярно засоряет периметр.
PERIMETER_EXCLUDE = [
    "ломбардн список", "ломбардного списка", "ломбардный список",
    "ломбардном списке", "ломбардным списком", "ломбардный кредит",
    "ломбардного кредитования", "ломбардных кредит",
]


# Собственный рубрикатор правовых актов Банка России: /na/?la.TagId=N
#
# Это главный источник. Разъяснения — FAQ по заполнению форм, ленты — новости;
# настоящие указания, положения и информационные письма лежат здесь, и регулятор
# сам проставляет им тему. Никаких ключевых слов и ложных друзей вроде
# «Ломбардного списка» или зданий-памятников с названием «Ломбард».
#
# Проверено 17.09.2026: тема 15 — 54 документа, 22 — 215, 209 — 47, 168 — 187.
NA_URL = "https://www.cbr.ru/na/"
NA_TOPICS = [
    (15, "Ломбарды"),
    (209, "Некредитные финансовые организации"),
    (168, "Бухгалтерский учет и отчетность в НФО"),
]
# Темы, которые можно добавить при расширении периметра:
#   22 — Микрофинансирование (215 документов, шире нашего)
#   53 — Защита прав потребителей финансовых услуг
#   193 — Противодействие отмыванию денег
#   177 — Потребительское кредитование

# Постраничная выдача. Обычная страница отдаёт первые 10; остальное —
# через тот же адрес, каким пользуется кнопка «Загрузить еще».
NA_PAGE_URL = "https://www.cbr.ru/Crosscut/LawActs/Page/94917"
NA_PAGE_LIMIT = 20          # предохранитель: 20 страниц это 200 документов

NA_SPLIT_RE = re.compile(r'<div class="cross-result[^"]*"\s+data-doc-id="(\d+)"')
NA_NUMBER_RE = re.compile(r'<span class="number[^"]*">(.*?)</span>', re.S)
NA_DATE_RE = re.compile(r'<span class="date[^"]*">(.*?)</span>', re.S)
NA_SOURCE_RE = re.compile(r'<div class="source">(.*?)</div>', re.S)
NA_ZOOM_RE = re.compile(r'data-zoom-title="([^"]*)"')
NA_HREF_RE = re.compile(r'href="([^"]+)"')


@dataclass
class Document:
    """Единый вид записи независимо от источника."""
    key: str                  # устойчивый ключ: источник + внешний id
    source: str               # код источника
    source_title: str         # человекочитаемое имя источника
    external_id: str
    title: str                # нормализованный заголовок
    body: str                 # нормализованный текст
    url: str = ""
    published: str = ""       # дата публикации как её отдаёт источник
    modification: str = ""    # время правки, НЕ дата вступления в силу
    category: str = ""
    in_perimeter: bool = False

    def payload(self) -> str:
        """Текст, от которого считается хеш и который уходит в анализ."""
        return f"{self.title}\n{self.body}".strip()

    def as_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------- вспомогательное

def normalize_text(raw: str | None) -> str:
    """Хеш должен меняться от смысла, а не от вёрстки."""
    if not raw:
        return ""
    text = TAG_RE.sub(" ", raw)
    text = html.unescape(text)
    text = text.replace(" ", " ")
    return WS_RE.sub(" ", text).strip()


def in_perimeter(*parts: str) -> bool:
    """Сильный термин — сразу да. Слабый — только вместе с финансовым контекстом.

    Отбор намеренно щедрый: пропустить публикацию хуже, чем показать лишнюю.
    Но щедрый не значит бессмысленный — макродоклады про потребительскую
    активность в периметр попадать не должны."""
    blob = " ".join(p for p in parts if p).lower().replace("ё", "е")
    if any(w.replace("ё", "е") in blob for w in PERIMETER_EXCLUDE):
        return False
    if any(w.replace("ё", "е") in blob for w in PERIMETER_STRONG):
        return True
    weak_hit = any(w.replace("ё", "е") in blob for w in PERIMETER_WEAK)
    context_hit = any(w.replace("ё", "е") in blob for w in PERIMETER_CONTEXT)
    return weak_hit and context_hit


def _fetch(url: str, timeout: int, attempts: int = 3) -> bytes:
    """GET с повторами. Последняя ошибка пробрасывается — отказ источника
    обязан быть виден, а не проглочен."""
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json, application/rss+xml, */*",
            })
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt < attempts:
                time.sleep(2 ** attempt)
    raise last  # type: ignore[misc]


def fetch_json(url: str, timeout: int = 30):
    return json.loads(_fetch(url, timeout).decode("utf-8"))


def as_list(payload) -> list:
    if payload is None:
        return []
    return payload if isinstance(payload, list) else [payload]


# --------------------------------------------------------------- API разъяснений

def fetch_subcategories(root: int, timeout: int = 30) -> list[int]:
    """Родительская категория не содержит записей дочерних — дерево надо обходить,
    а появление новой подкатегории замечать."""
    tree = fetch_json(f"{API_BASE}/categories/{root}", timeout)
    return [int(c["id"]) for c in as_list(tree) if isinstance(c, dict) and "id" in c]


def fetch_explains(category: int, timeout: int = 30) -> list[Document]:
    raw = as_list(fetch_json(f"{API_BASE}/categories/{category}/explains", timeout))
    docs: list[Document] = []
    for it in raw:
        question = normalize_text(it.get("questionHtml"))
        answer = normalize_text(it.get("answerHtml"))
        docs.append(Document(
            key=f"explain:{category}:{it.get('id')}",
            source="cbr-explain",
            source_title=f"Разъяснения, категория {category}",
            external_id=str(it.get("id")),
            title=question,
            body=answer,
            url=f"https://www.cbr.ru/explain/{category}/",
            modification=str(it.get("modification") or ""),
            category=str(category),
            # Разъяснения по ломбардным категориям в периметре по определению:
            # мы сами выбрали эти категории.
            in_perimeter=True,
        ))
    return docs


# --------------------------------------------------------------- RSS

DEADLINE_RE = re.compile(r"по\s+(\d{2}\.\d{2}\.\d{4})")


def parse_rss(xml_bytes: bytes, source: str, source_title: str) -> list[Document]:
    text = xml_bytes.decode("utf-8-sig", errors="replace")
    root = ET.fromstring(text)
    docs: list[Document] = []

    for item in root.iter("item"):
        def get(tag: str) -> str:
            node = item.find(tag)
            return (node.text or "").strip() if node is not None and node.text else ""

        title = normalize_text(get("title"))
        description = normalize_text(get("description"))
        category = normalize_text(get("category"))
        link = get("link")
        guid = get("guid") or link or title

        docs.append(Document(
            key=f"{source}:{guid}",
            source=source,
            source_title=source_title,
            external_id=guid,
            title=title,
            body=description,
            url=link,
            published=get("pubDate"),
            category=category,
            in_perimeter=in_perimeter(title, description, category),
        ))
    return docs


def fetch_rss(source: str, source_title: str, url: str, timeout: int = 30) -> list[Document]:
    return parse_rss(_fetch(url, timeout), source, source_title)


def _parse_acts_page(html_text: str, tag_id: int, tag_name: str) -> list[Document]:
    """Разбор одной страницы выдачи. Блоки режем по data-doc-id, поля тянем
    внутри блока — одним большим выражением получалось хрупко."""
    docs: list[Document] = []
    marks = list(NA_SPLIT_RE.finditer(html_text))

    for i, mark in enumerate(marks):
        start = mark.end()
        end = marks[i + 1].start() if i + 1 < len(marks) else len(html_text)
        block = html_text[start:end]
        doc_id = mark.group(1)

        def first(rx: re.Pattern, default: str = "") -> str:
            m = rx.search(block)
            return normalize_text(m.group(1)) if m else default

        number = first(NA_NUMBER_RE).lstrip("№").strip()
        date = first(NA_DATE_RE).replace("от ", "").strip()
        kind = first(NA_SOURCE_RE)
        # data-zoom-title несёт канонический заголовок целиком — с типом,
        # номером, датой и названием. Он полнее видимого текста ссылки,
        # который обрезается вёрсткой.
        title = first(NA_ZOOM_RE)
        href_m = NA_HREF_RE.search(block)
        href = href_m.group(1) if href_m else ""
        url = href if href.startswith("http") else f"https://www.cbr.ru{href}"

        docs.append(Document(
            key=f"na:{doc_id}",
            source="cbr-na",
            source_title=f"Правовые акты ЦБ: {tag_name}",
            external_id=doc_id,
            title=title or f"{kind} № {number} от {date}".strip(),
            body=f"{kind} № {number} от {date}".strip(),
            url=url,
            published=date,
            category=f"{tag_name} / {kind}",
            # Тему проставил сам регулятор — это и есть периметр, без догадок.
            in_perimeter=True,
        ))
    return docs


def fetch_legal_acts(tag_id: int, tag_name: str, timeout: int = 30,
                     max_pages: int = NA_PAGE_LIMIT) -> list[Document]:
    """Правовые акты Банка России по теме его собственного рубрикатора.

    Выдача постраничная по 10 записей, отсортирована по убыванию даты."""
    docs: list[Document] = []
    seen: set[str] = set()

    for page in range(max_pages):
        url = f"{NA_PAGE_URL}?TagId={tag_id}&Date.Time=Any&Page={page}"
        chunk = _parse_acts_page(
            _fetch(url, timeout).decode("utf-8", errors="replace"), tag_id, tag_name)
        fresh = [d for d in chunk if d.key not in seen]
        if not fresh:
            break                      # страницы кончились или пошли повторы
        seen.update(d.key for d in fresh)
        docs.extend(fresh)
        if len(chunk) < 10:
            break                      # неполная страница — она последняя
    return docs


def extract_comment_deadline(category: str) -> str:
    """У проектов НПА срок приёма замечаний лежит прямо в category:
    «Департамент страхового рынка (по 16.10.2026)».

    Это срок ОБСУЖДЕНИЯ, а не дата вступления требования в силу. Смешивать нельзя."""
    match = DEADLINE_RE.search(category or "")
    return match.group(1) if match else ""


# --------------------------------------------------------------- сбор всего

def collect(*, categories: list[int], root: int, timeout: int,
            feeds=RSS_FEEDS) -> tuple[list[Document], list[dict], list[int]]:
    """Возвращает документы, журнал источников и список подкатегорий.

    Журнал источников обязателен: отказ источника и отсутствие изменений —
    разные события, и путать их нельзя."""
    documents: list[Document] = []
    log: list[dict] = []
    subcategories: list[int] = []

    try:
        subcategories = fetch_subcategories(root, timeout)
        log.append({"name": f"Дерево категорий {root}", "status": "ok",
                    "detail": f"подкатегорий: {len(subcategories)}"})
    except Exception as exc:  # noqa: BLE001
        log.append({"name": f"Дерево категорий {root}", "status": "ошибка",
                    "detail": str(exc)})

    for cat in categories:
        try:
            docs = fetch_explains(cat, timeout)
            documents.extend(docs)
            log.append({"name": f"Разъяснения, категория {cat}", "status": "ok",
                        "detail": f"записей: {len(docs)}"})
        except Exception as exc:  # noqa: BLE001
            log.append({"name": f"Разъяснения, категория {cat}", "status": "ошибка",
                        "detail": str(exc)})

    # Главный источник: правовые акты по темам рубрикатора ЦБ.
    for tag_id, tag_name in NA_TOPICS:
        try:
            docs = fetch_legal_acts(tag_id, tag_name, timeout)
            documents.extend(docs)
            log.append({"name": f"Правовые акты ЦБ: {tag_name}", "status": "ok",
                        "detail": f"документов: {len(docs)}"})
        except Exception as exc:  # noqa: BLE001
            log.append({"name": f"Правовые акты ЦБ: {tag_name}", "status": "ошибка",
                        "detail": str(exc)})

    for source, title, url in feeds:
        try:
            docs = fetch_rss(source, title, url, timeout)
            documents.extend(docs)
            hits = sum(1 for d in docs if d.in_perimeter)
            log.append({"name": f"RSS: {title}", "status": "ok",
                        "detail": f"записей: {len(docs)}, в периметре: {hits}"})
        except Exception as exc:  # noqa: BLE001
            log.append({"name": f"RSS: {title}", "status": "ошибка",
                        "detail": str(exc)})

    return documents, log, subcategories

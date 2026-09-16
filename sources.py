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
# не идёт и попадает в еженедельный лист отсева.
PERIMETER = [
    "ломбард", "залогов", "некредитн", "нфо", "микрофинанс",
    "ювелирн", "драгоценн", "потребительск", "заём", "заем",
]


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
    blob = " ".join(p for p in parts if p).lower()
    return any(word in blob for word in PERIMETER)


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

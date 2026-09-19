"""Прозрачный бесплатный отбор уведомлений без обращения к модели."""
from __future__ import annotations

import hashlib

URGENT = ("вступает в силу завтра", "вступает в силу сегодня", "отзыв лицензии", "запрет")
IMPORTANT = ("ломбард", "пск", "залогов", "микрофинанс", "нфо", "отчётност")


def classify_alert(document: dict, change: str) -> dict | None:
    """Возвращает карточку alert только для нового/изменённого релевантного текста."""
    if change not in {"new", "changed"}:
        return None
    text = " ".join(str(document.get(k, "")) for k in ("title", "body", "text")).lower()
    if not any(word in text for word in IMPORTANT):
        return None
    level = "urgent" if any(word in text for word in URGENT) else "important"
    reason = "критическое ключевое слово" if level == "urgent" else "отраслевое ключевое слово"
    raw = f"{document.get('key', document.get('url', ''))}|{document.get('version', '')}|{change}"
    return {
        "level": level,
        "reason": reason,
        "idempotency_key": "RM-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12].upper(),
        "title": str(document.get("title", ""))[:300],
        "url": str(document.get("url", "")),
        "source": str(document.get("source_title", document.get("source", ""))),
    }

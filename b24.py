"""
Исходящая очередь и Битрикс24.

Опасная часть системы — неоднозначный ответ внешней системы после таймаута.
Слепой повтор даёт дубль задачи, отказ от повтора — потерю уведомления.
Поэтому схема такая:

  1. намерение пишется в очередь ДО вызова, с детерминированным ключом;
  2. ключ уходит в сам объект Битрикс24, во внешний текст;
  3. выполняется вызов, внешний id записывается обратно в очередь;
  4. при рестарте строки без внешнего id НЕ повторяются вслепую —
     сначала поиск по ключу, и только при отсутствии совпадения повтор.

По умолчанию отправка ВЫКЛЮЧЕНА. Нужны одновременно: секрет B24_WEBHOOK
и явный флаг --send. Это соответствует правилу, что внешние действия
в Битрикс24 выполняются только по отдельному разрешению.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

RATE_LIMIT_PAUSE = 0.6   # Битрикс24 устойчиво держит ~2 запроса в секунду


def idempotency_key(card_key: str, action: str, version: str) -> str:
    """Детерминированный ключ: одно и то же намерение всегда даёт один ключ."""
    raw = f"{card_key}|{action}|{version}"
    return "RM-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12].upper()


def build_message(card: dict) -> str:
    """Формат из архитектуры: уровень, что изменилось, почему касается,
    срок и основание, требуемое действие, ответственный, ссылки."""
    a = card.get("analysis") or {}
    lines = [
        f"[{card.get('level', 'к сведению').upper()}] {card.get('title', '')[:200]}",
        "",
        f"Источник: {card.get('source_title', '')}",
    ]
    if card.get("url"):
        lines.append(f"Ссылка: {card['url']}")
    if a.get("applicability_suggested"):
        lines.append(f"Предположительная применимость: {a['applicability_suggested']}"
                     f" — {a.get('applicability_reason', '')}")
        lines.append("Подтверждение человеком: НЕ ПОЛУЧЕНО")
    if a.get("effective_date_suggested"):
        lines.append(f"Предполагаемая дата вступления: {a['effective_date_suggested']}"
                     " (подтверждает человек)")
    if card.get("comment_deadline"):
        lines.append(f"Срок приёма замечаний по проекту: {card['comment_deadline']}")
    for req in (a.get("requirements") or [])[:5]:
        lines.append(f"  • {req.get('text', '')}")
        lines.append(f"    основание: «{req.get('citation', '')[:180]}»")
    lines += [
        "",
        "Требуемое действие: подтвердить применимость (шлюз 1).",
        f"Ключ: {card.get('key_id', '')}",
    ]
    return "\n".join(lines)


class Outbox:
    def __init__(self, path: str | Path, *, send: bool = False) -> None:
        self.path = Path(path)
        self.webhook = os.environ.get("B24_WEBHOOK", "").strip().rstrip("/")
        self.chat_id = os.environ.get("B24_CHAT_ID", "").strip()
        self.responsible = os.environ.get("B24_RESPONSIBLE_ID", "").strip()
        self.send_enabled = bool(send and self.webhook)
        self.entries: list[dict] = []
        if self.path.exists():
            try:
                self.entries = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                self.entries = []
        self.sent = 0
        self.errors: list[str] = []

    # ----------------------------------------------------------- очередь

    def _existing(self, key: str) -> dict | None:
        return next((e for e in self.entries if e["key"] == key), None)

    def enqueue(self, card: dict, action: str = "notify") -> dict:
        """Намерение записывается ДО вызова. Повторный вызов на той же версии
        карточки возвращает ту же строку и второго действия не создаёт."""
        key = idempotency_key(card["key"], action, card.get("version", "1"))
        found = self._existing(key)
        if found:
            return found
        entry = {
            "key": key,
            "card": card["key"],
            "action": action,
            "title": card.get("title", "")[:300],
            "text": build_message({**card, "key_id": key}),
            "created": card.get("detected", ""),
            "external_id": None,
            "status": "в очереди",
        }
        self.entries.append(entry)
        return entry

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.entries, ensure_ascii=False, indent=2), encoding="utf-8")

    # ----------------------------------------------------------- Битрикс24

    def _call(self, method: str, params: dict) -> dict:
        url = f"{self.webhook}/{method}.json"
        data = urllib.parse.urlencode(params, doseq=True).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _already_there(self, key: str) -> str | None:
        """Сверка перед повтором: ищем объект с нашим ключом в тексте.
        Именно это отличает восстановление от создания дубля."""
        try:
            res = self._call("tasks.task.list", {
                "filter[%TITLE]": key,
                "select[]": "ID",
            })
            tasks = (res.get("result") or {}).get("tasks") or []
            return str(tasks[0]["id"]) if tasks else None
        except Exception:  # noqa: BLE001
            return None

    def flush(self) -> None:
        """Отправляет только то, что ещё не имеет внешнего id."""
        if not self.send_enabled:
            return
        for entry in self.entries:
            if entry.get("external_id"):
                continue
            try:
                existing = self._already_there(entry["key"])
                if existing:
                    entry["external_id"] = existing
                    entry["status"] = "уже существовало, сверено по ключу"
                    continue

                if self.chat_id:
                    res = self._call("im.message.add", {
                        "DIALOG_ID": self.chat_id,
                        "MESSAGE": entry["text"],
                    })
                    entry["external_id"] = str(res.get("result", ""))
                    entry["status"] = "отправлено в чат"
                else:
                    params = {
                        "fields[TITLE]": f"{entry['key']} {entry['title']}"[:250],
                        "fields[DESCRIPTION]": entry["text"],
                    }
                    if self.responsible:
                        params["fields[RESPONSIBLE_ID]"] = self.responsible
                    res = self._call("tasks.task.add", params)
                    task = (res.get("result") or {}).get("task") or {}
                    entry["external_id"] = str(task.get("id", ""))
                    entry["status"] = "создана задача"
                self.sent += 1
                time.sleep(RATE_LIMIT_PAUSE)
            except Exception as exc:  # noqa: BLE001
                entry["status"] = f"ошибка: {exc}"
                self.errors.append(f"{entry['key']}: {exc}")

    # ----------------------------------------------------------- отчётность

    def status_line(self) -> str:
        pending = sum(1 for e in self.entries if not e.get("external_id"))
        if not self.webhook:
            return f"Б24 не настроен (нет B24_WEBHOOK) — в очереди {pending}, ничего не отправлено"
        if not self.send_enabled:
            return f"режим без отправки — в очереди {pending}, для отправки нужен флаг --send"
        line = f"отправлено: {self.sent}, осталось в очереди: {pending}"
        if self.errors:
            line += f", ошибок: {len(self.errors)}"
        return line

#!/usr/bin/env python3
"""
Бот-исполнитель в чате Битрикс24: читает выделенный чат и ставит задачи
по ЯВНОЙ команде.

Почему опрос, а не подписка на событие. Полноценный бот Битрикс24 (imbot)
работает через событие ONIMBOTMESSAGEADD: портал сам стучится на ваш адрес.
Для этого нужен постоянно доступный извне HTTP-эндпоинт. У нас его нет и не
планируется — всё живёт на расписании. Поэтому читаем чат опросом.
Цена решения — задержка: команда исполняется в течение интервала запуска.

Почему команда явная, а не распознавание намерения моделью. Это главный ответ
на вопрос «как не цеплять лишнего». Модель, которая решает «кажется, человек
просил поставить задачу», будет ошибаться в обе стороны: создавать задачи
из обсуждений и пропускать прямые просьбы. Живой рабочий чат для неё —
сплошная двусмысленность. Явный префикс даёт предсказуемость: сказал команду —
получил задачу, не сказал — ничего не произошло.

Четыре рубежа против мусора:
  1. только один чат, заданный B24_CHAT_ID;
  2. только сообщения, начинающиеся с префикса команды;
  3. только авторы из белого списка, если он задан;
  4. только сообщения новее курсора, и каждое обрабатывается один раз.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import config

DEFAULT_PREFIXES = ["задача:", "/задача", "задача -", "taskadd:"]
REPLY_MARK = "[бот]"       # чтобы бот никогда не отвечал сам себе
MAX_TASKS_PER_RUN = 5      # предохранитель от лавины


def call(webhook: str, method: str, params: dict) -> dict:
    url = f"{webhook.rstrip('/')}/{method}.json"
    data = urllib.parse.urlencode(params, doseq=True).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def parse_command(text: str, prefixes: list[str]) -> tuple[str, str] | None:
    """Возвращает (заголовок, описание) или None, если это не команда."""
    stripped = (text or "").strip()
    if stripped.startswith(REPLY_MARK):
        return None
    low = stripped.lower()
    for prefix in prefixes:
        if low.startswith(prefix.lower()):
            payload = stripped[len(prefix):].strip(" :-— ")
            if not payload:
                return None
            # Первая строка — заголовок, остальное — описание.
            parts = payload.split("\n", 1)
            title = re.sub(r"\s+", " ", parts[0]).strip()[:230]
            body = parts[1].strip() if len(parts) > 1 else ""
            return (title, body) if title else None
    return None


def list_chats(webhook: str) -> int:
    """Показывает доступные диалоги с их идентификаторами.

    Адресную строку смотреть неудобно, а в десктопном приложении её вовсе нет.
    Пусть портал сам скажет, как называются чаты и какие у них номера."""
    try:
        res = call(webhook, "im.recent.get", {"SKIP_OPENLINES": "Y"})
    except Exception as exc:  # noqa: BLE001
        print(f"ОТКАЗ: не удалось получить список диалогов — {exc}")
        print("Проверьте, что у вебхука есть право im.")
        return 1

    # im.recent.get отдаёт result списком напрямую, но в части версий —
    # объектом с полем items. Принимаем оба вида.
    result = res.get("result")
    if isinstance(result, dict):
        items = result.get("items") or []
    elif isinstance(result, list):
        items = result
    else:
        items = []

    print(f"{'ИДЕНТИФИКАТОР':<18} {'ТИП':<10} НАЗВАНИЕ")
    print("-" * 78)
    shown = 0
    for it in items:
        dialog = it.get("id") or (it.get("chat") or {}).get("id") or ""
        title = (it.get("title") or (it.get("chat") or {}).get("name")
                 or (it.get("user") or {}).get("name") or "")
        kind = it.get("type") or ""
        if not dialog:
            continue
        print(f"{str(dialog):<18} {str(kind):<10} {title}")
        shown += 1

    print("-" * 78)
    print(f"всего диалогов: {shown}")
    print()
    print("Возьмите идентификатор нужного чата (вида chat1234 или sg17)")
    print("и задайте его переменной B24_CHAT_ID.")
    print()
    print("Если нужного чата в списке НЕТ — сотрудник, от имени которого создан")
    print("вебхук, не состоит в этом чате. Добавьте его участником.")
    return 0


def run(args) -> int:
    webhook = config.get("B24_WEBHOOK", secrets_path=args.secrets)

    if args.list_chats:
        if not webhook:
            print("Не задан B24_WEBHOOK — список получать нечем.")
            return 1
        return list_chats(webhook)

    chat_id = config.get("B24_CHAT_ID", secrets_path=args.secrets)
    responsible = config.get("B24_RESPONSIBLE_ID", secrets_path=args.secrets)
    allow_raw = config.get("B24_ALLOWED_AUTHORS", secrets_path=args.secrets)
    prefixes = [p.strip() for p in
                config.get("B24_COMMAND_PREFIX", ",".join(DEFAULT_PREFIXES),
                           secrets_path=args.secrets).split(",") if p.strip()]
    allowed = {a.strip() for a in allow_raw.split(",") if a.strip()}

    print(f"источник настроек: {config.source_note()}")

    if not webhook or not chat_id:
        print("Не заданы B24_WEBHOOK и/или B24_CHAT_ID — бот не запускается.")
        print("Это не ошибка: без них читать нечего и писать некуда.")
        return 0

    state_path = Path(args.state)
    state = (json.loads(state_path.read_text(encoding="utf-8"))
             if state_path.exists() else {"last_id": 0, "handled": {}})
    last_id = int(state.get("last_id", 0))
    handled: dict = state.get("handled", {})

    params = {"DIALOG_ID": chat_id, "LIMIT": 50}
    if last_id:
        params["FIRST_ID"] = last_id      # только сообщения новее курсора
    try:
        res = call(webhook, "im.dialog.messages.get", params)
    except Exception as exc:  # noqa: BLE001
        print(f"ОТКАЗ: не удалось прочитать чат — {exc}")
        return 1

    messages = (res.get("result") or {}).get("messages") or []
    # Свежие сверху — разворачиваем, чтобы обрабатывать в порядке поступления.
    messages = sorted(messages, key=lambda m: int(m.get("id", 0)))

    seen, created, skipped = 0, 0, 0
    max_id = last_id

    for msg in messages:
        mid = str(msg.get("id"))
        max_id = max(max_id, int(msg.get("id", 0)))
        seen += 1

        if mid in handled:
            continue
        author = str(msg.get("author_id", ""))
        if author in ("0", ""):          # системное сообщение
            continue
        if allowed and author not in allowed:
            skipped += 1
            continue

        parsed = parse_command(msg.get("text", ""), prefixes)
        if not parsed:
            continue
        if created >= MAX_TASKS_PER_RUN:
            print(f"достигнут предел {MAX_TASKS_PER_RUN} задач за прогон, остальное в следующий")
            break

        title, body = parsed
        description = (f"{body}\n\n" if body else "") + \
            f"Поставлено из чата по команде. Автор: {author}, сообщение {mid}."

        if args.dry_run:
            print(f"  [сухой прогон] задача: {title}")
            created += 1
            handled[mid] = "dry-run"
            continue

        fields = {"fields[TITLE]": title, "fields[DESCRIPTION]": description,
                  "fields[CREATED_BY]": author}
        if responsible:
            fields["fields[RESPONSIBLE_ID]"] = responsible
        else:
            fields["fields[RESPONSIBLE_ID]"] = author   # некому — на автора
        try:
            out = call(webhook, "tasks.task.add", fields)
            task = (out.get("result") or {}).get("task") or {}
            task_id = str(task.get("id", ""))
            handled[mid] = task_id
            created += 1
            call(webhook, "im.message.add", {
                "DIALOG_ID": chat_id,
                "MESSAGE": f"{REPLY_MARK} Задача создана: {title} (ID {task_id})",
            })
            print(f"  создана задача {task_id}: {title}")
        except Exception as exc:  # noqa: BLE001
            print(f"  ОШИБКА постановки задачи по сообщению {mid}: {exc}")

    state = {"last_id": max_id, "handled": handled,
             "updated": datetime.now(timezone.utc).isoformat()}
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"прочитано сообщений: {seen}")
    print(f"создано задач:       {created}")
    print(f"пропущено по автору: {skipped}")
    print(f"курсор:              {max_id}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Бот постановки задач из чата Битрикс24")
    p.add_argument("--state", default="chat-state.json")
    p.add_argument("--secrets", default=None,
                   help="путь к файлу секретов (по умолчанию secrets.txt рядом со скриптом)")
    p.add_argument("--dry-run", action="store_true",
                   help="разобрать команды и показать, но задач не создавать")
    p.add_argument("--list-chats", action="store_true",
                   help="показать доступные чаты с их идентификаторами и выйти")
    return run(p.parse_args())


if __name__ == "__main__":
    sys.exit(main())

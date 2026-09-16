"""
Конфигурация: один текстовый файл либо переменные окружения.

Порядок поиска значения:
    1. файл секретов (по умолчанию secrets.txt рядом со скриптом);
    2. переменная окружения;
    3. значение по умолчанию.

Файл удобнее, когда всё живёт на одной машине и сервис может однажды стать
ненужным: удалил файл — доступов больше нет, ничего выковыривать из настроек
не надо.

ВАЖНОЕ ОГРАНИЧЕНИЕ, о котором легко забыть:
    файл секретов работает ТОЛЬКО там, где этот файл физически лежит.
    GitHub Actions ваш диск не видит. При запуске в облаке значения обязаны
    приходить из Secrets репозитория — третьего пути нет.

Формат файла — простые пары, решётка начинает комментарий:

    # комментарий
    B24_WEBHOOK = https://portal.bitrix24.ru/rest/12/xxxxxxxx/
    B24_CHAT_ID = chat1234
    LLM_API_KEY = sk-...
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

DEFAULT_SECRETS_NAME = "secrets.txt"

_cache: dict[str, str] | None = None
_source_note = "переменные окружения"


def _gitignore_covers(path: Path) -> bool:
    """Файл с вебхуком и ключами не должен попасть в репозиторий никогда."""
    for parent in [path.parent, *path.parent.parents]:
        gi = parent / ".gitignore"
        if gi.exists():
            try:
                lines = [ln.strip() for ln in gi.read_text(encoding="utf-8").splitlines()]
            except Exception:  # noqa: BLE001
                continue
            if path.name in lines or f"/{path.name}" in lines or "secrets*" in lines:
                return True
        if (parent / ".git").exists():
            break
    return False


def load(secrets_path: str | Path | None = None) -> dict[str, str]:
    """Читает файл секретов, если он есть. Повторные вызовы берут из кеша."""
    global _cache, _source_note
    if _cache is not None:
        return _cache

    path = Path(secrets_path) if secrets_path else Path(__file__).with_name(DEFAULT_SECRETS_NAME)
    values: dict[str, str] = {}

    if path.exists():
        # Громкая защита от самой дорогой ошибки в этой схеме.
        if not _gitignore_covers(path):
            print(f"ВНИМАНИЕ: {path.name} не закрыт .gitignore. "
                  f"Не коммитьте его — внутри вебхук и ключи.", file=sys.stderr)
        for raw in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            name, _, value = line.partition("=")
            value = value.strip().strip('"').strip("'")
            if value:
                values[name.strip().upper()] = value
        _source_note = f"файл {path.name} ({len(values)} значений)"
    _cache = values
    return values


def get(name: str, default: str = "", secrets_path: str | Path | None = None) -> str:
    """Файл важнее окружения: если значение задано в файле, берётся оно.

    Пустая строка считается отсутствием — GitHub Actions подставляет незаданный
    секрет именно пустой строкой, а не убирает переменную."""
    from_file = load(secrets_path).get(name.upper(), "").strip()
    if from_file:
        return from_file
    from_env = os.environ.get(name, "").strip()
    return from_env if from_env else default


def get_int(name: str, default: int) -> int:
    try:
        return int(get(name, str(default)))
    except ValueError:
        return default


def source_note() -> str:
    load()
    return _source_note

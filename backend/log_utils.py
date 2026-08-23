"""Подготовка значений к записи в лог: чужие управляющие символы и наши секреты."""

import logging
import re

# Управляющие символы C0 плюс DEL. ESC в терминале исполняется как команда, а перевод строки
# в значении из тела запроса даёт поддельную запись. В json-логе форматтер экранирует такое сам.
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")

# Потолок на длину значения в логе. Со своим адресом LLM клиент управляет и текстом ответа
# провайдера, и телом регистра, поэтому без потолка в лог наливается сколько угодно.
MAX_LOGGED_VALUE_CHARS = 1000


def sanitize_for_log(value: str, max_len: int = MAX_LOGGED_VALUE_CHARS) -> str:
    """Обрезает значение до max_len и заменяет управляющие символы на \\xNN.

    Под замену идут только управляющие символы, поэтому кириллица в путях и именах файлов
    остаётся читаемой. Обрезка идёт до экранирования, иначе она рубила бы `\\xNN` посередине.
    """
    if len(value) > max_len:
        value = f"{value[:max_len]}… (обрезано, всего {len(value)} симв.)"
    return _CONTROL_CHARS.sub(lambda m: f"\\x{ord(m.group()):02x}", value)


# Токен бота в пути запроса к Bot API — логгер httpx на INFO печатает полный URL. Хвост берётся
# до следующего слэша, набор разрешённых символов обрезал бы токен с неожиданным символом.
_BOT_TOKEN_IN_URL = re.compile(r"/bot\d+:[^/\s]+")


class SecretRedactingFilter(logging.Filter):
    """Вырезает секреты из готовых сообщений, включая записи чужих логгеров.

    Фильтром, а не уровнем логгера — поднять httpx до WARNING убрало бы из лога и строки
    обращений к LLM. Трейсбек не правится, в текстах исключений httpx URL не появляется.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = _BOT_TOKEN_IN_URL.sub("/bot<redacted>", message)
        if redacted != message:
            # Подстановка уже выполнена, иначе %-аргументы применятся второй раз
            record.msg = redacted
            record.args = None
        return True

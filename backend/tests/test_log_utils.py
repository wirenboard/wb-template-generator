"""Тесты подготовки значений к записи в лог (log_utils.py)."""

import logging
import sys
from pathlib import Path

import pytest

# Добавляем backend/ в sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from log_utils import SecretRedactingFilter, sanitize_for_log  # noqa: E402, I001


class TestSanitizeForLog:
    """Строки от пользователя не несут управляющих символов в лог.

    ESC доходит до лога, а в терминале исполняется как команда, то есть чужую строку
    можно покрасить или спрятать от читающего лог.
    """

    def test_escape_sequence_neutralized(self):
        assert sanitize_for_log("p-\x1b[31m-END") == r"p-\x1b[31m-END"

    def test_nul_byte_neutralized(self):
        assert sanitize_for_log("p-\x00-END") == r"p-\x00-END"

    def test_readable_text_untouched(self):
        """Кириллица и обычные символы остаются как есть."""
        assert sanitize_for_log("/api/анализ-файла_v2.xlsx") == "/api/анализ-файла_v2.xlsx"

    def test_long_value_truncated(self):
        """Длинное значение обрезается — со своим адресом LLM текст сбоя задаёт клиент."""
        result = sanitize_for_log("z" * 5_000)

        assert len(result) < 1_100
        assert "всего 5000 симв." in result

    def test_escaping_survives_truncation(self):
        """Обрезка идёт до экранирования, поэтому `\\xNN` не рубится посередине."""
        result = sanitize_for_log("a" * 999 + "\x1b" + "b" * 100, max_len=1000)

        assert result.endswith("симв.)")
        assert r"\x1b" in result
        assert "\x1b" not in result


def _record(msg: str, args: tuple = ()) -> logging.LogRecord:
    return logging.LogRecord(
        name="httpx", level=logging.INFO, pathname=__file__, lineno=1,
        msg=msg, args=args, exc_info=None,
    )


class TestSecretRedactingFilter:
    """Токен бота не доходит до лога даже из чужого логгера.

    Строку с полным URL печатает httpx, а не наш код, поэтому секрет вырезается на выходе.
    """

    def test_token_redacted(self):
        record = _record("HTTP Request: POST https://api.telegram.org/bot123456:AAF-Ez_tOkEn/sendMessage")
        SecretRedactingFilter().filter(record)

        assert "AAF-Ez_tOkEn" not in record.getMessage()
        assert "/bot<redacted>/sendMessage" in record.getMessage()

    def test_token_redacted_in_lazy_args(self):
        """Аргументы %-подстановки тоже проверяются, секрет обычно приходит в них."""
        record = _record(
            "HTTP Request: %s %s", ("POST", "https://api.telegram.org/bot99:tOkEn/sendMessage"),
        )
        SecretRedactingFilter().filter(record)

        assert "tOkEn" not in record.getMessage()

    def test_token_with_unexpected_character_redacted_whole(self):
        """Хвост режется до слэша, иначе остаток токена остался бы в логе."""
        record = _record("POST https://api.telegram.org/bot99:tO.kEn+xyz/sendMessage")
        SecretRedactingFilter().filter(record)

        assert "tO.kEn+xyz" not in record.getMessage()
        assert "kEn" not in record.getMessage()

    @pytest.mark.parametrize("message", [
        "POST /api/analyze → 200 (35 мс)",
        "HTTP Request: POST https://api.openai.com/v1/chat/completions",
    ])
    def test_other_messages_untouched(self, message):
        """Обычные строки не меняются — в логе остаётся видно, куда ушёл запрос."""
        record = _record(message)
        SecretRedactingFilter().filter(record)

        assert record.getMessage() == message


def test_filter_installed_on_root_handler():
    """Фильтр навешен в настройке логирования, а не только существует как класс.

    Регулярка покрыта тестами выше, но снятая строка `addFilter` не роняла ничего,
    и токен возвращался в лог.
    """
    import main  # noqa: F401 — импорт настраивает логирование

    handlers = logging.root.handlers
    assert handlers, "корневой логгер без хендлеров"
    assert any(
        isinstance(f, SecretRedactingFilter) for h in handlers for f in h.filters
    ), "SecretRedactingFilter не навешен на корневой хендлер"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

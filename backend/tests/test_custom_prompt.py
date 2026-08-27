"""Подстановка в пользовательский промпт.

Шаблон промпта приходит от пользователя, поэтому `str.format` для него не годится —
он даёт спецификаторы формата, доступ к атрибутам объектов и падение на опечатке.
"""

import sys
import time
from pathlib import Path

# Добавляем backend/ в sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest  # noqa: E402, I001

from user_errors import UserError  # noqa: E402, I001

from prompts import (  # noqa: E402, I001
    MAX_RENDERED_PROMPT_CHARS,
    get_analyze_prompt,
    get_raw_prompts,
    render_custom_prompt,
)


class TestPlaceholders:
    """Известные плейсхолдеры подставляются как раньше."""

    def test_all_placeholders_substituted(self):
        result = render_custom_prompt(
            "Type: {template_type}. {template_type_instruction} {translation_languages}",
            "small",
            ["ru"],
        )

        assert "{template_type}" not in result
        assert "{template_type_instruction}" not in result
        assert "{translation_languages}" not in result
        assert "SMALL" in result

    def test_unknown_template_type_falls_back(self):
        result = render_custom_prompt("Type: {template_type}", "неведомый", None)

        assert "FULL" in result

    def test_prompt_without_placeholders_unchanged(self):
        result = render_custom_prompt("Extract all Modbus registers", "full", None)

        assert result == "Extract all Modbus registers"


class TestNoFormatSemantics:
    """Возможности str.format пользователю недоступны."""

    def test_format_spec_not_expanded(self):
        """Спецификатор формата остаётся текстом, а не строкой на 200 млн символов."""
        result = render_custom_prompt("X{template_type:>200000000}Y", "full", None)

        assert len(result) < 100
        assert "{template_type:>200000000}" in result

    def test_attribute_access_not_expanded(self):
        """Доступ к атрибутам объекта не выполняется."""
        result = render_custom_prompt("{template_type.__class__.__mro__}", "full", None)

        assert "{template_type.__class__.__mro__}" in result
        assert "class" not in result.replace("__class__", "")

    def test_unknown_placeholder_does_not_raise(self):
        """Опечатка в имени плейсхолдера больше не даёт ошибку сервера."""
        result = render_custom_prompt("Extract {no_such_field} registers", "full", None)

        assert "{no_such_field}" in result

    def test_lone_brace_does_not_raise(self):
        """Одинокая фигурная скобка тоже не ломает разбор."""
        result = render_custom_prompt("Use JSON like { registers: [] }", "full", None)

        assert "{ registers: [] }" in result


class TestEscapedBraces:
    """Экранирование `{{`/`}}` снимается, как это делает str.format.

    Дефолтный шаблон написан под format, примеры JSON в нём заэкранированы, и без
    снятия скобок модель получает инструкцию с битыми примерами формата ответа.
    """

    @pytest.mark.parametrize("template_type,languages", [
        ("small", None),
        ("medium", ["ru"]),
        ("full", ["ru", "de", "it"]),
    ])
    def test_default_prompt_renders_same_as_server_path(self, template_type, languages):
        """Рендер дефолтного шаблона совпадает с серверным.

        Совпадение на всём _SYSTEM_PROMPT ловит и битое экранирование, и плейсхолдер,
        добавленный только в один из путей.
        """
        raw = get_raw_prompts()["system_prompt"]

        custom = render_custom_prompt(raw, template_type, languages)
        server = get_analyze_prompt(template_type, languages)

        assert custom == server
        assert "{{" not in custom

    def test_escaped_braces_collapsed(self):
        result = render_custom_prompt('Example: {{"ru": "Счётчики"}}', "full", None)

        assert result == 'Example: {"ru": "Счётчики"}'


class TestRenderedSizeCap:
    """Результат рендера ограничен по размеру — повтор плейсхолдера умножает подстановку.

    Оба сомножителя приходят от клиента одним запросом — шаблон это Form-поле,
    а список языков не ограничен.
    """

    def test_repeated_placeholder_bomb_rejected(self):
        """Бомба с повторами отклоняется до аллокации, мгновенно."""
        langs = [f"l{i}" for i in range(2000)]  # текст языков ~10 КБ
        bomb = "{translation_languages}" * 1000  # предсказанный рост ~12 МБ

        t = time.monotonic()
        with pytest.raises(UserError) as exc:
            render_custom_prompt(bomb, "full", langs)

        assert time.monotonic() - t < 0.5, "отказ обязан быть до разворачивания"
        # В тексте и фактический размер, и потолок — видно, насколько ужимать
        assert exc.value.key == "serverError.promptTooLarge"
        assert str(MAX_RENDERED_PROMPT_CHARS) in str(exc.value)
        assert "символов" in str(exc.value)

    def test_accepted_result_fits_the_cap(self):
        """Отказа не было — значит предсказание сошлось и результат влез в потолок."""
        langs = [f"l{i}" for i in range(500)]

        result = render_custom_prompt("{translation_languages}" * 5, "full", langs)

        assert len(result) <= MAX_RENDERED_PROMPT_CHARS

    def test_huge_prompt_without_placeholders_rejected(self):
        """Просто гигантский промпт тоже упирается в потолок."""
        with pytest.raises(UserError, match="сократите"):
            render_custom_prompt("x" * (MAX_RENDERED_PROMPT_CHARS + 1), "full", None)

    def test_default_prompt_well_under_cap(self):
        """Дефолтный шаблон проходит с запасом не меньше четырёхкратного."""
        raw = get_raw_prompts()["system_prompt"]

        result = render_custom_prompt(raw, "full", ["ru", "de", "it"])

        assert len(result) < MAX_RENDERED_PROMPT_CHARS // 4


class TestServerPromptCap:
    """Дефолтный промпт ограничен тем же потолком.

    Список языков приходит от клиента формой и на серверном ключе уезжает в промпт как есть.
    """

    def test_languages_cannot_blow_up_server_prompt(self):
        with pytest.raises(UserError) as exc:
            get_analyze_prompt("full", [f"lang{i}" for i in range(50_000)])

        assert exc.value.key == "serverError.promptTooLarge"

    def test_normal_languages_pass(self):
        prompt = get_analyze_prompt("full", ["ru", "de", "it"])

        assert len(prompt) < MAX_RENDERED_PROMPT_CHARS

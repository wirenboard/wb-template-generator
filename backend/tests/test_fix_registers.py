"""Тесты merge-back логики fix-registers (FW-1452 follow-up).

Кнопка «Исправить через AI» шлёт в LLM только регистры с ошибками (помеченные
временным уникальным id `__fix_<i>`), а исправления вмёрдживает обратно в полный
шаблон по позициям. Матч по временному тегу, а не по настоящему id, потому что id
в шаблонах не уникальны (condition-gated пары). Здесь проверяем это без вызова LLM.
"""

import sys
from pathlib import Path

# Добавляем backend/ в sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from llm_service import _merge_fixed_registers, _parse_registers
from models import Register


def test_merge_applies_fix_by_position():
    """Исправленный регистр встаёт на свою позицию, остальные не меняются."""
    r0 = Register(id="a", address=1, name="ok0")
    r1 = Register(id="b", address=2, name="Bad")  # ошибка на позиции 1
    fixed = Register(id="__fix_0", address=2, name="good")

    merged = _merge_fixed_registers([r0, r1], [fixed], [1])

    assert len(merged) == 2
    assert merged[0].name == "ok0"
    assert merged[1].name == "good" and merged[1].id == "b"  # исходный id восстановлен


def test_merge_preserves_dup_id_siblings():
    """Ключевой кейс: две записи с ОДИНАКОВЫМ id, ошибка только у одной.

    Матч по настоящему id схлопнул бы близнецов; матч по __fix_<i> и позиции — нет.
    """
    err = Register(id="input_0", address=7, name="Input 0", reg_type="press_counter")
    sibling = Register(id="input_0", address=7, name="Input 0", reg_type="discrete")
    fixed = Register(id="__fix_0", address=7, name="Input 0", reg_type="input")

    merged = _merge_fixed_registers([err, sibling], [fixed], [0])

    assert merged[0].reg_type == "input"      # исправлен
    assert merged[1].reg_type == "discrete"   # близнец с тем же id НЕ тронут
    assert merged[0].id == "input_0" and merged[1].id == "input_0"


def test_merge_handles_reordered_llm_output():
    """LLM вернул регистры в другом порядке — матч по __fix_<i> всё равно верный."""
    r0 = Register(id="x", address=1, name="e0")
    r1 = Register(id="y", address=2, name="e1")
    f1 = Register(id="__fix_1", address=2, name="fixed1")
    f0 = Register(id="__fix_0", address=1, name="fixed0")

    merged = _merge_fixed_registers([r0, r1], [f1, f0], [0, 1])

    assert merged[0].name == "fixed0" and merged[0].id == "x"
    assert merged[1].name == "fixed1" and merged[1].id == "y"


def test_merge_keeps_original_when_llm_drops():
    """Если LLM не вернул фикс для позиции — оригинал остаётся как есть."""
    r0 = Register(id="a", address=1, name="Bad")

    merged = _merge_fixed_registers([r0], [], [0])

    assert len(merged) == 1
    assert merged[0].name == "Bad"


def test_merge_touches_only_error_positions():
    """Не-error регистры (нет в error_positions) не трогаются вообще."""
    regs = [Register(id=str(i), address=i, name=f"n{i}") for i in range(5)]
    fixed = [Register(id="__fix_0", address=2, name="fixed2")]

    merged = _merge_fixed_registers(regs, fixed, [2])

    assert [r.name for r in merged] == ["n0", "n1", "fixed2", "n3", "n4"]
    assert [r.id for r in merged] == ["0", "1", "2", "3", "4"]


def test_parse_registers_preserve_id():
    """preserve_id=True сохраняет id из ответа LLM; по умолчанию id генерируется заново."""
    _, regs_default, _ = _parse_registers(
        {"device_info": {"name": "d", "id": "d"},
         "registers": [{"id": "__fix_0", "address": 1, "name": "n"}]},
    )
    assert regs_default[0].id != "__fix_0"  # id срезан, сгенерирован новый uuid

    _, regs_keep, _ = _parse_registers(
        {"device_info": {"name": "d", "id": "d"},
         "registers": [{"id": "__fix_0", "address": 1, "name": "n"}]},
        preserve_id=True,
    )
    assert regs_keep[0].id == "__fix_0"


def test_hex_address_survives_parse_fallback():
    """Мягкая ветка _parse_registers не должна терять регистр из-за записи адреса."""
    raw = {"device_info": {}, "registers": [{"address": "0xff", "name": "V", "enum": "не список"}]}

    _, registers, _ = _parse_registers(raw)

    assert [r.address for r in registers] == ["0xff"]

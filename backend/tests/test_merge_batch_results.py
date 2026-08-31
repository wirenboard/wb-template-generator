"""Мерж результатов анализа: дедуп по (address, reg_type, condition) и сортировка.

Функция чистая, LLM не участвует. Здесь закрепляются два свойства, потеря которых
приводит к молчаливой порче шаблона: condition-gated пары не должны схлопываться
в одну строку, а сортировка не должна падать на смешанных адресах.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from llm_service import _merge_batch_results  # noqa: E402
from models import DeviceInfo, Register  # noqa: E402


def _batch(registers: list[Register], name: str = "Device", fixed: int = 0):
    """Один результат батча в том виде, в котором его отдаёт анализ."""
    return (DeviceInfo(name=name, id=name.lower().replace(" ", "-")), registers, fixed)


def test_condition_gated_pair_survives_dedupe():
    """Один адрес и тип, но взаимоисключающие condition — это два разных регистра.

    Регресс, который лечим: ключ дедупа был (address, reg_type), и половина пары
    терялась. Пользователь получал шаблон, где условный канал остался один.
    """
    regs = [
        Register(address=10, name="Mode A", reg_type="holding", condition="mode==1"),
        Register(address=10, name="Mode B", reg_type="holding", condition="mode==2"),
    ]

    _, merged, _ = _merge_batch_results([_batch(regs)])

    assert len(merged) == 2
    assert {r.condition for r in merged} == {"mode==1", "mode==2"}


def test_full_duplicate_is_dropped():
    """Полный дубль (адрес, тип, condition совпали) схлопывается, побеждает первый."""
    regs = [
        Register(address=5, name="Voltage", reg_type="input"),
        Register(address=5, name="Voltage duplicate", reg_type="input"),
    ]

    _, merged, _ = _merge_batch_results([_batch(regs)])

    assert len(merged) == 1
    assert merged[0].name == "Voltage"  # первое вхождение


def test_same_address_different_reg_type_kept():
    """coil и holding на одном числовом адресе — разные адресные пространства."""
    regs = [
        Register(address=7, name="Relay", reg_type="coil"),
        Register(address=7, name="Setpoint", reg_type="holding"),
    ]

    _, merged, _ = _merge_batch_results([_batch(regs)])

    assert len(merged) == 2


def test_mixed_numeric_and_bitwise_addresses_sort_without_error():
    """Сортировка не падает на смешанных адресах.

    Побитовый адрес приходит строкой «2000:0:1», числовой — int. Прямой sorted()
    на таком наборе бросает TypeError, поэтому ключ сортировки считает значения
    всех частей записи (0xF010 = 61456).
    """
    regs = [
        Register(address="2000:0:1", name="Bit flag", reg_type="holding"),
        Register(address=100, name="Plain", reg_type="holding"),
        Register(address="0xF010", name="Hex", reg_type="holding"),
    ]

    _, merged, _ = _merge_batch_results([_batch(regs)])

    assert [r.address for r in merged] == [100, "2000:0:1", "0xF010"]


def test_device_info_taken_from_first_named_batch():
    """device_info берётся из первого батча, где имя устройства распознано."""
    unknown = (DeviceInfo(name="Unknown Device", id="unknown-device"), [], 0)
    named = _batch([Register(address=1, name="X", reg_type="holding")], name="Eastron SDM630")

    info, _, _ = _merge_batch_results([unknown, named])

    assert info.name == "Eastron SDM630"


def test_auto_fix_counts_are_summed():
    """Счётчик авто-исправлений складывается по всем батчам."""
    first = _batch([Register(address=1, name="A", reg_type="holding")], fixed=2)
    second = _batch([Register(address=2, name="B", reg_type="holding")], fixed=3)

    _, _, total_fixed = _merge_batch_results([first, second])

    assert total_fixed == 5


def test_same_address_in_two_notations_is_deduped():
    """Один регистр, записанный десятичным и hex, — не два регистра."""
    regs = [
        Register(address=255, name="Voltage", reg_type="holding"),
        Register(address="0xff", name="Voltage duplicate", reg_type="holding"),
    ]

    _, merged, _ = _merge_batch_results([_batch(regs)])

    assert len(merged) == 1
    assert merged[0].name == "Voltage"

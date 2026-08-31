"""Контракт близнецов serial_values ↔ utils/serialValues.ts — кейсы из общей фикстуры."""

import json
from pathlib import Path

import pytest

from serial_values import address_sort_key, parse_address

_FIXTURE = Path(__file__).parent / "fixtures" / "serial_values_contract.json"
_FRONTEND_COPY = (
    Path(__file__).resolve().parents[2]
    / "frontend" / "src" / "__tests__" / "fixtures" / "serial_values_contract.json"
)
CONTRACT = json.loads(_FIXTURE.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CONTRACT["parse"], ids=lambda c: repr(c["raw"]))
def test_parse_matches_contract(case):
    assert parse_address(case["raw"]) == case["stored"]


def test_sort_order_matches_contract():
    ordered = sorted(CONTRACT["order"]["unsorted"], key=address_sort_key)
    assert ordered == CONTRACT["order"]["sorted"]


def test_fixture_copies_in_sync():
    """Копия во фронтовом дереве обязана совпадать с нашей, см. _comment фикстуры."""
    if not _FRONTEND_COPY.exists():
        pytest.skip("рядом нет фронтового дерева — контейнер бэкенда")
    assert json.loads(_FRONTEND_COPY.read_text(encoding="utf-8")) == CONTRACT

"""Тесты для serial_values — разбор адреса и числовых полей во всех записях."""

import pytest

from serial_values import (
    address_sort_key,
    canonical_address,
    decimal_address,
    numeric_value,
    parse_address,
    parse_number,
)


class TestParseAddress:
    """Число для десятичной записи, строка для hex и побитовой."""

    # Строковые записи закреплены контрактом близнецов (test_serial_values_contract)
    @pytest.mark.parametrize("raw,expected", [
        (255, 255),
        (None, None),
        ("0X1f", "0x1f"),
    ])
    def test_forms(self, raw, expected):
        """Запись адреса должна дойти до шаблона такой, какой её задали."""
        assert parse_address(raw) == expected

    def test_giant_decimal_stays_string(self):
        """Разбор десятичной записи ограничен лимитом CPython — гигант не роняет импорт."""
        raw = "9" * 5000
        assert parse_address(raw) == raw


class TestAddressSortKey:
    """Общий порядок с фронтом закреплён контрактом, здесь — крайние случаи."""

    def test_bits_of_one_register_are_ordered(self):
        bits = ["109:1:1", "109:0:2", "109:0:1"]
        assert sorted(bits, key=address_sort_key) == ["109:0:1", "109:0:2", "109:1:1"]

    def test_garbage_does_not_raise(self):
        assert address_sort_key("12abc") == ((0,), "12abc")

    def test_giant_hex_goes_to_unparsed_group(self):
        assert address_sort_key("0x" + "F" * 3600)[0] == (0,)


class TestProgressionAddress:
    """Свёртка в Jinja-цикл только для адресов, записанных числом."""

    @pytest.mark.parametrize("raw,expected", [
        (464, 464),
        ("464", 464),
        ("0x1D0", None),
        ("0x012F0000", None),
        ("109:0:1", None),
    ])
    def test_only_decimal_folds(self, raw, expected):
        assert decimal_address(raw) == expected


class TestCanonicalAddress:
    """Одна запись адреса — один ключ дедупа."""

    @pytest.mark.parametrize("left,right", [
        ("0xff", 255),
        ("0xff", "255"),
        ("0xFF", "0xff"),
        ("0x6D:0:1", "109:0:1"),
    ])
    def test_same_address_same_key(self, left, right):
        assert canonical_address(left) == canonical_address(right)

    @pytest.mark.parametrize("left,right", [
        (255, 256),
        ("109:0:1", 109),
        ("109:0:1", "109:1:1"),
    ])
    def test_different_addresses_differ(self, left, right):
        assert canonical_address(left) != canonical_address(right)


class TestParseNumber:
    """Обе записи дробного числа означают одно значение."""

    @pytest.mark.parametrize("raw,expected", [
        ("0,5", 0.5),
        ("0.5", 0.5),
        ("-0,25", -0.25),
        ("1e-7", 1e-7),
        ("100", 100),
        ("0,0", 0),
        (0.5, 0.5),
        (100, 100),
        (None, None),
    ])
    def test_forms(self, raw, expected):
        assert parse_number(raw) == expected

    def test_whole_number_stays_integer(self):
        """Сравнение в test_forms типа не различает, 100 == 100.0."""
        assert isinstance(parse_number("100"), int)

    @pytest.mark.parametrize("raw", ["0xff", "0x012F0000", "мин", "", "1,2,3", "1e400"])
    def test_left_as_is(self, raw):
        """Hex законен в `on_value` и `off_value`, неразобранное пометит валидатор."""
        assert parse_number(raw) == raw

    def test_wide_integer_keeps_precision(self):
        """Разбор через float терял точность после 15 цифр — целые парсятся напрямую."""
        assert parse_number("18446744073709551615") == 18446744073709551615


class TestNumericValue:
    """Числовое значение записи — им разворачивается hex в лимитах."""

    def test_u64_boundary(self):
        """Драйвер читает значения через stoull — шире u64 запись не бывает."""
        assert numeric_value("0xFFFFFFFFFFFFFFFF") == 2**64 - 1
        assert numeric_value("0x1" + "0" * 16) is None

    def test_giant_hex_is_unparsed(self):
        """int из hex не ограничен лимитом CPython, а сериализация в JSON ограничена."""
        assert numeric_value("0x" + "F" * 3600) is None

    @pytest.mark.parametrize("raw", ["1e400", "-1e400"])
    def test_exponent_overflow_is_unparsed(self, raw):
        assert numeric_value(raw) is None

    @pytest.mark.parametrize("raw,expected", [
        ("0xff", 255),
        ("0,5", 0.5),
        ("0.5", 0.5),
        (100, 100),
        (-3.5, -3.5),
    ])
    def test_values(self, raw, expected):
        assert numeric_value(raw) == expected

    @pytest.mark.parametrize("raw", ["мин", "", None, True, "12abc"])
    def test_unparsed(self, raw):
        assert numeric_value(raw) is None

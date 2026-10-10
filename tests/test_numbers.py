from decimal import Decimal

import pytest

from correctron.numbers import format_number, parse_number, round_grade


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("7.5", Decimal("7.5")),
        ("7,5", Decimal("7.5")),
        (" 7 ", Decimal("7")),
        ("-0", Decimal("0")),
        ("10", Decimal("10")),
        (".5", Decimal("0.5")),
    ],
)
def test_parse_number_accepts(raw, expected):
    assert parse_number(raw) == expected


@pytest.mark.parametrize("raw", ["", "   "])
def test_parse_number_blank_is_none(raw):
    assert parse_number(raw) is None


@pytest.mark.parametrize("raw", ["1,234.5", "abc", "1,2,3", "nan", "inf", "1e3", "7 5", "--1"])
def test_parse_number_rejects(raw):
    with pytest.raises(ValueError):
        parse_number(raw)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("8.00"), "8"),
        (Decimal("10"), "10"),
        (Decimal("100.50"), "100.5"),
        (Decimal("7.50"), "7.5"),
        (Decimal("0.25"), "0.25"),
        (Decimal("-0"), "0"),
        (Decimal("1E+2"), "100"),
    ],
)
def test_format_number(value, expected):
    assert format_number(value) == expected


def test_round_grade_half_up():
    assert round_grade(Decimal("6.125"), 2) == Decimal("6.13")
    assert round_grade(Decimal("6.25"), 1) == Decimal("6.3")
    assert round_grade(Decimal("6.5"), 0) == Decimal("7")

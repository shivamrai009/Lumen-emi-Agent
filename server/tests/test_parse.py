import datetime as dt

import pytest

from lumen.parse import parse_date, parse_digits


@pytest.mark.parametrize(
    "words, expected",
    [
        ("fourteenth of March, nineteen eighty-eight", dt.date(1988, 3, 14)),
        ("14th March 1988", dt.date(1988, 3, 14)),
        ("March 14, 1988", dt.date(1988, 3, 14)),
        ("14/03/1988", dt.date(1988, 3, 14)),
        ("14 March 88", dt.date(1988, 3, 14)),
        ("the second of november nineteen eighty five", dt.date(1985, 11, 2)),
        ("twenty first december nineteen eighty three", dt.date(1983, 12, 21)),
        ("तीस जनवरी, उन्नीस सौ उन्यासी", dt.date(1979, 1, 30)),
        ("30 जनवरी 1979", dt.date(1979, 1, 30)),
        ("चौदह मार्च उन्नीस सौ अट्ठासी", dt.date(1988, 3, 14)),
        ("दो जुलाई दो हज़ार पाँच", dt.date(2005, 7, 2)),
        ("३० जनवरी १९७९", dt.date(1979, 1, 30)),
        # Not a full, valid date: the agent must ask again, not guess.
        ("थ्रीट्स जनवरी, उन्नीस सौ उन्यासी", None),
        ("it's in March", None),
        ("thirty one february 1990", None),
    ],
)
def test_parse_date(words, expected):
    assert parse_date(words) == expected


@pytest.mark.parametrize(
    "words, expected",
    [
        ("four eight two one", "4821"),
        ("चार आठ दो एक", "4821"),
        ("48 21", "4821"),
        ("forty-eight twenty-one", "4821"),
        ("double one seven seven", "1177"),
        ("zero five six zero", "0560"),
        ("it's three three zero eight", "3308"),
        ("हाँ, वही सही है", ""),
    ],
)
def test_parse_digits(words, expected):
    assert parse_digits(words) == expected

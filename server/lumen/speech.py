"""Turn amounts and dates into the words a person would say on the phone.

The LLM never formats numbers itself. After verification it receives ready-made
spoken strings ("twelve thousand five hundred rupees", "the fifth of December")
in English and Hindi, and the prompt tells it to use them verbatim. This keeps
the speech consistent and stops it reading "₹12,500" or "2026-12-05" like a form.

Both languages use the Indian grouping (thousand, lakh, crore).
"""

from __future__ import annotations

import datetime as dt

# --- English -----------------------------------------------------------------

_EN_ONES = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen "
    "fourteen fifteen sixteen seventeen eighteen nineteen"
).split()
_EN_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def _en_below_100(n: int) -> str:
    if n < 20:
        return _EN_ONES[n]
    tens, ones = divmod(n, 10)
    return _EN_TENS[tens] + (f"-{_EN_ONES[ones]}" if ones else "")


def _en_below_1000(n: int) -> str:
    hundreds, rest = divmod(n, 100)
    if hundreds and rest:
        return f"{_EN_ONES[hundreds]} hundred and {_en_below_100(rest)}"
    if hundreds:
        return f"{_EN_ONES[hundreds]} hundred"
    return _en_below_100(rest)


def number_en(n: int) -> str:
    """12500 -> 'twelve thousand five hundred'; 150000 -> 'one lakh fifty thousand'."""
    if n == 0:
        return "zero"
    parts = []
    crore, n = divmod(n, 10_000_000)
    lakh, n = divmod(n, 100_000)
    thousand, n = divmod(n, 1000)
    if crore:
        parts.append(f"{number_en(crore)} crore")
    if lakh:
        parts.append(f"{_en_below_100(lakh)} lakh")
    if thousand:
        parts.append(f"{_en_below_100(thousand)} thousand")
    if n:
        # "twenty-three thousand and seventy-five", as said in Indian English
        parts.append(("and " if parts and n < 100 else "") + _en_below_1000(n))
    return " ".join(parts)


_EN_ORDINAL_IRREGULAR = {
    "one": "first",
    "two": "second",
    "three": "third",
    "five": "fifth",
    "eight": "eighth",
    "nine": "ninth",
    "twelve": "twelfth",
}


def ordinal_en(n: int) -> str:
    """5 -> 'fifth', 21 -> 'twenty-first', 30 -> 'thirtieth'."""
    words = _en_below_100(n)
    head, sep, last = words.rpartition("-")
    if last in _EN_ORDINAL_IRREGULAR:
        last = _EN_ORDINAL_IRREGULAR[last]
    elif last.endswith("y"):
        last = last[:-1] + "ieth"
    else:
        last += "th"
    return f"{head}{sep}{last}"


def rupees_en(amount: int) -> str:
    return f"{number_en(amount)} rupees"


def date_en(d: dt.date, today: dt.date) -> str:
    """'the fifth of December'; adds the weekday when the date is within a week."""
    base = f"the {ordinal_en(d.day)} of {d.strftime('%B')}"
    if abs((d - today).days) <= 7:
        return f"{d.strftime('%A')}, {base}"
    return base


def relative_en(d: dt.date, today: dt.date) -> str:
    delta = (d - today).days
    if delta == 0:
        return "today"
    if delta == 1:
        return "tomorrow"
    if delta == -1:
        return "yesterday"
    if delta > 0:
        return f"in {number_en(delta)} days"
    return f"{number_en(-delta)} days ago"


# --- Hindi -------------------------------------------------------------------

# Hindi numbers below 100 are irregular, so they come from a table.
_HI_0_99 = (
    "शून्य एक दो तीन चार पाँच छह सात आठ नौ "
    "दस ग्यारह बारह तेरह चौदह पंद्रह सोलह सत्रह अठारह उन्नीस "
    "बीस इक्कीस बाईस तेईस चौबीस पच्चीस छब्बीस सत्ताईस अट्ठाईस उनतीस "
    "तीस इकतीस बत्तीस तैंतीस चौंतीस पैंतीस छत्तीस सैंतीस अड़तीस उनतालीस "
    "चालीस इकतालीस बयालीस तैंतालीस चवालीस पैंतालीस छियालीस सैंतालीस अड़तालीस उनचास "
    "पचास इक्यावन बावन तिरपन चौवन पचपन छप्पन सत्तावन अट्ठावन उनसठ "
    "साठ इकसठ बासठ तिरसठ चौंसठ पैंसठ छियासठ सड़सठ अड़सठ उनहत्तर "
    "सत्तर इकहत्तर बहत्तर तिहत्तर चौहत्तर पचहत्तर छिहत्तर सतहत्तर अठहत्तर उन्यासी "
    "अस्सी इक्यासी बयासी तिरासी चौरासी पचासी छियासी सत्तासी अट्ठासी नवासी "
    "नब्बे इक्यानवे बानवे तिरानवे चौरानवे पंचानवे छियानवे सत्तानवे अट्ठानवे निन्यानवे"
).split()
assert len(_HI_0_99) == 100

_HI_MONTHS = "जनवरी फ़रवरी मार्च अप्रैल मई जून जुलाई अगस्त सितंबर अक्टूबर नवंबर दिसंबर".split()
_HI_WEEKDAYS = "सोमवार मंगलवार बुधवार गुरुवार शुक्रवार शनिवार रविवार".split()


def number_hi(n: int) -> str:
    """12500 -> 'बारह हज़ार पाँच सौ'."""
    if n < 100:
        return _HI_0_99[n]
    parts = []
    crore, n = divmod(n, 10_000_000)
    lakh, n = divmod(n, 100_000)
    thousand, n = divmod(n, 1000)
    hundred, n = divmod(n, 100)
    if crore:
        parts.append(f"{number_hi(crore)} करोड़")
    if lakh:
        parts.append(f"{_HI_0_99[lakh]} लाख")
    if thousand:
        parts.append(f"{_HI_0_99[thousand]} हज़ार")
    if hundred:
        parts.append(f"{_HI_0_99[hundred]} सौ")
    if n:
        parts.append(_HI_0_99[n])
    return " ".join(parts)


def rupees_hi(amount: int) -> str:
    return f"{number_hi(amount)} रुपये"


def date_hi(d: dt.date, today: dt.date) -> str:
    """'पाँच दिसंबर'; adds the weekday when the date is within a week."""
    base = f"{number_hi(d.day)} {_HI_MONTHS[d.month - 1]}"
    if abs((d - today).days) <= 7:
        return f"{_HI_WEEKDAYS[d.weekday()]}, {base}"
    return base


def relative_hi(d: dt.date, today: dt.date) -> str:
    delta = (d - today).days
    if delta == 0:
        return "आज"
    if delta == 1:
        return "कल"  # tomorrow
    if delta == -1:
        return "कल"  # yesterday; Hindi uses the same word, context disambiguates
    if delta > 0:
        return f"{number_hi(delta)} दिन में"
    return f"{number_hi(-delta)} दिन पहले"


# --- Read-backs during verification -----------------------------------------
# What the tool checked, said back in words by code (not by the LLM), so a
# mis-heard date or digit is caught by the caller instead of being repeated wrongly.


def _year_en(y: int) -> str:
    """1979 -> 'nineteen seventy-nine', 2005 -> 'two thousand and five'."""
    hi, lo = divmod(y, 100)
    if 2000 <= y < 2010:
        return number_en(y)
    return f"{_en_below_100(hi)} hundred" if lo == 0 else f"{_en_below_100(hi)} {_en_below_100(lo)}"


def dob_en(d: dt.date) -> str:
    return f"the {ordinal_en(d.day)} of {d.strftime('%B')}, {_year_en(d.year)}"


def dob_hi(d: dt.date) -> str:
    hi, lo = divmod(d.year, 100)
    if d.year >= 2000:
        year = number_hi(d.year)
    else:
        year = f"{_HI_0_99[hi]} सौ" + (f" {_HI_0_99[lo]}" if lo else "")
    return f"{number_hi(d.day)} {_HI_MONTHS[d.month - 1]} {year}"


def digits_en(s: str) -> str:
    return " ".join(_EN_ONES[int(c)] for c in s)


def digits_hi(s: str) -> str:
    return " ".join(_HI_0_99[int(c)] for c in s)

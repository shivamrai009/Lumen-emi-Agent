"""Read a date of birth or phone digits out of the caller's own words, by code.

Why: the LLM converting spoken numbers was the weakest link in verification. In
evals it turned Hindi "तीस जनवरी, उन्नीस सौ उन्यासी" (30 January 1979) into
1979-01-03 and later 1985-01-30, and once sent phone_last4 "1234" that the caller
never said. verify_identity now takes the caller's words and parses them here; the
LLM's own conversion is only a fallback when this parser can't read them.

Handles English and Hindi (Devanagari) number words, digits (ASCII or Devanagari),
ordinals ("14th", "fourteenth", "twenty first"), month names in both languages,
"double/triple" for digits, and years said as "nineteen eighty-eight",
"nineteen hundred eighty-eight", "उन्नीस सौ अट्ठासी" or "दो हज़ार पाँच".
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata

from lumen.speech import _EN_ONES, _EN_TENS, _HI_0_99

# --- vocabulary ---------------------------------------------------------------


def _norm(word: str) -> str:
    """Fold spelling variants: nukta, chandrabindu vs anusvara, case."""
    w = unicodedata.normalize("NFD", word.lower())
    w = w.replace("़", "")  # nukta: ज़ -> ज, ड़ -> ड
    w = w.replace("ँ", "ं")  # chandrabindu -> anusvara: पाँच -> पांच
    return unicodedata.normalize("NFC", w)


NUMBER_WORDS: dict[str, int] = {}
for _i, _w in enumerate(_EN_ONES):
    NUMBER_WORDS[_w] = _i
for _i, _w in enumerate(_EN_TENS):
    if _w != "_":
        NUMBER_WORDS[_w] = _i * 10
NUMBER_WORDS.update({"oh": 0, "o": 0, "nought": 0})
for _i, _w in enumerate(_HI_0_99):
    NUMBER_WORDS[_norm(_w)] = _i
# Common Hindi spelling variants (and English loanwords said in Hindi).
for _w, _i in {
    "जीरो": 0,
    "ज़ीरो": 0,
    "छः": 6,
    "छे": 6,
    "छै": 6,
    "पांच": 5,
    "उन्नासी": 79,
    "उनासी": 79,
    "उनयासी": 79,
    "अठासी": 88,
    "अट्ठासी": 88,
    "अठत्तर": 78,
    "सितत्तर": 77,
    "इकयासी": 81,
    "बयालिस": 42,
    "पैंतालिस": 45,
    "तिरेसठ": 63,
    "चौसठ": 64,
    "नवासी": 89,
    "पिचासी": 85,
    "सत्तासी": 87,
    "छियासी": 86,
    "इक्यानबे": 91,
    "पचानवे": 95,
    "निन्यानबे": 99,
    "नब्बे": 90,
}.items():
    NUMBER_WORDS[_norm(_w)] = _i

ORDINAL_WORDS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7,
    "eighth": 8, "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12, "thirteenth": 13,
    "fourteenth": 14, "fifteenth": 15, "sixteenth": 16, "seventeenth": 17, "eighteenth": 18,
    "nineteenth": 19, "twentieth": 20, "thirtieth": 30,
}  # fmt: skip

HUNDRED = {"hundred", _norm("सौ")}
THOUSAND = {"thousand", _norm("हज़ार"), _norm("हजार")}
REPEAT = {"double": 2, "triple": 3, _norm("डबल"): 2, _norm("ट्रिपल"): 3}

MONTHS: dict[str, int] = {}
for _i, _m in enumerate(
    "january february march april may june july august september october november december".split(),
    start=1,
):
    MONTHS[_m] = _i
    MONTHS[_m[:3]] = _i
MONTHS["sept"] = 9
for _i, _names in enumerate(
    [
        "जनवरी",
        "फ़रवरी फरवरी",
        "मार्च",
        "अप्रैल अप्रेल",
        "मई",
        "जून",
        "जुलाई",
        "अगस्त",
        "सितंबर सितम्बर",
        "अक्टूबर अक्तूबर",
        "नवंबर नवम्बर",
        "दिसंबर दिसम्बर",
    ],
    start=1,
):
    for _m in _names.split():
        MONTHS[_norm(_m)] = _i

_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


# --- tokens -------------------------------------------------------------------


def _tokens(text: str) -> list[tuple[str, object]]:
    """('num', value, n_digits_said) / ('mult', 100|1000) / ('rep', n) / ('month', m)."""
    text = text.translate(_DEVANAGARI_DIGITS)
    text = re.sub(r"(\d+)\s*(st|nd|rd|th)\b", r"\1", text, flags=re.I)
    out: list[tuple[str, object]] = []
    for raw in re.split(r"[\s,.\-/।?!:;'\"()]+", text):
        if not raw:
            continue
        w = _norm(raw)
        if w.isdigit():
            out.append(("digits", w))
        elif w in MONTHS:
            out.append(("month", MONTHS[w]))
        elif w in NUMBER_WORDS:
            out.append(("num", NUMBER_WORDS[w]))
        elif w in ORDINAL_WORDS:
            out.append(("num", ORDINAL_WORDS[w]))
        elif w in HUNDRED:
            out.append(("mult", 100))
        elif w in THOUSAND:
            out.append(("mult", 1000))
        elif w in REPEAT:
            out.append(("rep", REPEAT[w]))
        else:
            out.append(("word", w))
    return out


def _numbers(tokens: list[tuple[str, object]]) -> list[tuple[int, int]]:
    """Combine number words into numbers: ('twenty','one') -> 21, ('nineteen','hundred',
    'seventy','nine') -> 1979. Returns (value, width): width is how many digits the
    speaker said, so 'zero five' keeps its leading zero for phone digits."""
    groups: list[tuple[int, int]] = []
    cur: int | None = None
    after_mult = False  # last token was hundred/thousand: a smaller number adds on
    tens_open = False  # last value was 20, 30, ... 90: a single unit adds on

    def close():
        nonlocal cur, after_mult, tens_open
        if cur is not None:
            groups.append((cur, len(str(cur))))
        cur, after_mult, tens_open = None, False, False

    for kind, val in tokens:
        if kind == "digits":
            close()
            groups.append((int(val), len(val)))  # type: ignore[arg-type]
        elif kind == "mult":
            cur = (cur or 1) * int(val)  # type: ignore[call-overload]
            after_mult, tens_open = True, False
        elif kind == "num":
            v = int(val)  # type: ignore[call-overload]
            if cur is not None and after_mult and v < 100:
                cur += v
                after_mult, tens_open = False, (v % 10 == 0 and v >= 20)
            elif cur is not None and tens_open and 1 <= v <= 9:
                cur += v
                tens_open = False
            else:
                close()
                cur, tens_open = v, (v % 10 == 0 and v >= 20)
        else:
            close()
    close()
    return groups


# --- public -------------------------------------------------------------------


def parse_date(text: str) -> dt.date | None:
    """A full date (day, month and year) from the caller's words, or None."""
    t = text.translate(_DEVANAGARI_DIGITS)
    if m := re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", t):
        y, mo, d = map(int, m.groups())
        return _date(y, mo, d)
    if m := re.search(r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})\b", t):
        d, mo, y = map(int, m.groups())  # Indian order: day/month/year
        return _date(y, mo, d)

    tokens = _tokens(t)
    month_at = next((i for i, (k, _) in enumerate(tokens) if k == "month"), None)
    if month_at is None:
        return None
    month = int(tokens[month_at][1])  # type: ignore[call-overload]
    before = [v for v, _ in _numbers(tokens[:month_at])]
    after = [v for v, _ in _numbers(tokens[month_at + 1 :])]

    # "14 March 1988" / "चौदह मार्च उन्नीस सौ अट्ठासी", or "March 14, 1988"
    if before and 1 <= before[-1] <= 31:
        day, year_parts = before[-1], after
    elif after and 1 <= after[0] <= 31:
        day, year_parts = after[0], after[1:]
    else:
        return None
    return _date(_year(year_parts), month, day)


def _year(parts: list[int]) -> int | None:
    if len(parts) == 1 and 1900 <= parts[0] <= 2030:
        return parts[0]
    if len(parts) == 2 and parts[0] in (19, 20) and 0 <= parts[1] <= 99:
        return parts[0] * 100 + parts[1]  # "nineteen eighty-eight"
    if len(parts) == 1 and 0 <= parts[0] <= 99:
        return (1900 if parts[0] > 30 else 2000) + parts[0]  # "14 March 88"
    return None


def _date(y: int | None, m: int, d: int) -> dt.date | None:
    if y is None:
        return None
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def parse_digits(text: str) -> str:
    """Every digit the caller said, in order: 'four eight two one', 'चार आठ दो एक',
    '48 21', 'forty-eight twenty-one', 'double one seven seven' -> '4821' / '1177'."""
    expanded: list[tuple[str, object]] = []
    repeat = 1
    for kind, val in _tokens(text):
        if kind == "rep":
            repeat = int(val)  # type: ignore[call-overload]
            continue
        if repeat > 1 and kind in ("num", "digits") and len(str(val)) == 1:
            # 'digits' tokens never combine, so "double one" stays 1, 1 (not 2)
            expanded += [("digits", str(val))] * repeat
        else:
            expanded.append((kind, val))
        repeat = 1
    return "".join(str(v).zfill(w) for v, w in _numbers(expanded))

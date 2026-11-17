"""Mock borrower data and the facts released to the agent after verification."""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path

from lumen import speech

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "borrowers.json"


@dataclass(frozen=True)
class Borrower:
    id: str
    name: str
    first_name: str
    date_of_birth: str  # ISO YYYY-MM-DD
    phone_last4: str
    loan_type: str
    loan_type_hi: str
    emi_amount: int
    due_date: dt.date
    overdue_amount: int
    preferred_language: str  # "en" | "hi"

    def days_overdue(self, today: dt.date) -> int:
        return max(0, (today - self.due_date).days)


def load_borrowers(today: dt.date | None = None) -> dict[str, Borrower]:
    today = today or dt.date.today()
    raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))["borrowers"]
    out = {}
    for r in raw:
        offset = r.pop("due_offset_days")
        out[r["id"]] = Borrower(**r, due_date=today + dt.timedelta(days=offset))
    return out


def loan_facts(b: Borrower, today: dt.date) -> dict:
    """What verify_identity hands the LLM once the caller is verified.

    Everything the agent might say aloud comes pre-spoken in both languages.
    """
    overdue_days = b.days_overdue(today)
    status = "overdue" if overdue_days > 0 else ("due_today" if b.due_date == today else "upcoming")
    facts = {
        "status": status,
        "loan_type": b.loan_type,
        "loan_type_hi": b.loan_type_hi,
        "emi_amount": b.emi_amount,
        "due_date_iso": b.due_date.isoformat(),
        "spoken_en": {
            "emi_amount": speech.rupees_en(b.emi_amount),
            "due_date": speech.date_en(b.due_date, today),
            "due_relative": speech.relative_en(b.due_date, today),
        },
        "spoken_hi": {
            "emi_amount": speech.rupees_hi(b.emi_amount),
            "due_date": speech.date_hi(b.due_date, today),
            "due_relative": speech.relative_hi(b.due_date, today),
        },
    }
    if overdue_days:
        facts["days_overdue"] = overdue_days
        facts["overdue_amount"] = b.overdue_amount
        facts["spoken_en"]["overdue_amount"] = speech.rupees_en(b.overdue_amount)
        facts["spoken_en"]["days_overdue"] = f"{speech.number_en(overdue_days)} days"
        facts["spoken_hi"]["overdue_amount"] = speech.rupees_hi(b.overdue_amount)
        facts["spoken_hi"]["days_overdue"] = f"{speech.number_hi(overdue_days)} दिन"
        if b.overdue_amount > b.emi_amount:
            facts["note"] = "More than one EMI is unpaid; the overdue amount covers all of them."
    return facts

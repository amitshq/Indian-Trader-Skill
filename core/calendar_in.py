"""NSE/BSE equity session clock. IST is fixed UTC+5:30 (no DST)."""
import json
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30), "IST")
CONFIG = Path(__file__).resolve().parent.parent / "config" / "holidays.json"

PRE_OPEN = time(9, 0)
OPEN = time(9, 15)
CLOSE = time(15, 30)
CLOSING_SESSION_END = time(16, 0)


def load_holidays(path: Path = CONFIG) -> set:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return set()
    return {date.fromisoformat(d) for d in data.get("holidays", [])}


def load_special_sessions(path: Path = CONFIG) -> set:
    """Days with a special (e.g. Muhurat) session; exchange announces the timings separately."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return set()
    return {date.fromisoformat(d) for d in data.get("special_sessions", [])}


def is_trading_day(d: date, holidays: set = None) -> bool:
    holidays = load_holidays() if holidays is None else holidays
    return d.weekday() < 5 and d not in holidays


def market_status(now: datetime = None, holidays: set = None, special: set = None) -> dict:
    """Return {status, now_ist, next_open}. status: open | pre_open | closed | holiday | special_session
    (special_session: a special-hours day such as Muhurat; hours are announced by the exchange, so open/closed is unknown)."""
    now = (now or datetime.now(IST)).astimezone(IST)
    holidays = load_holidays() if holidays is None else holidays
    t = now.time()
    special = load_special_sessions() if special is None else special
    if now.date() in special:
        status = "special_session"
    elif not is_trading_day(now.date(), holidays):
        status = "holiday"
    elif PRE_OPEN <= t < OPEN:
        status = "pre_open"
    elif OPEN <= t < CLOSE:
        status = "open"
    else:
        status = "closed"
    return {
        "status": status,
        "now_ist": now.isoformat(timespec="seconds"),
        "next_open": next_open(now, holidays).isoformat(timespec="seconds"),
    }


def next_open(now: datetime, holidays: set) -> datetime:
    now = now.astimezone(IST)
    d = now.date()
    candidate = datetime.combine(d, OPEN, IST)
    if now >= candidate:
        d += timedelta(days=1)
    while not is_trading_day(d, holidays):
        d += timedelta(days=1)
    return datetime.combine(d, OPEN, IST)

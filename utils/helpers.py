"""
utils/helpers.py - Utility functions shared across the bot.
"""

import random
import re
import string
from datetime import datetime, timezone

import config


def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


def generate_order_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%y%m%d")
    rand = "".join(random.choices(string.ascii_uppercase + string.digits, k=5))
    return f"ORD-{ts}-{rand}"


def format_currency(amount: float) -> str:
    return f"{config.CURRENCY_SYMBOL}{amount:,.2f}"


def chunks(seq, n):
    """Yield successive n-sized chunks from seq."""
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def safe_int(value, default=None):
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return default


def safe_float(value, default=None):
    try:
        return float(str(value).strip())
    except (ValueError, TypeError):
        return default


# A transaction ID / UTR is typically 10-30 chars, digits or alphanumeric.
TXN_RE = re.compile(r"^[A-Za-z0-9]{10,30}$")


def valid_txn_id(txn_id: str) -> bool:
    return bool(TXN_RE.match((txn_id or "").strip()))


def fmt_dt(dt) -> str:
    """Format a datetime (or ISO string) for display."""
    if dt is None:
        return "N/A"
    if isinstance(dt, str):
        return dt[:16]
    try:
        return dt.astimezone().strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(dt)[:16]


def format_delivery(category_name: str, items: list[str]) -> str:
    """Format delivered coupon codes for the buyer."""
    lines = [f"🎁 *Your {category_name} coupon(s):*", ""]
    for i, code in enumerate(items, 1):
        lines.append(f"{i}. `{code}`")
    lines.append("")
    lines.append("_Keep these safe. Thank you for your purchase!_")
    return "\n".join(lines)

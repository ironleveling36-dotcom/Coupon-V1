"""
config.py - Central configuration for the upgraded Coupon Selling Bot
All sensitive values are loaded from environment variables for Railway / .env support.
"""

import os
from dotenv import load_dotenv

load_dotenv()


def _clean(v):
    return v.strip() if isinstance(v, str) else v


def _parse_ids(raw: str) -> list[int]:
    """Parse comma-separated Telegram user IDs into a list of ints."""
    if not raw:
        return []
    return [int(x.strip()) for x in raw.split(",") if x.strip().isdigit()]


# ── Telegram ──────────────────────────────────────────────────────────────
BOT_TOKEN: str = _clean(os.getenv("BOT_TOKEN", ""))
ADMIN_IDS: list[int] = _parse_ids(_clean(os.getenv("ADMIN_IDS", "")))
ADMIN_CHAT_ID: str = _clean(os.getenv("ADMIN_CHAT_ID", ""))

# ── MongoDB ───────────────────────────────────────────────────────────────
MONGO_URI: str = _clean(os.getenv("MONGO_URI", "mongodb://localhost:27017"))
MONGO_DB_NAME: str = _clean(os.getenv("MONGO_DB_NAME", "coupon_bot"))

# ── Gmail (IMAP for auto payment verification) ────────────────────────────
GMAIL_ADDRESS: str = _clean(os.getenv("GMAIL_ADDRESS", ""))
GMAIL_APP_PASSWORD: str = _clean(os.getenv("GMAIL_APP_PASSWORD", ""))
IMAP_HOST: str = _clean(os.getenv("IMAP_HOST", "imap.gmail.com"))
SENDER_FILTER: str = _clean(os.getenv("SENDER_FILTER", ""))
EMAIL_LOOKBACK_HOURS: int = int(_clean(os.getenv("EMAIL_LOOKBACK_HOURS", "48")) or 48)

# ── Payment ───────────────────────────────────────────────────────────────
UPI_ID: str = _clean(os.getenv("UPI_ID", ""))
PAYEE_NAME: str = _clean(os.getenv("PAYEE_NAME", "CouponBot"))
QR_IMAGE_PATH: str = _clean(os.getenv("QR_IMAGE_PATH", "data/qr.png"))

# ── Bot branding ──────────────────────────────────────────────────────────
BOT_NAME: str = _clean(os.getenv("BOT_NAME", "CouponBot"))
CURRENCY_SYMBOL: str = _clean(os.getenv("CURRENCY_SYMBOL", "₹"))

# ── Performance / behavior ────────────────────────────────────────────────
PAYMENT_TIMEOUT_MINUTES: int = int(_clean(os.getenv("PAYMENT_TIMEOUT_MINUTES", "30")) or 30)
LOG_LEVEL: str = _clean(os.getenv("LOG_LEVEL", "INFO"))
MAINTENANCE_MODE: bool = os.getenv("MAINTENANCE_MODE", "false").lower() == "true"

# ── Webhook (optional — blank = polling) ──────────────────────────────────
WEBHOOK_URL: str = _clean(os.getenv("WEBHOOK_URL", ""))
PORT: int = int(_clean(os.getenv("PORT", "8443")) or 8443)

# ── Gmail poller interval ─────────────────────────────────────────────────
GMAIL_POLL_INTERVAL: int = int(_clean(os.getenv("GMAIL_POLL_INTERVAL", "60")) or 60)


def validate():
    """Raise SystemExit if required env vars are missing."""
    missing = []
    if not BOT_TOKEN:
        missing.append("BOT_TOKEN")
    if not MONGO_URI:
        missing.append("MONGO_URI")
    if missing:
        raise SystemExit(
            "Missing required environment variables: " + ", ".join(missing)
        )
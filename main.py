"""
main.py - Entry point for the upgraded Coupon Selling Bot.

• MongoDB-backed (wallet, users, coupons, transactions, orders) — data persists
  across restarts and Railway redeploys.
• Auto wallet recharge via Gmail UPI transaction verification.
• Full admin control panel.
• Runs in long-polling mode by default (ideal for Railway free plan — no public
  domain needed). Set WEBHOOK_URL to switch to webhook mode.
"""

import asyncio
import logging
import os
import sys
import warnings

from telegram.warnings import PTBUserWarning

warnings.filterwarnings("ignore", message=r".*per_message.*", category=PTBUserWarning)

from telegram import BotCommand, Update
from telegram.ext import Application, ApplicationBuilder, ContextTypes

import config
from database import Database
from handlers.user import register_user_handlers
from handlers.payment import register_payment_handlers
from handlers.admin import register_admin_handlers

# ── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=getattr(logging, config.LOG_LEVEL.upper(), logging.INFO),
    handlers=[logging.StreamHandler(sys.stdout)],
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


async def _post_init(app: Application):
    # Connect MongoDB once at startup
    await Database.get_instance()
    # Seed settings from env if not already set
    db = await Database.get_instance()
    if config.UPI_ID and not await db.get_setting("upi_id"):
        await db.set_setting("upi_id", config.UPI_ID)
    if config.PAYEE_NAME and not await db.get_setting("payee_name"):
        await db.set_setting("payee_name", config.PAYEE_NAME)
    if await db.get_setting("maintenance") is None:
        await db.set_setting("maintenance", "true" if config.MAINTENANCE_MODE else "false")

    await app.bot.set_my_commands([
        BotCommand("start", "Start the bot / main menu"),
        BotCommand("admin", "Admin control panel"),
    ])
    logger.info("Bot initialized and ready.")


async def _post_shutdown(app: Application):
    inst = Database._instance
    if inst:
        await inst.close()
    logger.info("Bot shut down cleanly.")


async def _on_error(update: object, ctx: ContextTypes.DEFAULT_TYPE):
    logger.error("Unhandled error: %s", ctx.error, exc_info=ctx.error)


def build_app() -> Application:
    app = (
        ApplicationBuilder()
        .token(config.BOT_TOKEN)
        .concurrent_updates(True)        # handle many users in parallel
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )
    register_user_handlers(app)
    register_payment_handlers(app)
    register_admin_handlers(app)
    app.add_error_handler(_on_error)
    return app


def main():
    config.validate()
    app = build_app()

    if config.WEBHOOK_URL:
        logger.info("Starting in WEBHOOK mode on port %s", config.PORT)
        app.run_webhook(
            listen="0.0.0.0",
            port=config.PORT,
            url_path=config.BOT_TOKEN,
            webhook_url=f"{config.WEBHOOK_URL.rstrip('/')}/{config.BOT_TOKEN}",
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )
    else:
        logger.info("Starting in POLLING mode.")
        app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
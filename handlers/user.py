"""
handlers/user.py - User-facing handlers: start, browse, wallet view,
transaction history, my orders.
"""

import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler

import keyboards
import messages
from database import Database
from utils import is_admin, format_currency, fmt_dt

logger = logging.getLogger(__name__)


async def _guard(update: Update, db: Database) -> bool:
    """Return True if the user is allowed to proceed."""
    user = update.effective_user
    if is_admin(user.id):
        return True
    if await db.is_banned(user.id):
        target = update.callback_query.message if update.callback_query else update.message
        await target.reply_text(messages.banned(), parse_mode=ParseMode.MARKDOWN)
        return False
    if await db.get_setting("maintenance") == "true":
        target = update.callback_query.message if update.callback_query else update.message
        await target.reply_text(messages.maintenance(), parse_mode=ParseMode.MARKDOWN)
        return False
    return True


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db = await Database.get_instance()
    rec = await db.upsert_user(user.id, user.username or "", user.full_name or "")

    if not await _guard(update, db):
        return

    await update.message.reply_text(
        messages.welcome(user.first_name, rec.get("wallet_balance", 0.0)),
        reply_markup=keyboards.main_menu_kb(),
        parse_mode=ParseMode.MARKDOWN,
    )


async def cbq_main_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    db = await Database.get_instance()
    balance = await db.get_balance(query.from_user.id)
    await query.edit_message_text(
        messages.welcome(query.from_user.first_name, balance),
        reply_markup=keyboards.main_menu_kb(),
        parse_mode=ParseMode.MARKDOWN,
    )


# ── Wallet ─────────────────────────────────────────────────────────────────
async def cbq_wallet(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    db = await Database.get_instance()
    u = await db.get_user(query.from_user.id)
    if not u:
        u = await db.upsert_user(query.from_user.id, query.from_user.username or "",
                                 query.from_user.full_name or "")
    await query.edit_message_text(
        messages.wallet_overview(
            u.get("wallet_balance", 0.0),
            u.get("total_recharged", 0.0),
            u.get("total_spent", 0.0),
        ),
        reply_markup=keyboards.wallet_kb(),
        parse_mode=ParseMode.MARKDOWN,
    )


async def cbq_txn_history(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    db = await Database.get_instance()
    txns = await db.get_transactions(query.from_user.id, limit=15)

    if not txns:
        await query.edit_message_text(
            "📜 *Transaction History*\n\nNo transactions yet.",
            reply_markup=keyboards.wallet_kb(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    lines = ["📜 *Transaction History*\n"]
    icons = {"recharge": "⬆️", "purchase": "🛒", "admin_adjust": "🛠️", "refund": "↩️"}
    for t in txns:
        sign = "+" if t["amount"] >= 0 else "−"
        icon = icons.get(t["type"], "•")
        lines.append(
            f"{icon} {sign}{format_currency(abs(t['amount']))} • "
            f"{t['type']} • {fmt_dt(t['created_at'])}"
        )
    await query.edit_message_text(
        "\n".join(lines),
        reply_markup=keyboards.wallet_kb(),
        parse_mode=ParseMode.MARKDOWN,
    )


# ── Browse ─────────────────────────────────────────────────────────────────
async def cbq_browse(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    db = await Database.get_instance()
    if not await _guard(update, db):
        return
    categories = await db.get_categories(active_only=True)

    if not categories:
        await query.edit_message_text(
            messages.no_categories(),
            reply_markup=keyboards.back_to_main_kb(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await query.edit_message_text(
        "🛍️ *Available Categories*\n\nSelect a category to continue:",
        reply_markup=keyboards.categories_kb(categories),
        parse_mode=ParseMode.MARKDOWN,
    )


async def cbq_select_category(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cat_id = int(query.data.split("_")[1])
    db = await Database.get_instance()

    cat = await db.get_category(cat_id)
    if not cat:
        await query.answer("Category not found!", show_alert=True)
        return

    stock = await db.stock_count(cat_id)
    balance = await db.get_balance(query.from_user.id)

    if stock == 0:
        await query.edit_message_text(
            messages.out_of_stock_msg(cat["name"]),
            reply_markup=keyboards.back_to_main_kb(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await query.edit_message_text(
        messages.category_detail(cat["name"], cat["price"], stock, balance),
        reply_markup=keyboards.quantity_kb(cat_id),
        parse_mode=ParseMode.MARKDOWN,
    )


# ── Help ───────────────────────────────────────────────────────────────────
async def cbq_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        messages.help_msg(),
        reply_markup=keyboards.back_to_main_kb(),
        parse_mode=ParseMode.MARKDOWN,
    )


# ── My Orders ──────────────────────────────────────────────────────────────
async def cbq_my_orders(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    db = await Database.get_instance()
    orders = await db.get_user_orders(query.from_user.id, limit=15)

    if not orders:
        await query.edit_message_text(
            "📦 *No orders found.*\n\nYou haven't purchased anything yet!",
            reply_markup=keyboards.back_to_main_kb(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await query.edit_message_text(
        "📦 *Your Recent Orders:*\n\nSelect an order to view its coupon codes.",
        reply_markup=keyboards.my_orders_kb(orders),
        parse_mode=ParseMode.MARKDOWN,
    )


async def cbq_view_order(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    order_id = query.data.split("vieworder_")[1]
    db = await Database.get_instance()

    order = await db.get_order(order_id)
    if not order or order["user_id"] != query.from_user.id:
        await query.answer("Order not found!", show_alert=True)
        return

    items = order.get("items", [])
    codes = "\n".join(f"{i}. `{c}`" for i, c in enumerate(items, 1)) or "_No codes stored_"
    text = (
        f"📋 *Order Details*\n\n"
        f"Order ID: `{order['order_id']}`\n"
        f"Category: {order.get('category_name', 'N/A')}\n"
        f"Quantity: {order['quantity']}\n"
        f"Amount: {format_currency(order['amount'])}\n"
        f"Status: {order['status'].upper()}\n"
        f"Date: {fmt_dt(order.get('created_at'))}\n\n"
        f"🎁 *Coupon Codes:*\n{codes}"
    )
    await query.edit_message_text(
        text, reply_markup=keyboards.back_to_main_kb(), parse_mode=ParseMode.MARKDOWN
    )


def register_user_handlers(app):
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(cbq_main_menu, pattern="^main_menu$"))
    app.add_handler(CallbackQueryHandler(cbq_wallet, pattern="^wallet$"))
    app.add_handler(CallbackQueryHandler(cbq_txn_history, pattern="^txn_history$"))
    app.add_handler(CallbackQueryHandler(cbq_browse, pattern="^browse$"))
    app.add_handler(CallbackQueryHandler(cbq_select_category, pattern=r"^cat_\d+$"))
    app.add_handler(CallbackQueryHandler(cbq_help, pattern="^help$"))
    app.add_handler(CallbackQueryHandler(cbq_my_orders, pattern="^my_orders$"))
    app.add_handler(CallbackQueryHandler(cbq_view_order, pattern=r"^vieworder_ORD-\w+-\w+$"))

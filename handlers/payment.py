"""
handlers/payment.py - Wallet recharge (auto Gmail verification) + coupon
purchase paid from the wallet balance.

Recharge flow:
  user taps "Recharge" -> bot shows UPI id -> user sends UPI Transaction ID
  -> bot searches Gmail for a matching bank-alert email -> verifies it's not
  already used -> credits the EXACT email amount to the wallet automatically.

Purchase flow:
  user picks category + quantity -> bot confirms total vs balance -> on confirm
  it atomically debits the wallet, reserves stock, creates the order, and
  delivers the coupon codes instantly.
"""

import asyncio
import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    ContextTypes,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

import config
import keyboards
import messages
from database import Database
from gmail_checker import find_transaction
from utils import (
    is_admin,
    generate_order_id,
    format_currency,
    format_delivery,
    valid_txn_id,
    safe_int,
)

logger = logging.getLogger(__name__)

# Conversation states
RECHARGE_TXN = 1
CUSTOM_QTY = 2


# ══════════════════════════════════════════════════════════════════════════
# RECHARGE
# ══════════════════════════════════════════════════════════════════════════
async def cbq_recharge_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    db = await Database.get_instance()
    upi = await db.get_setting("upi_id", config.UPI_ID) or config.UPI_ID
    payee = await db.get_setting("payee_name", config.PAYEE_NAME) or config.PAYEE_NAME

    if not upi:
        await query.edit_message_text(
            "⚠️ Recharge is not configured yet. Please contact the admin.",
            reply_markup=keyboards.wallet_kb(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return ConversationHandler.END

    await query.edit_message_text(
        messages.recharge_instructions(upi, payee),
        reply_markup=keyboards.recharge_cancel_kb(),
        parse_mode=ParseMode.MARKDOWN,
    )
    return RECHARGE_TXN


async def receive_txn_id(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    txn_id = (update.message.text or "").strip().replace(" ", "")
    db = await Database.get_instance()

    if not valid_txn_id(txn_id):
        await update.message.reply_text(
            "❌ That doesn't look like a valid Transaction ID.\n"
            "Please send only the UTR / reference number (10–30 letters or digits).",
            reply_markup=keyboards.recharge_cancel_kb(),
        )
        return RECHARGE_TXN

    # Anti-replay check
    if await db.is_txn_used(txn_id):
        await update.message.reply_text(
            "⚠️ This Transaction ID has already been used. "
            "Each payment can only be credited once.",
            reply_markup=keyboards.wallet_kb(),
        )
        await _notify_admin(ctx, f"🔁 Reused UTR attempt `{txn_id}` by @{user.username or user.id}")
        return ConversationHandler.END

    status_msg = await update.message.reply_text("🔎 Verifying your payment, please wait…")

    # Run blocking IMAP in a thread so the loop stays responsive
    try:
        result = await asyncio.to_thread(find_transaction, txn_id)
    except Exception as e:
        logger.exception("Gmail check failed")
        await status_msg.edit_text(
            "⚠️ Couldn't reach the verification system right now. "
            "Please try again in a minute.",
            reply_markup=keyboards.wallet_kb(),
        )
        await _notify_admin(ctx, f"❗ Gmail check error: {e}")
        return ConversationHandler.END

    if not result["found"]:
        await status_msg.edit_text(
            "❌ I couldn't find a payment with that Transaction ID yet.\n\n"
            "• Bank emails can take 1–2 minutes — wait and resend.\n"
            "• Double-check the UTR is correct.\n"
            "• Make sure the payment was made to the correct UPI ID.",
            reply_markup=keyboards.recharge_cancel_kb(),
        )
        return RECHARGE_TXN

    amount = result.get("amount")
    if not amount or amount <= 0:
        await status_msg.edit_text(
            "⚠️ Found the payment email, but I couldn't read the amount. "
            "Please contact the admin to credit it manually.",
            reply_markup=keyboards.wallet_kb(),
        )
        await _notify_admin(
            ctx,
            f"⚠️ Amount unreadable for UTR `{txn_id}` from @{user.username or user.id}. "
            "Manual credit needed.",
        )
        return ConversationHandler.END

    # Mark used FIRST (atomic, unique index) to prevent double-credit on races
    if not await db.mark_txn_used(txn_id, user.id, amount):
        await status_msg.edit_text(
            "⚠️ This Transaction ID has already been credited.",
            reply_markup=keyboards.wallet_kb(),
        )
        return ConversationHandler.END

    new_balance = await db.credit_wallet(
        user.id, amount, ttype="recharge", ref=txn_id, note="Auto Gmail verification"
    )

    await status_msg.edit_text(
        messages.recharge_success(amount, new_balance),
        reply_markup=keyboards.wallet_kb(),
        parse_mode=ParseMode.MARKDOWN,
    )
    await _notify_admin(
        ctx,
        f"✅ Auto-recharge {format_currency(amount)} | UTR `{txn_id}` | "
        f"@{user.username or user.id} | New balance {format_currency(new_balance)}",
    )
    return ConversationHandler.END


async def cancel_recharge(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    # Called when user taps "Cancel" (callback) during recharge conversation
    query = update.callback_query
    if query:
        await query.answer()
    return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════════════
# PURCHASE FROM WALLET
# ══════════════════════════════════════════════════════════════════════════
async def cbq_quantity(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Preset quantity buttons: qty_{cat_id}_{qty}"""
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    cat_id, qty = int(parts[1]), int(parts[2])
    await _show_confirm(query, cat_id, qty)


async def cbq_custom_qty_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cat_id = int(query.data.split("qtycustom_")[1])
    ctx.user_data["pending_cat_id"] = cat_id
    await query.edit_message_text(
        "✏️ *Enter Custom Quantity*\n\nType the number of items you want (1–100).",
        parse_mode=ParseMode.MARKDOWN,
    )
    return CUSTOM_QTY


async def receive_custom_qty(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    qty = safe_int(update.message.text)
    cat_id = ctx.user_data.get("pending_cat_id")
    if cat_id is None:
        await update.message.reply_text("Session expired. Please start again.",
                                        reply_markup=keyboards.back_to_main_kb())
        return ConversationHandler.END
    if qty is None or qty < 1 or qty > 100:
        await update.message.reply_text("❌ Please enter a valid number between 1 and 100.")
        return CUSTOM_QTY
    await _show_confirm(update.message, cat_id, qty, is_message=True)
    return ConversationHandler.END


async def _show_confirm(target, cat_id: int, qty: int, is_message: bool = False):
    db = await Database.get_instance()
    cat = await db.get_category(cat_id)
    if not cat:
        text = "Category not found."
        if is_message:
            await target.reply_text(text, reply_markup=keyboards.back_to_main_kb())
        else:
            await target.edit_message_text(text, reply_markup=keyboards.back_to_main_kb())
        return

    user_id = target.from_user.id if not is_message else target.chat.id
    # For messages, chat.id == user id in private chats
    stock = await db.stock_count(cat_id)
    balance = await db.get_balance(user_id)
    total = round(cat["price"] * qty, 2)

    if stock < qty:
        text = (f"😔 Only *{stock}* in stock for *{cat['name']}*.\n"
                f"Please choose a smaller quantity.")
        kb = keyboards.quantity_kb(cat_id)
    elif balance < total:
        text = messages.insufficient_balance(total, balance)
        kb = keyboards.confirm_purchase_kb(cat_id, qty)
    else:
        text = (
            f"🧾 *Confirm Purchase*\n\n"
            f"Item: {cat['name']}\n"
            f"Quantity: {qty}\n"
            f"Total: *{format_currency(total)}*\n"
            f"Wallet Balance: *{format_currency(balance)}*\n"
            f"After purchase: *{format_currency(balance - total)}*\n\n"
            "Confirm to pay from your wallet 👇"
        )
        kb = keyboards.confirm_purchase_kb(cat_id, qty)

    if is_message:
        await target.reply_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
    else:
        await target.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)


async def cbq_confirm_buy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """buy_{cat_id}_{qty} — finalize purchase paid from wallet."""
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    cat_id, qty = int(parts[1]), int(parts[2])
    user = query.from_user
    db = await Database.get_instance()

    cat = await db.get_category(cat_id)
    if not cat:
        await query.answer("Category not found!", show_alert=True)
        return

    total = round(cat["price"] * qty, 2)
    stock = await db.stock_count(cat_id)
    if stock < qty:
        await query.edit_message_text(
            f"😔 Not enough stock. Only {stock} left.",
            reply_markup=keyboards.back_to_main_kb(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # 1) Atomically debit wallet (fails if insufficient)
    new_balance = await db.debit_wallet(
        user.id, total, ttype="purchase", note=f"{qty}x {cat['name']}"
    )
    if new_balance is None:
        balance = await db.get_balance(user.id)
        await query.edit_message_text(
            messages.insufficient_balance(total, balance),
            reply_markup=keyboards.wallet_kb(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # 2) Reserve stock
    order_id = generate_order_id()
    codes = await db.reserve_stock(cat_id, qty, order_id)
    if not codes:
        # Refund — stock vanished between check and claim
        await db.credit_wallet(user.id, total, ttype="refund", ref=order_id,
                               note="Auto refund: stock unavailable")
        await query.edit_message_text(
            "😔 Sorry, the stock just sold out. Your wallet was *not* charged.",
            reply_markup=keyboards.back_to_main_kb(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # 3) Record order (purchase history)
    await db.create_order({
        "order_id": order_id,
        "user_id": user.id,
        "username": user.username or "",
        "category_id": cat_id,
        "category_name": cat["name"],
        "quantity": qty,
        "amount": total,
        "status": "completed",
        "items": codes,
        "ref": order_id,
    })
    # link the txn ref to this order
    await db.db.transactions.update_one(
        {"user_id": user.id, "type": "purchase", "ref": ""},
        {"$set": {"ref": order_id}},
        upsert=False,
    )

    # 4) Deliver codes
    await query.edit_message_text(
        messages.purchase_success(cat["name"], qty, total, new_balance),
        reply_markup=keyboards.back_to_main_kb(),
        parse_mode=ParseMode.MARKDOWN,
    )
    await ctx.bot.send_message(
        chat_id=user.id,
        text=format_delivery(cat["name"], codes),
        parse_mode=ParseMode.MARKDOWN,
    )
    await _notify_admin(
        ctx,
        f"🛒 Sale: {qty}x {cat['name']} = {format_currency(total)} | "
        f"@{user.username or user.id} | Order {order_id}",
    )


# ── Helpers ────────────────────────────────────────────────────────────────
async def _notify_admin(ctx, text: str):
    if config.ADMIN_CHAT_ID:
        try:
            await ctx.bot.send_message(
                chat_id=int(config.ADMIN_CHAT_ID), text=text, parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.warning("Could not notify admin: %s", e)


def register_payment_handlers(app):
    # Recharge conversation
    recharge_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cbq_recharge_start, pattern="^recharge$")],
        states={
            RECHARGE_TXN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_txn_id),
                CallbackQueryHandler(cancel_recharge, pattern="^wallet$"),
            ],
        },
        fallbacks=[CallbackQueryHandler(cancel_recharge, pattern="^(wallet|main_menu)$")],
        per_chat=True,
        per_user=True,
    )

    # Custom quantity conversation
    custom_qty_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cbq_custom_qty_start, pattern=r"^qtycustom_\d+$")],
        states={
            CUSTOM_QTY: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_custom_qty)],
        },
        fallbacks=[],
        per_chat=True,
        per_user=True,
    )

    app.add_handler(recharge_conv)
    app.add_handler(custom_qty_conv)
    app.add_handler(CallbackQueryHandler(cbq_quantity, pattern=r"^qty_\d+_\d+$"))
    app.add_handler(CallbackQueryHandler(cbq_confirm_buy, pattern=r"^buy_\d+_\d+$"))
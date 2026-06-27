"""
handlers/admin.py - Full admin control dashboard.

Features:
  • Manage coupons   - add / edit / delete categories, add stock
  • Manage users     - ban / unban
  • Wallet control   - add / deduct / check any user's balance
  • Transactions     - view recent wallet ledger
  • Analytics        - users, revenue, recharges, stock, top categories
  • Announcements    - broadcast a message to all users
  • Settings         - UPI id, payee name, maintenance mode
"""

import asyncio
import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

import keyboards
from database import Database
from utils import is_admin, safe_int, safe_float, format_currency, fmt_dt

logger = logging.getLogger(__name__)

# Conversation states
(
    ADD_CAT_NAME, ADD_CAT_PRICE,
    EDIT_NAME, EDIT_PRICE,
    ADD_STOCK,
    WALLET_ADD_UID, WALLET_ADD_AMT,
    WALLET_DED_UID, WALLET_DED_AMT,
    WALLET_CHECK_UID,
    BAN_UID, UNBAN_UID,
    ANNOUNCE_MSG,
    SET_UPI, SET_PAYEE,
) = range(15)


def admin_only(func):
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not is_admin(update.effective_user.id):
            if update.callback_query:
                await update.callback_query.answer("❌ Admin only.", show_alert=True)
            else:
                await update.message.reply_text("❌ This command is for admins only.")
            return ConversationHandler.END
        return await func(update, ctx)
    return wrapper


# ══════════════════════════════════════════════════════════════════════════
# MENU
# ══════════════════════════════════════════════════════════════════════════
@admin_only
async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = "🛠️ *Admin Control Panel*\n\nSelect an option below:"
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            text, reply_markup=keyboards.admin_menu_kb(), parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text(
            text, reply_markup=keyboards.admin_menu_kb(), parse_mode=ParseMode.MARKDOWN
        )


@admin_only
async def cbq_admin_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🛠️ *Admin Control Panel*\n\nSelect an option below:",
        reply_markup=keyboards.admin_menu_kb(),
        parse_mode=ParseMode.MARKDOWN,
    )


# ══════════════════════════════════════════════════════════════════════════
# COUPON MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════
@admin_only
async def cbq_coupons(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    db = await Database.get_instance()
    cats = await db.get_categories(active_only=False)
    await query.edit_message_text(
        "🏷️ *Manage Coupons*\n\nSelect a category or add a new one:",
        reply_markup=keyboards.admin_coupons_kb(cats),
        parse_mode=ParseMode.MARKDOWN,
    )


@admin_only
async def cbq_category(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cat_id = int(query.data.split("adm_cat_")[1])
    db = await Database.get_instance()
    cat = await db.get_category(cat_id)
    if not cat:
        await query.answer("Not found", show_alert=True)
        return
    stock = await db.stock_count(cat_id)
    text = (
        f"🏷️ *{cat['name']}*\n\n"
        f"💵 Price: {format_currency(cat['price'])}\n"
        f"📦 Stock: {stock}\n"
        f"Status: {'Active ✅' if cat.get('is_active') else 'Inactive ❌'}"
    )
    await query.edit_message_text(
        text, reply_markup=keyboards.admin_category_kb(cat_id), parse_mode=ParseMode.MARKDOWN
    )


# ── Add category ──
@admin_only
async def cbq_add_cat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("➕ *Add Category*\n\nSend the category name:",
                                  parse_mode=ParseMode.MARKDOWN)
    return ADD_CAT_NAME


async def add_cat_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["new_cat_name"] = update.message.text.strip()
    await update.message.reply_text("💵 Now send the price (e.g. 50 or 99.99):")
    return ADD_CAT_PRICE


async def add_cat_price(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    price = safe_float(update.message.text)
    if price is None or price < 0:
        await update.message.reply_text("❌ Invalid price. Send a number like 50:")
        return ADD_CAT_PRICE
    db = await Database.get_instance()
    name = ctx.user_data.get("new_cat_name", "Unnamed")
    try:
        cid = await db.add_category(name, price)
    except Exception:
        await update.message.reply_text(
            "❌ A category with that name already exists.",
            reply_markup=keyboards.admin_back_kb(),
        )
        return ConversationHandler.END
    await update.message.reply_text(
        f"✅ Category *{name}* added (ID {cid}) at {format_currency(price)}.\n"
        "Now add stock from the category menu.",
        reply_markup=keyboards.admin_back_kb(),
        parse_mode=ParseMode.MARKDOWN,
    )
    return ConversationHandler.END


# ── Edit name ──
@admin_only
async def cbq_edit_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["edit_cat_id"] = int(query.data.split("adm_editname_")[1])
    await query.edit_message_text("✏️ Send the new category name:", parse_mode=ParseMode.MARKDOWN)
    return EDIT_NAME


async def edit_name_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    db = await Database.get_instance()
    cid = ctx.user_data.get("edit_cat_id")
    await db.update_category(cid, name=update.message.text.strip())
    await update.message.reply_text("✅ Name updated.", reply_markup=keyboards.admin_back_kb())
    return ConversationHandler.END


# ── Edit price ──
@admin_only
async def cbq_edit_price(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["edit_cat_id"] = int(query.data.split("adm_editprice_")[1])
    await query.edit_message_text("💵 Send the new price:", parse_mode=ParseMode.MARKDOWN)
    return EDIT_PRICE


async def edit_price_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    price = safe_float(update.message.text)
    if price is None or price < 0:
        await update.message.reply_text("❌ Invalid price. Try again:")
        return EDIT_PRICE
    db = await Database.get_instance()
    await db.update_category(ctx.user_data.get("edit_cat_id"), price=round(price, 2))
    await update.message.reply_text("✅ Price updated.", reply_markup=keyboards.admin_back_kb())
    return ConversationHandler.END


# ── Add stock ──
@admin_only
async def cbq_add_stock(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["stock_cat_id"] = int(query.data.split("adm_addstock_")[1])
    await query.edit_message_text(
        "➕ *Add Stock*\n\nSend the coupon codes — *one per line*.\n"
        "Each line becomes one sellable coupon.",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ADD_STOCK


async def add_stock_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    db = await Database.get_instance()
    cid = ctx.user_data.get("stock_cat_id")
    items = [ln for ln in update.message.text.splitlines() if ln.strip()]
    added = await db.add_stock(cid, items)
    await update.message.reply_text(
        f"✅ Added *{added}* coupon code(s).",
        reply_markup=keyboards.admin_back_kb(),
        parse_mode=ParseMode.MARKDOWN,
    )
    return ConversationHandler.END


# ── Delete category ──
@admin_only
async def cbq_del_cat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cat_id = int(query.data.split("adm_delcat_")[1])
    await query.edit_message_text(
        "🗑️ *Delete this category and ALL its stock?*\nThis cannot be undone.",
        reply_markup=keyboards.admin_confirm_delete_kb(cat_id),
        parse_mode=ParseMode.MARKDOWN,
    )


@admin_only
async def cbq_del_cat_yes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cat_id = int(query.data.split("adm_delcatyes_")[1])
    db = await Database.get_instance()
    await db.delete_category(cat_id)
    await query.edit_message_text("✅ Category deleted.", reply_markup=keyboards.admin_back_kb())


# ══════════════════════════════════════════════════════════════════════════
# WALLET CONTROL
# ══════════════════════════════════════════════════════════════════════════
@admin_only
async def cbq_wallet_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "💰 *Wallet Control*\n\nManage any user's wallet balance:",
        reply_markup=keyboards.admin_wallet_kb(),
        parse_mode=ParseMode.MARKDOWN,
    )


@admin_only
async def cbq_wallet_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("➕ Send the *user ID* to credit:",
                                                  parse_mode=ParseMode.MARKDOWN)
    return WALLET_ADD_UID


async def wallet_add_uid(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = safe_int(update.message.text)
    if uid is None:
        await update.message.reply_text("❌ Invalid user ID. Try again:")
        return WALLET_ADD_UID
    ctx.user_data["w_uid"] = uid
    await update.message.reply_text("💵 Send the amount to ADD:")
    return WALLET_ADD_AMT


async def wallet_add_amt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    amt = safe_float(update.message.text)
    if amt is None or amt <= 0:
        await update.message.reply_text("❌ Invalid amount. Try again:")
        return WALLET_ADD_AMT
    db = await Database.get_instance()
    uid = ctx.user_data["w_uid"]
    new_bal = await db.admin_adjust_wallet(uid, amt, note="Admin credit")
    await update.message.reply_text(
        f"✅ Added {format_currency(amt)} to `{uid}`.\nNew balance: {format_currency(new_bal)}",
        reply_markup=keyboards.admin_back_kb(), parse_mode=ParseMode.MARKDOWN,
    )
    try:
        await ctx.bot.send_message(uid, f"💰 Your wallet was credited {format_currency(amt)} by admin.\n"
                                        f"New balance: {format_currency(new_bal)}")
    except Exception:
        pass
    return ConversationHandler.END


@admin_only
async def cbq_wallet_deduct(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("➖ Send the *user ID* to deduct from:",
                                                  parse_mode=ParseMode.MARKDOWN)
    return WALLET_DED_UID


async def wallet_ded_uid(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = safe_int(update.message.text)
    if uid is None:
        await update.message.reply_text("❌ Invalid user ID. Try again:")
        return WALLET_DED_UID
    ctx.user_data["w_uid"] = uid
    await update.message.reply_text("💵 Send the amount to DEDUCT:")
    return WALLET_DED_AMT


async def wallet_ded_amt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    amt = safe_float(update.message.text)
    if amt is None or amt <= 0:
        await update.message.reply_text("❌ Invalid amount. Try again:")
        return WALLET_DED_AMT
    db = await Database.get_instance()
    uid = ctx.user_data["w_uid"]
    new_bal = await db.admin_adjust_wallet(uid, -amt, note="Admin deduction")
    await update.message.reply_text(
        f"✅ Deducted {format_currency(amt)} from `{uid}`.\nNew balance: {format_currency(new_bal)}",
        reply_markup=keyboards.admin_back_kb(), parse_mode=ParseMode.MARKDOWN,
    )
    return ConversationHandler.END


@admin_only
async def cbq_wallet_check(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("🔍 Send the *user ID* to check:",
                                                  parse_mode=ParseMode.MARKDOWN)
    return WALLET_CHECK_UID


async def wallet_check_uid(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = safe_int(update.message.text)
    if uid is None:
        await update.message.reply_text("❌ Invalid user ID. Try again:")
        return WALLET_CHECK_UID
    db = await Database.get_instance()
    u = await db.get_user(uid)
    if not u:
        await update.message.reply_text("User not found.", reply_markup=keyboards.admin_back_kb())
        return ConversationHandler.END
    txns = await db.get_transactions(uid, limit=5)
    hist = "\n".join(
        f"  {'+' if t['amount']>=0 else '−'}{format_currency(abs(t['amount']))} • {t['type']} • {fmt_dt(t['created_at'])}"
        for t in txns
    ) or "  (no transactions)"
    await update.message.reply_text(
        f"👤 *User* `{uid}`\n"
        f"Name: {u.get('full_name','N/A')} (@{u.get('username','')})\n"
        f"💰 Balance: *{format_currency(u.get('wallet_balance',0))}*\n"
        f"⬆️ Recharged: {format_currency(u.get('total_recharged',0))}\n"
        f"🛒 Spent: {format_currency(u.get('total_spent',0))}\n"
        f"Banned: {'Yes' if u.get('is_banned') else 'No'}\n\n"
        f"*Recent:*\n{hist}",
        reply_markup=keyboards.admin_back_kb(), parse_mode=ParseMode.MARKDOWN,
    )
    return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════════════
# USERS (ban / unban)
# ══════════════════════════════════════════════════════════════════════════
@admin_only
async def cbq_users(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    db = await Database.get_instance()
    total = await db.count_users()
    await query.edit_message_text(
        f"👥 *Manage Users*\n\nTotal users: *{total}*",
        reply_markup=keyboards.admin_users_kb(),
        parse_mode=ParseMode.MARKDOWN,
    )


@admin_only
async def cbq_ban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("🚫 Send the *user ID* to ban:",
                                                  parse_mode=ParseMode.MARKDOWN)
    return BAN_UID


async def ban_uid_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = safe_int(update.message.text)
    if uid is None:
        await update.message.reply_text("❌ Invalid ID. Try again:")
        return BAN_UID
    db = await Database.get_instance()
    await db.set_banned(uid, True)
    await update.message.reply_text(f"🚫 User `{uid}` banned.",
                                    reply_markup=keyboards.admin_back_kb(),
                                    parse_mode=ParseMode.MARKDOWN)
    return ConversationHandler.END


@admin_only
async def cbq_unban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("✅ Send the *user ID* to unban:",
                                                  parse_mode=ParseMode.MARKDOWN)
    return UNBAN_UID


async def unban_uid_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = safe_int(update.message.text)
    if uid is None:
        await update.message.reply_text("❌ Invalid ID. Try again:")
        return UNBAN_UID
    db = await Database.get_instance()
    await db.set_banned(uid, False)
    await update.message.reply_text(f"✅ User `{uid}` unbanned.",
                                    reply_markup=keyboards.admin_back_kb(),
                                    parse_mode=ParseMode.MARKDOWN)
    return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════════════
# TRANSACTIONS
# ══════════════════════════════════════════════════════════════════════════
@admin_only
async def cbq_txns(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    db = await Database.get_instance()
    txns = await db.get_all_transactions(limit=20)
    if not txns:
        await query.edit_message_text("📜 No transactions yet.",
                                      reply_markup=keyboards.admin_back_kb())
        return
    icons = {"recharge": "⬆️", "purchase": "🛒", "admin_adjust": "🛠️", "refund": "↩️"}
    lines = ["📜 *Recent Transactions*\n"]
    for t in txns:
        sign = "+" if t["amount"] >= 0 else "−"
        lines.append(
            f"{icons.get(t['type'],'•')} `{t['user_id']}` {sign}{format_currency(abs(t['amount']))} "
            f"• {fmt_dt(t['created_at'])}"
        )
    await query.edit_message_text("\n".join(lines), reply_markup=keyboards.admin_back_kb(),
                                  parse_mode=ParseMode.MARKDOWN)


# ══════════════════════════════════════════════════════════════════════════
# ANALYTICS
# ══════════════════════════════════════════════════════════════════════════
@admin_only
async def cbq_analytics(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    db = await Database.get_instance()
    a = await db.analytics()
    top = "\n".join(
        f"  • {c['_id'] or 'N/A'}: {c['count']} sold ({format_currency(c['revenue'])})"
        for c in a["top_categories"]
    ) or "  (no sales yet)"
    text = (
        "📊 *Analytics & Sales Report*\n\n"
        f"👥 Total Users: *{a['total_users']}* (banned: {a['banned_users']})\n"
        f"🛒 Completed Orders: *{a['total_orders']}*\n"
        f"💵 Total Revenue: *{format_currency(a['revenue'])}*\n"
        f"⬆️ Total Recharged: *{format_currency(a['recharged'])}*\n"
        f"💰 Wallet Liability: *{format_currency(a['wallet_liability'])}*\n"
        f"📦 Available Stock: *{a['available_stock']}*\n\n"
        f"*Top Categories:*\n{top}"
    )
    await query.edit_message_text(text, reply_markup=keyboards.admin_back_kb(),
                                  parse_mode=ParseMode.MARKDOWN)


# ══════════════════════════════════════════════════════════════════════════
# ANNOUNCEMENTS (broadcast)
# ══════════════════════════════════════════════════════════════════════════
@admin_only
async def cbq_announce(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        "📢 *Send Announcement*\n\nSend the message to broadcast to ALL users.\n"
        "Markdown is supported.",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ANNOUNCE_MSG


async def announce_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    db = await Database.get_instance()
    user_ids = await db.all_user_ids()
    await update.message.reply_text(f"📤 Broadcasting to {len(user_ids)} users…")

    sent, failed = 0, 0
    for i, uid in enumerate(user_ids):
        try:
            await ctx.bot.send_message(uid, f"📢 *Announcement*\n\n{text}",
                                       parse_mode=ParseMode.MARKDOWN)
            sent += 1
        except Exception:
            failed += 1
        if i % 25 == 0:
            await asyncio.sleep(1)  # rate-limit friendly

    await update.message.reply_text(
        f"✅ Broadcast complete.\nSent: {sent} | Failed: {failed}",
        reply_markup=keyboards.admin_back_kb(),
    )
    return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════════════
# SETTINGS
# ══════════════════════════════════════════════════════════════════════════
@admin_only
async def cbq_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    db = await Database.get_instance()
    import config
    upi = await db.get_setting("upi_id", config.UPI_ID) or "(not set)"
    payee = await db.get_setting("payee_name", config.PAYEE_NAME) or "(not set)"
    maint = await db.get_setting("maintenance", "false")
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Set UPI ID", callback_data="adm_setupi")],
        [InlineKeyboardButton("👤 Set Payee Name", callback_data="adm_setpayee")],
        [InlineKeyboardButton(
            f"🛠️ Maintenance: {'ON' if maint=='true' else 'OFF'} (toggle)",
            callback_data="adm_togglemaint")],
        [InlineKeyboardButton("🔙 Admin Menu", callback_data="adm_menu")],
    ])
    await query.edit_message_text(
        f"⚙️ *Settings*\n\n"
        f"💳 UPI ID: `{upi}`\n"
        f"👤 Payee: {payee}\n"
        f"🛠️ Maintenance: {'ON' if maint=='true' else 'OFF'}",
        reply_markup=kb, parse_mode=ParseMode.MARKDOWN,
    )


@admin_only
async def cbq_toggle_maint(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    db = await Database.get_instance()
    cur = await db.get_setting("maintenance", "false")
    new = "false" if cur == "true" else "true"
    await db.set_setting("maintenance", new)
    await query.answer(f"Maintenance {'ON' if new=='true' else 'OFF'}")
    await cbq_settings(update, ctx)


@admin_only
async def cbq_set_upi(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("💳 Send the new UPI ID:",
                                                  parse_mode=ParseMode.MARKDOWN)
    return SET_UPI


async def set_upi_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    db = await Database.get_instance()
    await db.set_setting("upi_id", update.message.text.strip())
    await update.message.reply_text("✅ UPI ID updated.", reply_markup=keyboards.admin_back_kb())
    return ConversationHandler.END


@admin_only
async def cbq_set_payee(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("👤 Send the new payee name:",
                                                  parse_mode=ParseMode.MARKDOWN)
    return SET_PAYEE


async def set_payee_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    db = await Database.get_instance()
    await db.set_setting("payee_name", update.message.text.strip())
    await update.message.reply_text("✅ Payee name updated.", reply_markup=keyboards.admin_back_kb())
    return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════════════
# REGISTRATION
# ══════════════════════════════════════════════════════════════════════════
def _conv(entry_pattern, entry_func, state, state_func):
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(entry_func, pattern=entry_pattern)],
        states={state: [MessageHandler(filters.TEXT & ~filters.COMMAND, state_func)]},
        fallbacks=[CommandHandler("admin", cmd_admin),
                   CallbackQueryHandler(cbq_admin_menu, pattern="^adm_menu$")],
        per_chat=True, per_user=True,
    )


def register_admin_handlers(app):
    app.add_handler(CommandHandler("admin", cmd_admin))

    # Add category (2-step conversation)
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(cbq_add_cat, pattern="^adm_addcat$")],
        states={
            ADD_CAT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_cat_name)],
            ADD_CAT_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_cat_price)],
        },
        fallbacks=[CommandHandler("admin", cmd_admin)],
        per_chat=True, per_user=True,
    ))

    # Single-step conversations
    app.add_handler(_conv(r"^adm_editname_\d+$", cbq_edit_name, EDIT_NAME, edit_name_input))
    app.add_handler(_conv(r"^adm_editprice_\d+$", cbq_edit_price, EDIT_PRICE, edit_price_input))
    app.add_handler(_conv(r"^adm_addstock_\d+$", cbq_add_stock, ADD_STOCK, add_stock_input))
    # Wallet add (2-step)
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(cbq_wallet_add, pattern="^adm_walletadd$")],
        states={
            WALLET_ADD_UID: [MessageHandler(filters.TEXT & ~filters.COMMAND, wallet_add_uid)],
            WALLET_ADD_AMT: [MessageHandler(filters.TEXT & ~filters.COMMAND, wallet_add_amt)],
        },
        fallbacks=[CommandHandler("admin", cmd_admin)],
        per_chat=True, per_user=True,
    ))
    # Wallet deduct (2-step)
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(cbq_wallet_deduct, pattern="^adm_walletdeduct$")],
        states={
            WALLET_DED_UID: [MessageHandler(filters.TEXT & ~filters.COMMAND, wallet_ded_uid)],
            WALLET_DED_AMT: [MessageHandler(filters.TEXT & ~filters.COMMAND, wallet_ded_amt)],
        },
        fallbacks=[CommandHandler("admin", cmd_admin)],
        per_chat=True, per_user=True,
    ))
    app.add_handler(_conv("^adm_walletcheck$", cbq_wallet_check, WALLET_CHECK_UID, wallet_check_uid))
    app.add_handler(_conv("^adm_ban$", cbq_ban, BAN_UID, ban_uid_input))
    app.add_handler(_conv("^adm_unban$", cbq_unban, UNBAN_UID, unban_uid_input))
    app.add_handler(_conv("^adm_announce$", cbq_announce, ANNOUNCE_MSG, announce_input))
    app.add_handler(_conv("^adm_setupi$", cbq_set_upi, SET_UPI, set_upi_input))
    app.add_handler(_conv("^adm_setpayee$", cbq_set_payee, SET_PAYEE, set_payee_input))

    # Simple callbacks
    app.add_handler(CallbackQueryHandler(cbq_admin_menu, pattern="^adm_menu$"))
    app.add_handler(CallbackQueryHandler(cbq_coupons, pattern="^adm_coupons$"))
    app.add_handler(CallbackQueryHandler(cbq_category, pattern=r"^adm_cat_\d+$"))
    app.add_handler(CallbackQueryHandler(cbq_del_cat, pattern=r"^adm_delcat_\d+$"))
    app.add_handler(CallbackQueryHandler(cbq_del_cat_yes, pattern=r"^adm_delcatyes_\d+$"))
    app.add_handler(CallbackQueryHandler(cbq_wallet_menu, pattern="^adm_wallet$"))
    app.add_handler(CallbackQueryHandler(cbq_users, pattern="^adm_users$"))
    app.add_handler(CallbackQueryHandler(cbq_txns, pattern="^adm_txns$"))
    app.add_handler(CallbackQueryHandler(cbq_analytics, pattern="^adm_analytics$"))
    app.add_handler(CallbackQueryHandler(cbq_settings, pattern="^adm_settings$"))
    app.add_handler(CallbackQueryHandler(cbq_toggle_maint, pattern="^adm_togglemaint$"))
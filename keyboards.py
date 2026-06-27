"""
keyboards.py - All InlineKeyboardMarkup builders for the bot.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from utils import chunks


# ══════════════════════════════════════════════════════════════════════════
# USER KEYBOARDS
# ══════════════════════════════════════════════════════════════════════════
def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛍️ Browse Categories", callback_data="browse")],
        [InlineKeyboardButton("💼 My Wallet", callback_data="wallet")],
        [InlineKeyboardButton("📦 My Orders", callback_data="my_orders")],
        [InlineKeyboardButton("ℹ️ Help / Support", callback_data="help")],
    ])


def wallet_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Recharge Wallet", callback_data="recharge")],
        [InlineKeyboardButton("📜 Transaction History", callback_data="txn_history")],
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")],
    ])


def recharge_cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Cancel", callback_data="wallet")],
    ])


def categories_kb(categories: list[dict]) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(
            f"🏷️ {c['name']} ({c['price']:.0f}₹)", callback_data=f"cat_{c['id']}"
        )]
        for c in categories
    ]
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data="main_menu")])
    return InlineKeyboardMarkup(buttons)


def quantity_kb(cat_id: int) -> InlineKeyboardMarkup:
    quantities = [1, 2, 5, 10]
    rows = list(chunks(
        [InlineKeyboardButton(str(q), callback_data=f"qty_{cat_id}_{q}") for q in quantities],
        2,
    ))
    rows.append([InlineKeyboardButton("✏️ Custom Quantity", callback_data=f"qtycustom_{cat_id}")])
    rows.append([InlineKeyboardButton("🔙 Back", callback_data="browse")])
    return InlineKeyboardMarkup(rows)


def confirm_purchase_kb(cat_id: int, qty: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm & Pay from Wallet", callback_data=f"buy_{cat_id}_{qty}")],
        [InlineKeyboardButton("➕ Recharge", callback_data="recharge"),
         InlineKeyboardButton("🔙 Back", callback_data=f"cat_{cat_id}")],
    ])


def back_to_main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")],
    ])


def my_orders_kb(orders: list[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for o in orders:
        label = f"{o['order_id']} • {o.get('category_name', 'N/A')} • {o['status']}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"vieworder_{o['order_id']}")])
    buttons.append([InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")])
    return InlineKeyboardMarkup(buttons)


# ══════════════════════════════════════════════════════════════════════════
# ADMIN KEYBOARDS
# ══════════════════════════════════════════════════════════════════════════
def admin_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏷️ Manage Coupons", callback_data="adm_coupons")],
        [InlineKeyboardButton("👥 Manage Users", callback_data="adm_users")],
        [InlineKeyboardButton("💰 Wallet Control", callback_data="adm_wallet")],
        [InlineKeyboardButton("📜 Transactions", callback_data="adm_txns")],
        [InlineKeyboardButton("📊 Analytics", callback_data="adm_analytics")],
        [InlineKeyboardButton("📢 Announcement", callback_data="adm_announce")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="adm_settings")],
    ])


def admin_coupons_kb(categories: list[dict]) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton("➕ Add Category", callback_data="adm_addcat")]]
    for c in categories:
        buttons.append([
            InlineKeyboardButton(f"🏷️ {c['name']} ({c['price']:.0f}₹)", callback_data=f"adm_cat_{c['id']}"),
        ])
    buttons.append([InlineKeyboardButton("🔙 Admin Menu", callback_data="adm_menu")])
    return InlineKeyboardMarkup(buttons)


def admin_category_kb(cat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Stock", callback_data=f"adm_addstock_{cat_id}")],
        [InlineKeyboardButton("✏️ Edit Name", callback_data=f"adm_editname_{cat_id}"),
         InlineKeyboardButton("💵 Edit Price", callback_data=f"adm_editprice_{cat_id}")],
        [InlineKeyboardButton("🗑️ Delete Category", callback_data=f"adm_delcat_{cat_id}")],
        [InlineKeyboardButton("🔙 Coupons", callback_data="adm_coupons")],
    ])


def admin_confirm_delete_kb(cat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes, delete", callback_data=f"adm_delcatyes_{cat_id}"),
         InlineKeyboardButton("❌ No", callback_data=f"adm_cat_{cat_id}")],
    ])


def admin_wallet_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Balance", callback_data="adm_walletadd")],
        [InlineKeyboardButton("➖ Deduct Balance", callback_data="adm_walletdeduct")],
        [InlineKeyboardButton("🔍 Check User Balance", callback_data="adm_walletcheck")],
        [InlineKeyboardButton("🔙 Admin Menu", callback_data="adm_menu")],
    ])


def admin_users_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚫 Ban User", callback_data="adm_ban"),
         InlineKeyboardButton("✅ Unban User", callback_data="adm_unban")],
        [InlineKeyboardButton("🔙 Admin Menu", callback_data="adm_menu")],
    ])


def admin_back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Admin Menu", callback_data="adm_menu")],
    ])
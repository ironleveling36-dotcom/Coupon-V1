"""
messages.py - Static and dynamic message templates.
"""

from config import BOT_NAME, CURRENCY_SYMBOL


def _cur(amount: float) -> str:
    return f"{CURRENCY_SYMBOL}{amount:,.2f}"


def welcome(first_name: str, balance: float) -> str:
    return (
        f"👋 *Welcome to {BOT_NAME}, {first_name}!*\n\n"
        f"💰 Wallet Balance: *{_cur(balance)}*\n\n"
        "Buy coupons instantly using your wallet. Recharge anytime — "
        "payments are verified automatically.\n\n"
        "Choose an option below 👇"
    )


def wallet_overview(balance: float, total_recharged: float, total_spent: float) -> str:
    return (
        "💼 *My Wallet*\n\n"
        f"💰 Current Balance: *{_cur(balance)}*\n"
        f"⬆️ Total Recharged: {_cur(total_recharged)}\n"
        f"🛒 Total Spent: {_cur(total_spent)}\n\n"
        "Use the buttons below to recharge or view your transactions."
    )


def recharge_instructions(upi_id: str, payee: str) -> str:
    return (
        "➕ *Recharge Wallet*\n\n"
        f"1️⃣ Pay any amount to:\n"
        f"   💳 UPI ID: `{upi_id}`\n"
        f"   👤 Name: {payee}\n\n"
        "2️⃣ After paying, *send me your UPI Transaction ID / UTR* "
        "(the 12-digit reference from your UPI app).\n\n"
        "✅ Your wallet will be credited *automatically* once the payment "
        "is verified from our bank email — usually within 1–2 minutes."
    )


def recharge_success(amount: float, balance: float) -> str:
    return (
        "✅ *Recharge Successful!*\n\n"
        f"Added: *{_cur(amount)}*\n"
        f"New Balance: *{_cur(balance)}*\n\n"
        "You can now buy coupons instantly. 🎉"
    )


def category_detail(name: str, price: float, stock: int, balance: float) -> str:
    return (
        f"🏷️ *{name}*\n\n"
        f"💵 Price: *{_cur(price)}* each\n"
        f"📦 In stock: *{stock}*\n"
        f"💰 Your balance: *{_cur(balance)}*\n\n"
        "Select a quantity to buy 👇"
    )


def out_of_stock_msg(name: str) -> str:
    return (
        f"😔 *{name}* is currently *out of stock.*\n\n"
        "Please check back later or browse other categories."
    )


def insufficient_balance(needed: float, balance: float) -> str:
    return (
        "⚠️ *Insufficient Wallet Balance*\n\n"
        f"Order total: *{_cur(needed)}*\n"
        f"Your balance: *{_cur(balance)}*\n"
        f"Short by: *{_cur(needed - balance)}*\n\n"
        "Please recharge your wallet to continue."
    )


def purchase_success(name: str, qty: int, amount: float, balance: float) -> str:
    return (
        "✅ *Purchase Successful!*\n\n"
        f"Item: {name}\n"
        f"Quantity: {qty}\n"
        f"Paid: *{_cur(amount)}* (from wallet)\n"
        f"Remaining Balance: *{_cur(balance)}*\n"
    )


def help_msg() -> str:
    return (
        "ℹ️ *Help & Support*\n\n"
        "• *Browse Categories* — see available coupons\n"
        "• *My Wallet* — recharge & check balance\n"
        "• *My Orders* — view past purchases & codes\n\n"
        "*How to buy:*\n"
        "1. Recharge your wallet\n"
        "2. Pick a category & quantity\n"
        "3. Coupons are delivered instantly!\n\n"
        "Need help? Contact the admin."
    )


def maintenance() -> str:
    return (
        "🛠️ *Bot Under Maintenance*\n\n"
        "We'll be back shortly. Your wallet balance is safe. Thanks for your patience!"
    )


def banned() -> str:
    return "🚫 *Access Denied*\n\nYour account has been suspended. Contact support."


def no_categories() -> str:
    return "📭 No categories available yet. Please check back soon!"
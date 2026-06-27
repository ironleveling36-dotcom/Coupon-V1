"""
database.py - MongoDB async data layer (Motor) for the Coupon Selling Bot.

This is the single source of truth for ALL persistent data:
  • users          - profile + wallet balance (permanently linked to user_id)
  • categories     - coupon categories / products
  • stock          - individual coupon codes (one row per code)
  • orders         - purchase history
  • transactions   - wallet ledger (recharge + purchase + admin adjustments)
  • used_txns      - UPI transaction IDs already consumed (anti-replay)
  • settings       - key/value bot settings (UPI id, maintenance, etc.)

Design goals:
  • Wallet balance is stored on the user document and updated ATOMICALLY with
    $inc + conditional filters so concurrent purchases can never double-spend.
  • Every balance change writes a transactions ledger row -> nothing is ever lost.
  • Singleton client with pooled connections -> fast + supports many users.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ReturnDocument, ASCENDING, DESCENDING

import config

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Database:
    """Async MongoDB wrapper. Use `await Database.get_instance()`."""

    _instance: Optional["Database"] = None

    def __init__(self):
        self.client: Optional[AsyncIOMotorClient] = None
        self.db = None

    # ── Singleton / lifecycle ─────────────────────────────────────────────
    @classmethod
    async def get_instance(cls) -> "Database":
        if cls._instance is None:
            inst = cls()
            await inst.connect()
            cls._instance = inst
        return cls._instance

    async def connect(self):
        self.client = AsyncIOMotorClient(
            config.MONGO_URI,
            maxPoolSize=50,
            minPoolSize=5,
            serverSelectionTimeoutMS=10000,
            retryWrites=True,
        )
        self.db = self.client[config.MONGO_DB_NAME]
        # Fail fast if unreachable
        await self.client.admin.command("ping")
        await self._ensure_indexes()
        logger.info("Connected to MongoDB database '%s'", config.MONGO_DB_NAME)

    async def _ensure_indexes(self):
        await self.db.users.create_index([("user_id", ASCENDING)], unique=True)
        await self.db.categories.create_index([("name", ASCENDING)], unique=True)
        await self.db.stock.create_index([("category_id", ASCENDING), ("is_sold", ASCENDING)])
        await self.db.orders.create_index([("order_id", ASCENDING)], unique=True)
        await self.db.orders.create_index([("user_id", ASCENDING), ("created_at", DESCENDING)])
        await self.db.transactions.create_index([("user_id", ASCENDING), ("created_at", DESCENDING)])
        await self.db.transactions.create_index([("ref", ASCENDING)])
        await self.db.used_txns.create_index([("txn_id", ASCENDING)], unique=True)
        await self.db.settings.create_index([("key", ASCENDING)], unique=True)
        await self.db.counters.create_index([("_id", ASCENDING)])

    async def close(self):
        if self.client:
            self.client.close()
            self.client = None
        Database._instance = None

    # ── Counters (auto-increment ids for categories) ──────────────────────
    async def _next_seq(self, name: str) -> int:
        doc = await self.db.counters.find_one_and_update(
            {"_id": name},
            {"$inc": {"seq": 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return doc["seq"]

    # ══════════════════════════════════════════════════════════════════════
    # USERS + WALLET
    # ══════════════════════════════════════════════════════════════════════
    async def upsert_user(self, user_id: int, username: str, full_name: str) -> dict:
        """Create the user if new (wallet starts at 0), else update profile.
        Wallet balance is NEVER reset on update -> survives restarts/updates."""
        await self.db.users.update_one(
            {"user_id": user_id},
            {
                "$set": {"username": username, "full_name": full_name, "last_seen": _now()},
                "$setOnInsert": {
                    "wallet_balance": 0.0,
                    "is_banned": False,
                    "joined_at": _now(),
                    "total_spent": 0.0,
                    "total_recharged": 0.0,
                },
            },
            upsert=True,
        )
        return await self.get_user(user_id)

    async def get_user(self, user_id: int) -> Optional[dict]:
        return await self.db.users.find_one({"user_id": user_id})

    async def get_balance(self, user_id: int) -> float:
        u = await self.db.users.find_one({"user_id": user_id}, {"wallet_balance": 1})
        return float(u["wallet_balance"]) if u else 0.0

    async def is_banned(self, user_id: int) -> bool:
        u = await self.db.users.find_one({"user_id": user_id}, {"is_banned": 1})
        return bool(u and u.get("is_banned"))

    async def set_banned(self, user_id: int, banned: bool):
        await self.db.users.update_one(
            {"user_id": user_id}, {"$set": {"is_banned": banned}}, upsert=True
        )

    async def count_users(self) -> int:
        return await self.db.users.count_documents({})

    async def all_user_ids(self) -> list[int]:
        cur = self.db.users.find({"is_banned": {"$ne": True}}, {"user_id": 1})
        return [d["user_id"] async for d in cur]

    async def list_users(self, limit: int = 50, skip: int = 0) -> list[dict]:
        cur = self.db.users.find({}).sort("joined_at", DESCENDING).skip(skip).limit(limit)
        return [d async for d in cur]

    # ── Atomic wallet ops ─────────────────────────────────────────────────
    async def credit_wallet(
        self, user_id: int, amount: float, *, ttype: str, ref: str = "", note: str = ""
    ) -> float:
        """Add funds atomically and write a ledger row. Returns new balance."""
        amount = round(float(amount), 2)
        doc = await self.db.users.find_one_and_update(
            {"user_id": user_id},
            {"$inc": {"wallet_balance": amount, "total_recharged": amount if ttype == "recharge" else 0.0}},
            return_document=ReturnDocument.AFTER,
            upsert=True,
        )
        new_balance = round(float(doc["wallet_balance"]), 2)
        await self._log_txn(user_id, ttype, amount, new_balance, ref=ref, note=note, status="success")
        return new_balance

    async def debit_wallet(
        self, user_id: int, amount: float, *, ttype: str = "purchase", ref: str = "", note: str = ""
    ) -> Optional[float]:
        """Deduct funds ONLY if balance is sufficient (atomic). Returns new
        balance, or None if insufficient funds (no change made)."""
        amount = round(float(amount), 2)
        doc = await self.db.users.find_one_and_update(
            {"user_id": user_id, "wallet_balance": {"$gte": amount}},
            {"$inc": {"wallet_balance": -amount, "total_spent": amount if ttype == "purchase" else 0.0}},
            return_document=ReturnDocument.AFTER,
        )
        if not doc:
            return None  # insufficient funds
        new_balance = round(float(doc["wallet_balance"]), 2)
        await self._log_txn(user_id, ttype, -amount, new_balance, ref=ref, note=note, status="success")
        return new_balance

    async def admin_adjust_wallet(self, user_id: int, amount: float, note: str = "") -> float:
        """Admin sets wallet up or down by `amount` (can be negative)."""
        amount = round(float(amount), 2)
        doc = await self.db.users.find_one_and_update(
            {"user_id": user_id},
            {"$inc": {"wallet_balance": amount}},
            return_document=ReturnDocument.AFTER,
            upsert=True,
        )
        new_balance = round(float(doc["wallet_balance"]), 2)
        await self._log_txn(user_id, "admin_adjust", amount, new_balance, note=note, status="success")
        return new_balance

    async def _log_txn(self, user_id, ttype, amount, balance_after, *, ref="", note="", status="success"):
        await self.db.transactions.insert_one({
            "user_id": user_id,
            "type": ttype,                # recharge | purchase | admin_adjust | refund
            "amount": round(float(amount), 2),
            "balance_after": round(float(balance_after), 2),
            "ref": ref,
            "note": note,
            "status": status,
            "created_at": _now(),
        })

    async def get_transactions(self, user_id: int, limit: int = 20) -> list[dict]:
        cur = self.db.transactions.find({"user_id": user_id}).sort("created_at", DESCENDING).limit(limit)
        return [d async for d in cur]

    async def get_all_transactions(self, limit: int = 50) -> list[dict]:
        cur = self.db.transactions.find({}).sort("created_at", DESCENDING).limit(limit)
        return [d async for d in cur]

    # ── UPI anti-replay ───────────────────────────────────────────────────
    async def is_txn_used(self, txn_id: str) -> bool:
        return await self.db.used_txns.find_one({"txn_id": txn_id}) is not None

    async def mark_txn_used(self, txn_id: str, user_id: int, amount: float):
        try:
            await self.db.used_txns.insert_one({
                "txn_id": txn_id,
                "user_id": user_id,
                "amount": round(float(amount), 2),
                "approved_at": _now(),
            })
            return True
        except Exception:
            return False  # duplicate key -> already used

    # ══════════════════════════════════════════════════════════════════════
    # CATEGORIES (coupon products)
    # ══════════════════════════════════════════════════════════════════════
    async def add_category(self, name: str, price: float) -> int:
        cid = await self._next_seq("category_id")
        await self.db.categories.insert_one({
            "id": cid, "name": name, "price": round(float(price), 2),
            "is_active": True, "created_at": _now(),
        })
        return cid

    async def get_categories(self, active_only: bool = True) -> list[dict]:
        q = {"is_active": True} if active_only else {}
        cur = self.db.categories.find(q).sort("id", ASCENDING)
        return [d async for d in cur]

    async def get_category(self, cat_id: int) -> Optional[dict]:
        return await self.db.categories.find_one({"id": cat_id})

    async def update_category(self, cat_id: int, **fields):
        if fields:
            await self.db.categories.update_one({"id": cat_id}, {"$set": fields})

    async def delete_category(self, cat_id: int):
        await self.db.categories.delete_one({"id": cat_id})
        await self.db.stock.delete_many({"category_id": cat_id})

    # ══════════════════════════════════════════════════════════════════════
    # STOCK (coupon codes)
    # ══════════════════════════════════════════════════════════════════════
    async def add_stock(self, cat_id: int, items: list[str]) -> int:
        docs = [
            {"category_id": cat_id, "item": it.strip(), "is_sold": False,
             "sold_at": None, "order_id": None, "created_at": _now()}
            for it in items if it.strip()
        ]
        if not docs:
            return 0
        res = await self.db.stock.insert_many(docs)
        return len(res.inserted_ids)

    async def stock_count(self, cat_id: int) -> int:
        return await self.db.stock.count_documents({"category_id": cat_id, "is_sold": False})

    async def reserve_stock(self, cat_id: int, qty: int, order_id: str) -> list[str]:
        """Atomically claim `qty` unsold codes for an order. Returns the codes.
        If fewer than qty are available, claims none and returns []."""
        claimed = []
        for _ in range(qty):
            doc = await self.db.stock.find_one_and_update(
                {"category_id": cat_id, "is_sold": False},
                {"$set": {"is_sold": True, "sold_at": _now(), "order_id": order_id}},
                return_document=ReturnDocument.AFTER,
            )
            if not doc:
                break
            claimed.append(doc["item"])
        if len(claimed) < qty:
            # rollback partial claim
            await self.db.stock.update_many(
                {"order_id": order_id},
                {"$set": {"is_sold": False, "sold_at": None, "order_id": None}},
            )
            return []
        return claimed

    # ══════════════════════════════════════════════════════════════════════
    # ORDERS (purchase history)
    # ══════════════════════════════════════════════════════════════════════
    async def create_order(self, order: dict):
        order["created_at"] = _now()
        order["updated_at"] = _now()
        await self.db.orders.insert_one(order)

    async def get_order(self, order_id: str) -> Optional[dict]:
        return await self.db.orders.find_one({"order_id": order_id})

    async def update_order(self, order_id: str, **fields):
        fields["updated_at"] = _now()
        await self.db.orders.update_one({"order_id": order_id}, {"$set": fields})

    async def get_user_orders(self, user_id: int, limit: int = 20) -> list[dict]:
        cur = self.db.orders.find({"user_id": user_id}).sort("created_at", DESCENDING).limit(limit)
        return [d async for d in cur]

    async def recent_orders(self, limit: int = 20) -> list[dict]:
        cur = self.db.orders.find({}).sort("created_at", DESCENDING).limit(limit)
        return [d async for d in cur]

    # ══════════════════════════════════════════════════════════════════════
    # SETTINGS
    # ══════════════════════════════════════════════════════════════════════
    async def get_setting(self, key: str, default=None):
        d = await self.db.settings.find_one({"key": key})
        return d["value"] if d else default

    async def set_setting(self, key: str, value):
        await self.db.settings.update_one(
            {"key": key}, {"$set": {"value": value}}, upsert=True
        )

    # ══════════════════════════════════════════════════════════════════════
    # ANALYTICS
    # ══════════════════════════════════════════════════════════════════════
    async def analytics(self) -> dict:
        total_users = await self.db.users.count_documents({})
        banned = await self.db.users.count_documents({"is_banned": True})
        total_orders = await self.db.orders.count_documents({"status": "completed"})

        # Revenue from completed orders
        rev_cur = self.db.orders.aggregate([
            {"$match": {"status": "completed"}},
            {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
        ])
        rev = await rev_cur.to_list(1)
        revenue = round(rev[0]["total"], 2) if rev else 0.0

        # Total recharged
        rc_cur = self.db.transactions.aggregate([
            {"$match": {"type": "recharge"}},
            {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
        ])
        rc = await rc_cur.to_list(1)
        recharged = round(rc[0]["total"], 2) if rc else 0.0

        # Wallet liability (sum of all balances)
        wl_cur = self.db.users.aggregate([
            {"$group": {"_id": None, "total": {"$sum": "$wallet_balance"}}},
        ])
        wl = await wl_cur.to_list(1)
        wallet_liability = round(wl[0]["total"], 2) if wl else 0.0

        # Stock summary
        total_stock = await self.db.stock.count_documents({"is_sold": False})

        # Top categories by sales
        top_cur = self.db.orders.aggregate([
            {"$match": {"status": "completed"}},
            {"$group": {"_id": "$category_name", "count": {"$sum": "$quantity"},
                        "revenue": {"$sum": "$amount"}}},
            {"$sort": {"revenue": -1}},
            {"$limit": 5},
        ])
        top_categories = [d async for d in top_cur]

        return {
            "total_users": total_users,
            "banned_users": banned,
            "total_orders": total_orders,
            "revenue": revenue,
            "recharged": recharged,
            "wallet_liability": wallet_liability,
            "available_stock": total_stock,
            "top_categories": top_categories,
        }
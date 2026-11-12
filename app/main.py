from __future__ import annotations

import json
import os
import re
import sqlite3
import urllib.error
import urllib.request
from contextlib import closing
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pymongo import MongoClient

from app.features import create_feature_router

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB = BASE_DIR.parent / "data" / "store.db"

PRODUCTS = [
    ("orbit-headphones", "Orbit Wireless Headphones", "Electronics", 129.00, 18, "Immersive sound, all-day comfort, and 40-hour battery life.", "🎧", "from-violet-500 to-indigo-700", 4.8),
    ("arc-desk-lamp", "Arc Minimal Desk Lamp", "Home", 74.00, 12, "A dimmable, warm-glow lamp that makes any desk feel considered.", "💡", "from-amber-300 to-orange-500", 4.7),
    ("field-notebook-set", "Field Notes Set", "Stationery", 24.00, 35, "Three pocket-sized recycled-paper notebooks for your next big idea.", "📓", "from-emerald-300 to-teal-600", 4.9),
    ("cloud-knit-throw", "Cloud Knit Throw", "Home", 89.00, 9, "A soft, breathable cotton throw for slow mornings and cozy evenings.", "🧶", "from-rose-300 to-pink-600", 4.6),
    ("tempo-water-bottle", "Tempo Steel Bottle", "Lifestyle", 38.00, 24, "Keeps drinks cold for 24 hours in a durable, leakproof design.", "🥤", "from-sky-300 to-blue-600", 4.8),
    ("everyday-tote", "Everyday Canvas Tote", "Lifestyle", 32.00, 28, "A sturdy, roomy carryall made from 100% heavyweight organic cotton.", "👜", "from-orange-300 to-rose-500", 4.5),
    ("studio-speaker", "Studio Bluetooth Speaker", "Electronics", 159.00, 7, "Room-filling audio in a compact speaker made for design lovers.", "🔊", "from-fuchsia-400 to-purple-700", 4.9),
    ("ceramic-mug", "Sunday Ceramic Mug", "Home", 28.00, 16, "Hand-finished stoneware with a comfortable handle and generous pour.", "☕", "from-lime-300 to-green-600", 4.7),
]


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def initialize_database(db_path: Path) -> None:
    with closing(connect(db_path)) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'customer' CHECK (role IN ('customer', 'admin')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                csrf_token TEXT NOT NULL,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS carts (
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                product_id TEXT NOT NULL REFERENCES products(id),
                quantity INTEGER NOT NULL CHECK (quantity BETWEEN 1 AND 20),
                PRIMARY KEY (user_id, product_id)
            );
            CREATE TABLE IF NOT EXISTS products (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                price REAL NOT NULL CHECK (price >= 0),
                stock INTEGER NOT NULL CHECK (stock >= 0),
                description TEXT NOT NULL,
                emoji TEXT NOT NULL,
                color TEXT NOT NULL,
                rating REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_name TEXT NOT NULL,
                customer_email TEXT NOT NULL,
                total REAL NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                user_id INTEGER REFERENCES users(id),
                status TEXT NOT NULL DEFAULT 'processing',
                tracking_number TEXT
            );
            CREATE TABLE IF NOT EXISTS order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL REFERENCES orders(id),
                product_id TEXT NOT NULL REFERENCES products(id),
                product_name TEXT NOT NULL,
                quantity INTEGER NOT NULL CHECK (quantity > 0),
                unit_price REAL NOT NULL
            );
            """
        )
        order_columns = {row["name"] for row in conn.execute("PRAGMA table_info(orders)")}
        if "user_id" not in order_columns:
            conn.execute("ALTER TABLE orders ADD COLUMN user_id INTEGER REFERENCES users(id)")
        if "status" not in order_columns:
            conn.execute("ALTER TABLE orders ADD COLUMN status TEXT NOT NULL DEFAULT 'processing'")
        if "tracking_number" not in order_columns:
            conn.execute("ALTER TABLE orders ADD COLUMN tracking_number TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders(user_id)")
        conn.executemany(
            """
            INSERT OR IGNORE INTO products
                (id, name, category, price, stock, description, emoji, color, rating)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            PRODUCTS,
        )
        conn.commit()


def product_dict(row: sqlite3.Row) -> dict[str, object]:
    return dict(row)


class ChatMessage(BaseModel):
    message: str = Field(min_length=1, max_length=1000)


def local_chat_reply(message: str, products: list[dict[str, object]]) -> str:
    text = message.casefold()
    if any(word in text for word in ("shipping", "delivery", "arrive")):
        return "We offer free standard shipping on orders over $75. Most orders arrive in 3–5 business days."
    if any(word in text for word in ("return", "refund", "exchange")):
        return "We offer hassle-free returns within 30 days of delivery. Items should be unused and in their original packaging."
    if any(word in text for word in ("order", "checkout", "payment")):
        return "You can add items to your bag and check out securely from the bag panel. This demo records orders but does not process a real payment."

    stop_words = {"about", "and", "are", "can", "for", "have", "help", "looking", "me", "the", "what", "you"}
    terms = {term for term in re.findall(r"[a-z0-9]+", text) if len(term) > 2 and term not in stop_words}
    matches = []
    for product in products:
        product_words = set(re.findall(
            r"[a-z0-9]+",
            f"{product['name']} {product['category']} {product['description']}".casefold(),
        ))
        if terms.intersection(product_words):
            matches.append(product)
    if matches:
        suggestions = ", ".join(f"{p['name']} (${p['price']:.2f})" for p in matches[:3])
        return f"Here are a few things that may fit: {suggestions}. Open a product card to see all the details."
    return "I can help you find something in the collection, answer questions about shipping or returns, or help with checkout. What are you shopping for?"


def remote_chat_reply(message: str, products: list[dict[str, object]]) -> str:
    api_url = os.environ["CHAT_API_URL"].rstrip("/")
    if api_url.endswith("/chat/completions"):
        endpoint = api_url
    else:
        endpoint = f"{api_url}/chat/completions"
    catalog = [
        {"name": p["name"], "category": p["category"], "price": p["price"],
         "description": p["description"], "in_stock": p["stock"] > 0}
        for p in products
    ]
    payload = json.dumps({
        "model": os.getenv("CHAT_MODEL", "gpt-4o-mini"),
        "messages": [
            {"role": "system", "content": (
                "You are the friendly shopping assistant for Northstar. Answer concisely using only "
                "this product catalog: " + json.dumps(catalog) +
                " Shipping is free over $75 and typically takes 3-5 business days. Returns are accepted "
                "within 30 days. This demo does not process real payments. Never claim an item is in stock "
                "if the catalog says otherwise."
            )},
            {"role": "user", "content": message},
        ],
        "temperature": 0.5,
        "max_tokens": 220,
    }).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    api_key = os.getenv("CHAT_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(endpoint, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.loads(response.read())
        answer = result["choices"][0]["message"]["content"]
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("Chat provider returned an empty message")
        return answer.strip()
    except (urllib.error.URLError, TimeoutError, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail="The chat service is temporarily unavailable.") from exc


def create_app(
    db_path: Path | None = None,
    mongo_database: object | None = None,
) -> FastAPI:
    database = db_path or Path(os.getenv("DATABASE_PATH", str(DEFAULT_DB)))
    initialize_database(database)
    mongo_client = None
    if mongo_database is None and os.getenv("MONGO_URI"):
        mongo_client = MongoClient(
            os.environ["MONGO_URI"], serverSelectionTimeoutMS=2500
        )
        mongo_database = mongo_client["northstar"]

    app = FastAPI(title="Northstar Shop API", version="1.0.0")
    if mongo_client is not None:
        app.add_event_handler("shutdown", mongo_client.close)
    app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
    app.include_router(create_feature_router(database, mongo_database))

    @app.get("/", include_in_schema=False)
    def storefront() -> FileResponse:
        return FileResponse(BASE_DIR / "static" / "index.html")

    @app.get("/healthz", tags=["health"])
    def health() -> dict[str, str]:
        try:
            with closing(connect(database)) as conn:
                conn.execute("SELECT 1").fetchone()
        except sqlite3.Error as exc:
            raise HTTPException(status_code=503, detail="Database unavailable") from exc
        return {"status": "ok"}

    @app.get("/api/products", tags=["store"])
    def list_products(
        q: Annotated[str | None, Query(max_length=100)] = None,
        category: Annotated[str | None, Query(max_length=50)] = None,
    ) -> list[dict[str, object]]:
        sql = "SELECT * FROM products"
        clauses: list[str] = []
        params: list[str] = []
        if q:
            clauses.append("(name LIKE ? OR description LIKE ? OR category LIKE ?)")
            term = f"%{q.strip()}%"
            params.extend([term, term, term])
        if category and category.casefold() != "all":
            clauses.append("category = ? COLLATE NOCASE")
            params.append(category)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY rating DESC, name"
        with closing(connect(database)) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [product_dict(row) for row in rows]

    @app.get("/api/products/{product_id}", tags=["store"])
    def get_product(product_id: str) -> dict[str, object]:
        with closing(connect(database)) as conn:
            row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Product not found")
        return product_dict(row)

    @app.post("/api/chat", tags=["assistant"])
    def chat(body: ChatMessage) -> dict[str, str]:
        with closing(connect(database)) as conn:
            products = [product_dict(row) for row in conn.execute(
                "SELECT * FROM products ORDER BY name"
            ).fetchall()]
        if os.getenv("CHAT_API_URL"):
            reply = remote_chat_reply(body.message, products)
        else:
            reply = local_chat_reply(body.message, products)
        return {"reply": reply}

    return app


app = create_app()

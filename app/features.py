from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from pymongo.errors import DuplicateKeyError, PyMongoError


PASSWORD_ITERATIONS = 310_000
SESSION_DAYS = 30
ORDER_TRANSITIONS = {
    "processing": {"packed", "cancelled"},
    "packed": {"shipped", "cancelled"},
    "shipped": {"delivered"},
    "delivered": set(),
    "cancelled": set(),
}


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def _password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PASSWORD_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        PASSWORD_ITERATIONS,
        base64.urlsafe_b64encode(salt).decode(),
        base64.urlsafe_b64encode(digest).decode(),
    )


def _check_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations, salt, expected = stored_hash.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), base64.urlsafe_b64decode(salt),
            int(iterations),
        )
        return hmac.compare_digest(
            digest, base64.urlsafe_b64decode(expected)
        )
    except (ValueError, TypeError):
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _public_user(row: sqlite3.Row) -> dict[str, object]:
    return {
        "id": row["id"],
        "name": row["name"],
        "email": row["email"],
        "role": row["role"],
    }


class RegisterBody(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)


class LoginBody(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class OrderItem(BaseModel):
    product_id: str = Field(min_length=1, max_length=80)
    quantity: int = Field(ge=1, le=20)


class CreateOrder(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    customer_name: str = Field(min_length=2, max_length=100)
    customer_email: EmailStr
    items: list[OrderItem] = Field(min_length=1, max_length=50)


class CartItem(BaseModel):
    product_id: str = Field(min_length=1, max_length=80)
    quantity: int = Field(ge=1, le=20)


class CartUpdate(BaseModel):
    items: list[CartItem] = Field(max_length=50)


class ReviewBody(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    rating: int = Field(ge=1, le=5)
    title: str = Field(min_length=2, max_length=100)
    body: str = Field(min_length=5, max_length=2000)


class ProductBody(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=2, max_length=120)
    category: str = Field(min_length=2, max_length=50)
    price: float = Field(ge=0, le=100000)
    stock: int = Field(ge=0, le=100000)
    description: str = Field(min_length=5, max_length=1000)
    emoji: str = Field(min_length=1, max_length=8)
    color: str = Field(min_length=1, max_length=80)
    rating: float = Field(ge=0, le=5)


class NewProduct(ProductBody):
    id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", min_length=2, max_length=80)


class OrderStatusBody(BaseModel):
    status: Literal["processing", "packed", "shipped", "delivered", "cancelled"]


def create_feature_router(
    database: Path,
    mongo_database: Any | None,
) -> APIRouter:
    router = APIRouter()

    admin_email = os.getenv("ADMIN_EMAIL", "").strip().casefold()
    admin_password = os.getenv("ADMIN_PASSWORD", "")
    if bool(admin_email) != bool(admin_password):
        raise RuntimeError("Set both ADMIN_EMAIL and ADMIN_PASSWORD to bootstrap an admin.")
    if admin_email:
        with closing(_connect(database)) as conn:
            row = conn.execute("SELECT id FROM users WHERE email = ?", (admin_email,)).fetchone()
            if row:
                conn.execute("UPDATE users SET role = 'admin' WHERE id = ?", (row["id"],))
            else:
                conn.execute(
                    "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, 'admin')",
                    ("Store Admin", admin_email, _password_hash(admin_password)),
                )
            conn.commit()

    def current_user(
        request: Request,
        session_token: Annotated[str | None, Cookie(alias="northstar_session")] = None,
    ) -> dict[str, Any] | None:
        if not session_token:
            return None
        with closing(_connect(database)) as conn:
            row = conn.execute(
                """
                SELECT users.*, sessions.csrf_token, sessions.expires_at
                FROM sessions JOIN users ON users.id = sessions.user_id
                WHERE sessions.token_hash = ?
                """,
                (_token_hash(session_token),),
            ).fetchone()
        if not row:
            return None
        expires = datetime.fromisoformat(row["expires_at"])
        if expires <= datetime.now(timezone.utc):
            with closing(_connect(database)) as conn:
                conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(session_token),))
                conn.commit()
            return None
        user = _public_user(row)
        user["csrf_token"] = row["csrf_token"]
        return user

    def required_user(user: dict[str, Any] | None = Depends(current_user)) -> dict[str, Any]:
        if user is None:
            raise HTTPException(status_code=401, detail="Please sign in to continue")
        return user

    def required_admin(user: dict[str, Any] = Depends(required_user)) -> dict[str, Any]:
        if user["role"] != "admin":
            raise HTTPException(status_code=403, detail="Admin access required")
        return user

    def require_csrf(
        user: dict[str, Any] = Depends(required_user),
        csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
    ) -> dict[str, Any]:
        if not csrf_header or not hmac.compare_digest(csrf_header, user["csrf_token"]):
            raise HTTPException(status_code=403, detail="Invalid or missing CSRF token")
        return user

    def require_admin_csrf(user: dict[str, Any] = Depends(require_csrf)) -> dict[str, Any]:
        if user["role"] != "admin":
            raise HTTPException(status_code=403, detail="Admin access required")
        return user

    def create_session(user_id: int, response: Response) -> tuple[dict[str, object], str]:
        token = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(24)
        expires_at = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
        with closing(_connect(database)) as conn:
            conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (datetime.now(timezone.utc).isoformat(),))
            conn.execute(
                "INSERT INTO sessions (token_hash, csrf_token, user_id, expires_at) VALUES (?, ?, ?, ?)",
                (_token_hash(token), csrf_token, user_id, expires_at.isoformat()),
            )
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            conn.commit()
        response.set_cookie(
            "northstar_session",
            token,
            max_age=SESSION_DAYS * 24 * 60 * 60,
            httponly=True,
            secure=os.getenv("COOKIE_SECURE", "").casefold() in {"1", "true", "yes"},
            samesite="lax",
            path="/",
        )
        return _public_user(row), csrf_token

    @router.post("/api/auth/register", status_code=201, tags=["accounts"])
    def register(body: RegisterBody, response: Response) -> dict[str, object]:
        email = str(body.email).casefold()
        try:
            with closing(_connect(database)) as conn:
                cursor = conn.execute(
                    "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                    (body.name, email, _password_hash(body.password)),
                )
                user_id = cursor.lastrowid
                conn.commit()
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="An account with that email already exists") from exc
        user, csrf_token = create_session(user_id, response)
        return {"user": user, "csrf_token": csrf_token}

    @router.post("/api/auth/login", tags=["accounts"])
    def login(body: LoginBody, response: Response) -> dict[str, object]:
        with closing(_connect(database)) as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE email = ?", (str(body.email).casefold(),)
            ).fetchone()
        if row is None or not _check_password(body.password, row["password_hash"]):
            raise HTTPException(status_code=401, detail="Email or password is incorrect")
        user, csrf_token = create_session(row["id"], response)
        return {"user": user, "csrf_token": csrf_token}

    @router.get("/api/auth/me", tags=["accounts"])
    def who_am_i(user: dict[str, Any] | None = Depends(current_user)) -> dict[str, object]:
        if user is None:
            return {"user": None, "csrf_token": None}
        return {
            "user": {key: value for key, value in user.items() if key != "csrf_token"},
            "csrf_token": user["csrf_token"],
        }

    @router.post("/api/auth/logout", tags=["accounts"])
    def logout(
        request: Request,
        _: dict[str, Any] = Depends(require_csrf),
    ) -> Response:
        token = request.cookies.get("northstar_session")
        if token:
            with closing(_connect(database)) as conn:
                conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))
                conn.commit()
        response = Response(content='{"ok":true}', media_type="application/json")
        response.delete_cookie("northstar_session", path="/", samesite="lax")
        return response

    @router.get("/api/cart", tags=["cart"])
    def get_cart(user: dict[str, Any] = Depends(required_user)) -> dict[str, object]:
        with closing(_connect(database)) as conn:
            rows = conn.execute(
                """
                SELECT products.*, carts.quantity FROM carts
                JOIN products ON products.id = carts.product_id
                WHERE carts.user_id = ? ORDER BY products.name
                """,
                (user["id"],),
            ).fetchall()
        return {"items": [dict(row) for row in rows]}

    @router.put("/api/cart", tags=["cart"])
    def save_cart(
        body: CartUpdate,
        user: dict[str, Any] = Depends(require_csrf),
    ) -> dict[str, object]:
        quantities: dict[str, int] = {}
        for item in body.items:
            quantities[item.product_id] = quantities.get(item.product_id, 0) + item.quantity
        if any(quantity > 20 for quantity in quantities.values()):
            raise HTTPException(status_code=422, detail="Maximum quantity per product is 20")
        with closing(_connect(database)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            for product_id in quantities:
                if conn.execute("SELECT 1 FROM products WHERE id = ?", (product_id,)).fetchone() is None:
                    conn.rollback()
                    raise HTTPException(status_code=404, detail=f"Product {product_id} not found")
            conn.execute("DELETE FROM carts WHERE user_id = ?", (user["id"],))
            conn.executemany(
                "INSERT INTO carts (user_id, product_id, quantity) VALUES (?, ?, ?)",
                [(user["id"], product_id, quantity) for product_id, quantity in quantities.items()],
            )
            conn.commit()
        return {"saved": True, "items": len(quantities)}

    def order_document(conn: sqlite3.Connection, order: sqlite3.Row) -> dict[str, object]:
        result = dict(order)
        result["items"] = [
            dict(row) for row in conn.execute(
                "SELECT product_id, product_name, quantity, unit_price FROM order_items WHERE order_id = ?",
                (order["id"],),
            ).fetchall()
        ]
        return result

    @router.post("/api/orders", status_code=201, tags=["store"])
    def create_order(
        order: CreateOrder,
        user: dict[str, Any] | None = Depends(current_user),
        csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
    ) -> dict[str, object]:
        if user and (
            not csrf_header
            or not hmac.compare_digest(csrf_header, user["csrf_token"])
        ):
            raise HTTPException(status_code=403, detail="Invalid or missing CSRF token")
        quantities: dict[str, int] = {}
        for item in order.items:
            quantities[item.product_id] = quantities.get(item.product_id, 0) + item.quantity
        if any(quantity > 20 for quantity in quantities.values()):
            raise HTTPException(status_code=422, detail="Maximum quantity per product is 20")
        conn = _connect(database)
        try:
            conn.execute("BEGIN IMMEDIATE")
            order_lines: list[tuple[str, str, int, float]] = []
            total = 0.0
            for product_id, quantity in quantities.items():
                product = conn.execute(
                    "SELECT id, name, price, stock FROM products WHERE id = ?", (product_id,)
                ).fetchone()
                if product is None:
                    raise HTTPException(status_code=404, detail=f"Product {product_id} not found")
                if product["stock"] < quantity:
                    raise HTTPException(status_code=409, detail=f"Not enough stock for {product['name']}")
                price = float(product["price"])
                total += price * quantity
                order_lines.append((product_id, product["name"], quantity, price))
            name = user["name"] if user else order.customer_name
            email = user["email"] if user else str(order.customer_email)
            cursor = conn.execute(
                "INSERT INTO orders (customer_name, customer_email, total, user_id) VALUES (?, ?, ?, ?)",
                (name, email, round(total, 2), user["id"] if user else None),
            )
            order_id = cursor.lastrowid
            tracking_number = f"NS-{datetime.now(timezone.utc).year}-{order_id:06d}"
            conn.execute(
                "UPDATE orders SET tracking_number = ? WHERE id = ?",
                (tracking_number, order_id),
            )
            for product_id, product_name, quantity, price in order_lines:
                conn.execute(
                    "INSERT INTO order_items (order_id, product_id, product_name, quantity, unit_price) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (order_id, product_id, product_name, quantity, price),
                )
                conn.execute(
                    "UPDATE products SET stock = stock - ? WHERE id = ?",
                    (quantity, product_id),
                )
            if user:
                conn.execute("DELETE FROM carts WHERE user_id = ?", (user["id"],))
            conn.commit()
        except HTTPException:
            conn.rollback()
            raise
        except sqlite3.Error as exc:
            conn.rollback()
            raise HTTPException(status_code=500, detail="Could not place order") from exc
        finally:
            conn.close()
        return {
            "order_id": order_id,
            "tracking_number": tracking_number,
            "status": "processing",
            "total": round(total, 2),
            "currency": "USD",
        }

    @router.get("/api/orders", tags=["orders"])
    def list_orders(user: dict[str, Any] = Depends(required_user)) -> list[dict[str, object]]:
        with closing(_connect(database)) as conn:
            orders = conn.execute(
                "SELECT * FROM orders WHERE user_id = ? ORDER BY id DESC", (user["id"],)
            ).fetchall()
            return [order_document(conn, order) for order in orders]

    @router.get("/api/orders/{order_id}", tags=["orders"])
    def get_order(
        order_id: int,
        user: dict[str, Any] = Depends(required_user),
    ) -> dict[str, object]:
        with closing(_connect(database)) as conn:
            order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
            if order is None or (user["role"] != "admin" and order["user_id"] != user["id"]):
                raise HTTPException(status_code=404, detail="Order not found")
            return order_document(conn, order)

    def product_is_available(product_id: str) -> bool:
        with closing(_connect(database)) as conn:
            return conn.execute("SELECT 1 FROM products WHERE id = ?", (product_id,)).fetchone() is not None

    def reviews_collection() -> Any:
        if mongo_database is None:
            raise HTTPException(
                status_code=503,
                detail="Product reviews need MongoDB. Configure MONGO_URI or start the MongoDB service.",
            )
        try:
            collection = mongo_database["product_reviews"]
            collection.create_index(
                [("product_id", 1), ("user_id", 1)], unique=True,
                name="one_review_per_customer_product",
            )
            collection.create_index([("product_id", 1), ("created_at", -1)])
            return collection
        except PyMongoError as exc:
            raise HTTPException(status_code=503, detail="MongoDB reviews service is unavailable") from exc

    @router.get("/api/products/{product_id}/reviews", tags=["reviews"])
    def list_reviews(product_id: str) -> dict[str, object]:
        if not product_is_available(product_id):
            raise HTTPException(status_code=404, detail="Product not found")
        collection = reviews_collection()
        try:
            documents = list(
                collection.find({"product_id": product_id}, {"_id": 0})
                .sort("created_at", -1).limit(50)
            )
            summary = list(collection.aggregate([
                {"$match": {"product_id": product_id}},
                {"$group": {"_id": None, "average": {"$avg": "$rating"}, "count": {"$sum": 1}}},
            ]))
        except PyMongoError as exc:
            raise HTTPException(status_code=503, detail="Could not load product reviews") from exc
        count = summary[0]["count"] if summary else 0
        average = round(float(summary[0]["average"]), 1) if summary else None
        return {"reviews": documents, "count": count, "average": average}

    @router.post("/api/products/{product_id}/reviews", status_code=201, tags=["reviews"])
    def create_review(
        product_id: str,
        body: ReviewBody,
        user: dict[str, Any] = Depends(require_csrf),
    ) -> dict[str, object]:
        if not product_is_available(product_id):
            raise HTTPException(status_code=404, detail="Product not found")
        review = {
            "product_id": product_id,
            "user_id": user["id"],
            "customer_name": user["name"],
            "rating": body.rating,
            "title": body.title,
            "body": body.body,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        collection = reviews_collection()
        try:
            collection.insert_one(review)
        except DuplicateKeyError as exc:
            raise HTTPException(status_code=409, detail="You have already reviewed this product") from exc
        except PyMongoError as exc:
            raise HTTPException(status_code=503, detail="Could not save product review") from exc
        return review

    @router.get("/api/admin/products", tags=["admin"])
    def admin_products(_: dict[str, Any] = Depends(required_admin)) -> list[dict[str, object]]:
        with closing(_connect(database)) as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM products ORDER BY name").fetchall()]

    @router.post("/api/admin/products", status_code=201, tags=["admin"])
    def add_product(
        body: NewProduct,
        _: dict[str, Any] = Depends(require_admin_csrf),
    ) -> dict[str, object]:
        values = body.model_dump()
        try:
            with closing(_connect(database)) as conn:
                conn.execute(
                    "INSERT INTO products (id, name, category, price, stock, description, emoji, color, rating) "
                    "VALUES (:id, :name, :category, :price, :stock, :description, :emoji, :color, :rating)",
                    values,
                )
                conn.commit()
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="A product with that ID already exists") from exc
        return values

    @router.put("/api/admin/products/{product_id}", tags=["admin"])
    def update_product(
        product_id: str,
        body: ProductBody,
        _: dict[str, Any] = Depends(require_admin_csrf),
    ) -> dict[str, object]:
        values = body.model_dump()
        with closing(_connect(database)) as conn:
            cursor = conn.execute(
                """
                UPDATE products SET name=:name, category=:category, price=:price, stock=:stock,
                    description=:description, emoji=:emoji, color=:color, rating=:rating
                WHERE id=:id
                """,
                {**values, "id": product_id},
            )
            conn.commit()
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="Product not found")
        return {"id": product_id, **values}

    @router.get("/api/admin/orders", tags=["admin"])
    def admin_orders(_: dict[str, Any] = Depends(required_admin)) -> list[dict[str, object]]:
        with closing(_connect(database)) as conn:
            orders = conn.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 200").fetchall()
            return [order_document(conn, order) for order in orders]

    @router.patch("/api/admin/orders/{order_id}", tags=["admin"])
    def update_order_status(
        order_id: int,
        body: OrderStatusBody,
        _: dict[str, Any] = Depends(require_admin_csrf),
    ) -> dict[str, object]:
        with closing(_connect(database)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
            if order is None:
                conn.rollback()
                raise HTTPException(status_code=404, detail="Order not found")
            if body.status != order["status"] and body.status not in ORDER_TRANSITIONS[order["status"]]:
                conn.rollback()
                raise HTTPException(status_code=409, detail="That order status transition is not allowed")
            if body.status == "cancelled" and order["status"] != "cancelled":
                items = conn.execute(
                    "SELECT product_id, quantity FROM order_items WHERE order_id = ?", (order_id,)
                ).fetchall()
                for item in items:
                    conn.execute(
                        "UPDATE products SET stock = stock + ? WHERE id = ?",
                        (item["quantity"], item["product_id"]),
                    )
            conn.execute("UPDATE orders SET status = ? WHERE id = ?", (body.status, order_id))
            conn.commit()
            order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
            return order_document(conn, order)

    return router

import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from types import SimpleNamespace
from pathlib import Path

from fastapi.testclient import TestClient
from pymongo.errors import DuplicateKeyError

from app.main import create_app


class FakeCursor:
    def __init__(self, documents: list[dict[str, object]]) -> None:
        self.documents = documents

    def sort(self, key: str, direction: int) -> "FakeCursor":
        self.documents.sort(key=lambda item: item[key], reverse=direction < 0)
        return self

    def limit(self, count: int) -> "FakeCursor":
        self.documents = self.documents[:count]
        return self

    def __iter__(self):
        return iter(self.documents)


class FakeReviews:
    def __init__(self) -> None:
        self.documents: list[dict[str, object]] = []

    def create_index(self, *_args, **_kwargs) -> None:
        return None

    def find(self, query, _projection=None) -> FakeCursor:
        return FakeCursor([
            dict(document) for document in self.documents
            if all(document.get(key) == value for key, value in query.items())
        ])

    def insert_one(self, document: dict[str, object]) -> SimpleNamespace:
        if any(
            item["product_id"] == document["product_id"]
            and item["user_id"] == document["user_id"]
            for item in self.documents
        ):
            raise DuplicateKeyError("review already exists")
        self.documents.append(dict(document))
        return SimpleNamespace(inserted_id=len(self.documents))

    def aggregate(self, pipeline) -> list[dict[str, object]]:
        product_id = pipeline[0]["$match"]["product_id"]
        matches = [
            item for item in self.documents if item["product_id"] == product_id
        ]
        if not matches:
            return []
        return [{
            "_id": None,
            "average": sum(item["rating"] for item in matches) / len(matches),
            "count": len(matches),
        }]


class FakeMongoDatabase:
    def __init__(self) -> None:
        self.reviews = FakeReviews()

    def __getitem__(self, collection: str) -> FakeReviews:
        if collection != "product_reviews":
            raise KeyError(collection)
        return self.reviews


class StoreApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "test.db"
        self.client = TestClient(create_app(self.database))

    def tearDown(self) -> None:
        self.client.close()
        self.temp_dir.cleanup()

    def test_catalog_lists_seeded_products_and_filters_by_category(self) -> None:
        products = self.client.get("/api/products").json()
        home = self.client.get("/api/products", params={"category": "Home"}).json()
        self.assertGreaterEqual(len(products), 8)
        self.assertTrue(home)
        self.assertTrue(all(item["category"] == "Home" for item in home))

    def test_chat_answers_catalog_and_shipping_questions(self) -> None:
        catalog_reply = self.client.post(
            "/api/chat", json={"message": "Do you have headphones?"}
        ).json()["reply"]
        shipping_reply = self.client.post(
            "/api/chat", json={"message": "How does shipping work?"}
        ).json()["reply"]
        self.assertIn("Orbit Wireless Headphones", catalog_reply)
        self.assertIn("free standard shipping", shipping_reply)

    def test_order_uses_server_prices_and_updates_stock(self) -> None:
        response = self.client.post("/api/orders", json={
            "customer_name": "Alex Customer",
            "customer_email": "alex@example.com",
            "items": [{"product_id": "ceramic-mug", "quantity": 2}],
        })
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["total"], 56.0)
        product = self.client.get("/api/products/ceramic-mug").json()
        self.assertEqual(product["stock"], 14)

    def test_order_rejects_insufficient_stock_without_creating_order(self) -> None:
        response = self.client.post("/api/orders", json={
            "customer_name": "Alex Customer",
            "customer_email": "alex@example.com",
            "items": [{"product_id": "studio-speaker", "quantity": 20}],
        })
        self.assertEqual(response.status_code, 409)
        product = self.client.get("/api/products/studio-speaker").json()
        self.assertEqual(product["stock"], 7)

    def test_health_endpoint(self) -> None:
        self.assertEqual(self.client.get("/healthz").json(), {"status": "ok"})

    def test_storefront_and_static_assets_are_served(self) -> None:
        page = self.client.get("/")
        script = self.client.get("/static/app.js")
        self.assertEqual(page.status_code, 200)
        self.assertIn("northstar", page.text)
        self.assertEqual(script.status_code, 200)
        self.assertIn("loadProducts", script.text)

    def register(self, client: TestClient, email: str = "alex@example.com") -> dict:
        response = client.post("/api/auth/register", json={
            "name": "Alex Customer",
            "email": email,
            "password": "secure-password-123",
        })
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_registration_sign_in_and_passwords_are_not_stored_as_plaintext(self) -> None:
        data = self.register(self.client)
        self.assertEqual(data["user"]["role"], "customer")
        self.assertTrue(self.client.cookies.get("northstar_session"))
        me = self.client.get("/api/auth/me").json()
        self.assertEqual(me["user"]["email"], "alex@example.com")
        self.assertTrue(me["csrf_token"])

        with closing(sqlite3.connect(Path(self.temp_dir.name) / "test.db")) as conn:
            password_hash = conn.execute(
                "SELECT password_hash FROM users WHERE email = ?",
                ("alex@example.com",),
            ).fetchone()[0]
        self.assertNotEqual(password_hash, "secure-password-123")
        self.assertTrue(password_hash.startswith("pbkdf2_sha256$"))

        self.client.post("/api/auth/logout", headers={"X-CSRF-Token": me["csrf_token"]})
        login = self.client.post("/api/auth/login", json={
            "email": "alex@example.com",
            "password": "secure-password-123",
        })
        self.assertEqual(login.status_code, 200)
        wrong_password = self.client.post("/api/auth/login", json={
            "email": "alex@example.com",
            "password": "incorrect-password",
        })
        self.assertEqual(wrong_password.status_code, 401)

    def test_cart_is_saved_to_account_and_requires_csrf_token(self) -> None:
        data = self.register(self.client)
        body = {"items": [{"product_id": "ceramic-mug", "quantity": 3}]}
        self.assertEqual(self.client.put("/api/cart", json=body).status_code, 403)
        response = self.client.put(
            "/api/cart",
            json=body,
            headers={"X-CSRF-Token": data["csrf_token"]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/api/cart").json()["items"][0]["quantity"], 3)
        returning_client = TestClient(create_app(self.database))
        try:
            login = returning_client.post("/api/auth/login", json={
                "email": "alex@example.com",
                "password": "secure-password-123",
            })
            self.assertEqual(login.status_code, 200)
            saved_items = returning_client.get("/api/cart").json()["items"]
            self.assertEqual(saved_items[0]["quantity"], 3)
        finally:
            returning_client.close()

    def test_order_history_and_tracking_are_linked_to_signed_in_customer(self) -> None:
        user = self.register(self.client)
        response = self.client.post("/api/orders", json={
            "customer_name": "Ignored Guest Name",
            "customer_email": "guest@example.com",
            "items": [{"product_id": "ceramic-mug", "quantity": 2}],
        }, headers={"X-CSRF-Token": user["csrf_token"]})
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()["tracking_number"].startswith("NS-"))
        order = self.client.get("/api/orders").json()[0]
        self.assertEqual(order["customer_email"], "alex@example.com")
        self.assertEqual(order["status"], "processing")
        self.assertEqual(order["items"][0]["quantity"], 2)

    def test_signed_in_order_requires_csrf_token(self) -> None:
        self.register(self.client)
        response = self.client.post("/api/orders", json={
            "customer_name": "Alex Customer",
            "customer_email": "alex@example.com",
            "items": [{"product_id": "ceramic-mug", "quantity": 1}],
        })
        self.assertEqual(response.status_code, 403)

    def test_review_is_persisted_in_mongodb_collection(self) -> None:
        database = Path(self.temp_dir.name) / "reviews.db"
        mongo = FakeMongoDatabase()
        client = TestClient(create_app(database, mongo_database=mongo))
        try:
            user = self.register(client)
            body = {"rating": 5, "title": "Lovely mug", "body": "Just right for my morning coffee."}
            response = client.post(
                "/api/products/ceramic-mug/reviews",
                json=body,
                headers={"X-CSRF-Token": user["csrf_token"]},
            )
            self.assertEqual(response.status_code, 201, response.text)
            summary = client.get("/api/products/ceramic-mug/reviews").json()
            self.assertEqual(summary["count"], 1)
            self.assertEqual(summary["average"], 5.0)
            duplicate = client.post(
                "/api/products/ceramic-mug/reviews",
                json=body,
                headers={"X-CSRF-Token": user["csrf_token"]},
            )
            self.assertEqual(duplicate.status_code, 409)
        finally:
            client.close()

    def test_review_endpoint_explains_mongodb_configuration(self) -> None:
        response = self.client.get("/api/products/ceramic-mug/reviews")
        self.assertEqual(response.status_code, 503)
        self.assertIn("MONGO_URI", response.json()["detail"])

    def test_admin_dashboard_requires_admin_role(self) -> None:
        response = self.client.get("/api/admin/orders")
        self.assertEqual(response.status_code, 401)
        self.register(self.client)
        forbidden = self.client.get("/api/admin/orders")
        self.assertEqual(forbidden.status_code, 403)

        previous_email = os.environ.get("ADMIN_EMAIL")
        previous_password = os.environ.get("ADMIN_PASSWORD")
        os.environ["ADMIN_EMAIL"] = "store-admin@example.com"
        os.environ["ADMIN_PASSWORD"] = "admin-password-123"
        admin_db = Path(self.temp_dir.name) / "admin.db"
        try:
            admin_client = TestClient(create_app(admin_db))
            login = admin_client.post("/api/auth/login", json={
                "email": "store-admin@example.com",
                "password": "admin-password-123",
            })
            self.assertEqual(login.status_code, 200)
            csrf = login.json()["csrf_token"]
            created = admin_client.post(
                "/api/admin/products",
                json={
                    "id": "test-item",
                    "name": "Test Item",
                    "category": "Home",
                    "price": 10,
                    "stock": 5,
                    "description": "A test item for the shop.",
                    "emoji": "🧪",
                    "color": "from-lime-300 to-green-600",
                    "rating": 5,
                },
                headers={"X-CSRF-Token": csrf},
            )
            self.assertEqual(created.status_code, 201, created.text)
            self.assertEqual(admin_client.get("/api/admin/orders").status_code, 200)
            admin_client.close()
        finally:
            if previous_email is None:
                os.environ.pop("ADMIN_EMAIL", None)
            else:
                os.environ["ADMIN_EMAIL"] = previous_email
            if previous_password is None:
                os.environ.pop("ADMIN_PASSWORD", None)
            else:
                os.environ["ADMIN_PASSWORD"] = previous_password

    def test_admin_order_transitions_and_cancellation_restore_stock(self) -> None:
        previous_email = os.environ.get("ADMIN_EMAIL")
        previous_password = os.environ.get("ADMIN_PASSWORD")
        os.environ["ADMIN_EMAIL"] = "store-admin@example.com"
        os.environ["ADMIN_PASSWORD"] = "admin-password-123"
        database = Path(self.temp_dir.name) / "order-status.db"
        admin_client = TestClient(create_app(database))
        customer_client = TestClient(create_app(database))
        try:
            customer = self.register(customer_client)
            order = customer_client.post("/api/orders", json={
                "customer_name": "Alex Customer",
                "customer_email": "alex@example.com",
                "items": [{"product_id": "ceramic-mug", "quantity": 2}],
            }, headers={"X-CSRF-Token": customer["csrf_token"]}).json()
            admin_login = admin_client.post("/api/auth/login", json={
                "email": "store-admin@example.com",
                "password": "admin-password-123",
            }).json()
            csrf = admin_login["csrf_token"]
            status_url = f"/api/admin/orders/{order['order_id']}"
            skipped = admin_client.patch(
                status_url, json={"status": "shipped"},
                headers={"X-CSRF-Token": csrf},
            )
            self.assertEqual(skipped.status_code, 409)
            cancelled = admin_client.patch(
                status_url, json={"status": "cancelled"},
                headers={"X-CSRF-Token": csrf},
            )
            self.assertEqual(cancelled.status_code, 200)
            mug = customer_client.get("/api/products/ceramic-mug").json()
            self.assertEqual(mug["stock"], 16)
            self.assertEqual(customer_client.get("/api/orders").json()[0]["status"], "cancelled")
        finally:
            admin_client.close()
            customer_client.close()
            if previous_email is None:
                os.environ.pop("ADMIN_EMAIL", None)
            else:
                os.environ["ADMIN_EMAIL"] = previous_email
            if previous_password is None:
                os.environ.pop("ADMIN_PASSWORD", None)
            else:
                os.environ["ADMIN_PASSWORD"] = previous_password


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


class StoreApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database = Path(self.temp_dir.name) / "test.db"
        self.client = TestClient(create_app(database))

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


if __name__ == "__main__":
    unittest.main()

"""Tests for restocking recommendation and restock order endpoints"""
import pytest
from mock_data import restock_orders


@pytest.fixture(autouse=True)
def clear_restock_orders():
    """Restock orders are process-wide state; reset around each test to avoid leakage"""
    restock_orders.clear()
    yield
    restock_orders.clear()


class TestRestockRecommendationEndpoints:
    def test_zero_budget_returns_no_items(self, client):
        """Zero budget recommends nothing"""
        data = client.get("/api/restock/recommendations?budget=0").json()
        assert data["items"] == []
        assert data["total_cost"] == 0

    def test_recommendations_never_exceed_budget(self, client):
        """Total cost stays within budget for several budgets"""
        for budget in (100, 500, 5000, 50000):
            data = client.get(f"/api/restock/recommendations?budget={budget}").json()
            assert data["total_cost"] <= budget
            assert abs(data["remaining_budget"] - (budget - data["total_cost"])) < 0.01
            for item in data["items"]:
                assert item["recommended_quantity"] > 0
                assert item["recommended_quantity"] <= item["shortfall"]
                assert abs(item["line_total"] - item["recommended_quantity"] * item["unit_cost"]) < 0.01

    def test_larger_budget_covers_more_items(self, client):
        """A larger budget recommends at least as many items"""
        small = client.get("/api/restock/recommendations?budget=500").json()
        large = client.get("/api/restock/recommendations?budget=50000").json()
        assert len(large["items"]) >= len(small["items"])

    def test_negative_budget_rejected(self, client):
        """Negative budget fails validation"""
        assert client.get("/api/restock/recommendations?budget=-5").status_code == 422


class TestRestockOrderEndpoints:
    def _payload(self, **overrides):
        body = {"budget": 5000, "items": [{"item_sku": "SNR-420", "quantity": 5},
                                          {"item_sku": "CTL-330", "quantity": 2}]}
        body.update(overrides)
        return body

    def test_create_order_and_list(self, client):
        """Created order is returned and appears in the list"""
        response = client.post("/api/restock/orders", json=self._payload())
        assert response.status_code == 201
        order = response.json()
        assert order["status"] == "Submitted"
        assert abs(order["total_cost"] - (5 * 22.50 + 2 * 85.00)) < 0.01
        listed = client.get("/api/restock/orders").json()
        assert [o["id"] for o in listed] == [order["id"]]

    def test_lead_time_is_longest_item(self, client):
        """Order lead time equals the slowest item's lead time"""
        order = client.post("/api/restock/orders", json=self._payload()).json()
        assert order["lead_time_days"] == max(i["lead_time_days"] for i in order["items"])

    def test_unknown_sku_not_found(self, client):
        """Unknown SKU returns 404"""
        body = self._payload(items=[{"item_sku": "NOPE-1", "quantity": 1}])
        response = client.post("/api/restock/orders", json=body)
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_over_budget_rejected(self, client):
        """Total above budget returns 400"""
        assert client.post("/api/restock/orders", json=self._payload(budget=10)).status_code == 400

    def test_invalid_payload_rejected(self, client):
        """Zero quantity and empty items fail validation"""
        bad_qty = self._payload(items=[{"item_sku": "SNR-420", "quantity": 0}])
        assert client.post("/api/restock/orders", json=bad_qty).status_code == 422
        assert client.post("/api/restock/orders", json=self._payload(items=[])).status_code == 422

"""MemoryManager local-mode unit tests."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.memory import MemoryManager


def run(coro):
    return asyncio.run(coro)


def test_memory_record_and_read():
    memory = MemoryManager(redis_client=None)
    run(memory.record_behavior("u1", "view", "P001", {"category": "手机", "price": 7999}))
    run(memory.record_behavior("u1", "purchase", "P003", {"category": "耳机", "price": 1899, "amount": 1899}))

    data = run(memory.get_user_memory("u1"))
    assert data["memory_backend"] == "memory"
    assert data["view_count_24h"] == 1
    assert data["purchase_count_7d"] == 1
    assert data["recent_views"] == ["P001"]
    assert data["recent_purchases"] == ["P003"]
    assert data["profile_snapshot"]["behavior_counts"]["view"] == 1
    assert data["profile_snapshot"]["behavior_counts"]["purchase"] == 1
    assert data["profile_snapshot"]["purchase_count"] == 1
    assert data["profile_snapshot"]["total_spent"] == 1899.0
    assert "手机" in data["profile_snapshot"]["preferred_categories"]
    assert "耳机" in data["profile_snapshot"]["preferred_categories"]


def test_memory_impression_updates_last_recommendation():
    class P:
        def __init__(self, product_id, name, category, price):
            self.product_id = product_id
            self.name = name
            self.category = category
            self.price = price

    memory = MemoryManager(redis_client=None)
    products = [P("P001", "iPhone 16 Pro", "手机", 7999), P("P003", "AirPods Pro 3", "耳机", 1899)]
    run(memory.record_impression("u2", products, "req-1", "homepage", "control"))

    profile = run(memory.get_profile_snapshot("u2"))
    assert profile["last_recommendation"]["request_id"] == "req-1"
    assert profile["last_recommendation"]["product_ids"] == ["P001", "P003"]
    assert profile["behavior_counts"]["impression"] == 2


def test_memory_forget_user():
    memory = MemoryManager(redis_client=None)
    run(memory.record_behavior("u3", "view", "P001", {"category": "手机"}))
    run(memory.forget_user("u3"))
    data = run(memory.get_user_memory("u3"))
    assert data["view_count_24h"] == 0
    assert data["profile_snapshot"]["behavior_counts"] == {}


if __name__ == "__main__":
    test_memory_record_and_read()
    test_memory_impression_updates_last_recommendation()
    test_memory_forget_user()
    print("All memory tests passed!")

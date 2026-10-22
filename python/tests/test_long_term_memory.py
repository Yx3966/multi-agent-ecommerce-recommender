"""Long-term memory tests (SQLite-backed, no Redis/Milvus required)."""

import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.long_term_memory import LongTermMemoryStore
from services.memory import MemoryManager


def run(coro):
    return asyncio.run(coro)


def make_store():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    store = LongTermMemoryStore(f"sqlite:///{path}")
    run(store.init())
    return store, path


def test_long_term_profile_persists_across_manager_instances():
    store, path = make_store()
    try:
        memory1 = MemoryManager(redis_client=None, long_term_store=store)
        run(memory1.record_behavior("lt1", "purchase", "P003", {"category": "耳机", "price": 1899, "amount": 1899}))

        # 模拟服务重启：短期内存清空，但 SQLite 长期画像仍在。
        memory2 = MemoryManager(redis_client=None, long_term_store=store)
        data = run(memory2.get_user_memory("lt1"))
        assert data["long_term_memory"]["backend"] == "sqlite"
        assert data["profile_snapshot"]["purchase_count"] == 1
        assert data["profile_snapshot"]["total_spent"] == 1899.0
        assert "耳机" in data["profile_snapshot"]["preferred_categories"]
        assert data["long_term_memory"]["episodes"], "purchase should create a long-term episode"
    finally:
        run(store.delete_user("lt1"))
        if os.path.exists(path):
            os.remove(path)


def test_long_term_keyword_fallback_search():
    store, path = make_store()
    try:
        memory = MemoryManager(redis_client=None, long_term_store=store)
        run(memory.record_behavior("lt2", "favorite", "P001", {"name": "iPhone 16 Pro", "category": "手机", "price": 7999}))
        episodes = run(store.search_episodes("lt2", "手机", 5))
        assert episodes
        assert "iPhone 16 Pro" in episodes[0]["content"]
    finally:
        run(store.delete_user("lt2"))
        if os.path.exists(path):
            os.remove(path)


def test_long_term_forget_user():
    store, path = make_store()
    try:
        memory = MemoryManager(redis_client=None, long_term_store=store)
        run(memory.record_behavior("lt3", "purchase", "P001", {"category": "手机", "amount": 7999}))
        run(memory.forget_user("lt3"))
        assert run(store.get_profile_snapshot("lt3")) is None
        assert run(store.search_episodes("lt3", "手机", 5)) == []
    finally:
        if os.path.exists(path):
            os.remove(path)


if __name__ == "__main__":
    test_long_term_profile_persists_across_manager_instances()
    test_long_term_keyword_fallback_search()
    test_long_term_forget_user()
    print("All long-term memory tests passed!")

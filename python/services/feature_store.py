"""
实时特征存储服务
- Redis Sorted Set 存储用户行为序列 (score=timestamp)
- 滑动窗口计算实时特征 (1h/24h/7d)
- 离线+在线特征合并
- RFM模型计算
"""

from __future__ import annotations

import json
import time
from typing import Any

import structlog

logger = structlog.get_logger()


class FeatureStore:
    """Redis-backed real-time feature store for user behavior and profiles."""

    def __init__(self, redis_client: Any = None, ttl: int = 86400):
        self.redis = redis_client
        self.ttl = ttl

    # ---------- behavior tracking ----------

    async def record_behavior(
        self, user_id: str, behavior_type: str, item_id: str, metadata: dict | None = None
    ):
        """Append a behavior event to user's sorted set (score = timestamp)."""
        if not self.redis:
            return
        key = f"behavior:{user_id}:{behavior_type}"
        payload = json.dumps({"item_id": item_id, "ts": time.time(), **(metadata or {})})
        await self.redis.zadd(key, {payload: time.time()})
        await self.redis.expire(key, self.ttl)

    async def get_recent_behaviors(
        self, user_id: str, behavior_type: str, window_seconds: int = 3600
    ) -> list[dict]:
        """Retrieve behaviors within a sliding time window."""
        if not self.redis:
            return []
        key = f"behavior:{user_id}:{behavior_type}"
        cutoff = time.time() - window_seconds
        raw_items = await self.redis.zrangebyscore(key, cutoff, "+inf")
        return [json.loads(item) for item in raw_items]

    # ---------- real-time features ----------

    async def get_user_features(self, user_id: str) -> dict[str, Any]:
        """Build aggregated feature vector from recent behaviors."""
        views_1h = await self.get_recent_behaviors(user_id, "view", 3600)
        views_24h = await self.get_recent_behaviors(user_id, "view", 86400)
        clicks_1h = await self.get_recent_behaviors(user_id, "click", 3600)
        purchases_7d = await self.get_recent_behaviors(user_id, "purchase", 604800)

        recent_view_items = [v.get("item_id", "") for v in views_24h[-20:]]
        recent_purchase_items = [p.get("item_id", "") for p in purchases_7d[-10:]]

        rfm = await self._compute_rfm(user_id, purchases_7d)

        profile_key = f"profile:{user_id}"
        offline_tags = {}
        if self.redis:
            raw = await self.redis.get(profile_key)
            if raw:
                offline_tags = json.loads(raw)

        return {
            "user_id": user_id,
            "view_count_1h": len(views_1h),
            "view_count_24h": len(views_24h),
            "click_count_1h": len(clicks_1h),
            "purchase_count_7d": len(purchases_7d),
            "recent_views": recent_view_items,
            "recent_purchases": recent_purchase_items,
            "rfm": rfm,
            "offline_tags": offline_tags,
        }

    # ---------- RFM model ----------

    async def _compute_rfm(self, user_id: str, purchases: list[dict]) -> dict[str, float]:
        """
        Recency / Frequency / Monetary scoring (normalised 0-1).
        Without full data we use heuristics.
        """
        if not purchases:
            return {"recency": 0.0, "frequency": 0.0, "monetary": 0.0}

        now = time.time()
        latest_ts = max(p.get("ts", 0) for p in purchases)
        days_since = (now - latest_ts) / 86400

        recency = max(0.0, 1.0 - days_since / 30.0)
        frequency = min(1.0, len(purchases) / 10.0)
        avg_amount = sum(p.get("amount", 100) for p in purchases) / len(purchases)
        monetary = min(1.0, avg_amount / 1000.0)

        return {
            "recency": round(recency, 3),
            "frequency": round(frequency, 3),
            "monetary": round(monetary, 3),
        }

    # ---------- offline merge ----------

    async def merge_offline_tags(self, user_id: str, tags: dict[str, Any]):
        """Write offline (batch-computed) tags so the profile agent can read them."""
        if not self.redis:
            return
        key = f"profile:{user_id}"
        await self.redis.set(key, json.dumps(tags), ex=self.ttl)

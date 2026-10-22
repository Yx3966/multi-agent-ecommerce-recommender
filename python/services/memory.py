"""
分层记忆系统

包含五类记忆：
1. 请求内工作记忆：由 Supervisor / LangGraph State 显式传递。
2. 实时行为记忆：Redis Sorted Set 滑动窗口；无 Redis 时使用进程内存降级。
3. 长期画像记忆：SQLite 持久化 profile snapshot、行为事件流水。
4. 长期语义记忆：可选 Milvus 向量检索；不可用时退化为 SQLite 关键词检索。
5. 实验记忆：由 ABTestEngine 保存分组和 Thompson Sampling 后验。

默认不强制依赖 Redis / Milvus：本地可直接使用内存短期记忆 + SQLite 长期记忆。
"""

from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from typing import Any

from services.feature_store import FeatureStore


class MemoryManager:
    """Coordinates short-term behavior memory and long-term user memory."""

    def __init__(
        self,
        redis_client: Any = None,
        ttl: int = 86400,
        max_events_per_user: int = 1000,
        long_term_store: Any = None,
        semantic_memory: Any = None,
    ):
        self.redis = redis_client
        self.ttl = ttl
        self.max_events_per_user = max_events_per_user
        self.feature_store = FeatureStore(redis_client=redis_client, ttl=ttl) if redis_client else None
        self.long_term_store = long_term_store
        self.semantic_memory = semantic_memory

        # In-memory fallback when Redis is unavailable.
        self._local_events: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._local_profiles: dict[str, dict[str, Any]] = {}

    @property
    def backend(self) -> str:
        return "redis" if self.redis else "memory"

    @property
    def long_term_backend(self) -> str:
        return "sqlite" if self.long_term_store else "none"

    @property
    def semantic_backend(self) -> str:
        if self.semantic_memory and getattr(self.semantic_memory, "available", False):
            return "milvus"
        return "sqlite_keyword" if self.long_term_store else "none"

    async def record_behavior(
        self,
        user_id: str,
        behavior_type: str,
        item_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Record one user behavior event into short-term and long-term memory."""
        metadata = metadata or {}
        event = {
            "user_id": user_id,
            "behavior_type": behavior_type,
            "item_id": item_id,
            "ts": time.time(),
            **metadata,
        }

        if self.feature_store:
            await self.feature_store.record_behavior(user_id, behavior_type, item_id, metadata)
            profile = await self._get_profile_redis(user_id)
            profile = self._update_profile_snapshot(profile, event)
            await self._set_profile_redis(user_id, profile)
        else:
            events = self._local_events[user_id]
            events.append(event)
            del events[:-self.max_events_per_user]
            profile = self._local_profiles.get(user_id, self._empty_profile(user_id))
            self._local_profiles[user_id] = self._update_profile_snapshot(profile, event)

        if self.long_term_store:
            await self.long_term_store.append_behavior_event(event)
            long_profile = await self.long_term_store.get_profile_snapshot(user_id)
            long_profile = self._update_profile_snapshot(long_profile or self._empty_profile(user_id), event)
            await self.long_term_store.save_profile_snapshot(user_id, long_profile)

            if behavior_type in {"purchase", "favorite", "cart"}:
                content = self._episode_content(event)
                memory_id = await self.long_term_store.add_memory_episode(
                    user_id=user_id,
                    memory_type=behavior_type,
                    content=content,
                    metadata=event,
                )
                if self.semantic_memory:
                    await self.semantic_memory.add_memory(memory_id, user_id, content)

        return event

    async def record_impression(
        self,
        user_id: str,
        products: list[Any],
        request_id: str,
        scene: str = "homepage",
        experiment_group: str = "control",
    ) -> None:
        """Record recommendation impressions so later requests can use them as memory."""
        if not products:
            return

        for product in products:
            await self.record_behavior(
                user_id=user_id,
                behavior_type="impression",
                item_id=getattr(product, "product_id", str(product)),
                metadata={
                    "name": getattr(product, "name", ""),
                    "category": getattr(product, "category", ""),
                    "price": getattr(product, "price", 0),
                    "request_id": request_id,
                    "scene": scene,
                    "experiment_group": experiment_group,
                },
            )

        profile = await self.get_profile_snapshot(user_id)
        profile["last_recommendation"] = {
            "request_id": request_id,
            "scene": scene,
            "experiment_group": experiment_group,
            "product_ids": [getattr(p, "product_id", str(p)) for p in products],
            "ts": time.time(),
        }
        await self.save_profile_snapshot(user_id, profile)

    async def get_user_memory(
        self,
        user_id: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build the memory payload used by the profile agent."""
        context = context or {}
        if self.feature_store:
            features = await self.feature_store.get_user_features(user_id)
        else:
            features = self._compute_local_features(user_id)

        profile = await self.get_profile_snapshot(user_id)
        query = self._build_memory_query(user_id, context, profile)
        episodes = await self._get_relevant_episodes(user_id, query)

        return {
            **features,
            "profile_snapshot": profile,
            "long_term_memory": {
                "backend": self.long_term_backend,
                "semantic_backend": self.semantic_backend,
                "query": query,
                "episodes": episodes,
            },
            "request_context": context,
            "memory_backend": self.backend,
        }

    async def get_profile_snapshot(self, user_id: str) -> dict[str, Any]:
        if self.long_term_store:
            profile = await self.long_term_store.get_profile_snapshot(user_id)
            if profile:
                return profile
        if self.feature_store:
            return await self._get_profile_redis(user_id)
        return self._local_profiles.get(user_id, self._empty_profile(user_id))

    async def save_profile_snapshot(self, user_id: str, profile: dict[str, Any]) -> None:
        profile["user_id"] = user_id
        profile["updated_at"] = time.time()
        if self.long_term_store:
            await self.long_term_store.save_profile_snapshot(user_id, profile)
        if self.feature_store:
            await self._set_profile_redis(user_id, profile)
        else:
            self._local_profiles[user_id] = profile

    async def forget_user(self, user_id: str) -> None:
        """Delete user memory from short-term, long-term, and semantic stores."""
        if self.redis:
            behavior_types = ["view", "click", "purchase", "favorite", "cart", "impression"]
            keys = [f"behavior:{user_id}:{t}" for t in behavior_types]
            keys.append(f"profile:{user_id}")
            await self.redis.delete(*keys)
        self._local_events.pop(user_id, None)
        self._local_profiles.pop(user_id, None)
        if self.long_term_store:
            await self.long_term_store.delete_user(user_id)
        if self.semantic_memory:
            await self.semantic_memory.delete_user(user_id)

    async def _get_relevant_episodes(
        self,
        user_id: str,
        query: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        if not self.long_term_store:
            return []

        if self.semantic_memory and getattr(self.semantic_memory, "available", False):
            ids = await self.semantic_memory.search_memory_ids(user_id, query, limit)
            episodes = await self.long_term_store.get_episodes_by_ids(user_id, ids)
            if episodes:
                return episodes

        return await self.long_term_store.search_episodes(user_id, query, limit)

    def _build_memory_query(
        self,
        user_id: str,
        context: dict[str, Any],
        profile: dict[str, Any],
    ) -> str:
        parts = ["用户长期兴趣 偏好 购买 收藏"]
        parts.extend(profile.get("preferred_categories", [])[:5])
        parts.extend(context.get("recent_views", [])[:5])
        parts.extend(context.get("recent_purchases", [])[:5])
        return " ".join(str(p) for p in parts if p)

    def _episode_content(self, event: dict[str, Any]) -> str:
        behavior_type = event.get("behavior_type", "event")
        name = event.get("name") or event.get("item_id", "")
        category = event.get("category", "")
        price = event.get("price", event.get("amount", ""))
        action_map = {
            "purchase": "购买了",
            "favorite": "收藏了",
            "cart": "加购了",
        }
        action = action_map.get(behavior_type, "产生了行为")
        return f"用户{action}商品{name}，类目{category}，价格{price}。"

    def _compute_local_features(self, user_id: str) -> dict[str, Any]:
        now = time.time()
        events = self._local_events.get(user_id, [])

        def recent(behavior_type: str, window_seconds: int) -> list[dict[str, Any]]:
            cutoff = now - window_seconds
            return [
                e for e in events
                if e.get("behavior_type") == behavior_type and e.get("ts", 0) >= cutoff
            ]

        views_1h = recent("view", 3600)
        views_24h = recent("view", 86400)
        clicks_1h = recent("click", 3600)
        purchases_7d = recent("purchase", 604800)
        impressions_24h = recent("impression", 86400)

        return {
            "user_id": user_id,
            "view_count_1h": len(views_1h),
            "view_count_24h": len(views_24h),
            "click_count_1h": len(clicks_1h),
            "purchase_count_7d": len(purchases_7d),
            "impression_count_24h": len(impressions_24h),
            "recent_views": [e.get("item_id", "") for e in views_24h[-20:]],
            "recent_purchases": [e.get("item_id", "") for e in purchases_7d[-10:]],
            "recent_impressions": [e.get("item_id", "") for e in impressions_24h[-20:]],
            "rfm": self._compute_rfm(purchases_7d),
            "offline_tags": self._local_profiles.get(user_id, {}).get("offline_tags", {}),
        }

    def _compute_rfm(self, purchases: list[dict[str, Any]]) -> dict[str, float]:
        if not purchases:
            return {"recency": 0.0, "frequency": 0.0, "monetary": 0.0}

        now = time.time()
        latest_ts = max(p.get("ts", 0) for p in purchases)
        days_since = (now - latest_ts) / 86400
        amounts = [float(p.get("amount", p.get("price", 100)) or 100) for p in purchases]

        return {
            "recency": round(max(0.0, 1.0 - days_since / 30.0), 3),
            "frequency": round(min(1.0, len(purchases) / 10.0), 3),
            "monetary": round(min(1.0, (sum(amounts) / len(amounts)) / 1000.0), 3),
        }

    def _empty_profile(self, user_id: str) -> dict[str, Any]:
        return {
            "user_id": user_id,
            "behavior_counts": {},
            "preferred_categories": [],
            "category_affinity": {},
            "last_items": [],
            "purchase_count": 0,
            "total_spent": 0.0,
            "offline_tags": {},
            "created_at": time.time(),
            "updated_at": time.time(),
        }

    def _update_profile_snapshot(
        self,
        profile: dict[str, Any],
        event: dict[str, Any],
    ) -> dict[str, Any]:
        profile = dict(profile or self._empty_profile(event["user_id"]))
        behavior_type = event.get("behavior_type", "event")
        category = event.get("category")

        counts = dict(profile.get("behavior_counts", {}))
        counts[behavior_type] = counts.get(behavior_type, 0) + 1
        profile["behavior_counts"] = counts

        if category:
            affinity = dict(profile.get("category_affinity", {}))
            affinity[category] = affinity.get(category, 0) + 1
            profile["category_affinity"] = affinity
            profile["preferred_categories"] = [
                name for name, _ in Counter(affinity).most_common(5)
            ]

        last_items = list(profile.get("last_items", []))
        item_id = event.get("item_id")
        if item_id:
            last_items.append(item_id)
            profile["last_items"] = last_items[-20:]

        if behavior_type == "purchase":
            amount = float(event.get("amount", event.get("price", 0)) or 0)
            profile["purchase_count"] = int(profile.get("purchase_count", 0)) + 1
            profile["total_spent"] = round(float(profile.get("total_spent", 0.0)) + amount, 2)

        profile["last_behavior_at"] = event.get("ts", time.time())
        profile["updated_at"] = time.time()
        return profile

    async def _get_profile_redis(self, user_id: str) -> dict[str, Any]:
        if not self.redis:
            return self._empty_profile(user_id)
        raw = await self.redis.get(f"profile:{user_id}")
        if not raw:
            return self._empty_profile(user_id)
        try:
            return json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return self._empty_profile(user_id)

    async def _set_profile_redis(self, user_id: str, profile: dict[str, Any]) -> None:
        if not self.redis:
            return
        await self.redis.set(f"profile:{user_id}", json.dumps(profile, ensure_ascii=False), ex=self.ttl)

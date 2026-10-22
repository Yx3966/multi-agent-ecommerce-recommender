"""
长期记忆存储（Python 版）

职责：
- SQLite 持久化用户画像快照、行为事件流水、长期记忆片段。
- 可选接入 Milvus 做语义向量检索。
- 无 Milvus / 无 embedding 服务时，退化为 SQLite 关键词检索。

设计原则：
- SQLite 存事实：事件、画像快照、记忆元数据。
- Milvus 存语义：长期兴趣摘要/重要行为片段的向量。
- Redis 仍负责短期热点特征；本模块负责长期记忆。
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
import uuid
from typing import Any


class LongTermMemoryStore:
    """SQLite-backed durable memory store."""

    def __init__(self, database_url: str = "sqlite:///./ecommerce.db"):
        self.database_url = database_url
        self.path = self._parse_sqlite_path(database_url)
        self._memory_conn: sqlite3.Connection | None = None
        if self.path == ":memory:":
            self._memory_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._memory_conn.row_factory = sqlite3.Row

    def _parse_sqlite_path(self, database_url: str) -> str:
        if database_url.startswith("sqlite:///"):
            return database_url[len("sqlite:///"):]
        # 非 sqlite 场景下仍给一个本地文件，保证 Demo 默认可运行。
        return "./ecommerce_memory.db"

    def _connect(self) -> sqlite3.Connection:
        if self._memory_conn is not None:
            return self._memory_conn
        parent = os.path.dirname(os.path.abspath(self.path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    async def init(self) -> None:
        await asyncio.to_thread(self._init_sync)

    def _init_sync(self) -> None:
        conn = self._connect()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS user_profiles (
                    user_id TEXT PRIMARY KEY,
                    profile_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS behavior_events (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    behavior_type TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    ts REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS memory_episodes (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    memory_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    embedding_id TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_behavior_user_ts
                    ON behavior_events(user_id, ts);
                CREATE INDEX IF NOT EXISTS idx_episode_user_time
                    ON memory_episodes(user_id, created_at);
                """
            )
            conn.commit()
        finally:
            if self._memory_conn is None:
                conn.close()

    async def append_behavior_event(self, event: dict[str, Any]) -> str:
        event_id = str(uuid.uuid4())
        await asyncio.to_thread(self._append_behavior_event_sync, event_id, event)
        return event_id

    def _append_behavior_event_sync(self, event_id: str, event: dict[str, Any]) -> None:
        conn = self._connect()
        metadata = {
            k: v for k, v in event.items()
            if k not in {"user_id", "behavior_type", "item_id", "ts"}
        }
        try:
            conn.execute(
                """
                INSERT INTO behavior_events(id, user_id, behavior_type, item_id, metadata_json, ts)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    event.get("user_id", ""),
                    event.get("behavior_type", "event"),
                    event.get("item_id", ""),
                    json.dumps(metadata, ensure_ascii=False),
                    float(event.get("ts", time.time())),
                ),
            )
            conn.commit()
        finally:
            if self._memory_conn is None:
                conn.close()

    async def save_profile_snapshot(self, user_id: str, profile: dict[str, Any]) -> None:
        await asyncio.to_thread(self._save_profile_snapshot_sync, user_id, profile)

    def _save_profile_snapshot_sync(self, user_id: str, profile: dict[str, Any]) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO user_profiles(user_id, profile_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    profile_json = excluded.profile_json,
                    updated_at = excluded.updated_at
                """,
                (user_id, json.dumps(profile, ensure_ascii=False), time.time()),
            )
            conn.commit()
        finally:
            if self._memory_conn is None:
                conn.close()

    async def get_profile_snapshot(self, user_id: str) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._get_profile_snapshot_sync, user_id)

    def _get_profile_snapshot_sync(self, user_id: str) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT profile_json FROM user_profiles WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            if not row:
                return None
            return json.loads(row["profile_json"])
        finally:
            if self._memory_conn is None:
                conn.close()

    async def add_memory_episode(
        self,
        user_id: str,
        memory_type: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        memory_id = str(uuid.uuid4())
        await asyncio.to_thread(
            self._add_memory_episode_sync,
            memory_id,
            user_id,
            memory_type,
            content,
            metadata or {},
        )
        return memory_id

    def _add_memory_episode_sync(
        self,
        memory_id: str,
        user_id: str,
        memory_type: str,
        content: str,
        metadata: dict[str, Any],
    ) -> None:
        conn = self._connect()
        now = time.time()
        try:
            conn.execute(
                """
                INSERT INTO memory_episodes(
                    id, user_id, memory_type, content, metadata_json, embedding_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?)
                """,
                (
                    memory_id,
                    user_id,
                    memory_type,
                    content,
                    json.dumps(metadata, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            conn.commit()
        finally:
            if self._memory_conn is None:
                conn.close()

    async def get_episodes_by_ids(self, user_id: str, ids: list[str]) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._get_episodes_by_ids_sync, user_id, ids)

    def _get_episodes_by_ids_sync(self, user_id: str, ids: list[str]) -> list[dict[str, Any]]:
        if not ids:
            return []
        conn = self._connect()
        placeholders = ",".join("?" for _ in ids)
        try:
            rows = conn.execute(
                f"""
                SELECT * FROM memory_episodes
                WHERE user_id = ? AND id IN ({placeholders})
                ORDER BY created_at DESC
                """,
                (user_id, *ids),
            ).fetchall()
            return [self._row_to_episode(row) for row in rows]
        finally:
            if self._memory_conn is None:
                conn.close()

    async def search_episodes(
        self,
        user_id: str,
        query: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._search_episodes_sync, user_id, query, limit)

    def _search_episodes_sync(self, user_id: str, query: str, limit: int) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT * FROM memory_episodes
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT 200
                """,
                (user_id,),
            ).fetchall()
        finally:
            if self._memory_conn is None:
                conn.close()

        tokens = self._tokenize(query)
        scored = []
        for row in rows:
            episode = self._row_to_episode(row)
            haystack = episode["content"] + " " + json.dumps(episode["metadata"], ensure_ascii=False)
            score = sum(1 for token in tokens if token and token in haystack)
            if score > 0:
                episode["score"] = score
                scored.append(episode)
        scored.sort(key=lambda x: (x["score"], x["created_at"]), reverse=True)
        return scored[:limit]

    async def get_long_term_context(
        self,
        user_id: str,
        query: str = "",
        limit: int = 5,
    ) -> dict[str, Any]:
        profile = await self.get_profile_snapshot(user_id)
        episodes = await self.search_episodes(user_id, query, limit) if query else []
        if not episodes:
            episodes = await self.search_episodes(user_id, "偏好 购买 收藏 加购", limit)
        return {
            "profile_snapshot": profile,
            "episodes": episodes,
        }

    async def delete_user(self, user_id: str) -> None:
        await asyncio.to_thread(self._delete_user_sync, user_id)

    def _delete_user_sync(self, user_id: str) -> None:
        conn = self._connect()
        try:
            conn.execute("DELETE FROM user_profiles WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM behavior_events WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM memory_episodes WHERE user_id = ?", (user_id,))
            conn.commit()
        finally:
            if self._memory_conn is None:
                conn.close()

    def _row_to_episode(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "user_id": row["user_id"],
            "memory_type": row["memory_type"],
            "content": row["content"],
            "metadata": json.loads(row["metadata_json"]),
            "embedding_id": row["embedding_id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _tokenize(self, query: str) -> list[str]:
        raw = query.replace(",", " ").replace("，", " ").split()
        tokens = [t.strip() for t in raw if len(t.strip()) >= 2]
        if not tokens and query:
            tokens.append(query.strip())
        return tokens

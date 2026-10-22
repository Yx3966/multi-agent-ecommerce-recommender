"""
可选语义向量记忆（Milvus）。

默认关闭。只有同时满足以下条件时才启用：
1. ECOM_SEMANTIC_MEMORY_ENABLED=true
2. 配置 ECOM_EMBEDDING_MODEL
3. LLM base url 兼容 OpenAI /embeddings
4. Milvus 可连接

不满足时，MemoryManager 会自动退化为 SQLite 关键词检索。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx


class EmbeddingProvider:
    """OpenAI-compatible embedding client."""

    def __init__(self, settings: Any):
        self.settings = settings

    @property
    def available(self) -> bool:
        return bool(
            getattr(self.settings, "embedding_model", "")
            and getattr(self.settings, "llm_api_key", "")
        )

    async def embed(self, text: str) -> list[float] | None:
        if not self.available:
            return None
        url = f"{self.settings.llm_base_url.rstrip('/')}/embeddings"
        payload = {
            "model": self.settings.embedding_model,
            "input": text,
        }
        headers = {"Authorization": f"Bearer {self.settings.llm_api_key}"}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp = resp.json()
                return resp["data"][0]["embedding"]
        except Exception:
            return None


class SemanticMemoryStore:
    """Milvus-backed vector memory. Optional and fail-safe."""

    def __init__(self, settings: Any, embedding_provider: EmbeddingProvider):
        self.settings = settings
        self.embedding_provider = embedding_provider
        self.available = False
        self.collection = None

    async def connect(self) -> bool:
        if not getattr(self.settings, "semantic_memory_enabled", False):
            return False
        if not self.embedding_provider.available:
            return False

        try:
            from pymilvus import (  # type: ignore
                Collection,
                CollectionSchema,
                DataType,
                FieldSchema,
                connections,
                utility,
            )
        except Exception:
            return False

        def _connect_sync() -> bool:
            try:
                connections.connect(
                    alias="default",
                    host=self.settings.milvus_host,
                    port=str(self.settings.milvus_port),
                )
                name = getattr(self.settings, "milvus_memory_collection", "user_long_term_memory")
                dim = int(getattr(self.settings, "embedding_dimensions", 1024))
                if not utility.has_collection(name):
                    fields = [
                        FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
                        FieldSchema(name="memory_id", dtype=DataType.VARCHAR, max_length=64),
                        FieldSchema(name="user_id", dtype=DataType.VARCHAR, max_length=128),
                        FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=dim),
                        FieldSchema(name="created_at", dtype=DataType.DOUBLE),
                    ]
                    schema = CollectionSchema(fields, description="User long-term semantic memory")
                    collection = Collection(name=name, schema=schema)
                    collection.create_index(
                        field_name="embedding",
                        index_params={
                            "index_type": "IVF_FLAT",
                            "metric_type": "COSINE",
                            "params": {"nlist": 128},
                        },
                    )
                collection = Collection(name)
                collection.load()
                self.collection = collection
                return True
            except Exception:
                return False

        self.available = await asyncio.to_thread(_connect_sync)
        return self.available

    async def add_memory(
        self,
        memory_id: str,
        user_id: str,
        content: str,
    ) -> bool:
        if not self.available or self.collection is None:
            return False
        vector = await self.embedding_provider.embed(content)
        if not vector:
            return False

        def _insert_sync() -> bool:
            try:
                self.collection.insert([
                    [memory_id],
                    [user_id],
                    [vector],
                    [time.time()],
                ])
                self.collection.flush()
                return True
            except Exception:
                return False

        return await asyncio.to_thread(_insert_sync)

    async def search_memory_ids(
        self,
        user_id: str,
        query: str,
        limit: int = 5,
    ) -> list[str]:
        if not self.available or self.collection is None:
            return []
        vector = await self.embedding_provider.embed(query)
        if not vector:
            return []

        def _search_sync() -> list[str]:
            try:
                results = self.collection.search(
                    data=[vector],
                    anns_field="embedding",
                    param={"metric_type": "COSINE", "params": {"nprobe": 10}},
                    limit=limit,
                    expr=f'user_id == "{user_id}"',
                    output_fields=["memory_id"],
                )
                ids = []
                for hits in results:
                    for hit in hits:
                        memory_id = hit.entity.get("memory_id")
                        if memory_id:
                            ids.append(memory_id)
                return ids
            except Exception:
                return []

        return await asyncio.to_thread(_search_sync)

    async def delete_user(self, user_id: str) -> None:
        if not self.available or self.collection is None:
            return

        def _delete_sync() -> None:
            try:
                self.collection.delete(expr=f'user_id == "{user_id}"')
                self.collection.flush()
            except Exception:
                return

        await asyncio.to_thread(_delete_sync)

    async def close(self) -> None:
        if not self.available:
            return

        def _close_sync() -> None:
            try:
                if self.collection is not None:
                    self.collection.release()
                from pymilvus import connections  # type: ignore
                connections.disconnect("default")
            except Exception:
                return

        await asyncio.to_thread(_close_sync)

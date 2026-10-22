"""
Supervisor编排器 — 并行分发 + 聚合模式

                    ┌──────────────┐
                    │  Supervisor   │
                    └──────┬───────┘
           ┌───────┬───────┼───────┬────────┐
           ▼       ▼       ▼       ▼        │
      UserProfile  ProdRec  MktCopy  Inventory │
           │       │       │       │        │
           └───────┴───────┴───────┘        │
                    │                        │
                    ▼                        │
               Aggregator ◄─────────────────┘
                    │
                    ▼
              A/B Test Engine
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

import structlog

from agents import (
    InventoryAgent,
    MarketingCopyAgent,
    ProductRecAgent,
    UserProfileAgent,
)
from models.schemas import (
    Product,
    RecommendationRequest,
    RecommendationResponse,
    UserProfile,
)
from services.ab_test import ABTestEngine

logger = structlog.get_logger()


class SupervisorOrchestrator:
    """Coordinates four agents in parallel-then-aggregate pattern."""

    def __init__(
        self,
        ab_engine: ABTestEngine | None = None,
        memory_manager: Any = None,
    ):
        self.user_profile_agent = UserProfileAgent()
        self.product_rec_agent = ProductRecAgent()
        self.marketing_copy_agent = MarketingCopyAgent()
        self.inventory_agent = InventoryAgent()
        self.ab_engine = ab_engine or ABTestEngine()
        self.memory_manager = None
        self.set_memory_manager(memory_manager)

    def set_memory_manager(self, memory_manager: Any) -> None:
        """Inject the shared memory system into agents that need user memory."""
        self.memory_manager = memory_manager
        if not memory_manager:
            return
        self.user_profile_agent.memory_manager = memory_manager
        self.user_profile_agent.feature_store = memory_manager.feature_store

    async def recommend(self, request: RecommendationRequest) -> RecommendationResponse:
        request_id = str(uuid.uuid4())
        start = time.perf_counter()

        logger.info(
            "supervisor.start",
            request_id=request_id,
            user_id=request.user_id,
            scene=request.scene,
        )

        experiment = self.ab_engine.assign(request.user_id)

        # Phase 1: parallel — user profile + product recall
        profile_result, rec_result = await asyncio.gather(
            self.user_profile_agent.run(
                user_id=request.user_id,
                context=request.context,
            ),
            self.product_rec_agent.run(
                user_profile=None,
                num_items=request.num_items * 2,
            ),
        )

        user_profile: UserProfile | None = getattr(profile_result, "profile", None)
        raw_products: list[Product] = getattr(rec_result, "products", [])

        # Phase 2: parallel — re-rank with profile + inventory check
        rerank_task = self.product_rec_agent.run(
            user_profile=user_profile,
            num_items=request.num_items,
        )
        inventory_task = self.inventory_agent.run(products=raw_products)

        rerank_result, inventory_result = await asyncio.gather(
            rerank_task, inventory_task
        )

        ranked_products: list[Product] = getattr(rerank_result, "products", raw_products)

        available_ids = set(getattr(inventory_result, "available_products", []))
        final_products = [p for p in ranked_products if p.product_id in available_ids]
        if not final_products:
            final_products = ranked_products[:request.num_items]
        final_products = final_products[:request.num_items]

        # Phase 3: marketing copy generation with final product list
        copy_result = await self.marketing_copy_agent.run(
            user_profile=user_profile,
            products=final_products,
        )
        copies = getattr(copy_result, "copies", [])

        total_latency = (time.perf_counter() - start) * 1000

        logger.info(
            "supervisor.complete",
            request_id=request_id,
            total_latency_ms=round(total_latency, 1),
            product_count=len(final_products),
            copy_count=len(copies),
        )

        response = RecommendationResponse(
            request_id=request_id,
            user_id=request.user_id,
            products=final_products,
            marketing_copies=copies,
            experiment_group=experiment.get("group", "control"),
            agent_results={
                "user_profile": profile_result,
                "product_rec": rerank_result,
                "marketing_copy": copy_result,
                "inventory": inventory_result,
            },
            total_latency_ms=total_latency,
        )

        if self.memory_manager:
            try:
                await self.memory_manager.record_impression(
                    user_id=request.user_id,
                    products=final_products,
                    request_id=request_id,
                    scene=request.scene,
                    experiment_group=response.experiment_group,
                )
            except Exception as exc:
                logger.warning("memory.impression_failed", error=str(exc))

        return response
